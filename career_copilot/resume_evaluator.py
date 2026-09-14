"""Resume Evaluator & Optimizer — quality gate for generated resumes.

Provides sanitization, structural validation, and Gemini-powered re-polishing
to ensure every resume that enters the pipeline is clean, ATS-friendly, and
free of file paths, debug metadata, and formatting artifacts.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("career_copilot.resume_evaluator")


# ---------------------------------------------------------------------------
# Sanitization patterns — things that should NEVER appear in a resume
# ---------------------------------------------------------------------------

_PATH_PATTERNS: list[re.Pattern] = [
    # Windows absolute paths  (C:\..., D:\...)
    re.compile(r"[A-Z]:\\[^\s\"']+", re.IGNORECASE),
    # Unix absolute paths (/home/..., /Users/..., /tmp/...)
    re.compile(r"(?:^|[\s(])(/(?:home|Users|tmp|var|opt|etc|usr|mnt|PROJECT_FILE)[^\s\"')]+)", re.MULTILINE),
    # file:/// URIs
    re.compile(r"file:///[^\s\"']+", re.IGNORECASE),
]

_METADATA_PATTERNS: list[re.Pattern] = [
    # JSON-style key-value artifacts
    re.compile(r'"(?:resume_pdf|resume_text|match_percentage|autofill|apply_url|human_verification_step)"\s*:'),
    # [Tool] debug lines
    re.compile(r"^\[Tool\].*$", re.MULTILINE),
    # Raw keyword dump lines like "Keywords: python, flask, ..."
    re.compile(r"^(?:Keywords|Extracted Keywords|Top Keywords|Ranked Keywords)\s*:.*$", re.MULTILINE | re.IGNORECASE),
    # Base resume evidence markers
    re.compile(r"^(?:Evidence|Base Resume Evidence|Resume Evidence Lines?)\s*:.*$", re.MULTILINE | re.IGNORECASE),
    # Lines that look like raw dict/list artifacts
    re.compile(r"^\s*\{['\"](?:title|company|url|description)['\"].*\}\s*$", re.MULTILINE),
]

_FENCE_PATTERN = re.compile(r"^```[a-zA-Z]*\s*$", re.MULTILINE)

# Section headings we expect in a well-structured resume
_EXPECTED_SECTIONS = {
    "summary", "professional summary", "objective", "profile",
    "skills", "core skills", "technical skills",
    "experience", "work experience", "professional experience", "experience & impact",
    "projects", "project highlights", "portfolio",
    "education", "certifications", "certificates",
}


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

def sanitize_resume_text(text: str) -> str:
    """Strip file paths, markdown fences, debug artifacts, and metadata noise.

    This is the primary cleanup function — it should be called on every
    resume text before it reaches the PDF exporter or any user-facing output.
    """
    if not text:
        return text

    cleaned = text

    # 1. Remove entire markdown code fence blocks (``` ... ```)
    cleaned = re.sub(r"```[a-zA-Z]*\n.*?```", "", cleaned, flags=re.DOTALL)
    # Also remove any remaining standalone fence markers
    cleaned = _FENCE_PATTERN.sub("", cleaned)

    # 2. Remove file paths
    for pattern in _PATH_PATTERNS:
        cleaned = pattern.sub("", cleaned)

    # 3. Remove metadata / debug lines
    for pattern in _METADATA_PATTERNS:
        cleaned = pattern.sub("", cleaned)

    # 4. Clean up residual noise lines
    lines = cleaned.splitlines()
    result_lines: list[str] = []
    for line in lines:
        stripped = line.strip()

        # Skip completely empty lines (but keep one between sections)
        if not stripped:
            if result_lines and result_lines[-1].strip() == "":
                continue
            result_lines.append("")
            continue

        # Skip lines that are just quotes, brackets, or punctuation residue
        if re.fullmatch(r'["\'\[\]{}<>().,;:\-_|/\\*#`~\s]+', stripped):
            continue

        # Skip very short orphaned lines (< 4 chars, non-heading)
        if len(stripped) < 4 and not stripped.isupper():
            continue

        result_lines.append(line)

    # 5. Remove trailing blank lines
    while result_lines and result_lines[-1].strip() == "":
        result_lines.pop()

    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# Quality Evaluation
# ---------------------------------------------------------------------------

def evaluate_resume_quality(resume_text: str, candidate_name: str | None = None) -> dict:
    """Score a resume on multiple quality dimensions.

    Returns a dict with:
        score (int 0-100): overall quality score
        issues (list[str]): specific problems found
        passed (bool): True if score >= 70
        breakdown (dict): per-category scores
    """
    if not resume_text or len(resume_text.strip()) < 50:
        return {
            "score": 0,
            "issues": ["Resume text is empty or too short."],
            "passed": False,
            "breakdown": {},
        }

    issues: list[str] = []
    breakdown: dict[str, int] = {}

    # --- Category 1: Cleanliness (25 points) ---
    cleanliness = 25
    for pattern in _PATH_PATTERNS:
        if pattern.search(resume_text):
            cleanliness -= 10
            issues.append("Contains file system paths.")
            break

    for pattern in _METADATA_PATTERNS:
        if pattern.search(resume_text):
            cleanliness -= 8
            issues.append("Contains debug metadata or tool artifacts.")
            break

    if _FENCE_PATTERN.search(resume_text):
        cleanliness -= 7
        issues.append("Contains markdown code fences.")

    breakdown["cleanliness"] = max(0, cleanliness)

    # --- Category 2: Structure (25 points) ---
    structure = 0
    text_lower = resume_text.lower()
    found_sections = set()

    for section in _EXPECTED_SECTIONS:
        # Match as a standalone heading (entire line or line starting with it)
        pattern = re.compile(rf"^{re.escape(section)}$", re.MULTILINE | re.IGNORECASE)
        if pattern.search(resume_text):
            found_sections.add(section)

    # Also check for ALL-CAPS headings
    for line in resume_text.splitlines():
        stripped = line.strip()
        clean = re.sub(r"\s+", "", stripped)
        if clean and clean.isupper() and 3 < len(stripped) < 50:
            if not any(c in stripped for c in (":", "|", "@", ".com", "http")):
                found_sections.add(stripped.lower())

    section_count = len(found_sections)
    if section_count >= 4:
        structure = 25
    elif section_count >= 3:
        structure = 20
    elif section_count >= 2:
        structure = 15
    elif section_count >= 1:
        structure = 10
    else:
        issues.append("Missing standard resume section headings.")

    breakdown["structure"] = structure

    # --- Category 3: Contact Information (15 points) ---
    contact = 0
    if candidate_name is None:
        candidate_name = os.environ.get("RESUME_NAME", "")

    if candidate_name and candidate_name.lower() in text_lower[:300]:
        contact += 5
    else:
        issues.append("Candidate name not found in the first few lines.")

    if re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", resume_text):
        contact += 4
    else:
        issues.append("No email address found.")

    if re.search(r"\+?\d[\d\s\-()]{7,}", resume_text):
        contact += 3
    else:
        issues.append("No phone number found.")

    if "linkedin" in text_lower:
        contact += 3
    else:
        issues.append("No LinkedIn URL found.")

    breakdown["contact_info"] = contact

    # --- Category 4: Content Quality (20 points) ---
    content = 0
    bullet_count = len(re.findall(r"^[\s]*[-•*]\s", resume_text, re.MULTILINE))
    if bullet_count >= 6:
        content += 10
    elif bullet_count >= 3:
        content += 6
    elif bullet_count >= 1:
        content += 3
    else:
        issues.append("No bullet points found — resume may lack detail.")

    # Check for impact/metric language
    metric_patterns = [
        r"\d+%", r"\d+x", r"\$\d+",
        r"increased", r"decreased", r"improved", r"reduced",
        r"built", r"designed", r"developed", r"implemented",
        r"automated", r"optimized", r"delivered", r"launched",
    ]
    metric_hits = sum(1 for p in metric_patterns if re.search(p, resume_text, re.IGNORECASE))
    if metric_hits >= 5:
        content += 10
    elif metric_hits >= 3:
        content += 7
    elif metric_hits >= 1:
        content += 4
    else:
        issues.append("Lacks measurable impact statements (numbers, percentages, action verbs).")

    breakdown["content_quality"] = content

    # --- Category 5: Length (15 points) ---
    word_count = len(resume_text.split())
    length = 0
    if 150 <= word_count <= 800:
        length = 15
    elif 100 <= word_count <= 1000:
        length = 10
    elif 50 <= word_count <= 1200:
        length = 5
    else:
        if word_count < 50:
            issues.append(f"Resume too short ({word_count} words).")
        else:
            issues.append(f"Resume too long ({word_count} words) — consider trimming.")

    breakdown["length"] = length

    # --- Final Score ---
    total = sum(breakdown.values())
    return {
        "score": total,
        "issues": issues,
        "passed": total >= 70,
        "breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# Gemini-powered re-optimization
# ---------------------------------------------------------------------------

def optimize_resume_for_role(
    resume_text: str,
    title: str,
    company: str,
    description: str,
    quality_issues: list[str] | None = None,
) -> str:
    """Use Gemini to re-polish a resume that failed quality checks.

    If the Gemini API is unavailable, falls back to rule-based sanitization only.
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logger.info("No GOOGLE_API_KEY — applying rule-based sanitization only.")
        return sanitize_resume_text(resume_text)

    candidate_name = os.environ.get("RESUME_NAME", "Jagan Babu R")
    email = os.environ.get("RESUME_EMAIL", "jaganravi131@gmail.com")
    phone = os.environ.get("RESUME_PHONE", "+91-8124819503")
    linkedin = os.environ.get("RESUME_LINKEDIN", "https://www.linkedin.com/in/jagan-babu-r/")
    github = os.environ.get("RESUME_GITHUB", "https://github.com/Jaganravi131")
    portfolio = os.environ.get("RESUME_PORTFOLIO", "https://portfolio-ygig.vercel.app/")

    issues_block = ""
    if quality_issues:
        issues_block = (
            "\n\nThe following quality issues were detected in the current version and MUST be fixed:\n"
            + "\n".join(f"- {issue}" for issue in quality_issues)
        )

    prompt = (
        f"You are an expert ATS resume optimizer performing a FINAL POLISH pass.\n"
        f"The resume below was generated for the role: {title} at {company}.\n\n"
        f"Current resume text:\n{resume_text}\n\n"
        f"Target job description:\n{description}\n"
        f"{issues_block}\n\n"
        f"STRICT OUTPUT RULES:\n"
        f"1. Start DIRECTLY with the candidate name. No intro text, no markdown fences, no commentary.\n"
        f"2. Line 1: {candidate_name}\n"
        f"3. Line 2: Email: {email} | Phone: {phone}\n"
        f"4. Line 3: LinkedIn: {linkedin} | GitHub: {github} | Portfolio: {portfolio}\n"
        f"5. Use ALL-CAPS section headings: PROFESSIONAL SUMMARY, CORE SKILLS, EXPERIENCE, PROJECTS, EDUCATION\n"
        f"6. Use '- ' prefix for bullet points. Include measurable impact where possible.\n"
        f"7. ABSOLUTELY NO file paths, no debug info, no metadata, no JSON, no markdown fences.\n"
        f"8. ABSOLUTELY NO text after the last section. End cleanly after the final bullet point or entry.\n"
        f"9. Keep it concise — aim for 300-600 words total.\n"
        f"10. Tailor keywords to the job description but stay truthful to the candidate's background."
    )

    try:
        from google import genai
        from .config import get_gemini_model
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=get_gemini_model(),
            contents=prompt,
        )
        text = response.text.strip()

        # Final safety: run sanitizer on Gemini output too
        text = sanitize_resume_text(text)

        if text and candidate_name.lower() in text.lower()[:200]:
            return text

        logger.warning("Gemini optimization output did not pass validation, using sanitized original.")
    except Exception as exc:
        logger.warning("Gemini resume optimization failed: %s. Using sanitized original.", exc)

    return sanitize_resume_text(resume_text)


