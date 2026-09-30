"""Real-time resume analysis & truthful mechanical optimization.

Two public entry points, both fully deterministic and fast (<50 ms for a
typical resume) so the dashboard can re-run them on every keystroke:

  analyze_live(text, jd="")
      Complete instant check: ATS score + grade, word/line stats, section
      coverage checklist, bullet-quality heuristics (action verbs, measurable
      impact), and keyword gap against an optional job description.

  optimize_resume(text, jd="", name="", email="", phone="")
      Mechanical, TRUTHFUL fix-up: sanitization, bullet/heading normalization,
      contact block repair, missing-section placeh-templates (clearly marked
      "[Add: ...]" — never fabricated content). Returns (optimized, changes).

Honesty contract: the optimizer NEVER invents skills or achievements. It only
reformats and inserts clearly-marked placeholders; the anti-hallucination
guardrail can always validate the output afterwards.
"""

from __future__ import annotations

import logging
import re

from .config import STOPWORDS
from .relevance import _ALL_SKILLS, _tokenize
from .resume_evaluator import evaluate_resume_quality, sanitize_resume_text

logger = logging.getLogger("career_copilot.resume_optimizer")

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

SECTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "Contact info": (),  # special-cased: email or phone presence
    "Professional summary": ("summary", "profile", "objective", "about me", "about"),
    "Core skills": ("skills", "technical skills", "core skills", "tech stack", "technologies", "competencies"),
    "Experience": ("experience", "work experience", "employment", "work history", "professional experience", "internship"),
    "Projects": ("projects", "project work", "personal projects", "academic projects"),
    "Education": ("education", "academic", "qualification"),
    "Certifications": ("certification", "certificates", "courses", "licenses"),
    "Achievements / Awards": ("achievement", "award", "honors", "hackathon", "extracurricular"),
}

BULLET_MARKERS = ("- ", "•", "·", "* ", "◦", "▪", "– ", "— ")

ACTION_VERBS = {
    "built", "developed", "designed", "implemented", "created", "led", "managed",
    "improved", "optimized", "reduced", "increased", "launched", "delivered",
    "engineered", "automated", "deployed", "integrated", "architected", "scaled",
    "wrote", "trained", "evaluated", "analyzed", "migrated", "refactored",
    "collaborated", "mentored", "presented", "achieved", "secured", "won",
    "contributed", "maintained", "tested", "debugged", "researched",
}

CANONICAL_HEADINGS = {
    "professional summary": "PROFESSIONAL SUMMARY",
    "summary": "PROFESSIONAL SUMMARY",
    "profile": "PROFESSIONAL SUMMARY",
    "objective": "PROFESSIONAL SUMMARY",
    "skills": "CORE SKILLS",
    "technical skills": "CORE SKILLS",
    "core skills": "CORE SKILLS",
    "tech stack": "CORE SKILLS",
    "experience": "EXPERIENCE",
    "work experience": "EXPERIENCE",
    "professional experience": "EXPERIENCE",
    "employment history": "EXPERIENCE",
    "projects": "PROJECTS",
    "personal projects": "PROJECTS",
    "education": "EDUCATION",
    "certifications": "CERTIFICATIONS",
    "achievements": "ACHIEVEMENTS",
}

ESSENTIAL_SECTIONS = ("Contact info", "Professional summary", "Core skills",
                      "Experience", "Projects", "Education")

_SECTION_TEMPLATES = {
    "Professional summary": "PROFESSIONAL SUMMARY\n[Add 2-3 lines: years of experience, your 2-3 strongest skills, and the role you are targeting]",
    "Core skills": "CORE SKILLS\n[Add your real skills, grouped e.g. Languages / Frameworks / Tools — ONLY skills you can defend in an interview]",
    "Experience": "EXPERIENCE\n[Add roles: Company — Title (dates), then 3-4 bullets starting with an action verb and a number]",
    "Projects": "PROJECTS\n[Add 2-3 projects: name, 2 bullets (what it does + tech stack + measurable outcome), link]",
    "Education": "EDUCATION\n[Add degree, institution, years, and CGPA/percentage]",
}


