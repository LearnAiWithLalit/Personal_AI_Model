"""Computer Operator Browser Controller with Playwright & HTTP Graceful Fallback (Phase 5 Hardened).

Supports Playwright visual browser testing with URL security validation, Playwright route interception,
persistent account profiles, profile process locking, preflight selector existence/visibility/actionability validation,
late pre-action approval reservation, typed approval checks, sensitive action evidence, unknown_outcome recovery,
and real attached visual manual takeover with status, resume, cancel, and timeout CLI controls.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
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
    fetch_url_content_safe,
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
    """Inspect a web page with strict URL validation and Playwright or safe HTTP fallback."""
    allowed_domains = None
    if account_id:
        acc = get_account(brain, account_id)
        allowed_domains = acc.get("allowed_domains")

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

    # Safe Graceful fallback: Redirect-validated HTTP GET fetch
    try:
        content = fetch_url_content_safe(clean_url, allowed_domains=allowed_domains, allow_offline=allow_offline)
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


def _takeover_meta_path(brain: ProjectBrain, account_id: str) -> Path:
    audit_d = brain.directory / "audit"
    audit_d.mkdir(parents=True, exist_ok=True)
    return audit_d / f"takeover_{account_id}.json"


def get_takeover_status(brain: ProjectBrain, account_id: str) -> dict[str, Any]:
    """Return active takeover status for account."""
    meta_p = _takeover_meta_path(brain, account_id)
    if not meta_p.is_file():
        return {"account_id": account_id, "status": "inactive"}
    try:
        data = json.loads(meta_p.read_text(encoding="utf-8"))
        sig_p = Path(data.get("signal_path", ""))
        if not sig_p.is_file():
            data["status"] = "resumed"
        return data
    except Exception:
        return {"account_id": account_id, "status": "inactive"}


def resume_takeover(brain: ProjectBrain, account_id: str) -> dict[str, Any]:
    """Resume execution from an active manual takeover by removing the signal file."""
    meta_p = _takeover_meta_path(brain, account_id)
    sig_p = brain.directory / "audit" / f"takeover_{account_id}.signal"

    if sig_p.is_file():
        try:
            sig_p.unlink()
        except OSError:
            pass

    if meta_p.is_file():
        try:
            data = json.loads(meta_p.read_text(encoding="utf-8"))
            data["status"] = "resumed"
            meta_p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass

    audit_log_action(brain, "browser_takeover_resumed", account_id, "success", "Manual takeover resumed via control signal")
    return {"account_id": account_id, "status": "resumed"}


def cancel_takeover(brain: ProjectBrain, account_id: str) -> dict[str, Any]:
    """Cancel an active manual takeover session."""
    meta_p = _takeover_meta_path(brain, account_id)
    sig_p = brain.directory / "audit" / f"takeover_{account_id}.signal"

    if sig_p.is_file():
        try:
            sig_p.unlink()
        except OSError:
            pass

    if meta_p.is_file():
        try:
            data = json.loads(meta_p.read_text(encoding="utf-8"))
            data["status"] = "cancelled"
            meta_p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass

    audit_log_action(brain, "browser_takeover_cancelled", account_id, "cancelled", "Manual takeover cancelled by user request")
    return {"account_id": account_id, "status": "cancelled"}


def pause_for_takeover(
    brain: ProjectBrain,
    account_id: str,
    timeout_seconds: int = 300,
    signal_file: Path | None = None,
) -> dict[str, Any]:
    """Pause execution holding persistent profile lock for human visual takeover with attached headful context if available."""
    lock_mgr = ProfileLockManager(brain, account_id)
    with lock_mgr:
        takeover_id = f"takeover-{uuid.uuid4().hex[:8]}"
        audit_log_action(brain, "browser_takeover_requested", account_id, "started", f"Takeover ID: {takeover_id}; Timeout: {timeout_seconds}s")

        sig_path = signal_file or (brain.directory / "audit" / f"takeover_{account_id}.signal")
        sig_path.parent.mkdir(parents=True, exist_ok=True)
        sig_path.write_text(f"ACTIVE TAKEOVER for account {account_id} ({takeover_id}) created at {now_utc()}\n", encoding="utf-8")

        meta_p = _takeover_meta_path(brain, account_id)
        meta_data = {
            "takeover_id": takeover_id,
            "account_id": account_id,
            "status": "active",
            "created_at": now_utc(),
            "expires_at": time.time() + timeout_seconds,
            "signal_path": str(sig_path),
        }
        meta_p.write_text(json.dumps(meta_data, indent=2) + "\n", encoding="utf-8")

        p_dir = profile_path(brain, account_id)
        start = time.time()
        status = "resumed"

        try:
            # If Playwright is available, launch an attached headful persistent browser window for human inspection
            if check_playwright_available() and p_dir:
                try:
                    from playwright.sync_api import sync_playwright

                    with sync_playwright() as playwright:
                        context = playwright.chromium.launch_persistent_context(
                            user_data_dir=str(p_dir),
                            headless=False,
                        )
                        page = context.pages[0] if context.pages else context.new_page()
                        page.set_content(
                            f"<html><head><title>Guardian Takeover - {account_id}</title></head>"
                            f"<body style='font-family:sans-serif; padding:40px; background:#1e1e2e; color:#cdd6f4;'>"
                            f"<h1>Guardian Agent Manual Takeover Active</h1>"
                            f"<p>Account: <strong>{account_id}</strong> | Session ID: <code>{takeover_id}</code></p>"
                            f"<p>Interact with the browser window as needed. To resume automation, run:</p>"
                            f"<pre style='background:#11111b; padding:15px; border-radius:5px;'>guardian browser takeover resume --account-id {account_id}</pre>"
                            f"</body></html>"
                        )
                        while time.time() - start < timeout_seconds:
                            if not sig_path.is_file():
                                status = "resumed"
                                break
                            time.sleep(0.5)
                        else:
                            status = "cancelled_timeout"
                        context.close()
                except Exception:
                    # Fallback loop if GUI browser cannot launch
                    while time.time() - start < timeout_seconds:
                        if not sig_path.is_file():
                            status = "resumed"
                            break
                        time.sleep(0.5)
                    else:
                        status = "cancelled_timeout"
            else:
                while time.time() - start < timeout_seconds:
                    if not sig_path.is_file():
                        status = "resumed"
                        break
                    time.sleep(0.5)
                else:
                    status = "cancelled_timeout"
        finally:
            if sig_path.is_file():
                try:
                    sig_path.unlink()
                except OSError:
                    pass
            meta_data["status"] = status
            meta_data["completed_at"] = now_utc()
            meta_p.write_text(json.dumps(meta_data, indent=2) + "\n", encoding="utf-8")

        audit_log_action(brain, "browser_takeover_completed", account_id, status, f"Outcome: {status}")
        return {
            "account_id": account_id,
            "takeover_id": takeover_id,
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
    """Run one bounded Playwright action with route interception, preflight actionability validation, late reservation, evidence capture, and unknown_outcome handling."""
    allowed_domains = None
    p_dir = None
    connector_scope = None

    if account_id:
        acc = get_account(brain, account_id)
        allowed_domains = acc.get("allowed_domains")
        connector_scope = acc.get("service_name")
        p_dir = profile_path(brain, account_id)

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

    # Preflight Validation Checks BEFORE Playwright launch or reservation
    if not check_playwright_available():
        raise GuardianError("Playwright is required for interactive browser actions; install it and its browser binaries.")

    if clean_action in ACTIONS_REQUIRING_SELECTOR and not selector:
        raise GuardianError(f"Browser action {clean_action!r} requires an exact CSS/XPath selector.")

    if clean_action in {"fill", "fill_credential"} and value is None:
        raise GuardianError(f"Browser action {clean_action!r} requires a value supplied at execution time.")

    needs_approval = check_policy_permission(brain, policy_action, clean_url) == "requires_approval"
    if needs_approval and not approval_id:
        raise GuardianError(f"Browser action {policy_action!r} requires an approved policy request before execution.")

    force_visible = visible or is_sensitive

    lock_ctx = ProfileLockManager(brain, account_id) if account_id else None

    def _run_action():
        started_operation = False
        res_token = None
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
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

                if page.url != clean_url:
                    validate_redirect_url(clean_url, page.url, allowed_domains=allowed_domains)

                # PREFLIGHT SELECTOR ACTIONABILITY VALIDATION (Verify selector exists, is visible, and enabled)
                if selector:
                    try:
                        loc = page.locator(selector).first
                        loc.wait_for(state="visible", timeout=10_000)
                        if loc.is_disabled():
                            raise GuardianError(
                                f"Browser preflight failed: selector {selector!r} on page {clean_url!r} is disabled."
                            )
                    except GuardianError:
                        raise
                    except Exception as err:
                        raise GuardianError(
                            f"Browser preflight failed: selector {selector!r} is not visible or actionable on page {clean_url!r}: {err}"
                        ) from err

                art_dir = brain.directory / "artifacts"
                art_dir.mkdir(exist_ok=True)
                ts_str = now_utc().replace(":", "-").replace(" ", "_")

                before_shot = None
                if is_sensitive:
                    before_shot = art_dir / f"browser_before_{clean_action}_{ts_str}.png"
                    page.screenshot(path=str(before_shot))

                # LATE PRE-ACTION APPROVAL RESERVATION (Immediately before side effect execution)
                if approval_id:
                    res_rec = reserve_action_approval(
                        brain,
                        approval_id,
                        policy_action,
                        clean_url,
                        account_id=account_id,
                        connector_scope=connector_scope,
                    )
                    res_token = res_rec.get("reservation_token")

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
                        connector_scope=connector_scope,
                        reservation_token=res_token,
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
                    mark_approval_unknown_outcome(brain, approval_id, str(error), reservation_token=res_token)
                except Exception:
                    pass
            audit_log_action(brain, policy_action, audit_url, "failed", str(error))
            raise GuardianError(f"Browser action failed: {error}") from error

    if lock_ctx:
        with lock_ctx:
            return _run_action()
    return _run_action()
