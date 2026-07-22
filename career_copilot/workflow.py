from __future__ import annotations

import html
import os
import platform
import subprocess

from . import database, notifier
from . import tools


def run_daily_cycle(query: str = "Python Developer") -> dict:
    import os
    if query == "Python Developer":
        query = os.environ.get("JOB_SEARCH_QUERY", query)
    database.init_db()
    digest = tools.build_daily_digest(query)

    filtered_out = digest.get("filtered_out_count", 0)
    filter_reasons = digest.get("filter_reasons", [])

    if digest["digest"]:
        header = f"Daily career update for: {query}"
        stats = (
            f"Jobs fetched: {len(digest['jobs'])} | "
            f"Passed filters: {len(digest['digest'])} | "
            f"Filtered out: {filtered_out}"
        )
        lines = [header, stats]
        concise_lines = [header, stats]

        for item in digest["digest"]:
            lines.append(f"\n{item['title']} at {item['company']}")
            lines.append(f"Match: {item['match_percentage']}%")
            lines.append(f"Apply URL: {item['apply_url']}")
            lines.append(f"Source: {item['source']}")

            # Relevance breakdown
            rel = item.get("relevance", {})
            if rel:
                cat_scores = rel.get("category_scores", {})
                if cat_scores:
                    cat_str = ", ".join(f"{k}: {v}%" for k, v in cat_scores.items())
                    lines.append(f"Category scores: {cat_str}")
                matching = rel.get("top_matching_skills", [])
                missing = rel.get("top_missing_skills", [])
                if matching:
                    lines.append(f"Matching skills: {', '.join(matching)}")
                if missing:
                    lines.append(f"Missing skills: {', '.join(missing)}")
                lines.append(f"Experience level: {rel.get('experience_level_detected', 'unknown')}")

            lines.append("Resume:")
            lines.append(item["resume"])
            # Show only the filename — never the full system path
            pdf_name = item.get("resume_pdf", "")
            if os.sep in pdf_name or "/" in pdf_name:
                pdf_name = os.path.basename(pdf_name)
            lines.append(f"Resume PDF: {pdf_name}")
            lines.append("Projects:")
            lines.append(item["projects"])
            lines.append("Prep:")
            lines.append(item["prep"])
            lines.append("Profile sync:")
            lines.append(item["profile"])

            concise_pdf = item.get("resume_pdf", "")
            if os.sep in concise_pdf or "/" in concise_pdf:
                concise_pdf = os.path.basename(concise_pdf)
            concise_lines.append(
                f"- {item['title']} at {item['company']} | Match: {item['match_percentage']}% | Apply: {item['apply_url']} | PDF: {concise_pdf}"
            )

        if filter_reasons:
            lines.append(f"\n--- Filtered out ({filtered_out} jobs) ---")
            for reason in filter_reasons:
                lines.append(f"  • {reason}")

        summary = "\n".join(lines)
        concise_summary = "\n".join(concise_lines)

        # Escape HTML in email content to prevent injection
        safe_summary = html.escape(summary)
        telegram = notifier.send_telegram_message(concise_summary)
        whatsapp = notifier.send_whatsapp_message(concise_summary)
        email = notifier.send_email("Career Copilot Daily Digest", f"<pre>{safe_summary}</pre>")
        database.save_daily_report(summary)
    else:
        summary = (
            f"No jobs passed relevance filters for: {query}\n"
            f"Total fetched: {len(digest['jobs'])} | Filtered out: {filtered_out}"
        )
        if filter_reasons:
            summary += "\n\nFilter reasons:\n" + "\n".join(f"  • {r}" for r in filter_reasons)
        telegram = notifier.send_telegram_message(summary)
        whatsapp = notifier.send_whatsapp_message(summary)
        email = notifier.send_email("Career Copilot Daily Digest", html.escape(summary))
        database.save_daily_report(summary)

    # Periodic cleanup (runs alongside daily cycle)
    try:
        database.cleanup_old_records(days=90)
    except Exception:
        pass

    return {
        "query": query,
        "matched_jobs": len(digest["jobs"]),
        "digest_items": len(digest["digest"]),
        "filtered_out": filtered_out,
        "telegram": telegram,
        "whatsapp": whatsapp,
        "email": email,
        "summary": summary,
        "notification_status": (
            f"Daily digest sent. Passed: {len(digest['digest'])}. Filtered: {filtered_out}. "
            f"Telegram: {telegram}. WhatsApp: {whatsapp}. Email: {email}."
        ),
    }


