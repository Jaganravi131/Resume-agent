from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import logging
import os
import re
from urllib.parse import quote_plus

from pypdf import PdfReader
from reportlab.lib.pagesizes import LETTER

from . import database
from .config import STOPWORDS, fetch_json, fetch_with_retry, get_gemini_model
from .autofill_helpers import build_site_specific_packet, get_autofill_mapping
from .relevance import compute_relevance_score, filter_jobs_by_relevance, passes_minimum_threshold
from . import profile_optimizer as profopt
from .resume_evaluator import sanitize_resume_text, evaluate_and_optimize

logger = logging.getLogger("career_copilot.tools")


# ---------------------------------------------------------------------------
# Resume text cache — avoids re-reading PDF from disk on every call
# ---------------------------------------------------------------------------

_resume_text_cache: str | None = None


def _invalidate_resume_cache() -> None:
    """Clear the cached resume text (call when resume PDFs change)."""
    global _resume_text_cache
    _resume_text_cache = None


def _normalize_keywords(text: str) -> list[str]:
    return [word for word in re.split(r"\W+", text.lower()) if len(word) > 2]


def _extract_ranked_keywords(text: str, top_n: int = 8) -> list[str]:
    cleaned = [word for word in _normalize_keywords(text) if word not in STOPWORDS]
    if not cleaned:
        return ["python", "apis", "automation", "testing"]
    return [word for word, _ in Counter(cleaned).most_common(top_n)]


def _keywords_in_text(keywords: list[str], text: str) -> list[str]:
    haystack = text.lower()
    return [keyword for keyword in keywords if keyword in haystack]


def compute_match_percentage(title: str, description: str) -> int:
    """Compute match percentage using the advanced TF-IDF relevance engine.

    Backward-compatible: returns a single int (0-100).
    For the full breakdown, use ``compute_relevance_score`` from relevance.py.
    """
    base_resume_text = _extract_resume_text()
    if not base_resume_text:
        return 0
    result = compute_relevance_score(title, description, base_resume_text)
    return result.score


def compute_match_detailed(title: str, description: str, all_descriptions: list[str] | None = None) -> dict:
    """Compute match percentage with full relevance breakdown.

    Returns a dict with score, category_scores, experience info, matching/missing skills.
    """
    base_resume_text = _extract_resume_text()
    if not base_resume_text:
        return {"score": 0, "rejection_reason": "No resume text available."}
    result = compute_relevance_score(title, description, base_resume_text, all_descriptions)
    return result.to_dict()


def _build_autofill_payload(title: str, company: str, url: str, resume_pdf: str, match_percentage: int) -> dict:
    return {
        "job_title": title,
        "company": company,
        "apply_url": url,
        "match_percentage": match_percentage,
        "resume_pdf": resume_pdf,
        "full_name": os.environ.get("RESUME_NAME", "Jagan Babu R"),
        "email": os.environ.get("RESUME_EMAIL", "your.email@example.com"),
        "phone": os.environ.get("RESUME_PHONE", "+91-00000-00000"),
        "linkedin": os.environ.get("RESUME_LINKEDIN", "https://www.linkedin.com/in/jagan-babu-r/"),
        "github": os.environ.get("RESUME_GITHUB", "https://github.com/Jaganravi131"),
        "portfolio": os.environ.get("RESUME_PORTFOLIO", "https://portfolio-ygig.vercel.app/"),
    }


def build_application_packet(title: str, company: str, description: str, url: str) -> dict:
    """Build a complete application packet for one job.

    Generates resume text and PDF only once, and reuses the match score.
    """
    # Generate resume text once, reuse for PDF
    resume_text = generate_tailored_resume(title, company, description)
    resume_pdf = _export_resume_pdf_from_text(title, company, resume_text)
    match_percentage = compute_match_percentage(title, description)

    # Use only the filename — never expose absolute paths to the user
    resume_pdf_display = Path(resume_pdf).name if resume_pdf else ""

    base_packet = {
        "title": title,
        "company": company,
        "apply_url": url,
        "match_percentage": match_percentage,
        "resume_text": resume_text,
        "resume_pdf": resume_pdf,
        "resume_pdf_name": resume_pdf_display,
        "autofill": _build_autofill_payload(title, company, url, resume_pdf, match_percentage),
        "human_verification_step": "Open the page, complete any human verification, then paste the autofill values or use them in your form flow.",
    }

    # Enrich with site-specific selectors when a known ATS is detected
    return build_site_specific_packet(base_packet, url)


