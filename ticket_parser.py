"""
ticket_parser.py
=================
Turns a structured JSM ticket description into a plain Python dict the
provisioning bot can act on.

Real IT departments handle this with a proper JSM "request form" (custom
fields), which is the production-grade way to do it. This project uses
a simple `Key: Value` text convention instead so the whole thing runs
with a plain Jira Cloud project and no special JSM forms configuration
— it's easier to set up for a portfolio/lab project, and the parsing
logic is exactly what you'd write if you were pulling data out of any
semi-structured text (emails, tickets, forms).

Expected ticket description format (case-insensitive keys):

    Full Name: Jane Doe
    Username: jdoe
    Job Title: IT Support Analyst
    Department: IT
    Manager: jsmith
    Groups: VPN-Users, Helpdesk-Team

For offboarding tickets, only "Username" is required.
"""

import re

REQUIRED_ONBOARDING_FIELDS = ["full name", "username"]
REQUIRED_OFFBOARDING_FIELDS = ["username"]


def parse_ticket_fields(description_text):
    """
    Parse 'Key: Value' lines from a ticket description into a dict with
    lowercase keys, e.g. {'full name': 'Jane Doe', 'username': 'jdoe'}.
    Lines that don't match the pattern are ignored.
    """
    fields = {}
    if not description_text:
        return fields

    for line in description_text.splitlines():
        match = re.match(r"^\s*([A-Za-z ]+?)\s*:\s*(.+?)\s*$", line)
        if match:
            key = match.group(1).strip().lower()
            value = match.group(2).strip()
            fields[key] = value
    return fields


def parse_groups(fields):
    """Return the 'Groups' field as a clean list, e.g. ['VPN-Users', 'Helpdesk-Team']."""
    raw = fields.get("groups", "")
    return [g.strip() for g in raw.split(",") if g.strip()]


def validate_fields(fields, required_fields):
    """Return a list of missing required field names (empty list means valid)."""
    return [name for name in required_fields if not fields.get(name)]