# ---------------------------------------------------------------------------
# PDF Validation
# ---------------------------------------------------------------------------

def validate_pdf_output(pdf_path: str, candidate_name: str | None = None) -> dict:
    """Validate that an exported resume PDF is clean and well-formed.

    Returns a dict with:
        valid (bool): True if the PDF passes all checks
        issues (list[str]): specific problems found
        page_count (int): number of pages
        word_count (int): approximate word count from extracted text
    """
    result = {
        "valid": False,
        "issues": [],
        "page_count": 0,
        "word_count": 0,
    }

    path = Path(pdf_path)
    if not path.exists():
        result["issues"].append(f"PDF file does not exist: {path.name}")
        return result

    if path.stat().st_size < 500:
        result["issues"].append("PDF file is suspiciously small (< 500 bytes).")
        return result

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        result["page_count"] = len(reader.pages)

        full_text = ""
        for page in reader.pages:
            full_text += (page.extract_text() or "") + "\n"

        full_text = full_text.strip()
        result["word_count"] = len(full_text.split())

        if not full_text:
            result["issues"].append("PDF has no extractable text content.")
            return result

        if candidate_name is None:
            candidate_name = os.environ.get("RESUME_NAME", "")

        if candidate_name and candidate_name.lower() not in full_text.lower()[:500]:
            result["issues"].append("Candidate name not found in the PDF content.")

        # Check for path contamination in the PDF
        for pattern in _PATH_PATTERNS:
            if pattern.search(full_text):
                result["issues"].append("PDF content contains file system paths.")
                break

        if result["page_count"] > 3:
            result["issues"].append(f"Resume is {result['page_count']} pages — should be 1-2 pages.")

        if result["word_count"] < 50:
            result["issues"].append("PDF has very little text content.")

    except Exception as exc:
        result["issues"].append(f"Could not parse PDF: {exc}")
        return result

    result["valid"] = len(result["issues"]) == 0
    return result


