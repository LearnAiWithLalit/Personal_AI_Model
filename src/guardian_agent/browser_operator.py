"""Computer Operator Browser Controller with Playwright & HTTP Graceful Fallback (Phase 5B).

Supports Playwright visual browser testing with URL security validation, Playwright route interception,
persistent account profiles, profile process locking, preflight selector existence/visibility/actionability validation,
late pre-action approval reservation, typed approval checks, sensitive action evidence, in-flight browser takeover
with idempotency ledger tracking, unknown_outcome recovery via structured reconciliation, and
real attached visual manual takeover with status, resume, cancel, and timeout CLI controls.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from guardian_agent.accounts import ProfileLockManager, get_account, profile_path
from guardian_agent.connectors import IdempotencyLedger
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


_BROWSER_LEDGER_PREFIX = "browser"


def _browser_ledger_key(account_id: str, action: str, target_url: str) -> str:
    """Generate a composite idempotency ledger key for a browser operation.

    Format: browser:{action}:{account_id}:{url_hash[:12]}
    Action is at position 1 to match the connector key convention
    (connector:action:idempotency_key), which is critical for the
    reconcile() cross-field validation that parses position 1 as action.
    """
    clean_account = str(account_id or "default").strip()
    clean_action = str(action or "unknown").strip().lower()
    url_hash = hashlib.sha256(target_url.encode("utf-8")).hexdigest()[:12]
    return f"{_BROWSER_LEDGER_PREFIX}:{clean_action}:{clean_account}:{url_hash}"


def reserve_browser_operation(
    brain: ProjectBrain,
    account_id: str,
    action: str,
    target_url: str,
    ttl_seconds: int = 600,
) -> dict[str, Any]:
    """Reserve a browser operation in the idempotency ledger before execution.

    Returns a dict with 'owner_token' for the caller to use when completing
    or marking the operation as unknown.
    """
    comp_key = _browser_ledger_key(account_id, action, target_url)
    payload_hash = hashlib.sha256(f"{account_id}:{action}:{target_url}".encode("utf-8")).hexdigest()
    return IdempotencyLedger.reserve(brain, comp_key, payload_hash, ttl_seconds=ttl_seconds)


def complete_browser_operation(
    brain: ProjectBrain,
    account_id: str,
    action: str,
    target_url: str,
    receipt: dict[str, Any],
    owner_token: str,
) -> None:
    """Complete a browser operation in the idempotency ledger."""
    comp_key = _browser_ledger_key(account_id, action, target_url)
    IdempotencyLedger.complete(brain, comp_key, receipt, owner_token=owner_token)


def fail_browser_operation(
    brain: ProjectBrain,
    account_id: str,
    action: str,
    target_url: str,
    error_reason: str,
    owner_token: str,
) -> None:
    """Mark a browser operation as unknown_outcome in the idempotency ledger."""
    comp_key = _browser_ledger_key(account_id, action, target_url)
    IdempotencyLedger.mark_unknown(brain, comp_key, error_reason, owner_token=owner_token)


def list_browser_unknown_outcomes(
    brain: ProjectBrain,
    account_id: str | None = None,
) -> list[dict[str, Any]]:
    """List browser operations in the idempotency ledger with 'unknown_outcome' status.

    Args:
        brain: Project brain.
        account_id: Optional filter — only return entries matching this account.

    Returns:
        List of ledger entries in unknown_outcome state with composite_key populated.
    """
    ledger = IdempotencyLedger.load(brain)
    results: list[dict[str, Any]] = []
    prefix = f"{_BROWSER_LEDGER_PREFIX}:"

    for comp_key, entry in ledger.items():
        if not comp_key.startswith(prefix):
            continue
        if entry.get("status") != "unknown_outcome":
            continue
        if account_id:
            parts = comp_key.split(":", 3)
            # Format: browser:{action}:{account_id}:{url_hash[:12]}
            # account_id is at position 2
            if len(parts) < 3 or parts[2] != account_id:
                continue
        result = dict(entry)
        result["composite_key"] = comp_key
        results.append(result)

    return results


def reconcile_browser_unknown(
    brain: ProjectBrain,
    account_id: str,
    action: str,
    target_url: str,
    resolution: str,
    resolution_reason: str,
    evidence: dict[str, Any],
    approval_id: str,
    receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile a browser operation stuck in 'unknown_outcome' state.

    Calls IdempotencyLedger.reconcile() directly with the browser-scoped composite key
    to avoid the key wrapping that reconcile_connector_outcome() applies.

    Requires structured evidence with all RECONCILIATION_EVIDENCE_FIELDS and
    a non-empty approval_id.

    cancelled/failed reconciliation releases the lock allowing a new reservation.
    completed reconciliation is terminal.
    """
    comp_key = _browser_ledger_key(account_id, action, target_url)
    return IdempotencyLedger.reconcile(
        brain, comp_key, resolution, resolution_reason, evidence, approval_id, receipt=receipt,
    )


