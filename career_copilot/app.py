import os
import sys
import tempfile
import streamlit as st
import pandas as pd
from pypdf import PdfReader

# Ensure current package path is available
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from career_copilot.config import load_env
load_env()

from career_copilot import database, notifier
from career_copilot.tools import (
    search_job_postings,
    compute_match_percentage,
    generate_tailored_resume,
    export_resume_pdf,
    create_preparation_plan,
    generate_profile_updates,
    build_daily_digest,
)
from career_copilot.resume_evaluator import (
    evaluate_resume_quality,
    sanitize_resume_text,
    validate_pdf_output,
)

# --- Page Configuration & Custom CSS ---
st.set_page_config(
    page_title="Career Copilot AI | Multi-Agent System",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header {
        font-size: 2.3rem;
        font-weight: 800;
        background: linear-gradient(90deg, #6366f1 0%, #a855f7 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        color: #94a3b8;
        font-size: 1.05rem;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 18px;
        text-align: center;
    }
    .agent-badge {
        background: #312e81;
        color: #e0e7ff;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .stButton>button {
        background: linear-gradient(90deg, #6366f1 0%, #4f46e5 100%);
        color: white;
        font-weight: 600;
        border: none;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)

# --- Sidebar Configuration ---
with st.sidebar:
    st.image("https://img.icons8.com/color/96/bot.png", width=70)
    st.title("Career Copilot AI")
    st.caption("Autonomous Multi-Agent Career Suite")
    
    st.divider()
    
    # API Key Configuration
    st.subheader("⚙️ API Configuration")
    user_api_key = st.text_input(
        "Google Gemini API Key",
        value=os.environ.get("GEMINI_API_KEY", ""),
        type="password",
        help="Provide a Gemini API Key to enable AI features live."
    )
    if user_api_key:
        os.environ["GEMINI_API_KEY"] = user_api_key
        st.success("API Key Active", icon="✅")
    else:
        st.warning("Enter Gemini API Key to run live AI generation.")
        
    st.divider()
    
    # System Status & Telemetry
    st.subheader("📊 System Telemetry")
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM jobs")
    job_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM applications")
    app_count = c.fetchone()[0]
    conn.close()
    
    st.metric("Scouted Jobs", job_count)
    st.metric("Applications Tracked", app_count)
    st.metric("Active Agents", "9 / 9")
    
    st.divider()
    st.markdown("Developed with **Google ADK** & **Gemini**")

# --- Main App Header ---
st.markdown('<div class="main-header">Career Copilot AI Agent Suite</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">An autonomous 9-Agent system for automated job scouting, ATS resume evaluation, resume tailoring, and interview prep.</div>', unsafe_allow_html=True)

# --- Navigation Tabs ---
tab_arch, tab_scout, tab_eval, tab_tailor, tab_prep = st.tabs([
    "🏛️ System Architecture",
    "🔍 Job Scout & Matcher",
    "📊 ATS Resume Evaluator",
    "📝 Resume Tailor & PDF",
    "🎯 Interview & Profile Copilot",
])

# ==============================================================================
# TAB 1: ARCHITECTURE & INTERVIEW SHOWCASE
# ==============================================================================
with tab_arch:
    st.subheader("System Architecture & Multi-Agent Workflow")
    st.markdown("""
    Career Copilot is designed on a modular **Google ADK (Agent Development Kit)** multi-agent model. 
    Each agent acts as a specialized micro-service with strictly scoped tools, database state transitions, and evaluation gates.
    """)
    
    # Architecture Visual Diagram
    st.info("💡 **Architectural Highlight for Technical Interviews**: Features a quality-gate pattern where the `Resume_evaluator_agent` intercepts generated resumes to auto-fix formatting errors before output validation.")
    
    st.markdown("### 🤖 Specialized Agent Matrix")
    agent_data = [
        {"ID": 1, "Agent": "Job_scout_agent", "Role": "Scouts jobs across Remotive, Jobicy, RemoteOK & DDG", "Primary Tools": "`search_job_postings`, `compute_match_percentage`"},
        {"ID": 2, "Agent": "Resume_optimizer_agent", "Role": "Tailors resumes to job descriptions with ATS formatting", "Primary Tools": "`generate_tailored_resume`, `export_resume_pdf`"},
        {"ID": 3, "Agent": "Resume_evaluator_agent", "Role": "Quality Gate: Evaluates, sanitizes, & auto-fixes resumes", "Primary Tools": "`evaluate_resume_quality`, `sanitize_resume_text`"},
        {"ID": 4, "Agent": "Application_agent", "Role": "Records application drafts and tracks submission status", "Primary Tools": "`record_application`"},
        {"ID": 5, "Agent": "Project_recommender_agent", "Role": "Suggests portfolio projects aligned with target roles", "Primary Tools": "`recommend_projects`"},
        {"ID": 6, "Agent": "Preparation_agent", "Role": "Builds 7-day interview preparation plans & Q&A guides", "Primary Tools": "`create_preparation_plan`"},
        {"ID": 7, "Agent": "Profile_optimizer_agent", "Role": "Optimizes LinkedIn, GitHub, & Portfolio profiles", "Primary Tools": "`generate_profile_updates`"},
        {"ID": 8, "Agent": "Daily_monitor_agent", "Role": "Sends automated alerts via Telegram, WhatsApp, & Email", "Primary Tools": "`notify_user_of_matches`"},
        {"ID": 9, "Agent": "Browser_application_agent", "Role": "Automates real browser form-filling via Playwright", "Primary Tools": "`run_application_flow`"},
    ]
    st.table(pd.DataFrame(agent_data))
    
    st.subheader("⚡ Live Pipeline Execution Test")
    if st.button("🚀 Run Live Pipeline (Search → Score → Digest)"):
        with st.spinner("Running multi-agent execution pipeline..."):
            digest = build_daily_digest(query="Python Developer")
            scouted_count = len(digest.get("jobs", []))
            st.success(f"Pipeline executed successfully! Scouted {scouted_count} jobs. Generated {len(digest['digest'])} tailored packets.")
            st.json(digest["digest"][:2] if digest["digest"] else digest)

# ==============================================================================
# TAB 2: JOB SCOUT & MATCHER
# ==============================================================================
with tab_scout:
    st.subheader("🔍 Automated Job Scouting & Skills Matcher")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        search_query = st.text_input("Target Job Role / Keywords", value="Python Developer")
    with col2:
        num_results = st.slider("Max Results per Source", min_value=1, max_value=10, value=3)
        
    user_skills_input = st.text_area("Your Core Skills (for match scoring)", value="Python, FastAPI, SQL, Docker, Machine Learning, Git, REST APIs")
    
    if st.button("🔎 Scout Live Jobs"):
        with st.spinner(f"Scouting jobs for '{search_query}'..."):
            jobs = search_job_postings(search_query, max_results=num_results)
            
            if jobs:
                st.success(f"Found {len(jobs)} live job postings!")
                user_skills = [s.strip() for s in user_skills_input.split(",") if s.strip()]
                
                for idx, job in enumerate(jobs):
                    match_score = compute_match_percentage(job.get("description", "") + " " + job.get("title", ""), user_skills)
                    
                    with st.expander(f"📌 {job['title']} — {job['company']} (Match Score: {match_score}%)", expanded=(idx == 0)):
                        st.write(f"**Location:** {job.get('location', 'Remote')}")
                        st.write(f"**Source:** {job.get('source', 'Web')}")
                        st.markdown(f"**Apply Link:** [{job.get('url')}]({job.get('url')})")
                        st.write("**Description Preview:**")
                        st.caption(job.get("description", "No description provided.")[:500] + "...")
                        
                        if st.button(f"Save to Application Tracker #{idx}", key=f"save_{idx}"):
                            database.store_job(job['title'], job['company'], job.get('location', 'Remote'), job['url'], job.get('description', ''))
                            st.success("Saved to database successfully!")
            else:
                st.warning("No jobs found for the specified query.")

# ==============================================================================
# TAB 3: ATS RESUME EVALUATOR
# ==============================================================================
with tab_eval:
    st.subheader("📊 ATS Resume Evaluator & Quality Gate")
    st.markdown("Upload your existing resume (PDF) or paste the text to get a comprehensive ATS score, missing keywords, and sanitization report.")
    
    uploaded_file = st.file_uploader("Upload Resume (PDF)", type=["pdf"])
    resume_text_input = ""
    
    if uploaded_file is not None:
        reader = PdfReader(uploaded_file)
        resume_text_input = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
        st.success(f"Extracted {len(resume_text_input)} characters from PDF.")
        
    resume_text = st.text_area("Resume Content (Editable)", value=resume_text_input, height=180, placeholder="Paste your resume text here...")
    jd_eval_input = st.text_area("Target Job Description", height=140, placeholder="Paste the job description here...")
    
    if st.button("🔬 Run ATS Quality Gate Evaluation"):
        if not resume_text.strip():
            st.error("Please upload or paste a resume first.")
        else:
            with st.spinner("Evaluating ATS compatibility & sanitizing text..."):
                # Run Quality Gate
                eval_result = evaluate_resume_quality(resume_text, jd_eval_input)
                sanitized_text = sanitize_resume_text(resume_text)
                
                score = eval_result.get("score", 0)
                
                st.subheader(f"ATS Score: {score} / 100")
                st.progress(score / 100)
                
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("### ❌ Identified Flaws & Gaps")
                    for flaw in eval_result.get("flaws", []):
                        st.write(f"- {flaw}")
                with c2:
                    st.markdown("### 💡 Actionable Suggestions")
                    for sug in eval_result.get("suggestions", []):
                        st.write(f"- {sug}")
                        
                with st.expander("✨ View Sanitized Resume Text"):
                    st.text(sanitized_text)

# ==============================================================================
# TAB 4: RESUME TAILOR & PDF EXPORTER
# ==============================================================================
with tab_tailor:
    st.subheader("📝 AI Resume Tailor & ATS PDF Generator")
    st.markdown("Automatically re-write your resume tailored specifically to the target company & job description, then download a clean ATS PDF.")
    
    t_company = st.text_input("Target Company Name", value="Tech Corp Inc.")
    t_resume_base = st.text_area("Base Resume Text", height=150, placeholder="Paste your master resume text...")
    t_jd = st.text_area("Target Job Description", height=150, placeholder="Paste job description...")
    
    if st.button("✨ Generate Tailored Resume & ATS PDF"):
        if not t_resume_base.strip() or not t_jd.strip():
            st.error("Please provide both base resume text and job description.")
        else:
            with st.spinner("Tailoring resume with Gemini AI..."):
                tailored_markdown = generate_tailored_resume(t_resume_base, t_jd, t_company)
                
                st.markdown("### 📄 Tailored Resume Preview")
                st.markdown(tailored_markdown)
                
                with st.spinner("Generating ATS-Friendly PDF..."):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                        pdf_path = tmp_file.name
                        
                    export_resume_pdf(tailored_markdown, pdf_path)
                    
                    with open(pdf_path, "rb") as f:
                        pdf_bytes = f.read()
                        
                    st.download_button(
                        label="📥 Download Tailored ATS PDF",
                        data=pdf_bytes,
                        file_name=f"{t_company.replace(' ', '_')}_Tailored_Resume.pdf",
                        mime="application/pdf"
                    )

# ==============================================================================
# TAB 5: INTERVIEW & PROFILE COPILOT
# ==============================================================================
with tab_prep:
    st.subheader("🎯 Interview Prep & Profile Optimizer")
    
    prep_mode = st.radio("Select Tool Mode", ["7-Day Interview Prep Guide", "Profile Optimizer (LinkedIn/GitHub)"])
    
    if prep_mode == "7-Day Interview Prep Guide":
        st.markdown("Generate a structured 7-day interview study plan and anticipated technical Q&A based on the job description.")
        p_title = st.text_input("Target Job Title", value="Senior Backend Engineer")
        p_company = st.text_input("Company Name", value="Innovative AI Studio")
        p_jd = st.text_area("Job Description", height=150)
        
        if st.button("🚀 Build Interview Prep Plan"):
            if not p_jd.strip():
                st.error("Please provide job description.")
            else:
                with st.spinner("Generating preparation plan..."):
                    plan_result = create_preparation_plan(p_jd, p_title, p_company)
                    st.markdown("### 📋 Customized Preparation Guide")
                    st.markdown(plan_result.get("plan", "No plan generated."))
                    
    else:
        st.markdown("Optimize your LinkedIn, GitHub, and portfolio summaries for target roles.")
        prof_role = st.text_input("Target Role", value="AI / ML Engineer")
        prof_summary = st.text_area("Current Bio / Profile Summary", height=120)
        
        if st.button("✨ Optimize Profile"):
            with st.spinner("Optimizing profile content..."):
                updates = generate_profile_updates(prof_summary, prof_role)
                st.markdown("### 🌟 Optimized Profile Recommendations")
                st.markdown(updates.get("headline", ""))
                st.markdown(updates.get("summary", ""))
