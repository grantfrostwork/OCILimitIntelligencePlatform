"""Deployment invariants: credentials persist and invalid SSO cannot open the app."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bootstrap", SOURCE / "bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)

CONFIG = dict(public_url="https://limits.example.com", tenancy="example", region="us-ashburn-1",
              scan_all_regions=False, warning=81, critical=98, topic="example-alerts",
              notification_compartment="example")
OIDC = dict(discovery_url="https://example.identity.oraclecloud.com/.well-known/openid-configuration",
            client_id="example", client_secret='a$b"c\\d', admin_emails=["admin@example.com"])


class BootstrapTests(unittest.TestCase):
    def test_secure_defaults_and_compose_escaping(self):
        text, _ = bootstrap.environment(CONFIG, OIDC)
        values = dict(line.split("=", 1) for line in text.splitlines())
        decoded = {k: json.loads(v).replace("$$", "$") for k, v in values.items()}
        self.assertEqual(decoded["AUTH_OIDC_CLIENT_SECRET"], OIDC["client_secret"])
        self.assertEqual(decoded["AUTH_ENABLED"], "true")
        self.assertEqual(decoded["AUTH_COOKIE_SECURE"], "true")
        self.assertEqual(decoded["LIP_ENABLE_NOTIFICATIONS"], "false")
        self.assertEqual(decoded["LIP_NOTIFICATION_EMAILS"], "[]")
        self.assertEqual(decoded["WARNING_THRESHOLD_PERCENT"], "81")

    def test_rotation_preserves_database_and_session_credentials(self):
        _, initial = bootstrap.environment(CONFIG, OIDC)
        new_text, refreshed = bootstrap.environment(CONFIG, {**OIDC, "client_secret": "rotated"}, initial)
        self.assertEqual(initial, refreshed)
        self.assertIn(initial["postgres_password"], new_text)
        self.assertIn('AUTH_OIDC_CLIENT_SECRET="rotated"', new_text)

    def test_missing_or_invalid_oidc_fails_closed(self):
        for broken in ({}, {**OIDC, "client_secret": ""}, {**OIDC, "admin_emails": []},
                       {**OIDC, "discovery_url": "http://example.com/discovery"}):
            with self.subTest(broken=list(broken)):
                with self.assertRaises(ValueError):
                    bootstrap.environment(CONFIG, broken)

    def test_damaged_secret_backup_cannot_rotate_credentials(self):
        with self.assertRaises(ValueError):
            bootstrap.environment(CONFIG, OIDC, {"postgres_password": "existing"})

    def test_atomic_secret_file_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "env"
            bootstrap.atomic_write(path, "first")
            bootstrap.atomic_write(path, "second")
            self.assertEqual(path.read_text(), "second")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
