"""Computer Operator Browser Controller with Playwright & HTTP Graceful Fallback (Phase G).

Supports Playwright visual browser testing when installed. If Playwright is not installed,
gracefully falls back to standard library HTTP inspection without erroring out.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from pathlib import Path
from guardian_agent.core import ProjectBrain, append_journey, now_utc, markdown_escape
from guardian_agent.operator import audit_log_action


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
