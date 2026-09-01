#!/usr/bin/env python3
"""
JSM <-> Active Directory Provisioning Bot
============================================
Watches a Jira Service Management project for onboarding and
offboarding tickets, and automatically performs the matching Active
Directory action:

  - A ticket labeled "onboarding" (in an actionable status) creates a
    new, enabled AD user account with a random temporary password, adds
    them to the requested groups, and comments the result back onto the
    ticket.
  - A ticket labeled "offboarding" disables the matching AD account,
    strips its group memberships, and comments the result back onto the
    ticket.

This is exactly the kind of "swivel-chair" work — copy details from a
ticket, go do the same three clicks in Active Directory Users and
Computers, go back and update the ticket — that IT support automates
first, because it's repetitive, time-sensitive, and error-prone when
done by hand at 5pm on a Friday.

SAFETY: This script changes real user accounts. Always run with
--dry-run first against a lab/test AD environment until you're
confident it's doing exactly what you expect.

Author: (your name here)
License: MIT
"""

import argparse
import secrets
import string
import sys
import time

from dotenv import load_dotenv

from ad_client import ADClient
from jsm_client import JSMClient, JSMAPIError
from ticket_parser import parse_ticket_fields, parse_groups, validate_fields, \
    REQUIRED_ONBOARDING_FIELDS, REQUIRED_OFFBOARDING_FIELDS

load_dotenv()

ONBOARDING_JQL = 'labels = "onboarding" AND status = "To Do"'
OFFBOARDING_JQL = 'labels = "offboarding" AND status = "To Do"'

# Map a short group name from the ticket (e.g. "VPN-Users") to its full
# Distinguished Name in your AD. Edit this to match your lab's OU layout,
# or replace with a lookup against AD if you'd rather resolve it dynamically.
GROUP_DN_MAP_PLACEHOLDER = "CN={group_name},OU=Groups,{base_dn}"


def generate_temp_password(length=16):
    """Generate a random password that satisfies typical AD complexity rules."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_symbol = any(c in "!@#$%^&*" for c in password)
        if all([has_upper, has_lower, has_digit, has_symbol]):
            return password


def resolve_group_dn(group_name, base_dn):
    return GROUP_DN_MAP_PLACEHOLDER.format(group_name=group_name, base_dn=base_dn)


def process_onboarding_tickets(jsm, ad, dry_run=True):
    tickets = jsm.search_tickets(ONBOARDING_JQL)
    print(f"Found {len(tickets)} onboarding ticket(s) to process.")

    for issue in tickets:
        key = issue["key"]
        full_issue = jsm.get_ticket(key)
        description_text = _extract_plain_text(full_issue["fields"].get("description"))
        fields = parse_ticket_fields(description_text)

        missing = validate_fields(fields, REQUIRED_ONBOARDING_FIELDS)
        if missing:
            print(f"[{key}] SKIPPED — missing required field(s): {', '.join(missing)}")
            if not dry_run:
                jsm.add_comment(
                    key,
                    f"Could not auto-provision this account — missing required "
                    f"field(s): {', '.join(missing)}. Please update the ticket description."
                )
            continue

        username = fields["username"]
        full_name = fields["full name"]
        job_title = fields.get("job title", "")
        department = fields.get("department", "")
        groups = parse_groups(fields)
        temp_password = generate_temp_password()

        print(f"[{key}] Creating AD account '{username}' ({full_name})...")
        if dry_run:
            print(f"  DRY RUN — would create user, set temp password, "
                  f"and add to groups: {groups or 'none'}")
            continue

        try:
            ad.create_user(username, full_name, job_title, department,
                            temp_password=temp_password)
            for group in groups:
                group_dn = resolve_group_dn(group, ad.base_dn)
                ad.add_to_group(username, group_dn)

            jsm.add_comment(
                key,
                f"AD account '{username}' created successfully.\n"
                f"Temporary password: {temp_password}\n"
                f"Groups added: {', '.join(groups) or 'none'}\n"
                f"(Please deliver the password to the user through a secure channel, "
                f"not this ticket, in a real deployment.)"
            )
            jsm.transition_ticket(key, "Done")
            print(f"[{key}] Done.")
        except Exception as exc:
            print(f"[{key}] ERROR: {exc}")
            jsm.add_comment(key, f"Automated provisioning failed: {exc}")


def process_offboarding_tickets(jsm, ad, dry_run=True):
    tickets = jsm.search_tickets(OFFBOARDING_JQL)
    print(f"Found {len(tickets)} offboarding ticket(s) to process.")

    for issue in tickets:
        key = issue["key"]
        full_issue = jsm.get_ticket(key)
        description_text = _extract_plain_text(full_issue["fields"].get("description"))
        fields = parse_ticket_fields(description_text)

        missing = validate_fields(fields, REQUIRED_OFFBOARDING_FIELDS)
        if missing:
            print(f"[{key}] SKIPPED — missing required field(s): {', '.join(missing)}")
            continue

        username = fields["username"]
        print(f"[{key}] Disabling AD account '{username}'...")
        if dry_run:
            print("  DRY RUN — would disable account and remove all group memberships")
            continue

        try:
            ad.disable_user(username)
            removed_groups = ad.remove_all_group_memberships(username)
            jsm.add_comment(
                key,
                f"AD account '{username}' disabled and removed from "
                f"{len(removed_groups)} group(s)."
            )
            jsm.transition_ticket(key, "Done")
            print(f"[{key}] Done.")
        except Exception as exc:
            print(f"[{key}] ERROR: {exc}")
            jsm.add_comment(key, f"Automated deprovisioning failed: {exc}")


def _extract_plain_text(adf_description):
    """Pull plain text back out of Jira's Atlassian Document Format (ADF)."""
    if not adf_description:
        return ""
    lines = []
    for block in adf_description.get("content", []):
        for item in block.get("content", []):
            if item.get("type") == "text":
                lines.append(item.get("text", ""))
        lines.append("")  # blank line between paragraphs
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Automate Active Directory onboarding/offboarding from JSM tickets."
    )
    parser.add_argument("--dry-run", action="store_true",
                         help="Show what WOULD happen without changing AD or Jira.")
    parser.add_argument("--loop", action="store_true",
                         help="Keep checking for new tickets every 60 seconds instead of running once.")
    parser.add_argument("--onboarding-only", action="store_true")
    parser.add_argument("--offboarding-only", action="store_true")
    args = parser.parse_args()

    try:
        jsm = JSMClient()
        ad = ADClient()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        sys.exit(1)

    def run_once():
        if not args.offboarding_only:
            process_onboarding_tickets(jsm, ad, dry_run=args.dry_run)
        if not args.onboarding_only:
            process_offboarding_tickets(jsm, ad, dry_run=args.dry_run)

    if args.loop:
        print("Running continuously, checking every 60 seconds. Press Ctrl+C to stop.")
        try:
            while True:
                run_once()
                time.sleep(60)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        run_once()


if __name__ == "__main__":
    main()
