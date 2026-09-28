"""Follow-up agent: keeps applications moving instead of dying in a status column.

Upgrades the Application_agent (#4) with three capabilities:
1. **Outcome recording** — a validated event log per application
   (applied → recruiter_screen → interview → offer / rejected / ghosted).
2. **Stale detection** — submitted applications with no outcome in N days.
3. **Nudge generation** — a short, polite follow-up message draft per stale
   application (LLM-written when a key is configured, solid template otherwise).

This module is the *acting* half of the outcome feedback loop: it writes
outcomes (database.record_outcome) and surfaces stale applications so the
resume optimizer can later learn from them (tools.outcome_informed_context).
"""

from __future__ import annotations

import logging
import os

from . import database

logger = logging.getLogger("career_copilot.follow_up_agent")


# ---------------------------------------------------------------------------
# Outcome recording
# ---------------------------------------------------------------------------


def record_application_outcome(
    job_id: int, outcome: str, notes: str = "", resume_version: int | None = None
) -> str:
    """Record an outcome event for an application. Returns a human summary."""
    ok = database.record_outcome(job_id, outcome, notes=notes, resume_version=resume_version)
    if not ok:
        allowed = ", ".join(database.ALLOWED_OUTCOMES)
        return f"❌ Invalid outcome {outcome!r}. Allowed: {allowed}"
    return f"✅ Recorded outcome '{outcome}' for job {job_id}" + (
        f" (resume version {resume_version})" if resume_version else ""
    )


# ---------------------------------------------------------------------------
# Stale detection + nudges
# ---------------------------------------------------------------------------

_NUDGE_TEMPLATE = (
    "Subject: Following up — {title} application\n\n"
    "Hi {{hiring_team}},\n\n"
    "I applied for the {title} role at {company} on {applied_date} and wanted to "
    "reiterate my strong interest. Since applying, I've continued building directly "
    "relevant skills{extra}.\n\n"
    "I'd welcome the chance to discuss how my background fits the team's needs. "
    "Is there an update on the timeline for this role?\n\n"
    "Best regards,\n{{candidate_name}}"
)


def get_stale_applications(days: int = 14) -> list[dict]:
    """Submitted applications with no outcome in *days* (thin DB wrapper)."""
    return database.get_stale_applications(days=days)


def generate_follow_up_nudge(app: dict, *, use_llm: bool = True) -> str:
    """Draft a polite follow-up message for one stale application.

    Uses Gemini when available; otherwise a clean template (no API required).
    """
    if use_llm and os.environ.get("GOOGLE_API_KEY"):
        try:
            from .config import call_gemini

            prompt = (
                "Write a short (under 120 words), polite, non-desperate follow-up email "
                "for a job application that has had no response. Sign as '{name}'. "
                "Do NOT invent facts about the candidate beyond: interested in the role, "
                "applied on the date given, still available.\n\n"
                "Role: {title}\nCompany: {company}\nApplied/last update: {when}\n\n"
                "Return ONLY the email body (subject line + message)."
            ).format(
                name=_candidate_name(),
                title=app.get("title", "the role"),
                company=app.get("company", "the company"),
                when=(app.get("last_outcome_at") or "recently").split(" ")[0],
            )
            text = call_gemini(prompt, temperature=0.6)
            if text and len(text) > 60:
                return text.strip()
        except Exception as exc:  # noqa: BLE001 — template fallback below
            logger.warning("LLM nudge failed, using template: %s", exc)

    return _NUDGE_TEMPLATE.format(
        title=app.get("title", "the role"),
        company=app.get("company", "the company"),
        applied_date=(app.get("last_outcome_at") or "recently").split(" ")[0],
        extra="",
    )


def build_follow_up_digest(days: int = 14) -> dict:
    """All stale applications with a ready-to-send nudge each.

    Returns {'stale_count': int, 'items': [{'app':..., 'nudge':...}]}.
    """
    stale = get_stale_applications(days=days)
    items = [{"app": app, "nudge": generate_follow_up_nudge(app)} for app in stale]
    return {"stale_count": len(stale), "items": items}


def _candidate_name() -> str:
    try:
        from .config import get_candidate_profile

        return get_candidate_profile()["name"]
    except Exception:  # noqa: BLE001
        return "the candidate"