# ---------------------------------------------------------------------------
# Convenience: evaluate + auto-fix pipeline
# ---------------------------------------------------------------------------

def evaluate_and_optimize(
    resume_text: str,
    title: str,
    company: str,
    description: str,
) -> tuple[str, dict]:
    """Run the full evaluate → optimize → re-evaluate pipeline.

    Returns (optimized_text, final_evaluation).
    """
    # Always sanitize first
    cleaned = sanitize_resume_text(resume_text)

    # Evaluate
    evaluation = evaluate_resume_quality(cleaned)

    if evaluation["passed"]:
        return cleaned, evaluation

    # Didn't pass — try Gemini optimization
    logger.info(
        "Resume quality score %d/100 (below 70). Attempting optimization. Issues: %s",
        evaluation["score"],
        evaluation["issues"],
    )
    optimized = optimize_resume_for_role(
        cleaned, title, company, description, evaluation["issues"]
    )

    # Re-evaluate
    final_eval = evaluate_resume_quality(optimized)
    return optimized, final_eval


def check_anti_hallucination_guardrail(tailored_text: str, base_resume_text: str) -> list[str]:
    """Flag technical skills in the tailored resume that were absent in the base resume.

    Returns a list of warnings if ungrounded technical frameworks or tools were invented.
    """
    from .relevance import SKILL_CATEGORIES
    all_known_tech: set[str] = set()
    for cat_skills in SKILL_CATEGORIES.values():
        all_known_tech.update(cat_skills)

    tailored_lower = tailored_text.lower()
    base_lower = base_resume_text.lower()

    unverified = []
    for skill in all_known_tech:
        pattern = rf"\b{re.escape(skill)}\b"
        if re.search(pattern, tailored_lower) and not re.search(pattern, base_lower):
            unverified.append(skill)

    if unverified:
        return [f"Anti-Hallucination Warning: Found skills in tailored resume not present in base resume: {', '.join(unverified[:5])}"]
    return []

