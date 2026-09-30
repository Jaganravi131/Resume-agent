"""Career Copilot — Streamlit dashboard.

Professional single-page dashboard around the multi-agent backend:
job scouting, ATS evaluation, resume tailoring (with audit trail),
interview prep, application tracking (status machine + resume versions)
and an interactive copilot chat.

Every AI feature reports its execution mode honestly:
  🟢 LIVE        — Gemini connected, real LLM generation
  🟡 DETERMINISTIC — no API key: local fallbacks (template/grounded) are used
"""

from __future__ import annotations

import os
import sys
import tempfile

import pandas as pd
import streamlit as st
from pypdf import PdfReader

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from career_copilot.config import load_env, get_candidate_profile

load_env()

from career_copilot import database
from career_copilot.tools import (
    search_job_postings,
    compute_match_percentage,
    compute_match_detailed,
    generate_tailored_resume_with_audit,
    export_resume_pdf_from_markdown,
    generate_application_packet_for_job,
    create_preparation_plan,
    generate_profile_updates,
    build_daily_digest,
    _extract_resume_text,
)
from career_copilot.resume_evaluator import (
    evaluate_resume_quality,
    sanitize_resume_text,
)

# ---------------------------------------------------------------------------
# Page setup & theme
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Career Copilot — Multi-Agent Job Search Suite",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  :root {
    --cc-border: #e2e8f0;
    --cc-muted: #64748b;
    --cc-accent: #4f46e5;
  }
  .cc-header {
    display: flex; align-items: baseline; gap: 0.75rem; flex-wrap: wrap;
    border-bottom: 1px solid var(--cc-border); padding-bottom: 0.6rem; margin-bottom: 1rem;
  }
  .cc-title { font-size: 1.9rem; font-weight: 800; letter-spacing: -0.02em; margin: 0; }
  .cc-sub   { color: var(--cc-muted); font-size: 0.98rem; margin: 0; }
  .cc-pill {
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    font-size: 0.78rem; font-weight: 700; letter-spacing: 0.02em;
  }
  .cc-pill-green  { background: #dcfce7; color: #166534; }
  .cc-pill-yellow { background: #fef9c3; color: #854d0e; }
  .cc-pill-red    { background: #fee2e2; color: #991b1b; }
  .cc-pill-slate  { background: #e2e8f0; color: #334155; }
  .cc-pill-indigo { background: #e0e7ff; color: #3730a3; }
  .cc-card {
    border: 1px solid var(--cc-border); border-radius: 12px;
    padding: 1rem 1.2rem; margin-bottom: 0.8rem; background: rgba(127,127,127,0.04);
  }
  .cc-section { font-size: 1.15rem; font-weight: 700; margin: 0.4rem 0 0.6rem 0; }
  .cc-muted   { color: var(--cc-muted); font-size: 0.9rem; }
  .cc-job-title { font-weight: 700; font-size: 1.02rem; }
  .cc-kv b { font-weight: 600; }
  div[data-testid="stMetricValue"] { font-size: 1.6rem; }
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_key() -> str:
    return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY", "")


def _pill(text: str, kind: str = "slate") -> str:
    return f'<span class="cc-pill cc-pill-{kind}">{text}</span>'


def _mode_badge() -> str:
    if _api_key():
        return _pill("🟢 LIVE · Gemini connected", "green")
    return _pill("🟡 DETERMINISTIC MODE · no API key (local fallbacks)", "yellow")


def _health_icon(ok: bool) -> str:
    return "🟢" if ok else "⚪"


def _match_pill(score: int | float | None) -> str:
    if score is None:
        return _pill("n/a", "slate")
    if score >= 70:
        return _pill(f"{score}% match", "green")
    if score >= 40:
        return _pill(f"{score}% match", "yellow")
    return _pill(f"{score}% match", "red")


# ---------------------------------------------------------------------------
# Sidebar — configuration & system health
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🧭 Career Copilot")
    st.caption("Multi-agent job search suite · Google ADK + Gemini")

    database.init_db()

    with st.expander("⚙️ API configuration", expanded=not bool(_api_key())):
        key_input = st.text_input(
            "Google Gemini API key",
            value=_api_key(),
            type="password",
            help="Stored only in this session's environment. Enables real LLM features.",
        )
        if key_input:
            os.environ["GOOGLE_API_KEY"] = key_input
            os.environ["GEMINI_API_KEY"] = key_input
        if _api_key():
            st.success("Gemini connected — LIVE mode", icon="🟢")
        else:
            st.info("No key set — running in deterministic mode. All offline tools still work; "
                    "LLM features use honest local fallbacks.", icon="🟡")

    st.markdown("#### System health")
    try:
        _playwright_ok = True
        try:
            import playwright  # noqa: F401
        except ImportError:
            _playwright_ok = False
        health = [
            ("Gemini API", bool(_api_key())),
            ("Notifications", any(os.environ.get(k) for k in (
                "TELEGRAM_BOT_TOKEN", "WHATSAPP_TOKEN", "SMTP_USERNAME"))),
            ("Playwright (auto-apply)", _playwright_ok),
            ("Database", True),
        ]
        for name, ok in health:
            st.markdown(f"{_health_icon(ok)} {name}")
    except Exception:
        pass

    st.divider()
    st.markdown("#### Telemetry")
    c1, c2 = st.columns(2)
    c1.metric("Jobs scouted", database.get_job_count())
    c2.metric("Applications", database.get_application_count())

    st.caption("v1.2 · offline-verified backend (35 tests · 12 evals)")

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown(
    f"""
<div class="cc-header">
  <p class="cc-title">Career Copilot</p>
  {_mode_badge()}
</div>
<p class="cc-sub">Automated job scouting · ATS scoring · truthful resume tailoring · human-in-the-loop auto-apply</p>
""",
    unsafe_allow_html=True,
)

tab_home, tab_scout, tab_eval, tab_tailor, tab_prep, tab_tracker, tab_chat = st.tabs(
    ["📌 Overview", "🔍 Job Scout", "📊 ATS Evaluator", "✨ Resume Tailor",
     "🎯 Interview Prep", "📋 Tracker", "💬 Copilot Chat"]
)

# =============================================================================
# TAB: OVERVIEW
# =============================================================================
with tab_home:
    jobs_count = database.get_job_count()
    apps_count = database.get_application_count()
    applied = len(database.get_jobs_by_status("applied"))
    notified = len(database.get_jobs_by_status("notified"))

    st.markdown('<p class="cc-section">Pipeline at a glance</p>', unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Jobs scouted", jobs_count)
    m2.metric("Notified", notified)
    m3.metric("Applied", applied)
    m4.metric("Applications tracked", apps_count)

    st.markdown('<p class="cc-section">Run the daily pipeline</p>', unsafe_allow_html=True)
    st.caption("Search → two-phase scoring (TF-IDF, Gemini re-score in LIVE mode) → store → digest.")
    pipe_col1, pipe_col2 = st.columns([2, 1])
    with pipe_col1:
        pipe_query = st.text_input("Pipeline query", value=os.environ.get("JOB_SEARCH_QUERY", "Python Developer"),
                                   key="pipe_query")
    with pipe_col2:
        st.write("")
        st.write("")
        run_pipe = st.button("🚀 Run pipeline", type="primary", width="stretch")

    if run_pipe:
        with st.spinner("Running pipeline… (offline here, live on your machine)"):
            digest = build_daily_digest(query=pipe_query, generate_full_packets=False)
            st.success(
                f"Fetched **{len(digest.get('jobs', []))}** jobs · "
                f"passed filters **{len(digest.get('digest', []))}** · "
                f"filtered out **{digest.get('filtered_out_count', 0)}** · "
                f"LLM re-scored **{digest.get('llm_rescored', 0)}**",
                icon="✅",
            )
            if digest.get("digest"):
                rows = [{
                    "Title": j["title"], "Company": j["company"],
                    "Match": j.get("match_percentage", 0), "Source": j.get("source", ""),
                    "URL": j.get("apply_url") or j.get("url", ""),
                } for j in digest["digest"]]
                st.dataframe(
                    pd.DataFrame(rows),
                    width="stretch", hide_index=True,
                    column_config={
                        "Match": st.column_config.ProgressColumn("Match", min_value=0, max_value=100, format="%d%%"),
                        "URL": st.column_config.LinkColumn("URL", display_text="Open"),
                    },
                )

    st.markdown('<p class="cc-section">Agent roster</p>', unsafe_allow_html=True)
    agent_rows = [
        ("Job scout", "Searches Remotive · Jobicy · RemoteOK · board APIs (Greenhouse/Lever enrichment)"),
        ("Resume optimizer", "Tailors resumes under strict truth rules; grounded fallback offline"),
        ("Resume evaluator", "Quality gate: sanitize → 5-axis ATS score → anti-hallucination guardrail → critique loop"),
        ("Application manager", "Records applications; immutable resume version history"),
        ("Project recommender", "Company-aligned portfolio project ideas"),
        ("Prep coach", "7-day interview plan + anticipated Q&A"),
        ("Profile optimizer", "LinkedIn / GitHub / portfolio tuning + company intel (7-day cache)"),
        ("Daily monitor", "Telegram · WhatsApp · Email digests (deliver-or-retry semantics)"),
        ("Browser applicant", "Playwright form autofill — you always click Submit"),
    ]
    df_agents = pd.DataFrame(agent_rows, columns=["Agent", "Responsibility"])
    st.dataframe(df_agents, width="stretch", hide_index=True)

# =============================================================================
# TAB: JOB SCOUT
# =============================================================================
with tab_scout:
    st.markdown('<p class="cc-section">Live job scouting</p>', unsafe_allow_html=True)
    st.caption("Queries 4 providers, board results enriched via official Greenhouse/Lever APIs.")

    s1, s2, s3 = st.columns([3, 1, 1])
    with s1:
        search_query = st.text_input("Role / keywords", value="Python Developer", key="scout_query")
    with s2:
        num_results = st.number_input("Max results (total)", min_value=1, max_value=25, value=5, key="scout_max")
    with s3:
        st.write("")
        st.write("")
        scout_go = st.button("🔎 Scout", type="primary", width="stretch")

    if scout_go:
        with st.spinner(f"Scouting '{search_query}'…"):
            jobs = search_job_postings(search_query, max_results=int(num_results))
        if not jobs:
            st.warning("No jobs found — try a broader query (e.g. 'Python' instead of 'Python Developer Fresher Chennai').")
        else:
            st.markdown(f"**{len(jobs)} roles found.** Scores use the base resume in `career_copilot/resume/`.")
            for idx, job in enumerate(jobs):
                title = job.get("title", "")
                company = job.get("company", "Unknown")
                desc = job.get("description", "")
                score = compute_match_percentage(title, desc)
                url = job.get("url", "")
                with st.container(border=True):
                    top1, top2 = st.columns([5, 1])
                    with top1:
                        st.markdown(
                            f'<span class="cc-job-title">{title}</span> · {company} '
                            f'{_pill(job.get("location", "Remote"), "slate")} '
                            f'{_pill(job.get("source", "web"), "indigo")}',
                            unsafe_allow_html=True,
                        )
                    with top2:
                        st.markdown(_match_pill(score), unsafe_allow_html=True)
                    if desc:
                        st.caption(desc[:420] + ("…" if len(desc) > 420 else ""))
                    a1, a2 = st.columns([1, 5])
                    with a1:
                        st.link_button("Apply ↗", url or "#", width="stretch")
                    with a2:
                        if st.button("💾 Save to tracker", key=f"save_{idx}", width="content"):
                            saved = database.add_job(title, company, job.get("location", "Remote"), url, desc)
                            if saved:
                                st.toast(f"Saved: {title} at {company}", icon="💾")
                            else:
                                st.toast("Already in your tracker.", icon="ℹ️")

# =============================================================================
# TAB: ATS EVALUATOR
# =============================================================================
with tab_eval:
    st.markdown('<p class="cc-section">ATS quality gate</p>', unsafe_allow_html=True)
    st.caption("Same 5-axis rubric the pipeline applies before any resume is sent.")

    up_col, hint_col = st.columns([2, 3])
    with up_col:
        uploaded_file = st.file_uploader("Upload resume (PDF)", type=["pdf"])
    resume_text_input = ""
    if uploaded_file is not None:
        reader = PdfReader(uploaded_file)
        resume_text_input = "\n".join(
            page.extract_text() or "" for page in reader.pages
        ).strip()
        if resume_text_input:
            st.success(f"Extracted {len(resume_text_input):,} characters.", icon="📄")
        else:
            st.error("Could not extract text from this PDF.")

    resume_text = st.text_area("Resume text", value=resume_text_input, height=220,
                               placeholder="Paste your resume here…")

    if st.button("🔬 Evaluate", type="primary"):
        if not resume_text.strip():
            st.error("Upload a PDF or paste resume text first.")
        else:
            profile = get_candidate_profile()
            result = evaluate_resume_quality(resume_text, profile.get("name", "") or None)
            score = int(result.get("score", 0))

            sc_col, meta_col = st.columns([1, 2])
            with sc_col:
                st.metric("ATS score", f"{score} / 100")
                st.progress(score / 100)
                if result.get("passed"):
                    st.markdown(_pill("PASS ≥ 70", "green"), unsafe_allow_html=True)
                else:
                    st.markdown(_pill("BELOW GATE (< 70)", "red"), unsafe_allow_html=True)
            with meta_col:
                breakdown = result.get("breakdown", {})
                if breakdown:
                    st.markdown("**Score breakdown**")
                    bd = pd.DataFrame(
                        [(k.replace("_", " ").title(), v) for k, v in breakdown.items()],
                        columns=["Axis", "Points"],
                    )
                    st.dataframe(bd, width="stretch", hide_index=True)

            issues = result.get("issues", [])
            if issues:
                with st.container(border=True):
                    st.markdown("**⚠️ Issues detected**")
                    for issue in issues:
                        st.markdown(f"- {issue}")
            else:
                st.success("Clean resume — no structural, contact, or metadata issues.", icon="✅")

            with st.expander("View sanitized text (what the ATS sees)"):
                st.text(sanitize_resume_text(resume_text))

# =============================================================================
# TAB: RESUME TAILOR
# =============================================================================
with tab_tailor:
    st.markdown('<p class="cc-section">Truthful resume tailor</p>', unsafe_allow_html=True)
    st.markdown(
        f"Rewrites your base resume for a specific role — anti-hallucination guardrail active. {_mode_badge()}",
        unsafe_allow_html=True,
    )

    base_ok = bool(_extract_resume_text())
    if not base_ok:
        st.warning("No base resume found at `career_copilot/resume/*.pdf` — tailoring will rely on profile fields only.", icon="⚠️")

    t1, t2 = st.columns(2)
    with t1:
        t_title = st.text_input("Job title", value="Junior Python Engineer", key="t_title")
    with t2:
        t_company = st.text_input("Company", value="Tech Corp", key="t_company")
    t_jd = st.text_area("Job description", height=170, placeholder="Paste the job description…", key="t_jd")

    if st.button("✨ Tailor resume", type="primary"):
        if not t_jd.strip():
            st.error("Paste a job description first.")
        else:
            with st.spinner("Generating → critiquing → revising…"):
                audited = generate_tailored_resume_with_audit(t_title, t_company, t_jd)
                tailored = audited["resume_text"]
                evaluation = audited.get("evaluation", {})

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("ATS score", evaluation.get("score", 0))
            r2.metric("Gate", "PASS" if evaluation.get("passed") else "BELOW")
            r3.metric("Revise attempts", audited.get("optimization_attempts", 0))
            r4.metric("Generator", audited.get("generator", "?").replace("_", " "))

            hallucinated = audited.get("hallucinated_skills", [])
            if hallucinated:
                st.warning(f"Guardrail removed unverified skills: {', '.join(hallucinated)}", icon="🛡️")
            else:
                st.success("Guardrail: no unverified skills — every claim is evidence-backed.", icon="🛡️")

            with st.container(border=True):
                st.markdown("**Tailored resume**")
                st.text(tailored)

            with st.spinner("Rendering PDF…"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    pdf_path = tmp.name
                export_resume_pdf_from_markdown(t_title, t_company, tailored, pdf_path)
                with open(pdf_path, "rb") as fh:
                    pdf_bytes = fh.read()
            st.download_button(
                "📥 Download ATS PDF",
                data=pdf_bytes,
                file_name=f"{t_company.replace(' ', '_')}_{t_title.replace(' ', '_')}_Resume.pdf",
                mime="application/pdf",
                type="primary",
            )

# =============================================================================
# TAB: INTERVIEW PREP
# =============================================================================
with tab_prep:
    st.markdown('<p class="cc-section">Interview prep & profile optimization</p>', unsafe_allow_html=True)

    mode = st.segmented_control("Tool", ["7-day prep plan", "Profile optimizer"], default="7-day prep plan") \
        if hasattr(st, "segmented_control") else st.radio("Tool", ["7-day prep plan", "Profile optimizer"], horizontal=True)

    p1, p2 = st.columns(2)
    with p1:
        p_title = st.text_input("Job title", value="Backend Engineer", key="p_title")
    with p2:
        p_company = st.text_input("Company", value="Innovative AI Studio", key="p_company")
    p_jd = st.text_area("Job description / core skills", height=160, key="p_jd",
                        placeholder="Paste the job description…")

    if mode == "7-day prep plan":
        if st.button("🗓️ Build 7-day plan", type="primary"):
            if not p_jd.strip():
                st.error("Paste a job description first.")
            else:
                with st.spinner("Building day-by-day plan + practice Q&A…"):
                    plan = create_preparation_plan(p_title, p_jd)
                with st.container(border=True):
                    st.markdown(plan)
    else:
        if st.button("🌟 Optimize profiles", type="primary"):
            with st.spinner("Analyzing target role & your public profiles…"):
                report = generate_profile_updates(p_title, p_company, p_jd)
            with st.container(border=True):
                st.markdown(report)

# =============================================================================
# TAB: TRACKER
# =============================================================================
with tab_tracker:
    st.markdown('<p class="cc-section">Application tracker</p>', unsafe_allow_html=True)
    st.caption("Job lifecycle (found → notified → applied → interviewing → archived) and application lifecycle "
               "(drafted → ready_to_submit → submitted → interviewing → offer | rejected) are tracked separately and honestly.")

    all_jobs = database.get_all_jobs()
    if not all_jobs:
        st.info("No jobs yet — scout roles in the Job Scout tab or run the pipeline from Overview.", icon="📭")
    else:
        jobs_df = pd.DataFrame(
            all_jobs,
            columns=["ID", "Title", "Company", "Location", "URL", "Description", "Status", "Created"],
        )
        st.dataframe(
            jobs_df[["ID", "Title", "Company", "Location", "Status", "Created", "URL"]],
            width="stretch", hide_index=True,
            column_config={"URL": st.column_config.LinkColumn("URL", display_text="Open")},
        )

        st.markdown("#### Manage a job")
        sel_col, _ = st.columns([1, 2])
        with sel_col:
            selected_job_id = st.selectbox("Job ID", list(jobs_df["ID"]))
        row = jobs_df[jobs_df["ID"] == selected_job_id].iloc[0]

        st.markdown(
            f'<div class="cc-card cc-kv"><span class="cc-job-title">{row["Title"]}</span> · {row["Company"]}<br/>'
            f'<span class="cc-muted">{row["Location"]} · saved {row["Created"]}</span></div>',
            unsafe_allow_html=True,
        )

        a_col, b_col = st.columns(2)
        with a_col:
            st.markdown("**Job lifecycle**")
            current_status = row["Status"]
            new_status = st.selectbox(
                "Set job status", list(database.ALLOWED_JOB_STATUSES),
                index=list(database.ALLOWED_JOB_STATUSES).index(current_status)
                if current_status in database.ALLOWED_JOB_STATUSES else 0,
                key="job_status_sel",
            )
            if st.button("Update job status", key="upd_job"):
                if database.update_job_status(selected_job_id, new_status):
                    st.success(f"Job #{selected_job_id} → '{new_status}'")
                    st.rerun()

        with b_col:
            st.markdown("**Application lifecycle**")
            app_row = database.get_application(selected_job_id)
            if app_row:
                st.markdown(
                    f"Current: {_pill(app_row['status'], 'indigo')} · since {app_row['created_at']}",
                    unsafe_allow_html=True,
                )
                new_app_status = st.selectbox(
                    "Set application status", list(database.ALLOWED_APPLICATION_STATUSES),
                    index=list(database.ALLOWED_APPLICATION_STATUSES).index(app_row["status"])
                    if app_row["status"] in database.ALLOWED_APPLICATION_STATUSES else 0,
                    key="app_status_sel",
                )
                if st.button("Update application status", key="upd_app"):
                    if database.update_application_status(selected_job_id, new_app_status):
                        st.success(f"Application → '{new_app_status}'")
                        st.rerun()
            else:
                st.caption("No application recorded for this job yet — generate a packet below or apply via CLI.")

        st.divider()
        packet_col, versions_col = st.columns(2)
        with packet_col:
            st.markdown("**On-demand application packet**")
            if st.button("⚙️ Generate packet (resume + prep + profile)", key="gen_packet"):
                with st.spinner("Assembling packet…"):
                    packet = generate_application_packet_for_job(
                        row["Title"], row["Company"], row["Description"], row["URL"]
                    )
                audit = packet.get("audit", {})
                score = (audit.get("evaluation") or {}).get("score")
                st.markdown(
                    f"Match: {_match_pill(score)} "
                    f"{_pill('generator: ' + audit.get('generator', '?').replace('_', ' '), 'slate')}",
                    unsafe_allow_html=True,
                )
                hallucinated = audit.get("hallucinated_skills", [])
                if hallucinated:
                    st.warning(f"Guardrail removed unverified skills: {', '.join(hallucinated)}", icon="🛡️")
                with st.expander("Tailored resume", expanded=True):
                    st.text(packet.get("resume_text", ""))
                with st.expander("Interview prep"):
                    st.markdown(packet.get("prep", ""))
                with st.expander("Profile updates"):
                    st.markdown(packet.get("profile", ""))
                with st.expander("Recommended projects"):
                    st.markdown(packet.get("projects", ""))

        with versions_col:
            st.markdown("**Resume version history**")
            versions = database.get_resume_versions(selected_job_id)
            if not versions:
                st.caption("No versions recorded yet — versions are saved automatically when you record an application.")
            else:
                for v in versions:
                    score = f"ATS {v['ats_score']}" if v["ats_score"] is not None else "ATS n/a"
                    st.markdown(
                        f"{_pill('v' + str(v['version']), 'slate')} {score} · {v['generator']} · "
                        f"{v['text_length']:,} chars · {v['created_at']}",
                        unsafe_allow_html=True,
                    )

# =============================================================================
# TAB: COPILOT CHAT
# =============================================================================
with tab_chat:
    st.markdown('<p class="cc-section">Copilot chat</p>', unsafe_allow_html=True)

    if not _api_key():
        st.info(
            "Chat needs a Gemini API key (sidebar → API configuration). "
            "Unlike a mock reply bot, this assistant only speaks when a real model is connected — "
            "everything else in this dashboard works offline.",
            icon="🔑",
        )
    else:
        if "chat_messages" not in st.session_state:
            st.session_state.chat_messages = []

        for msg in st.session_state.chat_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("Ask about jobs, resumes, interview prep…"):
            st.session_state.chat_messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    from career_copilot.config import call_gemini

                    profile = get_candidate_profile()
                    stats = f"{database.get_job_count()} jobs scouted, {database.get_application_count()} applications tracked"
                    system_context = (
                        "You are Career Copilot, a concise career assistant. "
                        f"Candidate: {profile.get('name', 'the user')}. Current pipeline: {stats}. "
                        "Answer with practical, specific advice. Never invent facts about the candidate."
                    )
                    try:
                        reply = call_gemini(f"{system_context}\n\nUser: {prompt}", temperature=0.7)
                    except Exception as exc:
                        reply = f"⚠️ Model call failed: {exc}"
                st.markdown(reply)
            st.session_state.chat_messages.append({"role": "assistant", "content": reply})
