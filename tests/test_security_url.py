"""Unit tests for URL Security & SSRF Defense Layer (security_url.py)."""

import unittest
from guardian_agent.core import GuardianError
from guardian_agent.security_url import (
    sanitize_url_for_audit,
    validate_and_sanitize_url,
    validate_redirect_url,
)


class TestURLSecurity(unittest.TestCase):
    def test_https_urls_accepted(self) -> None:
        url = "https://canva.com/design"
        self.assertEqual(validate_and_sanitize_url(url, allow_offline=True), url)

    def test_embedded_credentials_strictly_rejected(self) -> None:
        with self.assertRaises(GuardianError) as ctx:
            validate_and_sanitize_url("https://user:password@canva.com")
        self.assertIn("embedded user/password credentials", str(ctx.exception).lower())

    def test_file_url_strictly_rejected(self) -> None:
        with self.assertRaises(GuardianError) as ctx:
            validate_and_sanitize_url("file:///etc/passwd")
        self.assertIn("forbidden url scheme", str(ctx.exception).lower())

    def test_data_and_javascript_urls_rejected(self) -> None:
        with self.assertRaises(GuardianError):
            validate_and_sanitize_url("data:text/html,hello")
        with self.assertRaises(GuardianError):
            validate_and_sanitize_url("javascript:alert(1)")

    def test_localhost_and_loopback_ip_rejected(self) -> None:
        with self.assertRaises(GuardianError):
            validate_and_sanitize_url("https://localhost")
        with self.assertRaises(GuardianError):
            validate_and_sanitize_url("https://127.0.0.1")

    def test_cloud_metadata_ip_rejected(self) -> None:
        with self.assertRaises(GuardianError):
            validate_and_sanitize_url("https://169.254.169.254/latest/meta-data")

    def test_private_class_a_b_c_ips_rejected(self) -> None:
        with self.assertRaises(GuardianError):
            validate_and_sanitize_url("https://10.0.0.1")
        with self.assertRaises(GuardianError):
            validate_and_sanitize_url("https://192.168.1.1")

    def test_domain_allowlist_enforcement(self) -> None:
        allowed = ["canva.com", "adobe.com"]
        self.assertTrue(validate_and_sanitize_url("https://canva.com/app", allowed_domains=allowed, allow_offline=True))
        self.assertTrue(validate_and_sanitize_url("https://sub.adobe.com/export", allowed_domains=allowed, allow_offline=True))

        with self.assertRaises(GuardianError):
            validate_and_sanitize_url("https://malicious.com", allowed_domains=allowed, allow_offline=True)

    def test_audit_query_parameter_sanitization(self) -> None:
        url = "https://canva.com/auth?token=secret123&api_key=key456&user=alice"
        sanitized = sanitize_url_for_audit(url)
        self.assertNotIn("secret123", sanitized)
        self.assertNotIn("key456", sanitized)
        self.assertIn("user=alice", sanitized)

    def test_redirect_url_validation(self) -> None:
        allowed = ["canva.com"]
        target = "https://canva.com/redirect_ok"
        self.assertEqual(validate_redirect_url("https://canva.com/start", target, allowed_domains=allowed, allow_offline=True), target)

        with self.assertRaises(GuardianError):
            validate_redirect_url("https://canva.com/start", "http://127.0.0.1/evil")


if __name__ == "__main__":
    unittest.main()
