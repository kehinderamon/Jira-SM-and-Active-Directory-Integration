# JSM ↔ Active Directory Provisioning Bot

A Python automation bot that connects **Jira Service Management** to **on-prem Active Directory**: when an onboarding or offboarding ticket is raised in JSM, the bot automatically creates/disables the matching AD user account, manages group membership, comments the result back on the ticket, and closes it  no manual "Active Directory Users and Computers" clicking required.

## Why this project

This is the integration IT support teams actually build once they outgrow doing everything by hand: a new-hire ticket comes in, someone manually creates the AD account, adds them to the right groups, sets a temp password, then goes back to close the ticket. That's slow, repetitive, and easy to get wrong under pressure (forgetting a group, misspelling a username). This project automates that entire loop and shows you can connect two real enterprise systems  a ticketing platform and a directory service  via their respective APIs (Jira REST API + LDAP).

## Features

* Polls JSM for tickets labeled `onboarding` or `offboarding` in a `To Do` status
* Parses structured ticket fields (Full Name, Username, Job Title, Department, Groups) out of the ticket description
* **Onboarding:** creates a new AD user account, sets a random temporary password meeting AD complexity rules, adds the user to the requested security groups, comments the result back on the ticket, and moves it to `Done`
* **Offboarding:** disables the matching AD account, removes it from every group it belonged to, comments back, and closes the ticket
* **`--dry-run` mode**  shows exactly what the bot would do without touching AD or Jira. Always test with this first.
* Missing or malformed ticket data is caught and reported back as a comment instead of silently failing
* Clean separation of concerns: `ad\_client.py` (LDAP/AD logic), `jsm\_client.py` (Jira REST API logic), `ticket\_parser.py` (text parsing), `provisioning\_bot.py` (orchestration/CLI)
* 22 automated tests, all using mocked LDAP and mocked HTTP calls  the full suite runs offline, in seconds, with no real AD or Jira credentials needed

## Tech stack

* Python 3
* [`ldap3`](https://ldap3.readthedocs.io/)  pure-Python LDAP client for talking to Active Directory
* [`requests`](https://pypi.org/project/requests/)  Jira Cloud REST API v3 calls
* [`python-dotenv`](https://pypi.org/project/python-dotenv/)  loads credentials from `.env`
* `unittest` + `unittest.mock` for automated tests

## Project structure

```
4-jsm-active-directory-integration/
├── ad\_client.py                 # Active Directory operations (via LDAP)
├── jsm\_client.py                # Jira Service Management REST API client
├── ticket\_parser.py             # parses ticket description text into fields
├── provisioning\_bot.py          # main script  run this
├── sample\_ticket\_templates.md   # copy-paste ticket text for testing
├── tests/
│   ├── test\_ad\_client.py
│   ├── test\_ticket\_parser.py
│   └── test\_provisioning\_bot.py
├── .env.example
├── requirements.txt
├── .gitignore
└── README.md
```

## ⚠️ Safety notes before you run this against a real domain

* **Never point this at your production Active Directory as a first test.** Use a lab/test domain  a Windows Server VM (Windows Server Evaluation is free from Microsoft) with AD DS installed, or a virtualized lab (VirtualBox/Hyper-V/VMware).
* Use a **dedicated service account** for `AD\_BIND\_USER` with only the delegated permissions it needs (create/disable users, edit group membership in a specific OU)  not a Domain Admin account.
* **Always run `--dry-run` first** and read the output carefully before running for real.
* Setting a password over LDAP requires an **encrypted connection (LDAPS, port 636)**  Active Directory will reject a plaintext password change otherwise. Make sure your domain controller has a certificate configured for LDAPS in your lab.

## Getting started

### 1\. Prerequisites

* Python 3.8+
* A lab Active Directory domain controller reachable over LDAPS
* A JSM project (see the [Jira Service Management Ticket Toolkit](../1-jira-service-management-toolkit) project for how to get your API token and project key  this project reuses the exact same `jsm\_client.py`)

### 2\. Install

```bash
git clone https://github.com/<your-username>/jsm-active-directory-integration.git
cd jsm-active-directory-integration
pip install -r requirements.txt --break-system-packages

cp .env.example .env
```

### 3\. Configure `.env`

Fill in both the Jira section and the Active Directory section  see the comments in `.env.example` for what each value means and where to find it.

### 4\. Set up a test ticket

In your JSM project, create a ticket with the label `onboarding`, status `To Do`, and this description (see `sample\_ticket\_templates.md` for more examples):

```
Full Name: Jane Doe
Username: jdoe
Job Title: IT Support Analyst
Department: IT
Groups: VPN-Users, Helpdesk-Team
```

> Note: `Groups` in the ticket must match a group name you configure the DN pattern for  see `resolve\_group\_dn()` in `provisioning\_bot.py`, which is deliberately left as a placeholder mapping for you to adapt to your own AD's OU layout (or replace with a live AD group lookup).

### 5\. Dry-run it

```bash
python3 provisioning\_bot.py --dry-run
```

You should see it find your test ticket and print what it *would* do, without touching AD.

### 6\. Run it for real

```bash
python3 provisioning\_bot.py
```

Check your AD user list  the account should exist, be enabled, and be in the right groups. Check the ticket  it should have a comment with the temp password and be moved to `Done`.

### 7\. Run continuously (optional)

```bash
python3 provisioning\_bot.py --loop
```

Checks for new onboarding/offboarding tickets every 60 seconds. In production you'd run this as a background service or scheduled task instead of leaving a terminal open.

### 8\. Run the tests

```bash
python3 tests/test\_ad\_client.py
python3 tests/test\_ticket\_parser.py
python3 tests/test\_provisioning\_bot.py
```

## Possible future improvements

* Resolve AD groups dynamically instead of the placeholder DN pattern
* Deliver the temporary password securely (e.g. a one-time-view link) instead of writing it into a ticket comment
* Add a "Manager approval" gate before onboarding tickets are processed
* Use real JSM request-type custom fields instead of parsed description text
* Add Slack/email notification when a provisioning action fails

## 

