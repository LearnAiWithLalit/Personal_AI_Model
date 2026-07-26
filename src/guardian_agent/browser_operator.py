"""Computer Operator Browser Controller with Playwright & HTTP Graceful Fallback (Phase G).

Supports Playwright visual browser testing when installed. If Playwright is not installed,
gracefully falls back to standard library HTTP inspection without erroring out.
"""

from __future__ import annotations

import urllib.request
import urllib.error
from guardian_agent.core import GuardianError, ProjectBrain, now_utc, markdown_escape
from guardian_agent.operator import audit_log_action
from guardian_agent.policy import check_policy_permission, consume_action_approval


def check_playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def inspect_web_page(brain: ProjectBrain, url: str) -> dict:
    clean_url = markdown_escape(url)
    
    if check_playwright_available():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(clean_url, timeout=10000)
                title = page.title()
                
                art_dir = brain.directory / "artifacts"
                art_dir.mkdir(exist_ok=True)
                shot_path = art_dir / f"screenshot_{now_utc().replace(':', '-').replace(' ', '_')}.png"
                page.screenshot(path=str(shot_path))
                browser.close()
                
                audit_log_action(brain, "browser_playwright_inspect", clean_url, "success", f"Title: {title}")
                return {
                    "url": clean_url,
                    "status": "success",
                    "method": "playwright",
                    "title": title,
                    "screenshot": str(shot_path),
                }
        except Exception as error:
            # Fall back to HTTP inspection if Playwright fails
            pass
            
    # Graceful fallback: Standard library HTTP GET
    try:
        req = urllib.request.Request(clean_url, headers={"User-Agent": "GuardianAgent/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode("utf-8", errors="ignore")[:2000]
            audit_log_action(brain, "browser_http_inspect", clean_url, "success", "Fetched HTTP content snippet")
            return {
                "url": clean_url,
                "status": "fallback_http",
                "method": "http",
                "snippet": content[:300],
            }
    except Exception as error:
        audit_log_action(brain, "browser_inspect", clean_url, "failed", str(error))
        return {
            "url": clean_url,
            "status": "failed",
            "method": "http_fallback",
            "error": str(error),
        }


def execute_browser_action(
    brain: ProjectBrain,
    *,
    url: str,
    action: str,
    selector: str | None = None,
    value: str | None = None,
    visible: bool = True,
    approval_id: str | None = None,
) -> dict:
    """Run one bounded Playwright action against a user-authorized session.

    This intentionally excludes CAPTCHA/MFA handling, legal acceptance, and
    identity verification. Form submission is blocked until an approval record
    exists in the policy workflow; callers should request that approval first.
    """
    clean_url = markdown_escape(url)
    clean_action = markdown_escape(action).lower()
    if clean_action not in {"navigate", "click", "fill", "screenshot", "submit"}:
        raise GuardianError("Browser action must be navigate, click, fill, screenshot, or submit.")
    policy_action = "browser_submit" if clean_action == "submit" else f"browser_{clean_action}"
    needs_approval = check_policy_permission(brain, policy_action, clean_url) == "requires_approval"
    if needs_approval and not approval_id:
        raise GuardianError("This browser action requires an approved policy request before execution.")
    if not check_playwright_available():
        raise GuardianError("Playwright is required for interactive browser actions; install it and its browser binaries.")
    if clean_action in {"click", "fill", "submit"} and not selector:
        raise GuardianError(f"Browser action {clean_action!r} requires an exact selector.")
    if clean_action == "fill" and value is None:
        raise GuardianError("Browser fill requires a value supplied at execution time.")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not visible)
            page = browser.new_page()
            page.goto(clean_url, timeout=20_000, wait_until="domcontentloaded")
            if clean_action == "click":
                page.locator(selector).click()
            elif clean_action == "fill":
                page.locator(selector).fill(value or "")
            elif clean_action == "submit":
                # Consume only when the page and selector are ready for the
                # side effect, not merely because a browser was opened.
                consume_action_approval(brain, approval_id or "", policy_action, clean_url)
                page.locator(selector).click()
            art_dir = brain.directory / "artifacts"
            art_dir.mkdir(exist_ok=True)
            shot_path = art_dir / f"browser_{now_utc().replace(':', '-').replace(' ', '_')}.png"
            page.screenshot(path=str(shot_path))
            title = page.title()
            browser.close()
        # Never record form values: they can contain passwords or tokens.
        audit_log_action(brain, policy_action, clean_url, "success", f"selector={selector or ''}; title={title}")
        return {"status": "success", "action": clean_action, "url": clean_url, "title": title, "screenshot": str(shot_path)}
    except Exception as error:
        audit_log_action(brain, policy_action, clean_url, "failed", str(error))
        raise GuardianError(f"Browser action failed: {error}") from error
