"""Unit tests for Account Registry & Persistent Browser Profiles (accounts.py)."""

import tempfile
import unittest
from pathlib import Path

from guardian_agent.accounts import (
    ProfileLockManager,
    get_account,
    profile_path,
    register_account,
    revoke_account,
)
from guardian_agent.core import GuardianError, initialize


class TestAccountRegistry(unittest.TestCase):
    def test_register_and_get_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Account Test", "Phase 5 test")
            acc = register_account(
                brain,
                account_id="canva1",
                service_name="canva",
                account_label="Main Canva Pro",
                vault_ref="vault:canva_credentials",
                allowed_domains=["canva.com"],
            )
            self.assertEqual(acc["id"], "canva1")
            self.assertEqual(acc["vault_ref"], "vault:canva_credentials")

            loaded = get_account(brain, "canva1")
            self.assertEqual(loaded["account_label"], "Main Canva Pro")

    def test_raw_passwords_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Account Test", "Phase 5 test")
            with self.assertRaises(GuardianError) as ctx:
                register_account(
                    brain,
                    account_id="canva1",
                    service_name="canva",
                    account_label="Main Canva Pro",
                    vault_ref="raw_plaintext_password_123",
                    allowed_domains=["canva.com"],
                )
            self.assertIn("vault:", str(ctx.exception).lower())

    def test_profile_locking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Account Test", "Phase 5 test")
            register_account(
                brain,
                account_id="adobe1",
                service_name="adobe",
                account_label="Adobe Express",
                vault_ref="vault:adobe_token",
                allowed_domains=["adobe.com"],
            )

            with ProfileLockManager(brain, "adobe1"):
                # Nested lock attempt by same or another thread should fail
                with self.assertRaises(GuardianError):
                    with ProfileLockManager(brain, "adobe1"):
                        pass

    def test_account_revocation_wipes_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Account Test", "Phase 5 test")
            register_account(
                brain,
                account_id="lovable1",
                service_name="lovable",
                account_label="Lovable Pro",
                vault_ref="vault:lovable_key",
                allowed_domains=["lovable.dev"],
            )

            # Create a file inside profile
            p_dir = profile_path(brain, "lovable1")
            (p_dir / "cookies.json").write_text("{}")

            revoke_account(brain, "lovable1")

            with self.assertRaises(GuardianError):
                get_account(brain, "lovable1")

            self.assertFalse((p_dir / "cookies.json").exists())



    def test_malicious_account_id_traversal_rejected(self) -> None:
        """Malicious account IDs containing path traversal must raise GuardianError and never escape containment."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Account Test", "Phase 5 test")
            malicious_ids = ["../../outside", "../etc/passwd", "/abs/path", "id\x00null", ".."]

            for bad_id in malicious_ids:
                with self.assertRaises(GuardianError, msg=f"Failed to reject bad_id: {bad_id!r}"):
                    register_account(
                        brain,
                        account_id=bad_id,
                        service_name="canva",
                        account_label="Hack",
                        vault_ref="vault:key",
                        allowed_domains=["canva.com"],
                    )

                with self.assertRaises(GuardianError, msg=f"Failed to reject get_account bad_id: {bad_id!r}"):
                    get_account(brain, bad_id)

                with self.assertRaises(GuardianError, msg=f"Failed to reject profile_path bad_id: {bad_id!r}"):
                    profile_path(brain, bad_id)

                with self.assertRaises(GuardianError, msg=f"Failed to reject revoke_account bad_id: {bad_id!r}"):
                    revoke_account(brain, bad_id)



if __name__ == "__main__":
    unittest.main()
