# Sample Ticket Templates

Paste one of these into a JSM ticket's **description** field (and add the matching label) to test the bot. These are the exact "Key: Value" formats `ticket_parser.py` expects.

## Onboarding ticket

- **Label:** `onboarding`
- **Status:** `To Do`
- **Description:**

```
Full Name: Jane Doe
Username: jdoe
Job Title: IT Support Analyst
Department: IT
Manager: jsmith
Groups: VPN-Users, Helpdesk-Team
```

## Offboarding ticket

- **Label:** `offboarding`
- **Status:** `To Do`
- **Description:**

```
Username: jdoe
```

## What happens next

Run `python3 provisioning_bot.py --dry-run` first to see what the bot *would* do without touching AD or Jira. Once you're confident, drop `--dry-run` to let it actually create/disable the account, comment the result on the ticket, and transition it to `Done`.
