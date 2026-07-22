from google.adk.agents.llm_agent import Agent
from typing import Any, cast
from .config import load_env, get_gemini_model
from .tools import (
    build_application_packet,
    build_daily_digest,
    create_preparation_plan,
    export_resume_pdf,
    compute_match_percentage,
    generate_profile_updates,
    generate_tailored_resume,
    recommend_projects,
    record_application,
    search_job_postings,
    store_scouted_job,
    analyze_target_company,
)
from .resume_evaluator import (
    evaluate_and_optimize,
    evaluate_resume_quality,
    sanitize_resume_text,
    validate_pdf_output,
)
from .autofill_helpers import get_autofill_mapping
from .browser_runner import run_application_flow
from . import database, notifier

# Load .env on module import so ADK mode gets env vars
load_env()

AgentFactory = cast(Any, Agent)


def notify_user_of_matches() -> str:
    """Send notifications about newly found jobs via Telegram, WhatsApp, and email.

    Processes all jobs with 'found' status, builds notification messages,
    and updates their status to 'notified' after successful delivery.
    """
    found_jobs = database.get_jobs_by_status("found")
    if not found_jobs:
        return "No new jobs with 'found' status were discovered to notify the user."

    email_content = "<h2>Daily Job Match Report</h2><p>Here are your new job matches:</p><ul>"
    telegram_message = "Daily Job Match Report\n\nHere are your new job matches:\n\n"
    whatsapp_message = "Daily Job Match Report\n\nHere are your new job matches:\n\n"

    for job in found_jobs:
        job_id, title, company, location, url, description, _, _ = job
        # Escape HTML in user-controlled data
        safe_title = str(title).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe_company = str(company).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe_location = str(location).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe_desc = str(description or "")[:200].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        email_content += (
            f"<li><strong>{safe_title}</strong> at <em>{safe_company}</em> ({safe_location})<br/>"
            f"<a href='{url}'>Apply Here</a><br/><small>{safe_desc}</small></li><br/>"
        )
        telegram_message += f"- {title} - {company} ({location})\n{url}\n\n"
        whatsapp_message += f"- {title} - {company} ({location})\n{url}\n\n"

    email_content += "</ul>"

    telegram_success = notifier.send_telegram_message(telegram_message)
    whatsapp_success = notifier.send_whatsapp_message(whatsapp_message)
    email_success = notifier.send_email("Career Copilot - Daily Job Match Report", email_content)

    for job in found_jobs:
        database.update_job_status(job[0], "notified")

    return (
        f"Processed {len(found_jobs)} jobs. Telegram success: {telegram_success}. "
        f"WhatsApp success: {whatsapp_success}. Email success: {email_success}."
    )


def run_career_pipeline(query: str = "Python Developer") -> dict:
    """Run the full pipeline: search → score → resume → apply → notify.

    Only processes actionable jobs (status 'found' or 'notified'),
    not every job ever stored in the database.
    """
    import os
    if query == "Python Developer":
        query = os.environ.get("JOB_SEARCH_QUERY", query)
    digest = build_daily_digest(query)
    prep_items = []
    application_items = []

    for item in digest["digest"]:
        prep_items.append(
            {
                "title": item["title"],
                "company": item["company"],
                "match_percentage": item["match_percentage"],
                "resume": item["resume"],
                "resume_pdf": item["resume_pdf"],
                "apply_url": item["apply_url"],
                "projects": item["projects"],
                "prep": item["prep"],
                "profile": item["profile"],
            }
        )

    # Only process actionable jobs, not ALL jobs ever stored
    for job in database.get_actionable_jobs():
        job_id, title, company, location, url, description, status, created_at = job
        packet = build_application_packet(title, company, description, url)
        application_items.append(
            {
                "job_id": job_id,
                "title": title,
                "company": company,
                "application": record_application(job_id, url, packet["resume_text"]),
                "match_percentage": packet["match_percentage"],
                "resume": packet["resume_text"],
                "resume_pdf": packet["resume_pdf"],
                "apply_url": packet["apply_url"],
                "autofill": packet["autofill"],
                "human_verification_step": packet["human_verification_step"],
                "prep": create_preparation_plan(title, description),
                "profile": generate_profile_updates(title, company, description),
                "projects": recommend_projects(title, description),
            }
        )

    notification_status = notify_user_of_matches()
    return {
        "query": query,
        "matched_jobs": len(digest["jobs"]),
        "prep_items": prep_items,
        "application_items": application_items,
        "notification_status": notification_status,
    }