def abort_browser_preflight(
    brain: ProjectBrain,
    account_id: str,
    action: str,
    target_url: str,
    preflight_reason: str,
    owner_token: str,
) -> None:
    """Abort a browser operation where preflight validation failed before any side effect started.

    Transitions the ledger entry from reserved → preflight_aborted, preserving an audit event.
    Never marks unknown_outcome because no external action occurred.
    Allows the next attempt to reserve a fresh operation safely.

    Raises GuardianError on owner token mismatch or ledger write failure (fail-closed).
    """
    comp_key = _browser_ledger_key(account_id, action, target_url)
    IdempotencyLedger.abort_preflight(brain, comp_key, preflight_reason, owner_token=owner_token)


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


# ---------------------------------------------------------------------------
# Priority 2 — Browser Reliability Improvements
#
# Overlay detection, navigation stability, stale-element checks,
# submission fingerprints, page-state reconciliation, and
# exact in-flight page context preservation for manual takeover.
# ---------------------------------------------------------------------------

_SUBMISSION_FINGERPRINT_VERSION = 1


def _check_overlay_blocking(page: Any, selector: str) -> list[dict]:
    """Detect if a target element is blocked by overlay elements.

    Uses JavaScript to check if the element at the given selector is
    covered by another element (modal, cookie banner, popup, etc.).

    Args:
        page: Playwright page object.
        selector: CSS/XPath selector for the target element.

    Returns:
        List of overlay descriptions. Empty list means no overlay detected.
    """
    try:
        overlays = page.evaluate("""(sel) => {
            const el = document.querySelector(sel);
            if (!el) return [{ 'type': 'missing', 'description': 'Element not found in DOM' }];

            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) {
                return [{ 'type': 'hidden', 'description': 'Element has zero dimensions' }];
            }

            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;

            const topEl = document.elementFromPoint(cx, cy);
            if (!topEl) return [];

            const results = [];
            if (topEl !== el && !el.contains(topEl) && !topEl.contains(el)) {
                const tag = topEl.tagName.toLowerCase();
                const id = topEl.id || '';
                const cls = topEl.className || '';
                const text = (topEl.textContent || '').trim().substring(0, 80);
                results.push({
                    'type': 'overlay',
                    'tag': tag,
                    'id': id,
                    'class': cls.substring(0, 60),
                    'text': text,
                    'description': `Covered by <${tag}>${id ? '#' + id : ''}${cls ? '.' + cls.substring(0, 30) : ''}`
                });
            }

            return results;
        }""", selector)
        return overlays or []
    except Exception:
        return []


