import json
import ssl
import unittest
from dataclasses import replace
from unittest.mock import Mock, call, patch

from flask_jwt_extended import decode_token
from sqlalchemy import create_engine, inspect

from app import create_app
from app.config import Config
from app.models.database import db
from app.models.user import User
from app.schema_migrations import upgrade_schema
from app.services.ldap_directory import (
    LDAPDirectory,
    DirectoryIdentity,
    DirectoryInvalidCredentials,
    DirectoryUnavailable,
)


class LDAPTestConfig(Config):
    API_KEY = None
    ENABLE_FRONTEND = False
    LOG_DIR = "/tmp/ias_stt_ldap_test_logs"
    LOG_LEVEL = "CRITICAL"
    MQTT_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    JWT_SECRET_KEY = "ldap-test-secret-with-enough-entropy-and-length"
    LDAP_ENABLED = True
    LDAP_DIRECTORY_KEY = "test-directory"
    LDAP_DIRECTORY_TYPE = "lldap"
    LDAP_SERVER_URI = "ldaps://directory.example.test:636"
    LDAP_BIND_DN = "cn=readonly,dc=example,dc=test"
    LDAP_BIND_PASSWORD = "directory-bind-secret"
    LDAP_SEARCH_BASE = "dc=example,dc=test"
    LDAP_SUBJECT_ATTRIBUTE = "uuid"


class FakeLDAPDirectory:
    directory_key = "test-directory"

    def __init__(self):
        self.identities = {
            "stable-id-001": DirectoryIdentity(
                directory_key=self.directory_key,
                subject="stable-id-001",
                dn="uid=ldap.user,dc=example,dc=test",
                username="ldap.user",
                display_name="LDAP User",
                email="ldap.user@example.test",
                is_enabled=True,
            )
        }
        self.passwords = {"stable-id-001": "ldap-password"}
        self.authenticate_calls = []
        self.lookup_calls = []
        self.unavailable = False

    def find_by_login(self, username):
        self.lookup_calls.append(("login", username))
        self._raise_if_unavailable()
        for identity in self.identities.values():
            if identity.username.casefold() == username.casefold():
                return identity
        return None

    def find_by_subject(self, subject):
        self.lookup_calls.append(("subject", subject))
        self._raise_if_unavailable()
        return self.identities.get(subject)

    def search_users(self, search):
        self._raise_if_unavailable()
        term = search.casefold()
        return [
            identity
            for identity in self.identities.values()
            if term in identity.username.casefold()
            or term in (identity.display_name or "").casefold()
            or term in (identity.email or "").casefold()
        ]

    def authenticate(self, identity, password):
        self.authenticate_calls.append((identity.subject, password))
        self._raise_if_unavailable()
        if self.passwords.get(identity.subject) != password:
            raise DirectoryInvalidCredentials()
        return True

    def _raise_if_unavailable(self):
        if self.unavailable:
            raise DirectoryUnavailable()


class LDAPAuthApiTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(LDAPTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()
        self.directory = FakeLDAPDirectory()
        self.auth_directory_patch = patch(
            "app.routes.auth.get_ldap_directory",
            return_value=self.directory,
        )
        self.users_directory_patch = patch(
            "app.routes.users.get_ldap_directory",
            return_value=self.directory,
        )
        self.auth_directory_patch.start()
        self.users_directory_patch.start()
        self.admin = self._add_user("admin", "administrator", "admin-password")
        self.operator = self._add_user(
            "operator", "field_operator", "operator-password"
        )

    def tearDown(self):
        self.auth_directory_patch.stop()
        self.users_directory_patch.stop()
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _add_user(self, username, role, password):
        user = User(
            username=username,
            auth_provider="LOCAL",
            role=role,
            display_name=username.title(),
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    def _login(self, username, password, secure=True):
        return self.client.post(
            "/auth/login",
            json={"username": username, "password": password},
            base_url="https://localhost" if secure else "http://localhost",
        )

    def _headers(self, username="admin", password="admin-password"):
        response = self._login(username, password)
        self.assertEqual(response.status_code, 200, response.get_json())
        return {"Authorization": f"Bearer {response.get_json()['access_token']}"}

    def _provision_ldap(self, role="field_operator"):
        response = self.client.post(
            "/api/users",
            json={
                "auth_provider": "LDAP",
                "directory_subject": "stable-id-001",
                "role": role,
                "is_active": True,
            },
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def test_admin_provisions_ldap_user_without_password_and_local_role(self):
        created = self._provision_ldap()

        self.assertEqual(created["auth_provider"], "LDAP")
        self.assertEqual(created["username"], "ldap.user")
        self.assertEqual(created["role"], "field_operator")
        self.assertEqual(created["directory_subject"], "stable-id-001")
        self.assertNotIn("password_hash", created)
        self.assertIsNone(db.session.get(User, created["id"]).password_hash)

        duplicate = self.client.post(
            "/api/users",
            json={
                "auth_provider": "LDAP",
                "directory_subject": "stable-id-001",
                "role": "read_only",
            },
            headers=self._headers(),
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_provider_selection_and_local_user_create_are_explicit(self):
        missing_provider = self.client.post(
            "/api/users",
            json={
                "username": "ambiguous",
                "password": "local-password",
                "role": "read_only",
            },
            headers=self._headers(),
        )
        self.assertEqual(missing_provider.status_code, 422)

        local = self.client.post(
            "/api/users",
            json={
                "auth_provider": "LOCAL",
                "username": "breakglass",
                "password": "local-password",
                "display_name": "Break Glass",
                "email": "breakglass@example.test",
                "role": "administrator",
            },
            headers=self._headers(),
        )
        self.assertEqual(local.status_code, 201)
        self.assertEqual(local.get_json()["auth_provider"], "LOCAL")
        self.assertTrue(
            db.session.get(User, local.get_json()["id"]).check_password("local-password")
        )

    def test_ldap_login_syncs_profile_and_issues_normal_local_id_jwt(self):
        provisioned = self._provision_ldap()
        identity = replace(
            self.directory.identities["stable-id-001"],
            dn="uid=ldap.user,ou=moved,dc=example,dc=test",
            display_name="Updated LDAP User",
            email="updated@example.test",
        )
        self.directory.identities["stable-id-001"] = identity
        self.directory.lookup_calls.clear()
        with patch.object(
            self.directory, "authenticate", wraps=self.directory.authenticate
        ) as authenticate:
            response = self._login("ldap.user", "ldap-password")
            authenticate.assert_called_once_with(identity, "ldap-password")

        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual(body["user"]["id"], provisioned["id"])
        self.assertEqual(body["user"]["auth_provider"], "LDAP")
        self.assertEqual(body["user"]["role"], "field_operator")
        self.assertEqual(self.directory.authenticate_calls[-1], ("stable-id-001", "ldap-password"))
        self.assertEqual(self.directory.lookup_calls, [("subject", "stable-id-001")])
        user = db.session.get(User, provisioned["id"])
        self.assertEqual(user.ldap_dn, identity.dn)
        self.assertEqual(user.display_name, identity.display_name)
        self.assertEqual(user.email, identity.email)
        self.assertIsNotNone(user.ldap_synced_at)

        claims = decode_token(body["access_token"])
        self.assertEqual(claims["sub"], str(provisioned["id"]))
        self.assertEqual(claims["auth_provider"], "LDAP")
        self.assertEqual(claims["role"], "field_operator")
        self.assertEqual(claims["token_version"], 0)
        self.assertNotIn("password", claims)
        self.assertNotIn("directory-bind-secret", json.dumps(claims))

    def test_failed_ldap_auth_does_not_fall_back_to_local(self):
        self._provision_ldap()
        response = self._login("ldap.user", "wrong-password")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_CREDENTIALS")
        self.assertEqual(len(self.directory.authenticate_calls), 1)
        self.assertIsNone(
            User.query.filter_by(directory_subject="stable-id-001").one().password_hash
        )

    def test_unprovisioned_ldap_identity_cannot_sign_in(self):
        for unavailable in (False, True):
            with self.subTest(directory_unavailable=unavailable):
                self.directory.unavailable = unavailable
                with patch(
                    "app.routes.auth.get_ldap_directory", return_value=self.directory
                ) as directory_factory:
                    response = self._login("ldap.user", "ldap-password")
                self.assertEqual(response.status_code, 401)
                self.assertEqual(
                    response.get_json()["error"]["code"], "INVALID_CREDENTIALS"
                )
                directory_factory.assert_not_called()
        self.assertEqual(self.directory.lookup_calls, [])
        self.assertEqual(self.directory.authenticate_calls, [])

    def test_locally_disabled_ldap_user_cannot_login_after_directory_rename(self):
        provisioned = self._provision_ldap()
        user = db.session.get(User, provisioned["id"])
        user.is_active = False
        db.session.commit()
        self.directory.identities["stable-id-001"] = replace(
            self.directory.identities["stable-id-001"],
            username="ldap.renamed",
        )

        self.directory.lookup_calls.clear()
        for username in ("ldap.user", "ldap.renamed"):
            with self.subTest(username=username):
                response = self._login(username, "ldap-password")
                self.assertEqual(response.status_code, 401)
        self.assertEqual(self.directory.lookup_calls, [])
        self.assertEqual(self.directory.authenticate_calls, [])

    def test_ldap_username_rename_requires_profile_sync_before_login(self):
        provisioned = self._provision_ldap()
        self.directory.identities["stable-id-001"] = replace(
            self.directory.identities["stable-id-001"],
            username="ldap.renamed",
        )
        self.directory.lookup_calls.clear()

        old_username = self._login("ldap.user", "ldap-password")
        self.assertEqual(old_username.status_code, 401)
        self.assertEqual(self.directory.lookup_calls, [("subject", "stable-id-001")])
        self.directory.lookup_calls.clear()
        new_username = self._login("ldap.renamed", "ldap-password")
        self.assertEqual(new_username.status_code, 401)
        self.assertEqual(self.directory.lookup_calls, [])
        self.assertEqual(self.directory.authenticate_calls, [])

        synced = self.client.post(
            f"/api/users/{provisioned['id']}/sync-profile",
            headers=self._headers(),
        )
        self.assertEqual(synced.status_code, 200)
        login = self._login("ldap.renamed", "ldap-password")
        self.assertEqual(login.status_code, 200, login.get_json())
        self.assertEqual(login.get_json()["user"]["id"], provisioned["id"])

    def test_login_matches_application_username_case_insensitively(self):
        self._provision_ldap()
        for username, password, provider in (
            (" OPERATOR ", "operator-password", "LOCAL"),
            (" LDAP.USER ", "ldap-password", "LDAP"),
        ):
            with self.subTest(provider=provider):
                response = self._login(username, password)
                self.assertEqual(response.status_code, 200, response.get_json())
                self.assertEqual(response.get_json()["user"]["auth_provider"], provider)

    def test_local_authentication_does_not_depend_on_ldap(self):
        self.directory.unavailable = True

        response = self._login("operator", "operator-password")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.directory.lookup_calls, [])
        self.assertEqual(self.directory.authenticate_calls, [])

    def test_ldap_login_reports_provider_outage(self):
        self._provision_ldap()
        self.directory.unavailable = True

        response = self._login("ldap.user", "ldap-password")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json()["error"]["code"],
            "AUTH_PROVIDER_UNAVAILABLE",
        )
        self.assertEqual(self.directory.authenticate_calls, [])

    def test_ldap_socket_timeouts_are_integers(self):
        self.assertIsInstance(LDAPTestConfig.LDAP_CONNECT_TIMEOUT, int)
        self.assertIsInstance(LDAPTestConfig.LDAP_RECEIVE_TIMEOUT, int)

    def test_refresh_checks_directory_account_and_returns_provider_outage(self):
        self._provision_ldap()
        login = self._login("ldap.user", "ldap-password").get_json()
        refresh_headers = {"Authorization": f"Bearer {login['refresh_token']}"}

        disabled = replace(
            self.directory.identities["stable-id-001"],
            is_enabled=False,
        )
        self.directory.identities["stable-id-001"] = disabled

        # Access JWTs remain local/stateless until their short expiry; normal
        # requests must not start querying LDAP after the account is disabled.
        access_headers = {"Authorization": f"Bearer {login['access_token']}"}
        self.directory.lookup_calls.clear()
        access = self.client.get("/api/traps", headers=access_headers)
        self.assertEqual(access.status_code, 200)
        self.assertEqual(self.directory.lookup_calls, [])

        rejected = self.client.post("/auth/refresh", headers=refresh_headers)
        self.assertEqual(rejected.status_code, 401)

        self.directory.identities["stable-id-001"] = replace(disabled, is_enabled=True)
        self.directory.unavailable = True
        unavailable = self.client.post("/auth/refresh", headers=refresh_headers)
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(
            unavailable.get_json()["error"]["code"],
            "AUTH_PROVIDER_UNAVAILABLE",
        )

    def test_ordinary_jwt_requests_do_not_contact_ldap_and_local_disable_revokes(self):
        provisioned = self._provision_ldap()
        login = self._login("ldap.user", "ldap-password").get_json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}
        self.directory.lookup_calls.clear()
        self.directory.authenticate_calls.clear()

        response = self.client.get("/api/traps", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.directory.lookup_calls, [])
        self.assertEqual(self.directory.authenticate_calls, [])

        updated = self.client.put(
            f"/api/users/{provisioned['id']}",
            json={"is_active": False},
            headers=self._headers(),
        )
        self.assertEqual(updated.status_code, 200)
        rejected = self.client.get("/api/traps", headers=headers)
        self.assertEqual(rejected.status_code, 401)

    def test_ldap_credentials_are_accepted_over_plain_http_outside_testing(self):
        self._provision_ldap()
        self.app.config["TESTING"] = False
        self.app.config["DEBUG"] = False

        response = self._login("ldap.user", "ldap-password", secure=False)

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["user"]["auth_provider"], "LDAP")
        self.assertIn("access_token", response.get_json())
        self.assertIn("refresh_token", response.get_json())
        self.assertEqual(
            self.directory.authenticate_calls, [("stable-id-001", "ldap-password")]
        )

    def test_local_credentials_are_accepted_over_plain_http_outside_testing(self):
        self.app.config["TESTING"] = False
        self.app.config["DEBUG"] = False

        response = self._login("operator", "operator-password", secure=False)

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["user"]["auth_provider"], "LOCAL")
        self.assertIn("access_token", response.get_json())
        self.assertIn("refresh_token", response.get_json())
        self.assertEqual(self.directory.lookup_calls, [])
        self.assertEqual(self.directory.authenticate_calls, [])

    def test_directory_search_is_admin_only_and_does_not_return_dn(self):
        headers = self._headers()
        response = self.client.get(
            "/api/ldap/users?search=ldap&limit=10",
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["directory_subject"], "stable-id-001")
        self.assertNotIn("dn", body[0])

        forbidden = self.client.get(
            "/api/ldap/users?search=ldap",
            headers=self._headers("operator", "operator-password"),
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_ldap_profile_sync_preserves_local_role_and_username_collisions_fail(self):
        provisioned = self._provision_ldap(role="read_only")
        self.directory.identities["stable-id-001"] = replace(
            self.directory.identities["stable-id-001"],
            username="ldap.renamed",
            display_name="Updated Directory Name",
            email="renamed@example.test",
        )
        response = self.client.post(
            f"/api/users/{provisioned['id']}/sync-profile",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["username"], "ldap.renamed")
        self.assertEqual(response.get_json()["role"], "read_only")

        self.directory.identities["stable-id-001"] = replace(
            self.directory.identities["stable-id-001"],
            username="operator",
        )
        conflict = self.client.post(
            f"/api/users/{provisioned['id']}/sync-profile",
            headers=self._headers(),
        )
        self.assertEqual(conflict.status_code, 409)

    def test_ldap_administrator_cannot_remove_last_local_break_glass_admin(self):
        self._provision_ldap(role="administrator")
        headers = self._headers("ldap.user", "ldap-password")

        deactivated = self.client.put(
            f"/api/users/{self.admin.id}",
            json={"is_active": False},
            headers=headers,
        )
        self.assertEqual(deactivated.status_code, 409)

        demoted = self.client.put(
            f"/api/users/{self.admin.id}",
            json={"role": "read_only"},
            headers=headers,
        )
        self.assertEqual(demoted.status_code, 409)

        deleted = self.client.delete(
            f"/api/users/{self.admin.id}",
            headers=headers,
        )
        self.assertEqual(deleted.status_code, 409)


class LDAPDirectoryTransportTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "LDAP_ENABLED": True,
            "LDAP_DIRECTORY_KEY": "test-directory",
            "LDAP_DIRECTORY_TYPE": "lldap",
            "LDAP_SERVER_URI": "ldap://directory.example.test",
            "LDAP_STARTTLS": False,
            "LDAP_BIND_DN": "cn=readonly,dc=example,dc=test",
            "LDAP_BIND_PASSWORD": "service-password",
            "LDAP_SEARCH_BASE": "dc=example,dc=test",
            "LDAP_SUBJECT_ATTRIBUTE": "uuid",
            "LDAP_CA_CERT_FILE": "/unused/custom-ca.pem",
            "TESTING": False,
            "DEBUG": False,
        }

    def test_plain_ldap_service_and_user_binds_work_in_production_without_opt_in(self):
        for legacy_allow_insecure in (None, False, True):
            config = dict(self.config)
            if legacy_allow_insecure is not None:
                config["LDAP_ALLOW_INSECURE"] = legacy_allow_insecure
            for service_bind in (False, True):
                with (
                    self.subTest(
                        legacy_allow_insecure=legacy_allow_insecure,
                        service_bind=service_bind,
                    ),
                    patch("ldap3.Tls") as tls_factory,
                    patch("ldap3.Server") as server_factory,
                    patch("ldap3.Connection") as connection_factory,
                ):
                    connection = Mock()
                    connection.open.return_value = True
                    connection.bind.return_value = True
                    connection_factory.return_value = connection

                    bound = LDAPDirectory(config)._connection(
                        user="uid=person,dc=example,dc=test",
                        password="user-password",
                        service_bind=service_bind,
                    )

                    self.assertIs(bound, connection)
                    tls_factory.assert_not_called()
                    self.assertFalse(server_factory.call_args.kwargs["use_ssl"])
                    self.assertIsNone(server_factory.call_args.kwargs["tls"])
                    self.assertEqual(server_factory.call_args.kwargs["port"], 389)
                    credentials = connection_factory.call_args.kwargs
                    self.assertEqual(
                        credentials["user"],
                        config["LDAP_BIND_DN"] if service_bind
                        else "uid=person,dc=example,dc=test",
                    )
                    self.assertEqual(
                        credentials["password"],
                        config["LDAP_BIND_PASSWORD"] if service_bind
                        else "user-password",
                    )
                    self.assertEqual(
                        connection.method_calls, [call.open(), call.bind()]
                    )

    def test_ldaps_and_starttls_are_optional_with_certificate_validation(self):
        for scheme, starttls, port in (("ldaps", False, 636), ("ldap", True, 389)):
            with (
                self.subTest(scheme=scheme, starttls=starttls),
                patch("ldap3.Tls") as tls_factory,
                patch("ldap3.Server") as server_factory,
                patch("ldap3.Connection") as connection_factory,
            ):
                config = dict(
                    self.config,
                    LDAP_SERVER_URI=f"{scheme}://directory.example.test",
                    LDAP_STARTTLS=starttls,
                )
                connection = Mock()
                connection.open.return_value = True
                connection.start_tls.return_value = True
                connection.bind.return_value = True
                connection_factory.return_value = connection

                LDAPDirectory(config)._connection(service_bind=True)

                tls_factory.assert_called_once_with(
                    validate=ssl.CERT_REQUIRED,
                    ca_certs_file=config["LDAP_CA_CERT_FILE"],
                )
                self.assertEqual(
                    server_factory.call_args.kwargs["use_ssl"], scheme == "ldaps"
                )
                self.assertEqual(server_factory.call_args.kwargs["port"], port)
                self.assertIs(
                    server_factory.call_args.kwargs["tls"], tls_factory.return_value
                )
                expected_calls = [call.open()]
                if starttls:
                    expected_calls.append(call.start_tls())
                expected_calls.append(call.bind())
                self.assertEqual(connection.method_calls, expected_calls)

    def test_configured_starttls_failure_does_not_bind_in_plaintext(self):
        config = dict(self.config, LDAP_STARTTLS=True)
        connection = Mock()
        connection.open.return_value = True
        connection.start_tls.return_value = False
        with (
            patch("ldap3.Tls"),
            patch("ldap3.Server"),
            patch("ldap3.Connection", return_value=connection),
        ):
            with self.assertRaisesRegex(
                DirectoryUnavailable, "Unable to establish LDAP TLS"
            ):
                LDAPDirectory(config)._connection(service_bind=True)
        connection.bind.assert_not_called()
        connection.unbind.assert_called_once_with()


class UserSchemaMigrationTest(unittest.TestCase):
    def test_existing_local_users_keep_hashes_and_get_provider_columns(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, "
                "username VARCHAR(150) NOT NULL UNIQUE, "
                "password_hash VARCHAR(255) NOT NULL, "
                "display_name VARCHAR(255), email VARCHAR(255), "
                "role VARCHAR(32) NOT NULL, is_active BOOLEAN NOT NULL, "
                "created_at DATETIME, updated_at DATETIME)"
            )
            connection.exec_driver_sql(
                "INSERT INTO users (id, username, password_hash, role, is_active) "
                "VALUES (1, 'breakglass', 'existing-secure-hash', 'administrator', 1)"
            )

        upgrade_schema(engine)
        upgrade_schema(engine)

        columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("users")
        }
        self.assertTrue(columns["password_hash"]["nullable"])
        self.assertIn("auth_provider", columns)
        self.assertIn("directory_subject", columns)
        self.assertIn("token_version", columns)
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT username, password_hash, auth_provider, token_version "
                "FROM users WHERE id = 1"
            ).one()
        self.assertEqual(row, ("breakglass", "existing-secure-hash", "LOCAL", 0))


if __name__ == "__main__":
    unittest.main()
