"""Site-specific autofill helpers for major ATS platforms.

Each platform entry provides:
- detect(url)              → True if the URL belongs to this ATS
- field_map                → autofill-packet key  →  CSS selector
- resume_upload_selector   → file-input selector for resume upload
- submit_selector          → apply/submit button (reference only; user clicks it)
- multi_step               → whether the form has Next/Continue steps
- next_button_selector     → CSS selector for the "Next" button in multi-step forms
- notes                    → platform-specific caveats
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Platform definitions
# ---------------------------------------------------------------------------

_PLATFORMS: list[dict] = [
    # ------------------------------------------------------------------
    # LinkedIn Easy Apply
    # ------------------------------------------------------------------
    {
        "name": "linkedin",
        "display_name": "LinkedIn Easy Apply",
        "detect_patterns": [r"linkedin\.com"],
        "field_map": {
            "full_name": "input[id*='first-name'], input[id*='single-line-text-form'][id*='name']",
            "email": "input[id*='email'], input[name*='email']",
            "phone": "input[id*='phone'], input[name*='phone']",
            "linkedin": None,  # pre-filled from profile
            "github": "input[id*='text-input'][aria-label*='Website'], input[aria-label*='GitHub']",
            "portfolio": "input[id*='text-input'][aria-label*='Website'], input[aria-label*='Portfolio']",
        },
        "resume_upload_selector": "input[type='file'][id*='resume'], input[name*='resume']",
        "submit_selector": "button[aria-label='Submit application'], button[aria-label='Review']",
        "multi_step": True,
        "next_button_selector": "button[aria-label='Continue to next step'], button[aria-label='Next']",
        "notes": (
            "LinkedIn Easy Apply uses a multi-step modal. Fields change per step. "
            "The runner must click 'Next' between steps. Some fields are pre-filled "
            "from the LinkedIn profile and should be skipped if already populated."
        ),
    },
    # ------------------------------------------------------------------
    # Greenhouse
    # ------------------------------------------------------------------
    {
        "name": "greenhouse",
        "display_name": "Greenhouse",
        "detect_patterns": [
            r"boards\.greenhouse\.io",
            r".*\.greenhouse\.io",
            r"job-boards\.greenhouse\.io",
        ],
        "field_map": {
            "full_name": "#first_name",
            "last_name": "#last_name",
            "email": "#email",
            "phone": "#phone",
            "linkedin": "input[autocomplete='custom-question'][id*='linkedin'], input[id*='job_application_answers'][data-question*='linkedin'], input[aria-label*='LinkedIn']",
            "github": "input[autocomplete='custom-question'][id*='github'], input[aria-label*='GitHub']",
            "portfolio": "input[autocomplete='custom-question'][id*='website'], input[aria-label*='Website'], input[aria-label*='Portfolio']",
        },
        "resume_upload_selector": "#resume, input[type='file'][name*='resume'], input[data-field='resume']",
        "submit_selector": "#submit_app, button[type='submit']",
        "multi_step": False,
        "next_button_selector": None,
        "notes": (
            "Greenhouse uses a standard single-page form. The #first_name and #last_name "
            "fields are separate. Custom questions (LinkedIn, GitHub) use auto-generated IDs "
            "so we fall back to aria-label matching."
        ),
    },
    # ------------------------------------------------------------------
    # Lever
    # ------------------------------------------------------------------
    {
        "name": "lever",
        "display_name": "Lever",
        "detect_patterns": [r"jobs\.lever\.co"],
        "field_map": {
            "full_name": "input[name='name']",
            "email": "input[name='email']",
            "phone": "input[name='phone']",
            "linkedin": "input[name='urls[LinkedIn]'], input[name*='linkedin'], input[placeholder*='LinkedIn']",
            "github": "input[name='urls[GitHub]'], input[name*='github'], input[placeholder*='GitHub']",
            "portfolio": "input[name='urls[Portfolio]'], input[name*='portfolio'], input[placeholder*='Website']",
        },
        "resume_upload_selector": "input[type='file'][name='resume'], input.resume-upload-input",
        "submit_selector": "button[type='submit'].postings-btn, button.template-btn-submit",
        "multi_step": False,
        "next_button_selector": None,
        "notes": (
            "Lever uses a single-page form. The full name goes in one field (not split). "
            "URL fields use name='urls[Label]' format. Resume upload is a standard file input."
        ),
    },
    # ------------------------------------------------------------------
    # Workday
    # ------------------------------------------------------------------
    {
        "name": "workday",
        "display_name": "Workday",
        "detect_patterns": [
            r".*\.myworkdayjobs\.com",
            r".*\.wd\d+\.myworkday.*",
            r".*\.workday\.com",
        ],
        "field_map": {
            "full_name": "input[data-automation-id='legalNameSection_firstName'], input[data-automation-id='firstName']",
            "last_name": "input[data-automation-id='legalNameSection_lastName'], input[data-automation-id='lastName']",
            "email": "input[data-automation-id='email'], input[data-automation-id='addressSection_emailAddress']",
            "phone": "input[data-automation-id='phone-number'], input[data-automation-id='addressSection_phoneNumber']",
            "linkedin": "input[data-automation-id*='linkedin'], input[placeholder*='LinkedIn']",
            "github": "input[data-automation-id*='github'], input[placeholder*='GitHub']",
            "portfolio": "input[data-automation-id*='website'], input[placeholder*='Website']",
        },
        "resume_upload_selector": "input[data-automation-id='file-upload-input-ref'], input[type='file']",
        "submit_selector": "button[data-automation-id='bottom-navigation-next-button'], button[data-automation-id='submit']",
        "multi_step": True,
        "next_button_selector": "button[data-automation-id='bottom-navigation-next-button']",
        "notes": (
            "Workday uses a multi-step wizard with data-automation-id attributes. "
            "Page structure varies by employer configuration. The runner must click "
            "'Next' between steps and wait for the next page to load. Some Workday "
            "instances require account creation before the application form."
        ),
    },
    # ------------------------------------------------------------------
    # Ashby
    # ------------------------------------------------------------------
    {
        "name": "ashby",
        "display_name": "Ashby",
        "detect_patterns": [r"jobs\.ashbyhq\.com"],
        "field_map": {
            "full_name": "input[data-testid='first-name-input'], input[name='_systemfield_name']",
            "last_name": "input[data-testid='last-name-input'], input[name*='last']",
            "email": "input[data-testid='email-input'], input[name='_systemfield_email']",
            "phone": "input[data-testid='phone-input'], input[name='_systemfield_phone']",
            "linkedin": "input[data-testid*='linkedin'], input[name*='linkedin'], input[placeholder*='LinkedIn']",
            "github": "input[data-testid*='github'], input[name*='github'], input[placeholder*='GitHub']",
            "portfolio": "input[data-testid*='website'], input[name*='website'], input[placeholder*='Portfolio']",
        },
        "resume_upload_selector": "input[data-testid='resume-upload'], input[type='file']",
        "submit_selector": "button[data-testid='submit-application'], button[type='submit']",
        "multi_step": False,
        "next_button_selector": None,
        "notes": (
            "Ashby uses React with data-testid attributes. Forms are typically single-page. "
            "Some employers add custom questions that appear dynamically after the base fields."
        ),
    },
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_all_platforms() -> list[dict]:
    """Return the full list of supported ATS platform definitions."""
    return list(_PLATFORMS)


def detect_platform(url: str) -> dict | None:
    """Detect which ATS platform a URL belongs to.

    Returns the platform definition dict, or None if no match.
    """
    for platform in _PLATFORMS:
        for pattern in platform["detect_patterns"]:
            if re.search(pattern, url, re.IGNORECASE):
                return platform
    return None


def get_autofill_mapping(url: str) -> dict | None:
    """Return the autofill field mapping for a URL's ATS platform.

    Returns a dict with keys:
        platform, field_map, resume_upload_selector, submit_selector,
        multi_step, next_button_selector, notes

    Returns None if the URL does not match any known ATS.
    """
    platform = detect_platform(url)
    if platform is None:
        return None

    return {
        "platform": platform["display_name"],
        "platform_key": platform["name"],
        "field_map": platform["field_map"],
        "resume_upload_selector": platform["resume_upload_selector"],
        "submit_selector": platform["submit_selector"],
        "multi_step": platform["multi_step"],
        "next_button_selector": platform.get("next_button_selector"),
        "notes": platform["notes"],
    }


def build_site_specific_packet(base_packet: dict, url: str | None = None) -> dict:
    """Enrich a generic autofill packet with site-specific selectors.

    Parameters
    ----------
    base_packet : dict
        The packet returned by ``build_application_packet`` in tools.py.
    url : str, optional
        Override URL to detect platform from.  Falls back to
        ``base_packet["apply_url"]``.

    Returns
    -------
    dict
        The original packet with an added ``site_mapping`` key inside
        the ``autofill`` sub-dict when a known ATS is detected.
        If no ATS matches, the packet is returned unchanged.
    """
    target_url = url or base_packet.get("apply_url", "")
    mapping = get_autofill_mapping(target_url)

    packet = dict(base_packet)
    autofill = dict(packet.get("autofill", {}))

    if mapping is not None:
        # Build field → (selector, value) pairs for the runner
        fill_instructions: dict[str, dict] = {}
        for field_key, selector in mapping["field_map"].items():
            if selector is None:
                continue  # field is auto-filled by platform (e.g. LinkedIn profile)
            value = autofill.get(field_key, "")
            if not value and field_key == "last_name":
                # Split full_name into first / last for platforms that need it
                parts = autofill.get("full_name", "").rsplit(" ", 1)
                value = parts[-1] if len(parts) > 1 else ""
            if not value and field_key == "full_name":
                value = autofill.get("full_name", "")
            fill_instructions[field_key] = {
                "selector": selector,
                "value": value,
            }

        autofill["site_mapping"] = {
            "platform": mapping["platform"],
            "platform_key": mapping["platform_key"],
            "fill_instructions": fill_instructions,
            "resume_upload_selector": mapping["resume_upload_selector"],
            "submit_selector": mapping["submit_selector"],
            "multi_step": mapping["multi_step"],
            "next_button_selector": mapping["next_button_selector"],
            "notes": mapping["notes"],
        }
        autofill["platform_detected"] = mapping["platform"]
    else:
        autofill["site_mapping"] = None
        autofill["platform_detected"] = "unknown"

    packet["autofill"] = autofill
    return packet


def supported_platforms_summary() -> str:
    """Return a human-readable summary of supported ATS platforms."""
    lines = ["Supported ATS platforms for autofill:"]
    for p in _PLATFORMS:
        step_type = "multi-step" if p["multi_step"] else "single-page"
        lines.append(f"  - {p['display_name']} ({step_type})")
    return "\n".join(lines)