def _wait_for_page_settled(page: Any, timeout: int = 5_000) -> dict:
    """Wait for the page to reach a settled state after navigation or action.

    Checks for network idle, no recent DOM mutations, and complete rendering.

    Args:
        page: Playwright page object.
        timeout: Maximum milliseconds to wait.

    Returns:
        Dict with 'settled' (bool), 'method', and details.
    """
    start = time.time()
    try:
        # Wait for network to be mostly idle
        page.wait_for_load_state("networkidle", timeout=timeout)

        # Check that the page signals it's interactive
        page.wait_for_load_state("domcontentloaded", timeout=5_000)

        # Use JavaScript to verify DOM stability
        stable = page.evaluate("""(ms) => {
            return new Promise((resolve) => {
                const start = performance.now();
                let lastMutation = 0;

                const observer = new MutationObserver(() => {
                    lastMutation = performance.now();
                });

                observer.observe(document.body || document.documentElement, {
                    childList: true,
                    subtree: true,
                    attributes: false,
                });

                const check = () => {
                    const elapsed = performance.now() - lastMutation;
                    if (elapsed > 300) {
                        observer.disconnect();
                        resolve(true);
                    } else if (performance.now() - start > ms) {
                        observer.disconnect();
                        resolve(false);
                    } else {
                        requestAnimationFrame(check);
                    }
                };

                // Start checking after a short delay
                setTimeout(check, 500);
            });
        }""", timeout)

        elapsed = round((time.time() - start) * 1000, 0)
        return {
            "settled": bool(stable),
            "method": "network_idle_and_dom_stable",
            "elapsed_ms": elapsed,
        }
    except Exception as err:
        return {
            "settled": False,
            "method": "timeout_or_error",
            "error": str(err)[:100],
        }


def _check_element_stable(page: Any, selector: str) -> dict:
    """Verify that an element is still attached to the DOM and actionable.

    Checks that the element exists, is visible, is enabled, and has not
    been detached from the DOM since the last interaction.

    Args:
        page: Playwright page object.
        selector: CSS/XPath selector for the target element.

    Returns:
        Dict with 'stable' (bool), 'reason', and optional 'stale' flag.
    """
    try:
        count = page.locator(selector).count()
        if count == 0:
            return {"stable": False, "reason": "Element not found in DOM", "stale": True}

        loc = page.locator(selector).first
        try:
            loc.wait_for(state="visible", timeout=3_000)
        except Exception:
            return {"stable": False, "reason": "Element not visible", "stale": False}

        if loc.is_disabled():
            return {"stable": False, "reason": "Element is disabled", "stale": False}

        return {"stable": True, "reason": "Element visible and enabled"}
    except Exception as err:
        return {"stable": False, "reason": str(err)[:100], "stale": True}


def _create_submission_fingerprint(page: Any, action_type: str) -> dict:
    """Capture durable page state evidence after a submission or sensitive action.

    Gathers: current URL, page title, key DOM text, screenshot path, timestamps,
    URL params, visible success/error indicators, and page visibility state.

    Args:
        page: Playwright page object at the post-action state.
        action_type: The type of action performed (submit, publish, etc.).

    Returns:
        Dict with durable fingerprint evidence for later reconciliation.
    """
    fp: dict = {
        "version": _SUBMISSION_FINGERPRINT_VERSION,
        "action_type": action_type,
        "captured_at": now_utc(),
        "current_url": page.url,
        "page_title": page.title(),
        "url_changed": False,
        "has_success_indicator": False,
        "has_error_indicator": False,
        "visible_text_snippet": "",
        "success_keywords": [],
        "error_keywords": [],
    }

    try:
        # Capture visible text for reconciliation
        body_text = page.evaluate("() => document.body?.innerText || ''")
        fp["visible_text_snippet"] = body_text[:2000]

        # Check for success indicators
        success_patterns = ["success", "thank you", "submitted", "confirmed", "complete",
                           "payment received", "order placed", "published"]
        fp["success_keywords"] = [
            kw for kw in success_patterns
            if kw in body_text.lower()[:5000]
        ]
        fp["has_success_indicator"] = len(fp["success_keywords"]) > 0

        # Check for error indicators
        error_patterns = ["error", "failed", "declined", "rejected", "timeout",
                         "try again", "something went wrong", "invalid"]
        fp["error_keywords"] = [
            kw for kw in error_patterns
            if kw in body_text.lower()[:5000]
        ]
        fp["has_error_indicator"] = len(fp["error_keywords"]) > 0

    except Exception:
        pass

    return fp


