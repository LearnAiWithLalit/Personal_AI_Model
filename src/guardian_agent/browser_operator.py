"""Computer Operator Browser Controller with Playwright & HTTP Graceful Fallback (Phase 5 Hardened).

Supports Playwright visual browser testing with URL security validation, Playwright route interception,
persistent account profiles, profile process locking, pre-action approval reservation, typed approval checks,
sensitive action evidence, unknown_outcome recovery, and visible manual takeover.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from guardian_agent.accounts import ProfileLockManager, get_account, profile_path
from guardian_agent.core import GuardianError, ProjectBrain, markdown_escape, now_utc
from guardian_agent.operator import audit_log_action
from guardian_agent.policy import (
    approve_action_request,
    check_policy_permission,
    consume_action_approval,
    mark_approval_unknown_outcome,
    reserve_action_approval,
)
from guardian_agent.security_url import (
    sanitize_url_for_audit,
    validate_and_sanitize_url,
    validate_redirect_url,
)


SUPPORTED_BROWSER_ACTIONS = {
    "navigate",
    "click_readonly",
    "fill",
    "screenshot",
    "submit",
    "publish",
    "purchase",
    "delete",
    "create_account",
    "accept_terms",
    "fill_credential",
    "identity_verification",
}

SENSITIVE_BROWSER_ACTIONS = {
    "submit",
    "publish",
    "purchase",
    "delete",
    "create_account",
    "accept_terms",
    "fill_credential",
    "identity_verification",
}

ACTIONS_REQUIRING_SELECTOR = {
    "click_readonly",
    "fill",
    "submit",
    "publish",
    "purchase",
    "delete",
    "create_account",
    "accept_terms",
    "fill_credential",
    "identity_verification",
}


def check_playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def inspect_web_page(
    brain: ProjectBrain,
    url: str,
    account_id: str | None = None,
    allow_offline: bool = False,
) -> dict[str, Any]:
    """Inspect a web page with strict URL validation and Playwright or HTTP fallback."""
    allowed_domains = None
    if account_id:
        acc = get_account(brain, account_id)
        allowed_domains = acc.get("allowed_domains")

    # Strictly validate URL scheme, IP range, and domain allowlist before any request
    try:
        clean_url = validate_and_sanitize_url(
            url, allow_http=False, allowed_domains=allowed_domains, allow_offline=allow_offline
        )
    except GuardianError as exc:
        return {
            "url": sanitize_url_for_audit(url),
            "status": "failed",
            "error": str(exc),
            "method": "url_validation",
        }
    audit_url = sanitize_url_for_audit(clean_url)

    if check_playwright_available():
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()

                # Network interception: validate every outgoing HTTP request
                def _route_handler(route, request):
                    try:
                        validate_and_sanitize_url(
                            request.url,
                            allow_http=False,
                            allowed_domains=allowed_domains,
                            allow_offline=allow_offline,
                        )
                        route.continue_()
                    except Exception:
                        route.abort("blockedbyclient")

                context.route("**/*", _route_handler)
                page = context.new_page()
                page.goto(clean_url, timeout=10_000)
                title = page.title()

                art_dir = brain.directory / "artifacts"
                art_dir.mkdir(exist_ok=True)
                shot_path = art_dir / f"screenshot_{now_utc().replace(':', '-').replace(' ', '_')}.png"
                page.screenshot(path=str(shot_path))
                browser.close()

                audit_log_action(brain, "browser_playwright_inspect", audit_url, "success", f"Title: {title}")
                return {
                    "url": audit_url,
                    "status": "success",
                    "method": "playwright",
                    "title": title,
                    "screenshot": str(shot_path),
                }
        except Exception:
            pass

    # Graceful fallback: Standard library HTTP GET
    try:
        req = urllib.request.Request(clean_url, headers={"User-Agent": "GuardianAgent/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode("utf-8", errors="ignore")[:2000]
            audit_log_action(brain, "browser_http_inspect", audit_url, "success", "Fetched HTTP content snippet")
            return {
                "url": audit_url,
                "status": "fallback_http",
                "method": "http",
                "snippet": content[:300],
            }
    except Exception as error:
        audit_log_action(brain, "browser_inspect", audit_url, "failed", str(error))
        return {
            "url": audit_url,
            "status": "failed",
            "method": "http_fallback",
            "error": str(error),
        }


def pause_for_takeover(
    brain: ProjectBrain,
    account_id: str,
    timeout_seconds: int = 300,
    signal_file: Path | None = None,
) -> dict[str, Any]:
    """Pause execution holding persistent profile lock for human visual takeover."""
    lock_mgr = ProfileLockManager(brain, account_id)
    with lock_mgr:
        audit_log_action(brain, "browser_takeover_requested", account_id, "started", f"Timeout: {timeout_seconds}s")
        sig_path = signal_file or (brain.directory / "audit" / f"takeover_{account_id}.signal")
        sig_path.parent.mkdir(parents=True, exist_ok=True)
        sig_path.write_text(f"ACTIVE TAKEOVER for account {account_id} created at {now_utc()}\n", encoding="utf-8")

        start = time.time()
        status = "resumed"
        try:
            while time.time() - start < timeout_seconds:
                if not sig_path.is_file():
                    status = "resumed"
                    break
                time.sleep(1)
            else:
                status = "cancelled_timeout"
        finally:
            if sig_path.is_file():
                try:
                    sig_path.unlink()
                except OSError:
                    pass

        audit_log_action(brain, "browser_takeover_completed", account_id, status, f"Outcome: {status}")
        return {
            "account_id": account_id,
            "status": status,
            "duration_seconds": round(time.time() - start, 2),
        }


def execute_browser_action(
    brain: ProjectBrain,
    *,
    url: str,
    action: str,
    account_id: str | None = None,
    selector: str | None = None,
    value: str | None = None,
    visible: bool = True,
    approval_id: str | None = None,
    allow_offline: bool = False,
) -> dict[str, Any]:
    """Run one bounded Playwright action with route interception, pre-action reservation, evidence capture, and unknown_outcome handling."""
    allowed_domains = None
    p_dir = None

    if account_id:
        acc = get_account(brain, account_id)
        allowed_domains = acc.get("allowed_domains")
        p_dir = profile_path(brain, account_id)

    # Validate URL scheme, IP range, and domain allowlist
    clean_url = validate_and_sanitize_url(
        url, allow_http=False, allowed_domains=allowed_domains, allow_offline=allow_offline
    )
    audit_url = sanitize_url_for_audit(clean_url)

    clean_action = markdown_escape(action).lower()

    if clean_action not in SUPPORTED_BROWSER_ACTIONS:
        raise GuardianError(
            f"Unsupported browser action {action!r}. Supported actions: {', '.join(sorted(SUPPORTED_BROWSER_ACTIONS))}."
        )

    policy_action = f"browser_{clean_action}"
    is_sensitive = clean_action in SENSITIVE_BROWSER_ACTIONS

    if is_sensitive:
        if not account_id:
            raise GuardianError(f"Sensitive browser action {clean_action!r} requires an explicit --account-id.")
        if not approval_id:
            raise GuardianError(f"Sensitive browser action {clean_action!r} requires an explicit --approval-id.")

    # Sensitive actions force visible (headful) mode for human oversight
    force_visible = visible or is_sensitive

    needs_approval = check_policy_permission(brain, policy_action, clean_url) == "requires_approval"
    if needs_approval and not approval_id:
        raise GuardianError(f"Browser action {policy_action!r} requires an approved policy request before execution.")

    # STAGE 1 PRE-ACTION APPROVAL RESERVATION BEFORE PLAYWRIGHT LAUNCHES
    if approval_id:
        reserve_action_approval(
            brain,
            approval_id,
            policy_action,
            clean_url,
            account_id=account_id,
        )

    if not check_playwright_available():
        raise GuardianError("Playwright is required for interactive browser actions; install it and its browser binaries.")

    if clean_action in ACTIONS_REQUIRING_SELECTOR and not selector:
        raise GuardianError(f"Browser action {clean_action!r} requires an exact CSS/XPath selector.")

    if clean_action in {"fill", "fill_credential"} and value is None:
        raise GuardianError(f"Browser action {clean_action!r} requires a value supplied at execution time.")

    lock_ctx = ProfileLockManager(brain, account_id) if account_id else None

    def _run_action():
        started_operation = False
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                # Launch context (persistent if account profile exists)
                if p_dir:
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(p_dir),
                        headless=not force_visible,
                    )
                    page = context.pages[0] if context.pages else context.new_page()
                else:
                    browser = playwright.chromium.launch(headless=not force_visible)
                    context = browser.new_context()
                    page = context.new_page()

                # Attach Playwright route interception for every outgoing network request
                def _route_handler(route, request):
                    try:
                        validate_and_sanitize_url(
                            request.url,
                            allow_http=False,
                            allowed_domains=allowed_domains,
                            allow_offline=allow_offline,
                        )
                        route.continue_()
                    except Exception:
                        route.abort("blockedbyclient")

                context.route("**/*", _route_handler)
                page.goto(clean_url, timeout=20_000, wait_until="domcontentloaded")

                # Handle redirect revalidation
                if page.url != clean_url:
                    validate_redirect_url(clean_url, page.url, allowed_domains=allowed_domains)

                art_dir = brain.directory / "artifacts"
                art_dir.mkdir(exist_ok=True)
                ts_str = now_utc().replace(":", "-").replace(" ", "_")

                before_shot = None
                if is_sensitive:
                    before_shot = art_dir / f"browser_before_{clean_action}_{ts_str}.png"
                    page.screenshot(path=str(before_shot))

                started_operation = True

                if clean_action in {"click_readonly"}:
                    page.locator(selector).click()
                elif clean_action in {"fill", "fill_credential"}:
                    page.locator(selector).fill(value or "")
                elif is_sensitive:
                    if selector:
                        page.locator(selector).click()

                after_shot = art_dir / f"browser_after_{clean_action}_{ts_str}.png"
                page.screenshot(path=str(after_shot))
                title = page.title()

                # STAGE 2 POST-CLICK COMPLETION
                if approval_id:
                    consume_action_approval(
                        brain,
                        approval_id,
                        policy_action,
                        clean_url,
                        after_evidence=str(after_shot),
                        account_id=account_id,
                    )

                if p_dir:
                    context.close()
                else:
                    browser.close()

            audit_log_action(brain, policy_action, audit_url, "success", f"selector={selector or ''}; title={title}")
            return {
                "status": "success",
                "action": clean_action,
                "url": audit_url,
                "title": title,
                "before_screenshot": str(before_shot) if before_shot else None,
                "after_screenshot": str(after_shot),
                "headful": force_visible,
            }
        except Exception as error:
            if started_operation and is_sensitive and approval_id:
                try:
                    mark_approval_unknown_outcome(brain, approval_id, str(error))
                except Exception:
                    pass
            audit_log_action(brain, policy_action, audit_url, "failed", str(error))
            raise GuardianError(f"Browser action failed: {error}") from error

    if lock_ctx:
        with lock_ctx:
            return _run_action()
    return _run_action()