def _build_resume_filename(title: str, company: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", f"{title}_{company}").strip("_")
    return f"resume_{safe.lower()}.pdf"


def _get_resume_sources() -> list[Path]:
    resume_dir = Path(__file__).resolve().parent / "resume"
    if not resume_dir.exists():
        return []
    return sorted(resume_dir.glob("*.pdf"))


def _extract_resume_text(max_chars: int = 6000) -> str:
    """Extract text from resume PDFs. Cached to avoid repeated disk reads."""
    global _resume_text_cache
    if _resume_text_cache is not None:
        return _resume_text_cache

    texts: list[str] = []
    for resume_pdf in _get_resume_sources():
        try:
            reader = PdfReader(str(resume_pdf))
            pages = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
            text = "\n".join(pages).strip()
            if text:
                texts.append(text)
        except Exception as exc:
            logger.warning("Failed to parse base resume %s: %s", resume_pdf, exc)
    if not texts:
        _resume_text_cache = ""
        return ""
    merged = "\n".join(texts)
    _resume_text_cache = merged[:max_chars]
    return _resume_text_cache


def _resume_evidence_lines(resume_text: str, keywords: list[str], max_lines: int = 3) -> list[str]:
    if not resume_text:
        return []
    lines = [line.strip() for line in resume_text.splitlines() if len(line.strip()) > 35]
    scored: list[tuple[int, str]] = []
    for line in lines:
        low = line.lower()
        score = sum(1 for kw in keywords if kw in low)
        if score > 0:
            scored.append((score, line))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected: list[str] = []
    for _, line in scored:
        cleaned = re.sub(r"\s+", " ", line)
        if cleaned not in selected:
            selected.append(cleaned)
        if len(selected) >= max_lines:
            break
    return selected


def _wrap_lines(text: str, width: int = 95) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        if len(candidate) <= width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def _score_job(title: str, description: str, company: str, keywords: list[str]) -> tuple[int, int, int]:
    title_text = title.lower()
    body_text = f"{company} {description}".lower()
    title_score = sum(1 for keyword in keywords if keyword in title_text)
    body_score = sum(1 for keyword in keywords if keyword in body_text)
    return title_score + body_score, title_score, body_score


def _normalize_live_job(job: dict, source: str) -> dict | None:
    title = (
        job.get("title")
        or job.get("jobTitle")
        or job.get("position")
        or job.get("job_title")
        or job.get("name")
    )
    company = (
        job.get("company_name")
        or job.get("companyName")
        or job.get("company")
        or job.get("employer")
    )
    url = job.get("url") or job.get("apply_url") or job.get("job_url")
    description = job.get("description") or job.get("jobDescription") or job.get("jobExcerpt") or ""
    location = (
        job.get("candidate_required_location")
        or job.get("jobGeo")
        or job.get("location")
        or job.get("job_location")
        or "Remote"
    )

    if not title or not company or not url:
        return None

    return {
        "title": str(title).strip(),
        "company": str(company).strip(),
        "location": str(location).strip(),
        "url": str(url).strip(),
        "description": str(description).strip(),
        "source": source,
        "apply_url": str(url).strip(),
    }


def _search_remotive(query: str) -> list[dict]:
    api_url = f"https://remotive.com/api/remote-jobs?search={quote_plus(query)}"
    payload = fetch_json(api_url)
    results: list[dict] = []
    if isinstance(payload, dict):
        for job in payload.get("jobs", []):
            normalized = _normalize_live_job(job, "remotive")
            if normalized:
                results.append(normalized)
    return results


def _search_jobicy(query: str) -> list[dict]:
    tag = quote_plus(_normalize_keywords(query)[0] if _normalize_keywords(query) else query)
    api_url = f"https://jobicy.com/api/v2/remote-jobs?count=20&tag={tag}"
    payload = fetch_json(api_url)
    results: list[dict] = []
    if isinstance(payload, dict):
        for job in payload.get("jobs", []):
            normalized = _normalize_live_job(job, "jobicy")
            if normalized:
                results.append(normalized)
    return results


def _search_remoteok() -> list[dict]:
    api_url = "https://remoteok.com/api"
    payload = fetch_json(api_url)
    results: list[dict] = []
    if isinstance(payload, list):
        for job in payload[1:]:
            normalized = _normalize_live_job(job, "remoteok")
            if normalized:
                results.append(normalized)
    return results


def _search_ddg_job_boards(query: str) -> list[dict]:
    """Search DuckDuckGo for job listings hosted on Greenhouse, Lever, and Ashby."""
    import urllib.parse
    import urllib.request
    import re
    import time

    # Clean query to remove quotes
    clean_query = query.replace('"', '').replace("'", "").strip()
    if not clean_query:
        return []

    results = []
    # Search key job board hosting platforms
    platforms = [
        ("greenhouse", "site:boards.greenhouse.io"),
        ("lever", "site:jobs.lever.co"),
        ("ashby", "site:jobs.ashbyhq.com"),
    ]

    for platform_name, site_filter in platforms:
        search_query = f"{site_filter} {clean_query}"
        
        # DuckDuckGo HTML search expects a POST request to this endpoint
        post_data = urllib.parse.urlencode({'q': search_query}).encode('utf-8')
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        
        raw_html = ""
        for attempt in range(1, 3):
            try:
                req = urllib.request.Request(
                    "https://html.duckduckgo.com/html/",
                    data=post_data,
                    headers=headers
                )
                with urllib.request.urlopen(req, timeout=12) as response:
                    raw_html = response.read().decode("utf-8", errors="ignore")
                break
            except Exception as exc:
                logger.warning(
                    "DuckDuckGo POST search attempt %d failed for %s: %s",
                    attempt, platform_name, exc
                )
                time.sleep(1.0)
                
        if not raw_html or "No results found" in raw_html:
            continue

        try:
            # Parse search results from DDG HTML structure
            links = re.findall(r'href="([^"]+)"[^>]*class="result__url"', raw_html)
            snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', raw_html, re.DOTALL)
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', raw_html, re.DOTALL)

            for i in range(min(len(links), len(titles))):
                link = links[i]
                # Clean up DDG proxy links if present (e.g. //duckduckgo.com/l/?uddg=URL)
                if "duckduckgo.com/l/?uddg=" in link:
                    parsed_link = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
                    if "uddg" in parsed_link:
                        link = parsed_link["uddg"][0]

                title_text = re.sub(r"<[^>]+>", "", titles[i]).strip()
                snippet_text = re.sub(r"<[^>]+>", "", snippets[i]) if i < len(snippets) else ""
                snippet_text = snippet_text.strip()

                # Extract company name from URL netloc/path
                company = "Unknown"
                parsed_url = urllib.parse.urlparse(link)
                if "greenhouse.io" in parsed_url.netloc:
                    parts = parsed_url.path.strip("/").split("/")
                    if len(parts) >= 2:
                        company = parts[0].title()
                elif "lever.co" in parsed_url.netloc:
                    parts = parsed_url.path.strip("/").split("/")
                    if parts:
                        company = parts[0].title()
                elif "ashbyhq.com" in parsed_url.netloc:
                    parts = parsed_url.path.strip("/").split("/")
                    if parts:
                        company = parts[0].title()

                # Clean job title from the link title text
                job_title = title_text
                for separator in (" - ", " | ", " at "):
                    if separator in job_title:
                        parts = job_title.split(separator)
                        if len(parts) > 1:
                            job_title = parts[0].strip()
                            break

                # Deduplicate within this search pass
                if not any(r["url"] == link for r in results):
                    results.append({
                        "title": job_title,
                        "company": company,
                        "location": "Remote",
                        "url": link,
                        "description": snippet_text,
                        "source": "duckduckgo",
                        "apply_url": link,
                    })
        except Exception as exc:
            logger.warning("Error parsing DuckDuckGo search results for %s: %s", platform_name, exc)
            
        # Mild pause to be a good citizen
        time.sleep(1.0)

    return results


def search_job_postings(query: str, max_results: int = 10) -> list[dict]:
    """Return live job postings with real apply URLs from public sources.

    Returns a list of up to max_results jobs, or an empty list with a logged warning
    if all providers failed.
    """
    print(f"[Tool] Searching job postings for query: '{query}'")

    # Split query by commas to support multiple distinct job search queries
    sub_queries = [q.strip() for q in query.split(",") if q.strip()]
    if not sub_queries:
        sub_queries = ["python developer remote"]

    candidates: list[dict] = []
    seen_urls: set[str] = set()
    provider_errors: int = 0
    total_providers: int = 0

    for sub_query in sub_queries:
        keywords = _normalize_keywords(sub_query)
        sub_candidates: list[dict] = []

        for provider in (_search_remotive, _search_jobicy, _search_remoteok, _search_ddg_job_boards):
            total_providers += 1
            try:
                # only call remoteok once since it doesn't support query parameters
                if provider is _search_remoteok:
                    if sub_query != sub_queries[0]:
                        continue
                    provider_jobs = provider()
                else:
                    provider_jobs = provider(sub_query)
                sub_candidates.extend(provider_jobs)
            except Exception as exc:
                provider_errors += 1
                logger.warning("Live job provider %s failed: %s", provider.__name__, exc)

        for job in sub_candidates:
            if job["url"] in seen_urls:
                continue

            total_score, title_score, body_score = _score_job(job["title"], job["description"], job["company"], keywords)
            if keywords and total_score == 0:
                continue
            if len(keywords) >= 2 and title_score == 0 and total_score < 2:
                continue

            # Store the score to sort by relevance to the query that matched it
            job_copy = dict(job)
            job_copy["_search_score"] = total_score
            seen_urls.add(job["url"])
            candidates.append(job_copy)

    if not candidates and provider_errors == total_providers and total_providers > 0:
        logger.error(
            "All %d job providers failed. Check your network connection.",
            total_providers,
        )

    # Sort all matched candidates by their query matching score
    candidates.sort(key=lambda item: item.get("_search_score", 0), reverse=True)
    return candidates[:max_results]


def store_scouted_job(title: str, company: str, location: str, url: str, description: str) -> str:
    added = database.add_job(title, company, location, url, description)
    if added:
        return f"Successfully saved new job: '{title}' at '{company}' to the database."
    return f"Job '{title}' at '{company}' already exists in the database (skipped)."


def _generate_fallback_resume(title: str, company: str, description: str) -> str:
    keywords = _extract_ranked_keywords(f"{title} {description}", top_n=8)
    primary = ", ".join(keywords[:6])
    candidate_name = os.environ.get("RESUME_NAME", "Jagan Babu R")
    email = os.environ.get("RESUME_EMAIL", "jaganravi131@gmail.com")
    phone = os.environ.get("RESUME_PHONE", "+91-8124819503")
    linkedin = os.environ.get("RESUME_LINKEDIN", "https://www.linkedin.com/in/jagan-babu-r/")
    github = os.environ.get("RESUME_GITHUB", "https://github.com/Jaganravi131")
    portfolio = os.environ.get("RESUME_PORTFOLIO", "https://portfolio-ygig.vercel.app/")

    return (
        f"{candidate_name}\n"
        f"Email: {email} | Phone: {phone}\n"
        f"LinkedIn: {linkedin} | GitHub: {github} | Portfolio: {portfolio}\n\n"
        f"TARGET ROLE\n"
        f"{title} at {company}\n\n"
        f"PROFESSIONAL SUMMARY\n"
        f"Detail-oriented software engineer tailored for the {title} role at {company}. "
        f"Possesses strong knowledge in {primary} and is committed to delivering high-quality, "
        f"scalable backend features and robust integrations.\n\n"
        f"CORE SKILLS\n"
        f"- {', '.join(keywords[:4])}\n"
        f"- {', '.join(keywords[4:8]) if len(keywords) > 4 else 'automation, software engineering'}\n\n"
        f"EXPERIENCE & IMPACT\n"
        f"- Developed and optimized software components using {keywords[0]} and {keywords[1]} to align with the requirements of {company}.\n"
        f"- Implemented automation workflows and structured test scripts to improve code coverage and reliability.\n"
        f"- Participated in design discussions and contributed to APIs and core services supporting the team's objectives.\n\n"
        f"PROJECT HIGHLIGHTS\n"
        f"- Career Copilot: Built an agentic application pipeline with daily search, TF-IDF scoring, and automated form filling.\n"
        f"- Portfolio Website: Designed and hosted a responsive showcase at {portfolio} containing highlighted works."
    )


def generate_tailored_resume(title: str, company: str, description: str) -> str:
    """Generate a professionally tailored, ATS-friendly resume using Gemini.

    Falls back to a clean keyword-optimized template if the API key is missing
    or the quota is exhausted.  The output is always sanitized and quality-checked
    through the resume evaluator before being returned.
    """
    base_resume_text = _extract_resume_text()
    candidate_name = os.environ.get("RESUME_NAME", "Jagan Babu R")
    email = os.environ.get("RESUME_EMAIL", "jaganravi131@gmail.com")
    phone = os.environ.get("RESUME_PHONE", "+91-8124819503")
    linkedin = os.environ.get("RESUME_LINKEDIN", "https://www.linkedin.com/in/jagan-babu-r/")
    github = os.environ.get("RESUME_GITHUB", "https://github.com/Jaganravi131")
    portfolio = os.environ.get("RESUME_PORTFOLIO", "https://portfolio-ygig.vercel.app/")

    raw_text: str | None = None
    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            
            prompt = (
                f"You are a professional ATS resume optimizer and resume writer.\n"
                f"Your task is to rewrite the candidate's base resume to align perfectly with the target role: {title} at {company}.\n\n"
                f"Target Job Description:\n{description}\n\n"
                f"Candidate's Base Resume Text:\n{base_resume_text}\n\n"
                f"Strict formatting rules:\n"
                f"1. Start directly with the Candidate's Name (do not output any intro text or Markdown code blocks like ```).\n"
                f"2. Line 1: {candidate_name}\n"
                f"3. Line 2: Email: {email} | Phone: {phone}\n"
                f"4. Line 3: LinkedIn: {linkedin} | GitHub: {github} | Portfolio: {portfolio}\n"
                f"5. Structure the rest with capitalized section headings (e.g., PROFESSIONAL SUMMARY, CORE SKILLS, EXPERIENCE, PROJECTS, EDUCATION) and bullet points starting with '- '.\n"
                f"6. Make sure all experience descriptions are tailored to match the job requirements but stay truthful to the candidate's background.\n"
                f"7. Do NOT append any debug info, base resume evidence lists, file paths, raw keywords lists, or metadata at the bottom. Keep it extremely clean and professional."
            )
            
            response = client.models.generate_content(
                model=get_gemini_model(),
                contents=prompt
            )
            
            text = response.text.strip()
            if text and candidate_name.lower() in text.lower()[:200]:
                # Remove markdown fences if model returned them anyway
                if text.startswith("```"):
                    text = re.sub(r"^```[a-zA-Z]*\n", "", text)
                    text = re.sub(r"\n```$", "", text)
                raw_text = text.strip()
            else:
                logger.warning("Gemini generated text did not look like a valid resume, falling back.")
        except Exception as exc:
            logger.warning("Failed to generate tailored resume via Gemini API: %s. Using fallback template.", exc)

    if raw_text is None:
        raw_text = _generate_fallback_resume(title, company, description)

    # --- Quality gate: sanitize and auto-optimize if needed ---
    optimized, evaluation = evaluate_and_optimize(raw_text, title, company, description)
    if not evaluation["passed"]:
        logger.warning(
            "Resume for '%s at %s' scored %d/100 after optimization. Issues: %s",
            title, company, evaluation["score"], evaluation["issues"],
        )
    return optimized


def _export_resume_pdf_from_text(title: str, company: str, resume_text: str) -> str:
    """Export a pre-generated resume text to PDF.

    This avoids the duplicate call to generate_tailored_resume() that the
    old export_resume_pdf() used to make.  The text is sanitized one final
    time before rendering to guarantee no paths or metadata leak into the PDF.
    """
    # Final sanitization pass before rendering into PDF
    resume_text = sanitize_resume_text(resume_text)
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Flowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.colors import HexColor

    class Divider(Flowable):
        """A simple, robust horizontal divider line Flowable."""
        def __init__(self, thickness=1, color=HexColor("#CBD5E0"), space_after=6):
            super().__init__()
            self.thickness = thickness
            self.color = color
            self.space_after = space_after
            self.width = 0

        def wrap(self, availWidth, availHeight):
            self.width = availWidth
            return availWidth, self.thickness + self.space_after

        def draw(self):
            self.canv.saveState()
            self.canv.setStrokeColor(self.color)
            self.canv.setLineWidth(self.thickness)
            self.canv.line(0, self.space_after, self.width, self.space_after)
            self.canv.restoreState()

    output_dir = Path(__file__).resolve().parent / "generated_resumes"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / _build_resume_filename(title, company)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    name_style = ParagraphStyle(
        "CandidateName",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        alignment=1,
        textColor=HexColor("#1A365D"),
        spaceAfter=4
    )

    contact_style = ParagraphStyle(
        "ContactInfo",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=1,
        textColor=HexColor("#4A5568"),
        spaceAfter=12
    )

    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=HexColor("#1A365D"),
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        "BodyTextCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        textColor=HexColor("#2D3748"),
        spaceAfter=4
    )

    bullet_style = ParagraphStyle(
        "BulletCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        textColor=HexColor("#2D3748"),
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=3
    )

    story = []
    raw_lines = resume_text.splitlines()
    lines = [line.strip() for line in raw_lines]

    # Process Candidate Header (lines 0-2)
    if len(lines) >= 3:
        name = lines[0]
        contact = lines[1]
        urls = lines[2]
        story.append(Paragraph(name, name_style))
        story.append(Paragraph(f"{contact}<br/>{urls}", contact_style))
        story.append(Divider(thickness=1.5, color=HexColor("#1A365D"), space_after=8))
        remaining_lines = lines[3:]
    else:
        remaining_lines = lines

    # Process remaining lines
    for line in remaining_lines:
        if not line:
            continue

        # Check if line is a section heading
        is_heading = False
        clean_line = re.sub(r"\s+", "", line)
        if clean_line.isupper() and len(line) > 3 and not any(c in line for c in (":", "|", "@", ".com")):
            is_heading = True

        if is_heading:
            story.append(Spacer(1, 4))
            story.append(Paragraph(line, heading_style))
            story.append(Divider(thickness=0.8, color=HexColor("#CBD5E0"), space_after=4))
        elif line.startswith("- ") or line.startswith("* "):
            bullet_text = line[2:].strip()
            bullet_text = bullet_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(f"&bull; {bullet_text}", bullet_style))
        else:
            text = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(text, body_style))

    doc.build(story)
    return str(output_path)


