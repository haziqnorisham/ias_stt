"""LDAP/LDAPS access for LLDAP or Microsoft Active Directory.

This module owns all directory I/O. It never issues JWTs, reads password
attributes, assigns application roles, or contacts LDAP during API JWT checks.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import ssl
import re
import uuid
from urllib.parse import urlparse

from flask import current_app


class DirectoryError(Exception):
    """Base class for directory errors safe to translate at the API boundary."""


class DirectoryUnavailable(DirectoryError):
    """LDAP is disabled, misconfigured, or temporarily unreachable."""


class DirectoryInvalidCredentials(DirectoryError):
    """The supplied password was rejected by LDAP."""


class DirectoryIdentityNotFound(DirectoryError):
    """No matching user identity exists in the configured directory."""


class DirectoryAmbiguousIdentity(DirectoryError):
    """The directory search returned more than one matching identity."""


@dataclass(frozen=True)
class DirectoryIdentity:
    directory_key: str
    subject: str
    dn: str
    username: str
    display_name: str | None
    email: str | None
    is_enabled: bool | None

    def to_public_dict(self):
        return {
            "directory_key": self.directory_key,
            "directory_subject": self.subject,
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "is_enabled": self.is_enabled,
        }


class LDAPDirectory:
    """One configured LDAP directory adapter, selected by server config."""

    def __init__(self, config=None):
        self.config = config or current_app.config

    @property
    def directory_key(self):
        return self.config.get("LDAP_DIRECTORY_KEY", "primary")

    def _settings(self):
        if not self.config.get("LDAP_ENABLED"):
            raise DirectoryUnavailable("LDAP authentication is not enabled")

        uri = self.config.get("LDAP_SERVER_URI")
        bind_dn = self.config.get("LDAP_BIND_DN")
        bind_password = self.config.get("LDAP_BIND_PASSWORD")
        search_base = self.config.get("LDAP_SEARCH_BASE")
        subject_attribute = self.config.get("LDAP_SUBJECT_ATTRIBUTE")
        if not all((uri, bind_dn, bind_password, search_base, subject_attribute)):
            raise DirectoryUnavailable("LDAP configuration is incomplete")
        if (
            not str(self.directory_key).strip()
            or len(str(self.directory_key)) > 100
        ):
            raise DirectoryUnavailable("LDAP_DIRECTORY_KEY is invalid")

        parsed = urlparse(uri)
        if parsed.scheme not in {"ldap", "ldaps"} or not parsed.hostname:
            raise DirectoryUnavailable("LDAP_SERVER_URI must use ldap:// or ldaps://")
        starttls = bool(self.config.get("LDAP_STARTTLS"))
        allow_insecure = bool(self.config.get("LDAP_ALLOW_INSECURE"))
        if allow_insecure and not (
            self.config.get("TESTING") or self.config.get("DEBUG")
        ):
            raise DirectoryUnavailable(
                "Insecure LDAP transport is permitted only in development or tests"
            )
        if parsed.scheme == "ldap" and not starttls and not allow_insecure:
            raise DirectoryUnavailable("LDAP connections must use TLS")

        directory_type = self.config.get("LDAP_DIRECTORY_TYPE", "lldap")
        if directory_type not in {"lldap", "active_directory"}:
            raise DirectoryUnavailable("Unsupported LDAP_DIRECTORY_TYPE")
        if parsed.scheme == "ldaps" and starttls:
            raise DirectoryUnavailable("LDAP_STARTTLS cannot be used with an ldaps:// URI")

        attribute_names = [
            self.config.get("LDAP_USERNAME_ATTRIBUTE", "uid"),
            self.config.get("LDAP_DISPLAY_NAME_ATTRIBUTE", "displayName"),
            self.config.get("LDAP_EMAIL_ATTRIBUTE", "mail"),
            subject_attribute,
            self.config.get("LDAP_ENABLED_ATTRIBUTE"),
            *(self.config.get("LDAP_LOGIN_ATTRIBUTES") or []),
        ]
        for attribute in attribute_names:
            if attribute and not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9-]*(?:;[A-Za-z0-9-]+)*",
                attribute,
            ):
                raise DirectoryUnavailable("LDAP attribute mapping is invalid")

        return parsed, starttls, directory_type

    def _ldap_modules(self):
        try:
            from ldap3 import (
                ALL,
                NONE,
                Connection,
                Server,
                Tls,
                SUBTREE,
            )
            from ldap3.core.exceptions import LDAPException
            from ldap3.utils.conv import escape_bytes, escape_filter_chars
        except ImportError as exc:
            raise DirectoryUnavailable("LDAP support is not installed") from exc
        return {
            "ALL": ALL,
            "NONE": NONE,
            "Connection": Connection,
            "LDAPException": LDAPException,
            "Server": Server,
            "SUBTREE": SUBTREE,
            "Tls": Tls,
            "escape_bytes": escape_bytes,
            "escape_filter_chars": escape_filter_chars,
        }

    def _connection(self, user=None, password=None, service_bind=False):
        ldap = self._ldap_modules()
        parsed, starttls, _ = self._settings()
        tls = ldap["Tls"](
            validate=ssl.CERT_REQUIRED,
            ca_certs_file=self.config.get("LDAP_CA_CERT_FILE"),
        )
        server = ldap["Server"](
            parsed.hostname,
            port=parsed.port or (636 if parsed.scheme == "ldaps" else 389),
            use_ssl=parsed.scheme == "ldaps",
            tls=tls,
            get_info=ldap["NONE"],
            connect_timeout=float(self.config.get("LDAP_CONNECT_TIMEOUT", 5)),
        )
        if service_bind:
            user = self.config.get("LDAP_BIND_DN")
            password = self.config.get("LDAP_BIND_PASSWORD")
        connection = None
        try:
            connection = ldap["Connection"](
                server,
                user=user,
                password=password,
                auto_bind=False,
                auto_referrals=False,
                receive_timeout=float(self.config.get("LDAP_RECEIVE_TIMEOUT", 5)),
                raise_exceptions=False,
            )
            if not connection.open():
                raise DirectoryUnavailable("Unable to connect to LDAP")
            if starttls and not connection.start_tls():
                raise DirectoryUnavailable("Unable to establish LDAP TLS")
            if not connection.bind():
                result = getattr(connection, "result", {}) or {}
                if service_bind:
                    raise DirectoryUnavailable("LDAP service bind failed")
                if str(result.get("description", "")).casefold() in {
                    "invalidcredentials",
                    "strongerauthrequired",
                } or result.get("result") == 49:
                    raise DirectoryInvalidCredentials()
                raise DirectoryUnavailable("LDAP user bind failed")
            return connection
        except DirectoryError:
            if connection is not None:
                try:
                    connection.unbind()
                except Exception:
                    pass
            raise
        except ldap["LDAPException"] as exc:
            if connection is not None:
                try:
                    connection.unbind()
                except Exception:
                    pass
            raise DirectoryUnavailable("LDAP operation failed") from exc
        except (OSError, ssl.SSLError, TimeoutError) as exc:
            if connection is not None:
                try:
                    connection.unbind()
                except Exception:
                    pass
            raise DirectoryUnavailable("LDAP connection failed") from exc

    @staticmethod
    def _first_value(attributes, name):
        if not name:
            return None
        value = attributes.get(name)
        if value is None:
            value = next(
                (
                    candidate
                    for key, candidate in attributes.items()
                    if str(key).casefold() == str(name).casefold()
                ),
                None,
            )
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8")
            except UnicodeDecodeError:
                return value
        if value is None:
            return None
        return str(value).strip()

    def _subject_value(self, value, directory_type):
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value is None:
            return None
        subject_attribute = str(self.config["LDAP_SUBJECT_ATTRIBUTE"]).casefold()
        if directory_type == "active_directory" and subject_attribute == "objectguid":
            if isinstance(value, bytes):
                return str(uuid.UUID(bytes_le=value))
            try:
                return str(uuid.UUID(str(value)))
            except ValueError:
                return None
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8")
            except UnicodeDecodeError:
                return value.hex()
        return str(value).strip()

    def _account_enabled(self, attributes, directory_type):
        if directory_type == "active_directory":
            user_control = self._first_value(attributes, "userAccountControl")
            if user_control is not None:
                try:
                    if int(user_control) & 0x2:
                        return False
                except ValueError:
                    return False

            account_expires = self._first_value(attributes, "accountExpires")
            if account_expires:
                try:
                    ticks = int(account_expires)
                    if ticks not in (0, 9223372036854775807):
                        expiry = datetime.fromtimestamp(
                            ticks / 10_000_000 - 11644473600,
                            tz=timezone.utc,
                        )
                        if expiry <= datetime.now(timezone.utc):
                            return False
                except (ValueError, OverflowError, OSError):
                    return False

        enabled_attribute = self.config.get("LDAP_ENABLED_ATTRIBUTE")
        if enabled_attribute:
            value = self._first_value(attributes, enabled_attribute)
            if value is None:
                return False
            allowed = self.config.get("LDAP_ENABLED_VALUES", {"true", "1", "yes"})
            return value.casefold() in allowed
        return None

    def _entry_to_identity(self, entry):
        _, _, directory_type = self._settings()
        attributes = entry.entry_attributes_as_dict
        subject_raw = next(
            (
                value
                for key, value in attributes.items()
                if str(key).casefold()
                == str(self.config["LDAP_SUBJECT_ATTRIBUTE"]).casefold()
            ),
            None,
        )
        subject = self._subject_value(
            subject_raw,
            directory_type,
        )
        username = self._first_value(
            attributes, self.config.get("LDAP_USERNAME_ATTRIBUTE", "uid")
        )
        if (
            not subject
            or not username
            or len(subject) > 255
            or len(username) > 150
        ):
            raise DirectoryUnavailable(
                "LDAP user entry has missing or invalid identity attributes"
            )

        display_name = self._first_value(
            attributes,
            self.config.get("LDAP_DISPLAY_NAME_ATTRIBUTE", "displayName"),
        )
        if not display_name:
            given_name = self._first_value(attributes, "givenName")
            surname = self._first_value(attributes, "sn")
            display_name = " ".join(value for value in (given_name, surname) if value)
        email = self._first_value(
            attributes, self.config.get("LDAP_EMAIL_ATTRIBUTE", "mail")
        )
        dn = str(entry.entry_dn)
        if (
            len(dn) > 1024
            or len(display_name or username) > 255
            or (email is not None and len(email) > 255)
        ):
            raise DirectoryUnavailable("LDAP user profile exceeds application field limits")
        return DirectoryIdentity(
            directory_key=self.directory_key,
            subject=subject,
            dn=dn,
            username=username,
            display_name=display_name or username,
            email=email,
            is_enabled=self._account_enabled(attributes, directory_type),
        )

    def _attributes_to_fetch(self):
        attrs = {
            self.config["LDAP_SUBJECT_ATTRIBUTE"],
            self.config.get("LDAP_USERNAME_ATTRIBUTE", "uid"),
            self.config.get("LDAP_DISPLAY_NAME_ATTRIBUTE", "displayName"),
            self.config.get("LDAP_EMAIL_ATTRIBUTE", "mail"),
            "givenName",
            "sn",
        }
        enabled_attribute = self.config.get("LDAP_ENABLED_ATTRIBUTE")
        if enabled_attribute:
            attrs.add(enabled_attribute)
        if self.config.get("LDAP_DIRECTORY_TYPE") == "active_directory":
            attrs.update({"userAccountControl", "accountExpires"})
        return sorted(value for value in attrs if value)

    def _lookup(self, filter_value, require_single=True):
        ldap = self._ldap_modules()
        self._settings()
        search_filter = f"(&{self.config['LDAP_USER_FILTER']}{filter_value})"
        connection = self._connection(service_bind=True)
        try:
            search_succeeded = connection.search(
                search_base=self.config["LDAP_SEARCH_BASE"],
                search_filter=search_filter,
                search_scope=ldap["SUBTREE"],
                attributes=self._attributes_to_fetch(),
                size_limit=max(1, int(self.config.get("LDAP_SEARCH_LIMIT", 200))),
            )
            result = getattr(connection, "result", {}) or {}
            result_code = result.get("result", 0)
            if require_single and result_code == 4:
                raise DirectoryAmbiguousIdentity()
            if not search_succeeded and result_code not in {0, 4}:
                raise DirectoryUnavailable("LDAP search was rejected")
            entries = list(connection.entries)
            if not entries:
                return []
            if require_single and len(entries) != 1:
                raise DirectoryAmbiguousIdentity()
            return [self._entry_to_identity(entry) for entry in entries]
        except DirectoryError:
            raise
        except ldap["LDAPException"] as exc:
            raise DirectoryUnavailable("LDAP search failed") from exc
        except Exception as exc:
            raise DirectoryUnavailable("LDAP search failed") from exc
        finally:
            try:
                connection.unbind()
            except Exception:
                pass

    def _escape_text(self, value):
        ldap = self._ldap_modules()
        return ldap["escape_filter_chars"](str(value))

    def _subject_filter_value(self, subject):
        _, _, directory_type = self._settings()
        attribute = str(self.config["LDAP_SUBJECT_ATTRIBUTE"]).casefold()
        if directory_type == "active_directory" and attribute == "objectguid":
            try:
                raw = uuid.UUID(str(subject)).bytes_le
            except (ValueError, AttributeError) as exc:
                raise DirectoryIdentityNotFound() from exc
            return self._ldap_modules()["escape_bytes"](raw)
        return self._escape_text(subject)

    def find_by_subject(self, subject):
        attribute = self.config.get("LDAP_SUBJECT_ATTRIBUTE")
        if not attribute:
            raise DirectoryUnavailable("LDAP_SUBJECT_ATTRIBUTE is not configured")
        matches = self._lookup(
            f"({attribute}={self._subject_filter_value(subject)})"
        )
        return matches[0] if matches else None

    def find_by_login(self, username):
        attrs = self.config.get("LDAP_LOGIN_ATTRIBUTES") or [
            self.config.get("LDAP_USERNAME_ATTRIBUTE", "uid")
        ]
        if not attrs:
            raise DirectoryUnavailable("LDAP_LOGIN_ATTRIBUTES is empty")
        clauses = "".join(
            f"({attribute}={self._escape_text(username)})" for attribute in attrs
        )
        matches = self._lookup(f"(|{clauses})")
        return matches[0] if matches else None

    def search_users(self, search):
        escaped = self._escape_text(search)
        attrs = {
            self.config.get("LDAP_USERNAME_ATTRIBUTE", "uid"),
            self.config.get("LDAP_DISPLAY_NAME_ATTRIBUTE", "displayName"),
            self.config.get("LDAP_EMAIL_ATTRIBUTE", "mail"),
        }
        clauses = "".join(
            f"({attribute}=*{escaped}*)" for attribute in sorted(attrs) if attribute
        )
        return self._lookup(f"(|{clauses})", require_single=False)

    def authenticate(self, identity, password):
        if not password:
            raise DirectoryInvalidCredentials()
        connection = self._connection(user=identity.dn, password=password)
        try:
            return True
        finally:
            try:
                connection.unbind()
            except Exception:
                pass


def get_ldap_directory():
    """Return a request-scoped adapter using the current Flask config."""
    return LDAPDirectory()
