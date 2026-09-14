import os
import sys
import tempfile
import streamlit as st
import pandas as pd
from pypdf import PdfReader

# Ensure current package path is available
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from career_copilot.config import load_env, get_gemini_model
load_env()

from career_copilot import database, notifier
from career_copilot.tools import (
    search_job_postings,
    compute_match_percentage,
    generate_tailored_resume,
    export_resume_pdf,
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
    
    # API Key Configuration (Checks GOOGLE_API_KEY and GEMINI_API_KEY)
    st.subheader("⚙️ API Configuration")
    configured_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    user_api_key = st.text_input(
        "Google Gemini API Key",
        value=configured_key,
        type="password",
        help="Provide a Google API Key to enable AI features live."
    )
    if user_api_key:
        os.environ["GOOGLE_API_KEY"] = user_api_key
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
tab_arch, tab_scout, tab_eval, tab_tailor, tab_prep, tab_tracker, tab_chat = st.tabs([
    "🏛️ System Architecture",
    "🔍 Job Scout & Matcher",
    "📊 ATS Resume Evaluator",
    "📝 Resume Tailor & PDF",
    "🎯 Interview & Profile Copilot",
    "📋 Application Tracker",
    "💬 Interactive AI Copilot",
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
    
    st.info("💡 **Architectural Highlight for Technical Interviews**: Features a quality-gate pattern where the `Resume_evaluator_agent` intercepts generated resumes to auto-fix formatting errors and prevent hallucinations before output validation.")
    
    st.markdown("### 🤖 Specialized Agent Matrix")
    agent_data = [
        {"ID": 1, "Agent": "Job_scout_agent", "Role": "Scouts jobs across Remotive, Jobicy, RemoteOK & DDG with seniority query expansion", "Primary Tools": "`search_job_postings`, `database.add_job`"},
        {"ID": 2, "Agent": "Resume_optimizer_agent", "Role": "Tailors resumes with strict anti-hallucination guardrails and ATS formatting", "Primary Tools": "`generate_tailored_resume`, `export_resume_pdf_from_markdown`"},
        {"ID": 3, "Agent": "Resume_evaluator_agent", "Role": "Quality Gate: Evaluates, sanitizes, & auto-fixes resumes", "Primary Tools": "`evaluate_resume_quality`, `sanitize_resume_text`"},
        {"ID": 4, "Agent": "Application_agent", "Role": "Records application drafts and tracks submission status", "Primary Tools": "`record_application`"},
        {"ID": 5, "Agent": "Project_recommender_agent", "Role": "Suggests portfolio projects aligned with target roles", "Primary Tools": "`recommend_projects`"},
        {"ID": 6, "Agent": "Preparation_agent", "Role": "Builds 7-day interview preparation plans & Q&A guides", "Primary Tools": "`create_preparation_plan`"},
        {"ID": 7, "Agent": "Profile_optimizer_agent", "Role": "Optimizes LinkedIn, GitHub, & Portfolio profiles", "Primary Tools": "`generate_profile_updates`"},
        {"ID": 8, "Agent": "Daily_monitor_agent", "Role": "Sends automated alerts via Telegram, WhatsApp, & Email", "Primary Tools": "`notify_user_of_matches`"},
        {"ID": 9, "Agent": "Browser_application_agent", "Role": "Automates real browser form-filling via Playwright with human verification", "Primary Tools": "`run_application_flow`"},
    ]
    st.table(pd.DataFrame(agent_data))
    
    st.subheader("⚡ Live Pipeline Execution Test (On-Demand Scouting Mode)")
    if st.button("🚀 Run Live Pipeline (Search → Score → Digest)"):
        with st.spinner("Running multi-agent execution pipeline..."):
            digest = build_daily_digest(query="Python Developer", generate_full_packets=False)
            scouted_count = len(digest.get("jobs", []))
            st.success(f"Pipeline executed successfully! Scouted {scouted_count} jobs. Filtered: {digest.get('filtered_out_count', 0)}. Generated {len(digest.get('digest', []))} matched records in database.")
            st.json(digest.get("digest", [])[:2] if digest.get("digest") else digest)

# ==============================================================================
# TAB 2: JOB SCOUT & MATCHER
# ==============================================================================
with tab_scout:
    st.subheader("🔍 Automated Job Scouting & Seniority-Aware Matcher")
    st.markdown("Search across multiple job boards. The query engine automatically incorporates your seniority preferences (`fresher`/`junior`) to ensure relevant roles.")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        search_query = st.text_input("Target Job Role / Keywords", value="Python Developer")
    with col2:
        num_results = st.slider("Max Results per Source", min_value=1, max_value=10, value=3)
        
    user_skills_input = st.text_area("Your Core Skills (for reference)", value="Python, FastAPI, SQL, Docker, Machine Learning, Git, REST APIs")
    
    if st.button("🔎 Scout Live Jobs"):
        with st.spinner(f"Scouting jobs for '{search_query}'..."):
            jobs = search_job_postings(search_query, max_results=num_results)
            
            if jobs:
                st.success(f"Found {len(jobs)} live job postings!")
                
                for idx, job in enumerate(jobs):
                    job_title = job.get("title", "")
                    job_desc = job.get("description", "")
                    match_score = compute_match_percentage(job_title, job_desc)
                    
                    with st.expander(f"📌 {job_title} — {job.get('company', 'Unknown')} (Match Score: {match_score}%)", expanded=(idx == 0)):
                        st.write(f"**Location:** {job.get('location', 'Remote')}")
                        st.write(f"**Source:** {job.get('source', 'Web')}")
                        st.markdown(f"**Apply Link:** [{job.get('url')}]({job.get('url')})")
                        st.write("**Description Preview:**")
                        st.caption(job_desc[:500] + "..." if job_desc else "No description provided.")
                        
                        if st.button(f"Save to Application Tracker #{idx}", key=f"save_{idx}"):
                            saved = database.add_job(
                                job_title,
                                job.get('company', 'Unknown'),
                                job.get('location', 'Remote'),
                                job.get('url', ''),
                                job_desc
                            )
                            if saved:
                                st.success("Saved to database successfully!")
                            else:
                                st.info("This job is already saved in your database.")
            else:
                st.warning("No jobs found for the specified query.")

# ==============================================================================
# TAB 3: ATS RESUME EVALUATOR
# ==============================================================================
with tab_eval:
    st.subheader("📊 ATS Resume Evaluator & Anti-Hallucination Quality Gate")
    st.markdown("Upload your existing resume (PDF) or paste the text to get a comprehensive ATS score, missing sections, and formatting analysis.")
    
    uploaded_file = st.file_uploader("Upload Resume (PDF)", type=["pdf"])
    resume_text_input = ""
    
    if uploaded_file is not None:
        reader = PdfReader(uploaded_file)
        resume_text_input = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
        st.success(f"Extracted {len(resume_text_input)} characters from PDF.")
        
    resume_text = st.text_area("Resume Content (Editable)", value=resume_text_input, height=180, placeholder="Paste your resume text here...")
    
    if st.button("🔬 Run ATS Quality Gate Evaluation"):
        if not resume_text.strip():
            st.error("Please upload or paste a resume first.")
        else:
            with st.spinner("Evaluating ATS compatibility & sanitizing text..."):
                candidate_name = os.environ.get("RESUME_NAME", "")
                eval_result = evaluate_resume_quality(resume_text, candidate_name)
                sanitized_text = sanitize_resume_text(resume_text)
                
                score = eval_result.get("score", 0)
                
                st.subheader(f"ATS Score: {score} / 100")
                st.progress(score / 100)
                
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("### ⚠️ Quality Gate Issues Detected")
                    issues = eval_result.get("issues", [])
                    if issues:
                        for issue in issues:
                            st.write(f"- ❌ {issue}")
                    else:
                        st.success("✅ Clean structure! No major formatting, metadata, or contact info gaps found.")
                with c2:
                    st.markdown("### 📊 Score Breakdown")
                    breakdown = eval_result.get("breakdown", {})
                    for cat, pts in breakdown.items():
                        st.write(f"- **{cat.replace('_', ' ').title()}:** {pts} pts")
                        
                with st.expander("✨ View Sanitized Resume Text"):
                    st.text(sanitized_text)

# ==============================================================================
# TAB 4: RESUME TAILOR & PDF EXPORTER
# ==============================================================================
with tab_tailor:
    st.subheader("📝 AI Resume Tailor & ATS PDF Generator (With Truth Guardrails)")
    st.markdown("Automatically rewrite your resume tailored specifically to the target company & job description with strict anti-hallucination rules, then download a clean ATS PDF.")
    
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        t_title = st.text_input("Target Job Title", value="Junior Python Engineer")
    with col_t2:
        t_company = st.text_input("Target Company Name", value="Tech Corp Inc.")
    t_jd = st.text_area("Target Job Description", height=150, placeholder="Paste job description...")
    
    if st.button("✨ Generate Tailored Resume & ATS PDF"):
        if not t_jd.strip():
            st.error("Please provide a job description.")
        else:
            with st.spinner("Tailoring resume with Gemini AI (Anti-Hallucination active)..."):
                tailored_markdown = generate_tailored_resume(t_title, t_company, t_jd)
                
                st.markdown("### 📄 Tailored Resume Preview")
                st.markdown(tailored_markdown)
                
                with st.spinner("Generating ATS-Friendly PDF..."):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                        pdf_path = tmp_file.name
                        
                    export_resume_pdf_from_markdown(t_title, t_company, tailored_markdown, pdf_path)
                    
                    with open(pdf_path, "rb") as f:
                        pdf_bytes = f.read()
                        
                    st.download_button(
                        label="📥 Download Tailored ATS PDF",
                        data=pdf_bytes,
                        file_name=f"{t_company.replace(' ', '_')}_{t_title.replace(' ', '_')}_Resume.pdf",
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
        p_title = st.text_input("Target Job Title", value="Junior Backend Engineer")
        p_company = st.text_input("Company Name", value="Innovative AI Studio")
        p_jd = st.text_area("Job Description", height=150)
        
        if st.button("🚀 Build Interview Prep Plan"):
            if not p_jd.strip():
                st.error("Please provide job description.")
            else:
                with st.spinner("Generating preparation plan..."):
                    plan_text = create_preparation_plan(p_title, p_jd)
                    st.markdown("### 📋 Customized Preparation Guide")
                    st.markdown(plan_text)
                    
    else:
        st.markdown("Optimize your LinkedIn, GitHub, and portfolio summaries for target roles.")
        prof_title = st.text_input("Target Job Title", value="AI / ML Engineer")
        prof_company = st.text_input("Target Company Name", value="Google")
        prof_jd = st.text_area("Target Job Description (or core skills)", height=120, value="Python, Machine Learning, Docker, Agentic AI, SQL")
        
        if st.button("✨ Optimize Profile"):
            with st.spinner("Optimizing profile recommendations..."):
                report = generate_profile_updates(prof_title, prof_company, prof_jd)
                st.markdown("### 🌟 Optimized Profile Recommendations")
                st.markdown(report)

# ==============================================================================
# TAB 6: APPLICATION TRACKER & ON-DEMAND TAILORING
# ==============================================================================
with tab_tracker:
    st.subheader("📋 Application Tracker & On-Demand Tailoring")
    st.markdown("Manage saved jobs in `copilot.db` and generate tailored resumes and interview packets **on demand** only for the jobs you select.")
    
    all_jobs = database.get_all_jobs()
    if all_jobs:
        jobs_df = pd.DataFrame(
            all_jobs,
            columns=["ID", "Title", "Company", "Location", "URL", "Description", "Status", "Created At"]
        )
        st.dataframe(
            jobs_df[["ID", "Title", "Company", "Location", "Status", "Created At", "URL"]],
            width="stretch"
        )
        
        col_act1, col_act2 = st.columns([1, 1])
        with col_act1:
            selected_job_id = st.selectbox("Select Job ID to Manage", jobs_df["ID"])
        with col_act2:
            new_status = st.selectbox("Update Status", ["found", "notified", "drafted", "applied", "interviewing", "archived"])
            if st.button("Save Status Update"):
                database.update_job_status(selected_job_id, new_status)
                st.success(f"Job #{selected_job_id} status updated to '{new_status}'!")
                st.rerun()

        # Selected Job Details & On-Demand Actions
        selected_row = jobs_df[jobs_df["ID"] == selected_job_id].iloc[0]
        st.divider()
        st.markdown(f"### 🎯 Action Center for: **{selected_row['Title']}** at **{selected_row['Company']}**")
        st.write(f"**URL:** [{selected_row['URL']}]({selected_row['URL']})")
        st.caption(selected_row['Description'][:300] + "..." if selected_row['Description'] else "No description.")

        if st.button(f"⚡ Generate Tailored Resume & PDF for Job #{selected_job_id}"):
            with st.spinner(f"Generating on-demand application packet for {selected_row['Company']}..."):
                packet = generate_application_packet_for_job(
                    selected_row['Title'],
                    selected_row['Company'],
                    selected_row['Description'] or selected_row['Title'],
                    selected_row['URL']
                )
                st.success("Packet generated successfully!")
                
                c_res1, c_res2 = st.columns(2)
                with c_res1:
                    st.markdown("#### 📄 Tailored Resume Text")
                    st.text_area("Resume Content", packet["resume_text"], height=300)
                with c_res2:
                    st.markdown("#### 🎯 7-Day Interview Prep")
                    st.markdown(packet["prep"])
                    if packet["projects"]:
                        st.markdown("#### 🚀 Recommended Portfolio Projects")
                        st.markdown(packet["projects"])

                # Provide Download button if PDF generated
                pdf_path = packet.get("resume_pdf")
                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as pf:
                        pdf_bytes = pf.read()
                    st.download_button(
                        label=f"📥 Download Tailored PDF ({packet['resume_pdf_name']})",
                        data=pdf_bytes,
                        file_name=packet["resume_pdf_name"],
                        mime="application/pdf"
                    )
    else:
        st.info("No jobs recorded in the database yet. Scout jobs in Tab 2 or run the daily cycle to populate!")

# ==============================================================================
# TAB 7: CONVERSATIONAL AI COPILOT
# ==============================================================================
with tab_chat:
    st.subheader("💬 Interactive Career Copilot (Google ADK / Gemini Agent)")
    st.markdown("Talk directly to your AI Career Copilot. Ask about job scouting, resume tips, interview prep, or application strategy.")

    # Initialize chat history
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = [
            {"role": "assistant", "content": "Hello! I am your Career Copilot. How can I help you accelerate your job search today? You can ask me to search for jobs, suggest interview prep questions, or review your resume."}
        ]

    # Display chat messages
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # User input
    user_prompt = st.chat_input("Ask Career Copilot (e.g. 'What are good interview questions for a junior FastAPI role?')...")
    if user_prompt:
        # Append user message
        st.session_state.chat_messages.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)

        # Generate response using Gemini
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            reply = "⚠️ Google API Key is not configured. Please enter your Gemini API key in the sidebar to chat."
        else:
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                
                base_resume = _extract_resume_text()
                system_context = (
                    f"You are the Career Copilot AI Agent. You help software engineers, ML engineers, and developers "
                    f"find jobs, prepare for interviews, tailor resumes, and optimize portfolio projects.\n"
                    f"Candidate's Background:\n{base_resume[:2000]}\n\n"
                    f"Always provide concrete, actionable, highly practical technical career advice."
                )

                response = client.models.generate_content(
                    model=get_gemini_model(),
                    contents=f"{system_context}\n\nUser Question: {user_prompt}"
                )
                reply = response.text
            except Exception as e:
                reply = f"Error generating response: {e}"

        st.session_state.chat_messages.append({"role": "assistant", "content": reply})
        with st.chat_message("assistant"):
            st.markdown(reply)