def export_resume_pdf(title: str, company: str, description: str) -> str:
    """Generate a tailored resume and export as PDF.

    Public wrapper that generates text then delegates to _export_resume_pdf_from_text.
    """
    resume_text = generate_tailored_resume(title, company, description)
    return _export_resume_pdf_from_text(title, company, resume_text)


def recommend_projects(title: str, description: str, company: str = "", job_url: str = "") -> str:
    """Suggest strategic portfolio projects aligned with the target company.

    When company and job_url are provided, performs company intelligence
    analysis to generate company-specific project suggestions. Falls back
    to keyword-based suggestions otherwise.
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    base_resume_text = _extract_resume_text()
    if api_key and company:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            
            prompt = (
                f"You are a Project Recommender Agent.\n"
                f"Analyze the candidate's base resume and the target job description at {company}.\n\n"
                f"Candidate Resume:\n{base_resume_text}\n\n"
                f"Target Job: {title} at {company}\n"
                f"Job Description:\n{description}\n\n"
                f"Generate 3 highly tailored, strategic portfolio project recommendations. Each project should demonstrate "
                f"skills required for the job that are missing or weak on the candidate's resume, and align with what the company builds.\n\n"
                f"Format each recommendation exactly as follows:\n"
                f"Project Name: [Name]\n"
                f"Build: [Concrete description of features and architecture]\n"
                f"Why: [How it closes a gap or aligns with the company's work]\n"
                f"Stack: [Suggested technologies, comma separated]\n"
                f"Interview Frame: [How to explain this build in an interview]\n\n"
                f"Separate each project with a blank line. Do not include markdown formatting."
            )
            
            response = client.models.generate_content(
                model=get_gemini_model(),
                contents=prompt
            )
            
            text = response.text.strip()
            if text and "Project Name:" in text:
                return text
        except Exception as exc:
            logger.warning("Gemini project recommendation failed: %s. Falling back.", exc)

    if company:
        try:
            intel = profopt.analyze_company(company, job_url, description)
            projects = profopt.suggest_company_aligned_projects(
                intel, title, description, base_resume_text
            )
            if projects:
                lines = []
                for i, proj in enumerate(projects, 1):
                    lines.append(f"{i}. {proj.name}")
                    lines.append(f"   Build: {proj.what_to_build}")
                    lines.append(f"   Why: {proj.why_relevant}")
                    lines.append(f"   Stack: {', '.join(proj.tech_stack)}")
                    lines.append(f"   Effort: {proj.difficulty}")
                    lines.append(f"   Interview frame: \"{proj.interview_frame}\"")
                    lines.append("")
                return "\n".join(lines)
        except Exception as exc:
            logger.warning("Company-aligned project suggestion failed: %s", exc)

    # Fallback: keyword-based suggestions
    keywords = _normalize_keywords(f"{title} {description}")
    suggestions = [
        "A job-matching dashboard with saved searches and application tracking.",
        "A resume tailoring pipeline that rewrites bullets for a target role.",
        "A portfolio project that demonstrates the job's top 3 technical keywords.",
    ]
    if "agent" in keywords:
        suggestions.insert(0, "A multi-agent workflow demo with task delegation and notifications.")
    if "ml" in keywords or "model" in keywords:
        suggestions.insert(0, "A model evaluation and deployment project with clear metrics and monitoring.")
    return "\n".join(f"- {item}" for item in suggestions)


def create_preparation_plan(title: str, description: str) -> str:
    keywords = _normalize_keywords(description)
    focus = ", ".join(keywords[:6]) if keywords else "core role requirements"
    return (
        f"Interview prep for {title}:\n"
        f"- Review the role's core topics: {focus}\n"
        f"- Prepare 3 STAR stories around impact, ownership, and problem solving.\n"
        f"- Practice explaining one portfolio project and one resume bullet in depth.\n"
        f"- Do one timed technical drill and one behavioral mock interview today."
    )


def generate_profile_updates(title: str, company: str, description: str, job_url: str = "") -> str:
    """Generate comprehensive profile optimization for LinkedIn, Portfolio, and GitHub using Gemini.

    Falls back to the template-based report if the API is down or quota is exceeded.
    """
    base_resume_text = _extract_resume_text()
    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            
            prompt = (
                f"You are a Profile Optimizer Agent.\n"
                f"Analyze the candidate's resume, the target company, and the job description to generate customized profile optimization recommendations.\n\n"
                f"Candidate Resume:\n{base_resume_text}\n\n"
                f"Target Job: {title} at {company}\n"
                f"Job Description:\n{description}\n\n"
                f"Provide optimized recommendations for:\n"
                f"1. LINKEDIN PROFILE:\n"
                f"   - Headline (max 120 chars, highly targeted)\n"
                f"   - About Section (professional 3-paragraph summary blending candidate achievements with target stack)\n"
                f"   - Experience Bullets (how to rewrite current experience to stand out for this company)\n"
                f"   - Connection Note (a standard 250-char networking note to send to recruiters at this company)\n"
                f"2. PORTFOLIO WEBSITE:\n"
                f"   - Hero Tagline & Subtitle updates\n"
                f"   - Case Study Angle (suggest how the candidate should frame their most complex projects to align with the company's work)\n"
                f"3. GITHUB PROFILE:\n"
                f"   - Bio update\n"
                f"   - Suggestions on which of the candidate's existing repos (from the resume) to pin first and why\n"
                f"   - Specific README updates to highlight targeted skills\n\n"
                f"Format the output as a clean, highly structured professional report. Do not use generic placeholders."
            )
            
            response = client.models.generate_content(
                model=get_gemini_model(),
                contents=prompt
            )
            
            text = response.text.strip()
            if text and "LINKEDIN" in text:
                return text
        except Exception as exc:
            logger.warning("Gemini profile optimization failed: %s. Falling back.", exc)

    # Fallback to the standard template report
    if not job_url:
        job_url = ""

    try:
        report = profopt.generate_full_profile_optimization(
            title, company, description, job_url, base_resume_text
        )
        # Cache company intel
        database.save_company_intel(
            company,
            report.company_intel.domain,
            json.dumps(report.company_intel.to_dict()),
        )
        return profopt.format_optimization_report(report)
    except Exception as exc:
        logger.warning("Full profile optimization failed, using fallback: %s", exc)
        keywords = _normalize_keywords(description)
        keyword_line = ", ".join(keywords[:5]) if keywords else "the target role"
        return (
            f"GitHub: pin a project that demonstrates {keyword_line}.\n"
            f"Portfolio: update the hero section, project cards, and case study to match {title}.\n"
            f"LinkedIn: align headline, about section, and featured projects with {company} style roles."
        )


def analyze_target_company(company: str, job_url: str, description: str) -> str:
    """Analyze a target company and return intelligence about their mission, products, tech stack, and industry.

    This is a standalone tool for the agent to understand a company before
    generating tailored recommendations.
    """
    # Check cache first
    cached = database.get_company_intel(company)
    if cached:
        try:
            intel_dict = json.loads(cached[1])
            intel = profopt.CompanyIntel(**{k: v for k, v in intel_dict.items() if k in profopt.CompanyIntel.__dataclass_fields__})
            return f"[Cached] {intel.summary()}"
        except Exception:
            pass

    intel = profopt.analyze_company(company, job_url, description)

    # Cache the result
    database.save_company_intel(
        company, intel.domain, json.dumps(intel.to_dict())
    )

    return intel.summary()


def record_application(job_id: int, apply_url: str, resume_text: str, status: str = "drafted") -> str:
    database.save_application(job_id, apply_url, status, resume_text)
    return f"Application for job {job_id} recorded with status '{status}'."


def build_daily_digest(query: str) -> dict:
    """Build a daily digest with TF-IDF relevance filtering.

    Jobs below MIN_MATCH_PERCENTAGE are excluded. The digest includes
    a full relevance breakdown for each included job.
    """
    jobs = search_job_postings(query)
    all_descriptions = [j.get("description", "") for j in jobs]

    digest = []
    filtered_out_count = 0
    filter_reasons: list[str] = []

    for job in jobs:
        # Compute detailed relevance with IDF across the full batch
        relevance = compute_match_detailed(
            job["title"], job["description"], all_descriptions
        )

        # Check minimum threshold
        if relevance.get("rejection_reason") or relevance.get("score", 0) < int(os.environ.get("MIN_MATCH_PERCENTAGE", "40")):
            filtered_out_count += 1
            reason = relevance.get("rejection_reason") or f"Score {relevance.get('score', 0)}% below threshold"
            filter_reasons.append(f"{job['title']} at {job['company']}: {reason}")
            continue

        store_scouted_job(job["title"], job["company"], job["location"], job["url"], job["description"])

        # Generate resume text once, reuse for PDF
        resume_text = generate_tailored_resume(job["title"], job["company"], job["description"])
        resume_pdf_path = _export_resume_pdf_from_text(job["title"], job["company"], resume_text)

        # Only expose the filename — never the full system path
        resume_pdf_display = Path(resume_pdf_path).name if resume_pdf_path else ""

        digest.append(
            {
                "title": job["title"],
                "company": job["company"],
                "url": job["url"],
                "apply_url": job["apply_url"],
                "source": job["source"],
                "match_percentage": relevance["score"],
                "relevance": relevance,
                "resume": resume_text,
                "resume_pdf": resume_pdf_display,
                "projects": recommend_projects(job["title"], job["description"], job["company"], job["url"]),
                "prep": create_preparation_plan(job["title"], job["description"]),
                "profile": generate_profile_updates(job["title"], job["company"], job["description"], job["url"]),
            }
        )

    return {
        "query": query,
        "jobs": jobs,
        "digest": digest,
        "filtered_out_count": filtered_out_count,
        "filter_reasons": filter_reasons,
    }