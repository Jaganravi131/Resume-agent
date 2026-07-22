"""Playwright-based browser runner for job application form filling.

Opens the apply URL, pauses at CAPTCHA / login verification for the user
to complete manually, then fills form fields from the autofill packet.
NEVER clicks Submit — the user does that themselves.

Playwright is an optional dependency.  If not installed the module still
imports cleanly and ``run_application_flow`` returns an error dict.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("career_copilot.browser_runner")

# ---------------------------------------------------------------------------
# Playwright availability check
# ---------------------------------------------------------------------------

_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext  # type: ignore
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Verification detection
# ---------------------------------------------------------------------------

_VERIFICATION_INDICATORS = [
    # CAPTCHA / reCAPTCHA / hCaptcha
    "iframe[src*='captcha']",
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[src*='challenge']",
    # Cloudflare
    "#cf-challenge-running",
    ".cf-browser-verification",
    "[id*='challenge-form']",
    # Generic human verification text
    "[aria-label*='not a robot']",
    "[aria-label*='verify']",
]

_LOGIN_INDICATORS = [
    "input[type='password']",
    "form[action*='login']",
    "form[action*='signin']",
    "form[action*='session']",
    "button[data-automation-id='signInLink']",
]


def _detect_verification(page: "Page") -> str | None:
    """Check the page for known verification / login patterns.

    Returns a human-readable reason string if verification is detected,
    or None if the page appears ready for form-filling.
    """
    for selector in _VERIFICATION_INDICATORS:
        try:
            if page.locator(selector).count() > 0:
                return f"Verification element detected: {selector}"
        except Exception:
            pass

    # Check for visible text clues
    try:
        body_text = (page.locator("body").inner_text() or "").lower()
        for phrase in ("i'm not a robot", "verify you are human", "complete the captcha",
                       "one more step", "checking your browser", "security check"):
            if phrase in body_text:
                return f"Verification text detected: '{phrase}'"
    except Exception:
        pass

    # Check for login walls
    for selector in _LOGIN_INDICATORS:
        try:
            if page.locator(selector).count() > 0:
                return f"Login form detected: {selector}"
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# Form filling
# ---------------------------------------------------------------------------

def _try_fill_field(page: "Page", selector: str, value: str) -> bool:
    """Try to fill a form field using a comma-separated list of selectors.

    Returns True if at least one selector matched and was filled.
    """
    if not value:
        return False

    for sel in selector.split(","):
        sel = sel.strip()
        try:
            locator = page.locator(sel).first
            if locator.count() > 0:
                # Check if already populated — skip if so
                current = locator.input_value() if locator.is_visible() else ""
                if current and current.strip():
                    logger.info("Field '%s' already has value '%s', skipping.", sel, current[:30])
                    return True
                locator.click()
                locator.fill(value)
                logger.info("Filled field '%s' with value '%s'.", sel, value[:30])
                return True
        except Exception as exc:
            logger.debug("Selector '%s' failed: %s", sel, exc)

    return False


def _try_upload_file(page: "Page", selector: str, file_path: str) -> bool:
    """Try to upload a resume file.

    Returns True if the upload succeeded.
    """
    if not file_path or not Path(file_path).exists():
        logger.warning("Resume file not found: %s", file_path)
        return False

    for sel in selector.split(","):
        sel = sel.strip()
        try:
            locator = page.locator(sel).first
            if locator.count() > 0:
                locator.set_input_files(file_path)
                logger.info("Uploaded resume via selector '%s'.", sel)
                return True
        except Exception as exc:
            logger.debug("Upload selector '%s' failed: %s", sel, exc)

    return False


def _click_next_button(page: "Page", selector: str | None) -> bool:
    """Click the 'Next' / 'Continue' button in multi-step forms.

    Returns True if a button was found and clicked.
    """
    if not selector:
        return False

    for sel in selector.split(","):
        sel = sel.strip()
        try:
            locator = page.locator(sel).first
            if locator.count() > 0 and locator.is_visible():
                locator.click()
                page.wait_for_load_state("networkidle", timeout=10000)
                logger.info("Clicked next button '%s'.", sel)
                return True
        except Exception as exc:
            logger.debug("Next button '%s' failed: %s", sel, exc)

    return False


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_application_flow(packet: dict, headless: bool = False, timeout_ms: int = 30000) -> dict:
    """Open the apply URL and fill form fields from the autofill packet.

    Parameters
    ----------
    packet : dict
        The enriched application packet from ``build_application_packet``,
        which includes ``autofill.site_mapping`` when a known ATS is detected.
    headless : bool
        Run the browser without a visible window (default False so user can
        interact with verification steps).
    timeout_ms : int
        Page load timeout in milliseconds.

    Returns
    -------
    dict
        Status dict with keys:
        - status: "filled" | "filled_generic" | "verification_paused" | "error" | "no_playwright"
        - fields_filled: list of field names that were successfully filled
        - fields_skipped: list of field names that could not be filled
        - screenshot: path to a post-fill screenshot (or None)
        - message: human-readable status message
    """
    if not _PLAYWRIGHT_AVAILABLE:
        return {
            "status": "no_playwright",
            "fields_filled": [],
            "fields_skipped": [],
            "screenshot": None,
            "message": (
                "Playwright is not installed. Install it with:\n"
                "  pip install playwright && playwright install chromium\n"
                "The autofill packet is still available for manual use."
            ),
        }

    apply_url = packet.get("apply_url", "")
    autofill = packet.get("autofill", {})
    site_mapping = autofill.get("site_mapping")

    if not apply_url:
        return {
            "status": "error",
            "fields_filled": [],
            "fields_skipped": [],
            "screenshot": None,
            "message": "No apply_url found in the packet.",
        }

    # Initialize all variables BEFORE the try block so they're available in except
    fields_filled: list[str] = []
    fields_skipped: list[str] = []
    screenshot_path: str | None = None
    status = "error"
    message = "Unknown error"

    try:
        with sync_playwright() as pw:
            browser: Browser = pw.chromium.launch(headless=headless)
            context: BrowserContext = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            page: Page = context.new_page()

            # Navigate to the apply URL
            print(f"\n[Browser Runner] Opening: {apply_url}")
            page.goto(apply_url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=15000)

            # --- Verification check ---
            verification_reason = _detect_verification(page)
            if verification_reason:
                print(f"\n[Browser Runner] ⚠ Verification/Login detected: {verification_reason}")
                print("[Browser Runner] Please complete the verification/login in the browser window...")

                # Poll page state to check when verification is resolved or a timeout is reached (up to 5 minutes)
                max_wait_sec = 300
                resolved = False
                for _ in range(max_wait_sec):
                    time.sleep(1)
                    try:
                        if _detect_verification(page) is None:
                            resolved = True
                            break
                    except Exception:
                        break

                if resolved:
                    print("[Browser Runner] ✅ Verification/Login cleared! Proceeding with form autofill.")
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass
                else:
                    print("[Browser Runner] ⚠ Timeout or page closed waiting for verification resolution. Proceeding anyway...")

            # --- Fill form fields ---
            if site_mapping and site_mapping.get("fill_instructions"):
                print(f"[Browser Runner] Detected platform: {site_mapping['platform']}")
                fill_instructions = site_mapping["fill_instructions"]

                for field_key, instruction in fill_instructions.items():
                    selector = instruction["selector"]
                    value = instruction["value"]
                    if _try_fill_field(page, selector, value):
                        fields_filled.append(field_key)
                    else:
                        fields_skipped.append(field_key)

                # Upload resume
                resume_pdf = packet.get("resume_pdf", "")
                upload_selector = site_mapping.get("resume_upload_selector", "")
                if upload_selector and resume_pdf:
                    if _try_upload_file(page, upload_selector, resume_pdf):
                        fields_filled.append("resume_pdf")
                    else:
                        fields_skipped.append("resume_pdf")

                # Handle multi-step forms
                if site_mapping.get("multi_step") and site_mapping.get("next_button_selector"):
                    print("[Browser Runner] Multi-step form detected. Attempting to advance...")
                    step = 1
                    max_steps = 5
                    while step <= max_steps:
                        if _click_next_button(page, site_mapping["next_button_selector"]):
                            step += 1
                            time.sleep(1)
                            # Try filling fields on the new step
                            for field_key, instruction in fill_instructions.items():
                                if field_key not in fields_filled:
                                    if _try_fill_field(page, instruction["selector"], instruction["value"]):
                                        fields_filled.append(field_key)
                        else:
                            break

                status = "filled"
                message = (
                    f"Form filled on {site_mapping['platform']}. "
                    f"{len(fields_filled)} fields filled, {len(fields_skipped)} skipped. "
                    f"Review the form in the browser and click Apply/Submit when ready."
                )
            else:
                # No site mapping — try generic approach
                print("[Browser Runner] No known ATS detected. Trying generic field filling...")
                generic_map = {
                    "full_name": "input[name*='name'], input[id*='name'], input[autocomplete='name']",
                    "email": "input[type='email'], input[name*='email'], input[id*='email']",
                    "phone": "input[type='tel'], input[name*='phone'], input[id*='phone']",
                    "linkedin": "input[name*='linkedin'], input[placeholder*='LinkedIn']",
                    "github": "input[name*='github'], input[placeholder*='GitHub']",
                    "portfolio": "input[name*='website'], input[name*='portfolio'], input[placeholder*='Website']",
                }
                for field_key, selector in generic_map.items():
                    value = autofill.get(field_key, "")
                    if _try_fill_field(page, selector, value):
                        fields_filled.append(field_key)
                    else:
                        fields_skipped.append(field_key)

                # Try generic resume upload
                resume_pdf = packet.get("resume_pdf", "")
                if resume_pdf:
                    if _try_upload_file(page, "input[type='file']", resume_pdf):
                        fields_filled.append("resume_pdf")
                    else:
                        fields_skipped.append("resume_pdf")

                status = "filled_generic"
                message = (
                    f"Generic form fill attempted. "
                    f"{len(fields_filled)} fields filled, {len(fields_skipped)} skipped. "
                    f"Review the form in the browser and click Apply/Submit when ready."
                )

            # --- Screenshot ---
            screenshot_dir = Path(__file__).resolve().parent / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            import re
            safe_name = re.sub(r"[^a-zA-Z0-9]+", "_", f"{packet.get('title', 'job')}_{packet.get('company', 'unknown')}").strip("_").lower()
            screenshot_file = screenshot_dir / f"filled_{safe_name}.png"
            page.screenshot(path=str(screenshot_file), full_page=True)
            screenshot_path = str(screenshot_file)
            print(f"[Browser Runner] Screenshot saved: {screenshot_path}")

            # --- Wait for browser close ---
            print(f"\n[Browser Runner] ✅ {message}")
            print("[Browser Runner] Review/Submit the form in the browser. The runner will exit once you close the browser window.")

            try:
                page.wait_for_event("close", timeout=600000)  # Wait up to 10 minutes
            except Exception:
                pass

            browser.close()

    except Exception as exc:
        logger.error("Browser runner failed: %s", exc)
        return {
            "status": "error",
            "fields_filled": fields_filled,
            "fields_skipped": fields_skipped,
            "screenshot": screenshot_path,
            "message": f"Browser runner error: {exc}",
        }

    return {
        "status": status,
        "fields_filled": fields_filled,
        "fields_skipped": fields_skipped,
        "screenshot": screenshot_path,
        "message": message,
    }