# ---------------------------------------------------------------------------
# Live analysis
# ---------------------------------------------------------------------------

def _section_map(text: str) -> dict[str, bool]:
    lines = [re.sub(r"[^a-zA-Z ]", "", ln).strip().lower() for ln in text.splitlines()]
    result: dict[str, bool] = {}
    for section, patterns in SECTION_PATTERNS.items():
        if section == "Contact info":
            result[section] = bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)) or bool(
                re.search(r"(?:\+?\d[\d\s-]{8,}\d)", text))
            continue
        found = any(
            ln == p or ln.startswith(p + " ") or ln.endswith(" " + p) or f" {p} " in f" {ln} "
            for ln in lines for p in patterns
        )
        result[section] = found
    return result


def _bullet_lines(text: str) -> list[str]:
    bullets = []
    for ln in text.splitlines():
        stripped = ln.strip()
        if any(stripped.startswith(m) for m in BULLET_MARKERS):
            content = re.sub(r"^[-•·*◦▪–—]\s*", "", stripped).strip()
            if len(content) > 8:
                bullets.append(content)
    return bullets


def _bullet_stats(bullets: list[str]) -> dict:
    if not bullets:
        return {"count": 0, "with_numbers": 0, "with_action_verb": 0}
    with_numbers = sum(1 for b in bullets if re.search(r"\d", b))
    with_verbs = sum(
        1 for b in bullets
        if (first := (b.split() or [""])[0].lower().strip(".,;:()")) in ACTION_VERBS
    )
    return {"count": len(bullets), "with_numbers": with_numbers, "with_action_verb": with_verbs}