def _reconcile_submission_state(brain: ProjectBrain, before_fp: dict, after_fp: dict) -> dict:
    """Compare before/after submission fingerprints to determine action outcome.

    Analyzes URL changes, success/error indicators, and visible text changes
    to classify the outcome as: likely_success, likely_failed, or uncertain.

    Args:
        brain: Project brain.
        before_fp: Submission fingerprint captured before the action.
        after_fp: Submission fingerprint captured after the action.

    Returns:
        Dict with reconciliation result and confidence score (0.0-1.0).
    """
    result = {
        "reconciled": True,
        "outcome": "uncertain",
        "confidence": 0.0,
        "url_changed": False,
        "has_success": False,
        "has_error": False,
        "details": [],
    }

    # 1. Check URL change (strongest signal)
    before_url = before_fp.get("current_url", "")
    after_url = after_fp.get("current_url", "")
    if before_url != after_url:
        result["url_changed"] = True
        result["details"].append(f"URL changed: {before_url[:60]} -> {after_url[:60]}")

    # 2. Check success indicators
    has_success = after_fp.get("has_success_indicator", False)
    success_kws = after_fp.get("success_keywords", [])
    if has_success:
        result["has_success"] = True
        result["details"].append(f"Success keywords found: {', '.join(success_kws)}")

    # 3. Check error indicators
    has_error = after_fp.get("has_error_indicator", False)
    error_kws = after_fp.get("error_keywords", [])
    if has_error:
        result["has_error"] = True
        result["details"].append(f"Error keywords found: {', '.join(error_kws)}")

    # 4. Determine outcome
    if result["url_changed"] and has_success and not has_error:
        result["outcome"] = "likely_success"
        result["confidence"] = 0.9
    elif result["url_changed"] and not has_error:
        result["outcome"] = "likely_success"
        result["confidence"] = 0.7
    elif has_success and not has_error:
        result["outcome"] = "likely_success"
        result["confidence"] = 0.6
    elif has_error:
        result["outcome"] = "likely_failed"
        result["confidence"] = 0.8
    else:
        result["outcome"] = "uncertain"
        result["confidence"] = 0.3

    return result


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
    current_page_url: str | None = None,
    current_page_title: str | None = None,
) -> dict[str, Any]:
    """Pause execution holding persistent profile lock for human visual takeover with attached headful context if available.

    When current_page_url and/or current_page_title are provided, the takeover
    preserves the exact in-flight page context so the human user sees the same
    page the agent was interacting with.
    """
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
            "page_url": current_page_url,
            "page_title": current_page_title,
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

                        # PRESERVE IN-FLIGHT PAGE CONTEXT: Navigate to the exact page the agent was on
                        if current_page_url:
                            try:
                                page.goto(current_page_url, timeout=15_000, wait_until="domcontentloaded")
                            except Exception:
                                pass

                        try:
                            page.evaluate(
                                f"""() => {{
                                    if (document.getElementById('guardian-takeover-banner')) return;
                                    const div = document.createElement('div');
                                    div.id = 'guardian-takeover-banner';
                                    div.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:999999;background:#e74c3c;color:#fff;padding:10px 20px;font-family:sans-serif;font-size:14px;font-weight:bold;box-shadow:0 2px 10px rgba(0,0,0,0.5);';
                                    div.innerHTML = '⚠️ GUARDIAN MANUAL TAKEOVER ACTIVE ({account_id}) — Session: {takeover_id} | Resume via CLI';
                                    if (document.body) document.body.prepend(div);
                                }}"""
                            )
                        except Exception:
                            pass

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

    # Pre-reserve in the idempotency ledger (fail-closed before Playwright launches).
    # If a prior operation is in unknown_outcome state, the reservation will raise
    # GuardianError and block the action until reconciliation is performed.
    ledger_res = reserve_browser_operation(
        brain, account_id or "default", clean_action, clean_url, ttl_seconds=600
    )
    ledger_owner_token: str | None = (
        ledger_res.get("owner_token") if not ledger_res.get("already_completed") else None
    )

    def _run_action():
        started_operation = False
        res_token = None
        nonlocal ledger_owner_token
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

                # NAVIGATION STABILITY: Wait for page to fully settle after navigation
                page.goto(clean_url, timeout=20_000, wait_until="domcontentloaded")
                settle_result = _wait_for_page_settled(page, timeout=5_000)

                if page.url != clean_url:
                    validate_redirect_url(clean_url, page.url, allowed_domains=allowed_domains)
                    # Re-settle after redirect
                    _wait_for_page_settled(page, timeout=5_000)

                # ENHANCED PREFLIGHT: overlay check + stale element check + actionability
                if selector:
                    # Step 1: Check for overlay blocking
                    overlays = _check_overlay_blocking(page, selector)
                    blocking_overlays = [o for o in overlays if o.get('type') == 'overlay']
                    if blocking_overlays:
                        overlay_desc = '; '.join(o.get('description', '') for o in blocking_overlays[:3])
                        raise GuardianError(
                            f"Browser preflight failed: selector {selector!r} on page {clean_url!r} "
                            f"is blocked by overlay(s): {overlay_desc}"
                        )

                    # Step 2: Check element stability (not stale)
                    stability = _check_element_stable(page, selector)
                    if not stability.get("stable"):
                        raise GuardianError(
                            f"Browser preflight failed: selector {selector!r} on page {clean_url!r} "
                            f"is not stable: {stability.get('reason', 'unknown')}"
                        )

                    # Step 3: Original actionability check
                    try:
                        loc = page.locator(selector).first
                        loc.wait_for(state="visible", timeout=5_000)
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

                # SUBMISSION FINGERPRINT: Capture before-state for sensitive actions
                before_fp = None
                before_shot = None
                if is_sensitive:
                    before_shot = art_dir / f"browser_before_{clean_action}_{ts_str}.png"
                    page.screenshot(path=str(before_shot))
                    before_fp = _create_submission_fingerprint(page, clean_action)

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

                # SUBMISSION RECONCILIATION: Compare before/after state for sensitive actions
                submission_reconciliation = None
                if is_sensitive and before_fp:
                    after_fp = _create_submission_fingerprint(page, clean_action)
                    submission_reconciliation = _reconcile_submission_state(brain, before_fp, after_fp)

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

                # Build enhanced receipt with submission reconciliation evidence
                receipt = {
                    "status": "completed",
                    "action": clean_action,
                    "url": audit_url,
                    "title": title,
                    "after_screenshot": str(after_shot),
                    "completed_at": now_utc(),
                }
                if submission_reconciliation:
                    receipt["submission_reconciliation"] = submission_reconciliation

                # Complete the ledger entry (fail closed — do not silently ignore failures)
                if ledger_owner_token:
                    complete_browser_operation(
                        brain, account_id or "default", clean_action, clean_url,
                        receipt=receipt,
                        owner_token=ledger_owner_token,
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
            # If the operation never started (preflight failure), release the
            # reservation via abort_preflight. This transitions reserved → preflight_aborted,
            # preserving an audit event but allowing the next attempt to reserve a fresh
            # operation safely. Never marks unknown_outcome because no external action occurred.
            # Errors are propagated (fail-closed) — no silent except/ignore.
            if not started_operation and ledger_owner_token:
                abort_browser_preflight(
                    brain, account_id or "default", clean_action, clean_url,
                    preflight_reason=str(error)[:200],
                    owner_token=ledger_owner_token,
                )
            # Mark ledger entry as unknown_outcome ONLY if a side effect started.
            elif started_operation and ledger_owner_token:
                fail_browser_operation(
                    brain, account_id or "default", clean_action, clean_url,
                    error_reason=str(error),
                    owner_token=ledger_owner_token,
                )
            audit_log_action(brain, policy_action, audit_url, "failed", str(error))
            raise GuardianError(f"Browser action failed: {error}") from error

    if lock_ctx:
        with lock_ctx:
            return _run_action()
    return _run_action()