scout_agent = AgentFactory(
    model=get_gemini_model(),
    name="Job_scout_agent",
    description="Finds suitable job listings and stores them for the rest of the pipeline.",
    instruction=(
        "Search for jobs using search_job_postings, save matches with store_scouted_job, and pass the work "
        "to downstream agents for resume tailoring, project recommendations, notifications, and match scoring."
    ),
    tools=[search_job_postings, store_scouted_job, compute_match_percentage],
)

resume_agent = AgentFactory(
    model=get_gemini_model(),
    name="Resume_optimizer_agent",
    description="Tailors resumes to each job and captures the best keywords for the role.",
    instruction=(
        "Use generate_tailored_resume to rewrite the resume for the target job. Keep the wording specific "
        "to the posting and emphasize measurable impact. Export the final version to PDF with export_resume_pdf. "
        "Provide an application packet with build_application_packet when the browser step is ready."
    ),
    tools=[generate_tailored_resume, export_resume_pdf, build_application_packet, get_autofill_mapping],
)

resume_evaluator_agent = AgentFactory(
    model=get_gemini_model(),
    name="Resume_evaluator_agent",
    description="Evaluates, sanitizes, and optimizes generated resumes for quality, ATS-readiness, and formatting.",
    instruction=(
        "You are a Resume Quality Evaluator. Your job is to ensure every resume is perfectly formatted and "
        "free of artifacts before it reaches the candidate or a recruiter. "
        "Use evaluate_resume_quality to score the resume on structure, cleanliness, contact info, and content quality. "
        "Use sanitize_resume_text to strip file paths, markdown fences, debug metadata, and other noise. "
        "If a resume scores below 70/100, use evaluate_and_optimize to run a full Gemini-powered rewrite. "
        "Use validate_pdf_output to verify exported PDFs are clean. "
        "NEVER pass through a resume that contains file paths, JSON artifacts, or debug metadata."
    ),
    tools=[evaluate_resume_quality, sanitize_resume_text, evaluate_and_optimize, validate_pdf_output],
)

application_agent = AgentFactory(
    model=get_gemini_model(),
    name="Application_agent",
    description="Records application drafts and submission-ready application details.",
    instruction=(
        "Use record_application to track where the resume was sent and what status it has. If actual submission "
        "is not available, maintain a clean draft record for later follow-up."
    ),
    tools=[record_application],
)

project_agent = AgentFactory(
    model=get_gemini_model(),
    name="Project_recommender_agent",
    description="Suggests company-aligned portfolio projects that close key skill gaps.",
    instruction="Use recommend_projects with title, description, company name, and job URL to propose strategic project ideas.",
    tools=[recommend_projects],
)

prep_agent = AgentFactory(
    model=get_gemini_model(),
    name="Preparation_agent",
    description="Builds interview preparation plans from job descriptions.",
    instruction="Use create_preparation_plan to generate daily prep tasks and practice topics.",
    tools=[create_preparation_plan],
)

profile_agent = AgentFactory(
    model=get_gemini_model(),
    name="Profile_optimizer_agent",
    description="Optimizes LinkedIn, portfolio websites, and GitHub profiles to appeal to target companies.",
    instruction="Use generate_profile_updates to generate comprehensive suggestions. Use analyze_target_company to retrieve company intelligence first.",
    tools=[generate_profile_updates, analyze_target_company],
)

monitor_agent = AgentFactory(
    model=get_gemini_model(),
    name="Daily_monitor_agent",
    description="Dispatches daily updates to Telegram, WhatsApp, and email.",
    instruction=(
        "Use notify_user_of_matches to deliver a daily summary, then keep the user informed of send status "
        "across Telegram, WhatsApp, and email."
    ),
    tools=[notify_user_of_matches],
)

browser_agent = AgentFactory(
    model=get_gemini_model(),
    name="Browser_application_agent",
    description="Opens job application pages in the browser, pauses at verification, and fills form fields.",
    instruction=(
        "Use run_application_flow to open the apply URL in a real browser. The flow pauses at "
        "CAPTCHA or login verification so the user can complete it manually, then fills form fields "
        "using the autofill packet. NEVER click Submit — the user does that themselves. Return the "
        "status dict with filled/skipped fields and the screenshot path."
    ),
    tools=[run_application_flow],
)

root_agent = AgentFactory(
    model=get_gemini_model(),
    name="Career_copilot_agent",

    description="Coordinates job scouting, resume tailoring, application tracking, profile updates, and daily monitoring.",
    instruction=(
        "You are a Career Copilot. Orchestrate the sub-agents to find relevant jobs, tailor the resume, "
        "recommend supporting projects, prepare for interviews, sync public profiles, and send a daily update."
    ),
    sub_agents=[
        scout_agent,
        resume_agent,
        resume_evaluator_agent,
        application_agent,
        project_agent,
        prep_agent,
        profile_agent,
        monitor_agent,
        browser_agent,
    ],
)