def prepare_application_for_job(title: str, company: str, description: str, apply_url: str) -> dict:
    return tools.build_application_packet(title, company, description, apply_url)


def _open_file_cross_platform(filepath: str) -> bool:
    """Open a file with the OS default application (works on Windows, Mac, Linux)."""
    import os
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(filepath)
        elif system == "Darwin":
            subprocess.Popen(["open", filepath])
        else:
            subprocess.Popen(["xdg-open", filepath])
        return True
    except Exception as exc:
        print(f"→ Could not open file automatically: {exc}")
        return False


def run_browser_application(
    title: str,
    company: str,
    description: str,
    apply_url: str,
    headless: bool = False,
) -> dict:
    """Build an application packet, prompt the user to confirm the tailored resume,

    and then run the browser form-fill flow.

    Steps:
    1. Build the application packet (includes tailored resume + autofill data + PDF)
    2. Display resume summary and automatically open the PDF for review
    3. Wait for user confirmation (y/n)
    4. If approved, launch Playwright, navigate, pause at verification, fill fields
    5. Return status with filled/skipped fields and a screenshot
    """
    from .browser_runner import run_application_flow
    import os

    packet = tools.build_application_packet(title, company, description, apply_url)

    # --- Interactive Review Step ---
    print("\n" + "=" * 60)
    print(f" RESUME REVIEW: {title} at {company}")
    print("=" * 60)

    # Print the core summary & targeted impact bullets for quick console review
    resume_text = packet.get("resume_text", "")
    lines = resume_text.splitlines()
    summary_lines = []
    capture = False
    for line in lines:
        if any(hdr in line for hdr in ("PROFESSIONAL SUMMARY", "CORE SKILLS", "TARGETED IMPACT BULLETS")):
            capture = True
        elif line.isupper() and len(line) > 3:
            capture = False

        if capture:
            summary_lines.append(line)

    if summary_lines:
        print("\n".join(summary_lines))
    else:
        # Fallback to printing first 30 lines
        print("\n".join(lines[:30]))

    print("=" * 60)
    pdf_path = packet.get("resume_pdf", "")
    print(f"Tailored PDF generated at: {pdf_path}")

    # Open PDF using cross-platform helper
    if pdf_path and os.path.exists(pdf_path):
        if _open_file_cross_platform(pdf_path):
            print("→ Opened the tailored PDF resume on your screen for review.")

    confirm = input("\nDo you approve this customized resume and want to proceed with form autofilling? (y/n): ").strip().lower()
    if confirm != "y":
        print("\n[Application Flow] Cancelled by user. Form autofill aborted.")
        return {
            "status": "cancelled",
            "message": "User cancelled the application after reviewing the customized resume.",
            "packet": packet,
            "browser_result": None,
        }

    # User approved — continue to form filler
    print("\n[Application Flow] Approved! Launching browser automation...")
    result = run_application_flow(packet, headless=headless)

    return {
        "packet": packet,
        "browser_result": result,
    }


def run_profile_optimization(
    title: str,
    company: str,
    description: str,
    apply_url: str,
) -> dict:
    """Run the complete company analysis and profile optimization pipeline.

    Generates customized suggestions for:
    - Company intelligence
    - Aligned portfolio projects
    - LinkedIn profile headlines, about sections, experience bullets
    - Portfolio taglines, project card details, case study ideas
    - GitHub bio, repo pins, README updates, new repo ideas
    """
    report_text = tools.generate_profile_updates(title, company, description, apply_url)
    return {
        "title": title,
        "company": company,
        "report": report_text,
    }