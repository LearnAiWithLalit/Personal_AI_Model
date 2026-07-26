"""Unit tests for Phase 5 Connectors (connectors.py)."""

import os
import tempfile
import unittest
from pathlib import Path

from guardian_agent.accounts import register_account
from guardian_agent.connectors import get_connector
from guardian_agent.core import GuardianError, initialize


class TestConnectors(unittest.TestCase):
    def test_canva_connector_lifecycle_with_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Connector Test", "Phase 5 test")
            register_account(
                brain,
                account_id="canva1",
                service_name="canva",
                account_label="Canva Test",
                vault_ref="vault:canva_key",
                allowed_domains=["canva.com"],
            )

            conn = get_connector("canva", "canva1")

            # Without vault secret, auth must fail and return authentication_required
            auth = conn.authenticate(brain)
            self.assertFalse(auth["authenticated"])
            self.assertEqual(auth["status"], "authentication_required")
            self.assertNotIn("vault_ref", auth)

            with self.assertRaises(GuardianError):
                conn.create_asset(brain, title="Header Graphic", allow_mock=True)

            # Set vault secret via environment fallback
            os.environ["CANVA_KEY"] = "secret_api_token_123"
            try:
                auth = conn.authenticate(brain)
                self.assertTrue(auth["authenticated"])
                self.assertEqual(auth["status"], "authenticated")
                self.assertNotIn("secret_api_token_123", str(auth))

                # First creation
                created1 = conn.create_asset(brain, title="Header Graphic", allow_mock=True)
                self.assertEqual(created1["status"], "created")

                # Duplicate creation call must return identical cached receipt (durable idempotency)
                created2 = conn.create_asset(brain, title="Header Graphic", allow_mock=True)
                self.assertEqual(created1["asset_id"], created2["asset_id"])

                exported = conn.export_asset(brain, created1["asset_id"], export_format="png", allow_mock=True)
                self.assertTrue(Path(exported["artifact_path"]).is_file())
            finally:
                os.environ.pop("CANVA_KEY", None)

    def test_session_revocation_wipes_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Connector Test", "Phase 5 test")
            register_account(
                brain,
                account_id="canva2",
                service_name="canva",
                account_label="Canva Test 2",
                vault_ref="vault:canva_key2",
                allowed_domains=["canva.com"],
            )
            os.environ["CANVA_KEY2"] = "token2"
            try:
                conn = get_connector("canva", "canva2")
                self.assertTrue(conn.authenticate(brain)["authenticated"])

                # Revoke session
                res = conn.revoke_session(brain)
                self.assertTrue(res["revoked"])

                with self.assertRaises(GuardianError):
                    conn.authenticate(brain)
            finally:
                os.environ.pop("CANVA_KEY2", None)


if __name__ == "__main__":
    unittest.main()
