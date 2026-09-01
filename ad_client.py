"""
ad_client.py
=============
A small wrapper around python-ldap3 for the Active Directory operations
an onboarding/offboarding workflow needs: create a user account, set an
initial password, enable/disable the account, and manage group
membership.

This talks to a real, on-prem Active Directory domain controller over
LDAP (ideally LDAPS/SSL, since setting a password over plain LDAP is
rejected by AD for security reasons). See README.md for how to point
this at your own lab domain controller.

No CLI code lives here on purpose — see provisioning_bot.py for the
script that ties this together with Jira Service Management.
"""

import os
import ssl

from ldap3 import Server, Connection, Tls, ALL, MODIFY_REPLACE, SUBTREE

# Active Directory's userAccountControl bit flags (we only need these two).
UAC_NORMAL_ACCOUNT = 512      # normal, enabled account
UAC_ACCOUNT_DISABLED = 514    # normal account + "disabled" bit set


class ADClient:
    def __init__(self, server_address=None, domain=None, bind_user=None,
                 bind_password=None, base_dn=None, users_ou=None, use_ssl=True):
        self.server_address = server_address or os.environ.get("AD_SERVER")
        self.domain = domain or os.environ.get("AD_DOMAIN")
        self.bind_user = bind_user or os.environ.get("AD_BIND_USER")
        self.bind_password = bind_password or os.environ.get("AD_BIND_PASSWORD")
        self.base_dn = base_dn or os.environ.get("AD_BASE_DN")
        self.users_ou = users_ou or os.environ.get("AD_USERS_OU", self.base_dn)
        self.use_ssl = use_ssl

        if not all([self.server_address, self.domain, self.bind_user,
                    self.bind_password, self.base_dn]):
            raise ValueError(
                "Missing Active Directory configuration. Set AD_SERVER, AD_DOMAIN, "
                "AD_BIND_USER, AD_BIND_PASSWORD, and AD_BASE_DN (e.g. in a .env file). "
                "See README.md for setup instructions."
            )

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------
    def _connect(self):
        tls_config = Tls(validate=ssl.CERT_NONE) if self.use_ssl else None
        server = Server(self.server_address, use_ssl=self.use_ssl, tls=tls_config, get_info=ALL)
        conn = Connection(
            server,
            user=f"{self.bind_user}@{self.domain}",
            password=self.bind_password,
            auto_bind=True,
        )
        return conn

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    def find_user(self, username):
        """Return the LDAP entry for a user by sAMAccountName, or None if not found."""
        conn = self._connect()
        try:
            conn.search(
                search_base=self.base_dn,
                search_filter=f"(sAMAccountName={username})",
                search_scope=SUBTREE,
                attributes=["distinguishedName", "displayName", "userAccountControl", "memberOf"],
            )
            if not conn.entries:
                return None
            return conn.entries[0]
        finally:
            conn.unbind()

    def user_exists(self, username):
        return self.find_user(username) is not None

    # ------------------------------------------------------------------
    # Onboarding
    # ------------------------------------------------------------------
    def create_user(self, username, full_name, job_title="", department="",
                     manager_dn=None, temp_password=None):
        """
        Create a new, enabled AD user account under the configured Users OU.
        Returns the new user's distinguishedName.
        """
        if self.user_exists(username):
            raise ValueError(f"AD account '{username}' already exists.")

        user_dn = f"CN={full_name},{self.users_ou}"
        first_name, _, last_name = full_name.partition(" ")

        attributes = {
            "objectClass": ["top", "person", "organizationalPerson", "user"],
            "sAMAccountName": username,
            "userPrincipalName": f"{username}@{self.domain}",
            "displayName": full_name,
            "givenName": first_name,
            "sn": last_name or first_name,
            "title": job_title,
            "department": department,
            "userAccountControl": UAC_ACCOUNT_DISABLED,  # created disabled until password is set
        }
        if manager_dn:
            attributes["manager"] = manager_dn

        conn = self._connect()
        try:
            success = conn.add(user_dn, attributes=attributes)
            if not success:
                raise RuntimeError(f"Failed to create AD user: {conn.result}")

            if temp_password:
                self._set_password(conn, user_dn, temp_password)

            # Now that a password is set, enable the account.
            conn.modify(user_dn, {"userAccountControl": [(MODIFY_REPLACE, [UAC_NORMAL_ACCOUNT])]})
            return user_dn
        finally:
            conn.unbind()

    @staticmethod
    def _set_password(conn, user_dn, password):
        """
        AD requires the password wrapped in quotes, UTF-16LE encoded, and
        sent over an encrypted (LDAPS) connection — plain LDAP will reject it.
        """
        encoded_password = f'"{password}"'.encode("utf-16-le")
        success = conn.modify(
            user_dn, {"unicodePwd": [(MODIFY_REPLACE, [encoded_password])]}
        )
        if not success:
            raise RuntimeError(f"Failed to set password: {conn.result}")

    # ------------------------------------------------------------------
    # Offboarding
    # ------------------------------------------------------------------
    def disable_user(self, username):
        entry = self.find_user(username)
        if not entry:
            raise ValueError(f"AD account '{username}' not found.")

        conn = self._connect()
        try:
            conn.modify(
                entry.entry_dn,
                {"userAccountControl": [(MODIFY_REPLACE, [UAC_ACCOUNT_DISABLED])]},
            )
            return True
        finally:
            conn.unbind()

    def remove_all_group_memberships(self, username):
        """Remove a disabled user from every group they currently belong to."""
        from ldap3 import MODIFY_DELETE

        entry = self.find_user(username)
        if not entry:
            raise ValueError(f"AD account '{username}' not found.")

        groups = list(entry.memberOf) if "memberOf" in entry else []
        conn = self._connect()
        try:
            removed = []
            for group_dn in groups:
                success = conn.modify(group_dn, {"member": [(MODIFY_DELETE, [entry.entry_dn])]})
                if success:
                    removed.append(group_dn)
            return removed
        finally:
            conn.unbind()

    # ------------------------------------------------------------------
    # Group membership (onboarding uses this too)
    # ------------------------------------------------------------------
    def add_to_group(self, username, group_dn):
        from ldap3 import MODIFY_ADD

        entry = self.find_user(username)
        if not entry:
            raise ValueError(f"AD account '{username}' not found.")

        conn = self._connect()
        try:
            success = conn.modify(group_dn, {"member": [(MODIFY_ADD, [entry.entry_dn])]})
            if not success:
                raise RuntimeError(f"Failed to add {username} to {group_dn}: {conn.result}")
            return True
        finally:
            conn.unbind()

    def remove_from_group(self, username, group_dn):
        from ldap3 import MODIFY_DELETE

        entry = self.find_user(username)
        if not entry:
            raise ValueError(f"AD account '{username}' not found.")

        conn = self._connect()
        try:
            success = conn.modify(group_dn, {"member": [(MODIFY_DELETE, [entry.entry_dn])]})
            if not success:
                raise RuntimeError(f"Failed to remove {username} from {group_dn}: {conn.result}")
            return True
        finally:
            conn.unbind()