def _keyword_gap(resume_text: str, jd_text: str, top_n: int = 20) -> dict:
    if not jd_text.strip():
        return {"total": 0, "present": [], "missing": [], "coverage": 0.0}
    jd_tokens = _tokenize(jd_text)
    resume_set = set(_tokenize(resume_text))
    freq: dict[str, int] = {}
    for tok in jd_tokens:
        if tok not in STOPWORDS and len(tok) > 2:
            freq[tok] = freq.get(tok, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    keywords = [k for k, _ in ranked[:top_n]]
    present = [k for k in keywords if k in resume_set]
    missing = [k for k in keywords if k not in resume_set]
    coverage = (len(present) / len(keywords) * 100) if keywords else 0.0
    return {"total": len(keywords), "present": present, "missing": missing,
            "coverage": round(coverage, 1)}


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 50:
        return "D"
    return "F"


def analyze_live(text: str, jd: str = "", candidate_name: str | None = None) -> dict:
    """Complete instant resume check (real-time friendly, deterministic)."""
    cleaned = sanitize_resume_text(text or "")
    quality = evaluate_resume_quality(cleaned, candidate_name)
    words = len(cleaned.split())
    bullets = _bullet_lines(cleaned)
    stats = _bullet_stats(bullets)
    sections = _section_map(cleaned)
    gap = _keyword_gap(cleaned, jd)

    suggestions: list[str] = []
    missing_sections = [s for s in ESSENTIAL_SECTIONS if not sections.get(s)]
    for section in missing_sections:
        suggestions.append(f"Missing section: {section}")
    if stats["count"] == 0:
        suggestions.append("No bullet points — use '- ' bullets so ATS parses your impact.")
    elif stats["with_numbers"] / stats["count"] < 0.5:
        suggestions.append(
            f"Quantify impact: only {stats['with_numbers']}/{stats['count']} bullets contain a number."
        )
    if stats["count"] and stats["with_action_verb"] / stats["count"] < 0.6:
        suggestions.append(
            f"Start bullets with strong action verbs ({stats['with_action_verb']}/{stats['count']} do)."
        )
    if words < 150:
        suggestions.append("Resume is very short (<150 words) — add projects/experience detail.")
    if words > 900:
        suggestions.append("Resume is long (>900 words) — trim to 1 page for fresher roles.")
    if gap["total"] and gap["coverage"] < 60 and jd.strip():
        suggestions.append(
            f"JD keyword coverage is {gap['coverage']}% — mirror the posting's language where TRUE."
        )

    return {
        "cleaned_text": cleaned,
        "score": quality["score"],
        "passed": quality["passed"],
        "grade": _grade(quality["score"]),
        "issues": quality["issues"],
        "breakdown": quality.get("breakdown", {}),
        "words": words,
        "sections": sections,
        "missing_sections": missing_sections,
        "bullets": stats,
        "keyword_gap": gap,
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# Truthful mechanical optimization
# ---------------------------------------------------------------------------

def _normalize_bullets_and_headings(text: str, changes: list[str]) -> str:
    out_lines = []
    bullets_fixed = 0
    headings_fixed = 0
    for ln in text.splitlines():
        stripped = ln.rstrip()
        s = stripped.strip()
        # Normalize exotic bullets to '- '
        m = re.match(r"^[•·*◦▪–—]\s*(.+)$", s)
        if m:
            stripped = "- " + m.group(1)
            bullets_fixed += 1
        # Normalize '-.' / '*.' style dash-dot
        m2 = re.match(r"^[-*]\.\s*(.+)$", s)
        if m2:
            stripped = "- " + m2.group(1)
            bullets_fixed += 1
        # Canonical ALL-CAPS headings (single-line, alpha-only headings)
        key = re.sub(r"[^a-zA-Z ]", "", s).strip().lower()
        if key in CANONICAL_HEADINGS and s != CANONICAL_HEADINGS[key]:
            stripped = CANONICAL_HEADINGS[key]
            headings_fixed += 1
        out_lines.append(stripped)

    # Collapse 3+ blank lines
    text_out = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip() + "\n"
    if bullets_fixed:
        changes.append(f"Normalized {bullets_fixed} bullet marker(s) to '- '")
    if headings_fixed:
        changes.append(f"Canonicalized {headings_fixed} section heading(s) to ALL-CAPS")
    return text_out


def optimize_resume(text: str, jd: str = "", name: str = "", email: str = "", phone: str = "") -> tuple[str, list[str]]:
    """Return (optimized_text, changes). Mechanical & truthful only — the output
    never contains claims the input did not contain (placeholders are bracketed)."""
    changes: list[str] = []
    working = sanitize_resume_text(text or "")

    working = _normalize_bullets_and_headings(working, changes)

    # Contact block: only from explicit inputs (never invented)
    has_email = bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", working))
    has_phone = bool(re.search(r"(?:\+?\d[\d\s-]{8,}\d)", working))
    header_lines: list[str] = []
    if name and name.lower() not in working.lower()[:300]:
        header_lines.append(name)
    contact_bits = []
    if email and not has_email:
        contact_bits.append(f"Email: {email}")
    if phone and not has_phone:
        contact_bits.append(f"Phone: {phone}")
    if contact_bits:
        header_lines.append(" | ".join(contact_bits))
    if header_lines:
        working = "\n".join(header_lines) + "\n\n" + working.lstrip()
        changes.append("Added contact header from your profile settings")

    # Missing essential sections → insert clearly-marked placeholder templates
    sections = _section_map(working)
    inserted = [s for s in ESSENTIAL_SECTIONS if s != "Contact info" and not sections.get(s)]
    if inserted:
        blocks = [working.rstrip(), ""]
        for section in inserted:
            tpl = _SECTION_TEMPLATES.get(section)
            if tpl:
                blocks.append(tpl)
                blocks.append("")
        working = "\n".join(blocks).rstrip() + "\n"
        changes.append(
            "Inserted placeholder section(s) to fill: " + ", ".join(inserted)
        )

    if not changes:
        changes.append("No mechanical fixes needed — structure already clean")
    return working, changes
