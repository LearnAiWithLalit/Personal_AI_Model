"""URL Security & SSRF Defense Layer (Phase 5).

Protects against SSRF, local file inclusion (file://), cloud metadata theft (169.254.169.254),
private network access (localhost, 127.0.0.1, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16),
embedded credentials (user:pass@host), DNS rebinding, and unvalidated redirects.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from guardian_agent.core import GuardianError

# Allowed URI schemes for web interaction
_ALLOWED_SCHEMES_DEFAULT = ("https",)
_ALLOWED_SCHEMES_DEV = ("https", "http")

# Private and internal IP ranges to block
_BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # Private IPv4 Class A
    ipaddress.ip_network("172.16.0.0/12"),    # Private IPv4 Class B
    ipaddress.ip_network("192.168.0.0/16"),   # Private IPv4 Class C
    ipaddress.ip_network("169.254.0.0/16"),   # Link-Local / Cloud Metadata (169.254.169.254)
    ipaddress.ip_network("0.0.0.0/8"),        # Current network
    ipaddress.ip_network("::1/128"),          # IPv6 Loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 Unique Local
    ipaddress.ip_network("fe80::/10"),        # IPv6 Link-Local
]

_SENSITIVE_QUERY_PARAMS = frozenset({
    "token", "api_key", "key", "secret", "auth", "code", "password", "pwd", "session", "access_token"
})


def _is_ip_blocked(ip_str: str) -> bool:
    """Return True if the IP address belongs to a private, loopback, link-local, or metadata network."""
    try:
        addr = ipaddress.ip_address(ip_str)
        if not addr.is_global:
            return True
        return any(addr in net for net in _BLOCKED_IP_NETWORKS)
    except ValueError:
        return True



def sanitize_url_for_audit(url: str) -> str:
    """Redact sensitive query parameters from audit log URLs."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        params = parse_qs(parsed.query, keep_blank_values=True)
        sanitized_params = {}
        for key, values in params.items():
            if key.lower() in _SENSITIVE_QUERY_PARAMS:
                sanitized_params[key] = ["[REDACTED_QUERY_PARAM]"]
            else:
                sanitized_params[key] = values
        query_str = urlencode(sanitized_params, doseq=True)
        return urlunparse(parsed._replace(query=query_str))
    except Exception:
        return url


def validate_and_sanitize_url(
    url: str,
    allow_http: bool = False,
    allowed_domains: list[str] | None = None,
    allow_offline: bool = False,
) -> str:
    """Validate URL scheme, host, embedded credentials, IP range, and domain allowlist.

    Raises GuardianError if the URL attempts SSRF, local file access (file://),
    embedded credentials (user:pass@host), private network traversal, or DNS failure.
    """
    clean_url = str(url or "").strip()
    if not clean_url:
        raise GuardianError("URL cannot be empty.")

    try:
        parsed = urlparse(clean_url)
    except Exception as exc:
        raise GuardianError(f"Invalid URL structure: {exc}") from exc

    scheme = (parsed.scheme or "").lower()
    allowed_schemes = _ALLOWED_SCHEMES_DEV if allow_http else _ALLOWED_SCHEMES_DEFAULT

    if scheme not in allowed_schemes:
        raise GuardianError(
            f"Forbidden URL scheme {scheme!r}. Only {', '.join(allowed_schemes)} schemes are allowed."
        )

    # Reject embedded URL user/pass credentials
    if parsed.username or parsed.password:
        raise GuardianError("Security violation: embedded user/password credentials in URL are strictly prohibited.")

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        raise GuardianError("URL host is missing or invalid.")

    # Block direct localhost keywords
    if hostname in ("localhost", "localhost.localdomain", "loopback"):
        raise GuardianError(f"Access to internal host {hostname!r} is strictly forbidden.")

    # Check direct IP input
    try:
        ip_obj = ipaddress.ip_address(hostname)
        if _is_ip_blocked(str(ip_obj)):
            raise GuardianError(
                f"Security violation: IP address {hostname!r} is a forbidden private/internal IP."
            )
    except ValueError:
        # Domain name — resolve IP addresses to prevent DNS rebinding
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            resolved_ips = {item[4][0] for item in addr_info if item[4]}
            for ip in resolved_ips:
                if _is_ip_blocked(ip):
                    raise GuardianError(
                        f"Security violation: host {hostname!r} resolved to forbidden private/internal IP {ip}."
                    )
        except socket.gaierror as exc:
            # Fail closed on DNS lookup failure unless explicit offline test mode is enabled
            if not allow_offline:
                raise GuardianError(f"Security violation: could not resolve host {hostname!r}: {exc}") from exc

    # Domain allowlist validation if specified
    if allowed_domains and len(allowed_domains) > 0:
        matched = False
        for dom in allowed_domains:
            clean_dom = dom.lower().strip()
            if hostname == clean_dom or hostname.endswith("." + clean_dom):
                matched = True
                break
        if not matched:
            raise GuardianError(
                f"Host {hostname!r} is not in the allowed domain list: {allowed_domains}"
            )

    return clean_url


def validate_redirect_url(
    original_url: str,
    redirect_target: str,
    allowed_domains: list[str] | None = None,
    allow_offline: bool = False,
) -> str:
    """Revalidate redirect target URL scheme, IP address, and domain allowlist."""
    return validate_and_sanitize_url(
        redirect_target,
        allow_http=False,
        allowed_domains=allowed_domains,
        allow_offline=allow_offline,
    )
