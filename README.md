# Career Copilot — AI-Powered Job Search & Application Agent

An agentic multi-agent system built with [Google ADK](https://google.github.io/adk-docs/) that automates your entire job search pipeline: scouting jobs from live APIs, scoring relevance with TF-IDF, tailoring resumes with Gemini, filling application forms via browser automation, and sending daily digests to Telegram/WhatsApp/Email.

> 🌐 **Interactive Web App & Showcase UI**: Launch live with `streamlit run career_copilot/app.py` for interactive job scouting, ATS resume scoring, tailoring, and interview prep!

---

## Table of Contents

- [Live Web UI & Showcase](#live-web-ui--showcase)
- [Architecture](#architecture)

- [Sub-Agents](#sub-agents)
- [Setup](#setup)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
  - [Resume Setup](#resume-setup)
- [Commands Reference](#commands-reference)
  - [ADK Interactive Mode](#1-adk-interactive-mode-recommended)
  - [ADK Web UI](#2-adk-web-ui)
  - [CLI Workflow Mode](#3-cli-workflow-mode)
  - [Scheduled Automation](#4-scheduled-automation)
  - [Browser Application Flow](#5-browser-application-flow)
  - [Profile Optimization](#6-profile-optimization)
  - [Individual Tools](#7-individual-tools-python-repl)
  - [Testing](#8-testing)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Career_copilot_agent (Root)                      │
│   Orchestrates all sub-agents based on user queries                     │
├───────┬────────┬──────────┬──────────┬───────┬──────────┬──────┬───────┤
│ Scout │ Resume │ Resume   │ Appli-   │ Proj  │ Prep     │ Prof │ Brwsr │
│ Agent │ Optim. │ Evaluator│ cation   │ Recom │ Agent    │ Opt  │ Agent │
│       │ Agent  │ Agent    │ Agent    │ Agent │          │ Agnt │       │
└───────┴────────┴──────────┴──────────┴───────┴──────────┴──────┴───────┘
    │        │         │          │         │        │        │       │
    ▼        ▼         ▼          ▼         ▼        ▼        ▼       ▼
 Live    Gemini    Sanitize    Record   Company  Interview LinkedIn Playwright
 Job     Resume    + Quality   Appli-   Aligned  Plans &   GitHub   Form
 APIs    Tailor    Gate        cations  Projects Topics   Portfolio Fill
```

---

## Sub-Agents

| # | Agent | Description | Key Tools |
|---|-------|-------------|-----------|
| 1 | **Job_scout_agent** | Searches Remotive, Jobicy, RemoteOK, and DuckDuckGo for live job postings | `search_job_postings`, `store_scouted_job`, `compute_match_percentage` |
| 2 | **Resume_optimizer_agent** | Generates tailored resumes using Gemini with ATS-friendly formatting | `generate_tailored_resume`, `export_resume_pdf`, `build_application_packet` |
| 3 | **Resume_evaluator_agent** | Quality gate — evaluates, sanitizes, and auto-fixes resumes before they reach the user | `evaluate_resume_quality`, `sanitize_resume_text`, `evaluate_and_optimize`, `validate_pdf_output` |
| 4 | **Application_agent** | Records application drafts and tracks submission status | `record_application` |
| 5 | **Project_recommender_agent** | Suggests portfolio projects aligned with target companies | `recommend_projects` |
| 6 | **Preparation_agent** | Builds interview preparation plans from job descriptions | `create_preparation_plan` |
| 7 | **Profile_optimizer_agent** | Optimizes LinkedIn, Portfolio, and GitHub profiles for target roles | `generate_profile_updates`, `analyze_target_company` |
| 8 | **Daily_monitor_agent** | Sends daily job digest via Telegram, WhatsApp, and Email | `notify_user_of_matches` |
| 9 | **Browser_application_agent** | Opens job pages in a real browser, fills form fields, pauses for human verification | `run_application_flow` |

---

## Setup

### Prerequisites

- **Python 3.11+**
- **Google Gemini API Key** — [Get one here](https://aistudio.google.com/apikey)
- **Telegram Bot** (optional) — Create via [@BotFather](https://t.me/BotFather)
- **Gmail App Password** (optional) — For email notifications

### Installation

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd adk-workspace

# 2. Create and activate virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install additional dependencies (if not in requirements.txt)
pip install google-adk google-genai pypdf reportlab playwright

# 5. Install Playwright browsers (for browser automation)
playwright install chromium
```

### Environment Variables

Copy the example and fill in your values:

```bash
cp career_copilot/.env.example career_copilot/.env
```

| Variable | Description | Required |
|----------|-------------|----------|
| `GOOGLE_API_KEY` | Gemini API key for AI features | ✅ Yes |
| `RESUME_NAME` | Your full name (appears on resumes) | ✅ Yes |
| `RESUME_EMAIL` | Your email address | ✅ Yes |
| `RESUME_PHONE` | Your phone number | ✅ Yes |
| `RESUME_LINKEDIN` | Your LinkedIn profile URL | ✅ Yes |
| `RESUME_GITHUB` | Your GitHub profile URL | Recommended |
| `RESUME_PORTFOLIO` | Your portfolio website URL | Recommended |
| `JOB_SEARCH_QUERY` | Comma-separated job titles to search | ✅ Yes |
| `MIN_MATCH_PERCENTAGE` | Minimum relevance score (0-100, default: 40) | Optional |
| `EXPERIENCE_LEVEL` | Your level: `fresher`, `junior`, `mid`, `senior` | Optional |
| `EXCLUDE_KEYWORDS` | Comma-separated keywords to exclude from results | Optional |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for notifications | Optional |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID | Optional |
| `SMTP_SERVER` | SMTP server (default: `smtp.gmail.com`) | Optional |
| `SMTP_PORT` | SMTP port (default: `587`) | Optional |
| `SMTP_USERNAME` | SMTP login email | Optional |
| `SMTP_PASSWORD` | Gmail App Password (not your regular password) | Optional |
| `RECEIVER_EMAIL` | Email to receive notifications | Optional |
| `WHATSAPP_TOKEN` | Meta WhatsApp API token | Optional |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp phone number ID | Optional |
| `WHATSAPP_TO_NUMBER` | Recipient WhatsApp number | Optional |

### Resume Setup

Place your base resume PDF(s) in the `career_copilot/resume/` directory:

```
career_copilot/
├── resume/
│   ├── Resume_latest.pdf     ← Your most recent resume
│   └── Resume (1).pdf        ← Additional versions (optional)
```

The agent reads these as source material and tailors them per job. Generated PDFs are saved to `career_copilot/generated_resumes/`.

---

## Commands Reference

### 1. ADK Interactive Mode (Recommended)

Launch the agent in an interactive chat where you can give natural language commands:

```bash
# Start interactive chat with the Career Copilot
adk run career_copilot
```

**Example prompts you can type in ADK mode:**

```
> Search for Python Developer jobs
> Find machine learning engineer roles at remote companies
> Generate a tailored resume for the Senior Backend Developer role at Google
> Show me my daily job digest
> Evaluate the quality of my latest generated resume
> Recommend portfolio projects for an AI Engineer role
> Create an interview preparation plan for a Data Scientist position
> Optimize my LinkedIn profile for a Software Engineer role at Meta
> Run the full career pipeline for "AI Engineer, Backend Developer"
> What's the match percentage for this job description: [paste description]
```

### 2. ADK Web UI

Launch a browser-based UI for interacting with all agents visually:

```bash
# Start the ADK web server
adk web career_copilot

# Opens at http://localhost:8000 by default
# You can specify a different port:
adk web career_copilot --port 8080
```

### 3. CLI Workflow Mode

Run the full pipeline directly from the command line without interactive mode:

```bash
# Activate your virtual environment first
.venv\Scripts\activate    # Windows
source .venv/bin/activate  # Linux/macOS

# Run the daily pipeline (uses JOB_SEARCH_QUERY from .env)
python -c "from career_copilot.workflow import run_daily_cycle; print(run_daily_cycle())"

# Run with a custom query
python -c "from career_copilot.workflow import run_daily_cycle; print(run_daily_cycle('Machine Learning Engineer'))"

# Run with multiple search queries (comma-separated)
python -c "from career_copilot.workflow import run_daily_cycle; print(run_daily_cycle('AI Engineer, Backend Developer, Python Developer'))"
```

### 4. Scheduled Automation

Set up automated daily job searches using the built-in scheduler:

```bash
# Run the scheduler (uses Windows Task Scheduler / cron)
python career_copilot/scheduler.py

# Or install as a Windows scheduled task
powershell -ExecutionPolicy Bypass -File career_copilot/install_task.ps1
```

### 5. Browser Application Flow

Open a job application in the browser with auto-fill. The flow pauses at CAPTCHA/login for human verification:

```bash
# Interactive browser application (prompts for resume review before filling)
python -c "
from career_copilot.workflow import run_browser_application
result = run_browser_application(
    title='Python Developer',
    company='Acme Corp',
    description='We are looking for a Python developer...',
    apply_url='https://careers.hpe.com/us/en/job/1209483/Software-Engineer'
)
print(result)
"

# Headless mode (no visible browser window)
python -c "
from career_copilot.workflow import run_browser_application
result = run_browser_application(
    title='Python Developer',
    company='Acme Corp',
    description='Looking for Python dev...',
    apply_url='https://example.com/apply',
    headless=True
)
print(result)
"
```

### 6. Profile Optimization

Generate tailored profile recommendations for LinkedIn, GitHub, and your portfolio:

```bash
python -c "
from career_copilot.workflow import run_profile_optimization
result = run_profile_optimization(
    title='AI Engineer',
    company='Google DeepMind',
    description='We are looking for an AI engineer to work on large language models...',
    apply_url='https://careers.google.com/jobs/12345'
)
print(result['report'])
"
```

### 7. Individual Tools (Python REPL)

Use specific tools directly for granular control:

```bash
python
```

```python
# --- Setup ---
from career_copilot.config import load_env
load_env()

# --- Search Jobs ---
from career_copilot.tools import search_job_postings
jobs = search_job_postings("Python Developer")
for job in jobs:
    print(f"{job['title']} at {job['company']} — {job['url']}")

# --- Generate Tailored Resume ---
from career_copilot.tools import generate_tailored_resume
resume = generate_tailored_resume(
    title="Backend Developer",
    company="Stripe",
    description="Build and scale payment APIs..."
)
print(resume)

# --- Export Resume to PDF ---
from career_copilot.tools import export_resume_pdf
pdf_path = export_resume_pdf(
    title="Backend Developer",
    company="Stripe",
    description="Build and scale payment APIs..."
)
print(f"PDF saved: {pdf_path}")

# --- Evaluate Resume Quality ---
from career_copilot.resume_evaluator import evaluate_resume_quality
result = evaluate_resume_quality(resume)
print(f"Score: {result['score']}/100 | Passed: {result['passed']}")
print(f"Issues: {result['issues']}")
print(f"Breakdown: {result['breakdown']}")

# --- Sanitize Resume Text ---
from career_copilot.resume_evaluator import sanitize_resume_text
clean = sanitize_resume_text(resume)
print(clean)

# --- Evaluate + Auto-Optimize (full pipeline) ---
from career_copilot.resume_evaluator import evaluate_and_optimize
optimized_text, evaluation = evaluate_and_optimize(
    resume_text=resume,
    title="Backend Developer",
    company="Stripe",
    description="Build and scale payment APIs..."
)
print(f"Final score: {evaluation['score']}/100")
print(optimized_text)

# --- Validate PDF ---
from career_copilot.resume_evaluator import validate_pdf_output
pdf_check = validate_pdf_output(pdf_path)
print(f"Valid: {pdf_check['valid']} | Pages: {pdf_check['page_count']} | Words: {pdf_check['word_count']}")
if pdf_check['issues']:
    print(f"Issues: {pdf_check['issues']}")

# --- Compute Match Percentage ---
from career_copilot.tools import compute_match_percentage
score = compute_match_percentage("Backend Developer", "Build and scale payment APIs using Python, FastAPI...")
print(f"Match: {score}%")

# --- Detailed Match Breakdown ---
from career_copilot.tools import compute_match_detailed
details = compute_match_detailed("Backend Developer", "Build and scale payment APIs using Python...")
print(details)

# --- Recommend Projects ---
from career_copilot.tools import recommend_projects
projects = recommend_projects(
    title="ML Engineer",
    description="Train and deploy ML models...",
    company="Google",
    job_url="https://careers.google.com/jobs/12345"
)
print(projects)

# --- Interview Prep Plan ---
from career_copilot.tools import create_preparation_plan
plan = create_preparation_plan("Data Scientist", "Statistical modeling, Python, SQL, A/B testing...")
print(plan)

# --- Profile Optimization ---
from career_copilot.tools import generate_profile_updates
profile = generate_profile_updates(
    title="Full Stack Developer",
    company="Vercel",
    description="Build web infrastructure..."
)
print(profile)

# --- Analyze Target Company ---
from career_copilot.tools import analyze_target_company
intel = analyze_target_company("Stripe", "https://stripe.com/jobs/listing/backend-engineer", "Build payment APIs...")
print(intel)

# --- Build Full Application Packet ---
from career_copilot.tools import build_application_packet
packet = build_application_packet(
    title="Python Developer",
    company="Acme",
    description="We need a Python dev...",
    url="https://acme.com/apply"
)
print(f"Resume PDF: {packet['resume_pdf_name']}")
print(f"Match: {packet['match_percentage']}%")
print(f"Autofill keys: {list(packet['autofill'].keys())}")

# --- Build Daily Digest ---
from career_copilot.tools import build_daily_digest
digest = build_daily_digest("AI Engineer")
print(f"Found: {len(digest['jobs'])} | Passed filters: {len(digest['digest'])} | Filtered out: {digest['filtered_out_count']}")

# --- Send Notifications ---
from career_copilot.notifier import send_telegram_message, send_email
send_telegram_message("Test message from Career Copilot")
send_email("Test Subject", "<p>Test email body</p>")

# --- Database Queries ---
from career_copilot.database import get_all_jobs, get_actionable_jobs
all_jobs = get_all_jobs()
active = get_actionable_jobs()
print(f"Total jobs: {len(all_jobs)} | Actionable: {len(active)}")
```

### 8. Testing

```bash
# Run the full test suite
cd career_copilot
python -m pytest test_career_copilot.py -v

# Run tests with the test runner script
python career_copilot/run_tests.py

# Run a specific test
python -m pytest test_career_copilot.py -v -k "test_generate_tailored_resume"
```

---

## Project Structure

```
adk-workspace/
├── README.md                           ← This file
├── requirements.txt                    ← Python dependencies
├── career_copilot/
│   ├── __init__.py                     ← Package init, loads .env
│   ├── agent.py                        ← All sub-agent definitions + root agent
│   ├── tools.py                        ← Core tool functions (search, resume, digest)
│   ├── resume_evaluator.py             ← Resume quality gate (sanitize, evaluate, optimize)
│   ├── workflow.py                     ← CLI workflow entry points
│   ├── config.py                       ← Env loader, stopwords, HTTP helpers
│   ├── database.py                     ← SQLite database (jobs, applications, reports)
│   ├── relevance.py                    ← TF-IDF relevance scoring engine
│   ├── profile_optimizer.py            ← LinkedIn/GitHub/Portfolio optimization
│   ├── autofill_helpers.py             ← ATS form-fill mapping
│   ├── browser_runner.py               ← Playwright browser automation
│   ├── notifier.py                     ← Telegram, WhatsApp, Email notifications
│   ├── scheduler.py                    ← Daily task scheduler
│   ├── install_task.ps1                ← Windows Task Scheduler setup
│   ├── test_career_copilot.py          ← Test suite
│   ├── run_tests.py                    ← Test runner script
│   ├── .env                            ← Your environment variables (DO NOT COMMIT)
│   ├── .env.example                    ← Template for .env
│   ├── .gitignore                      ← Git ignore rules
│   ├── copilot.db                      ← SQLite database file
│   ├── resume/                         ← Your base resume PDFs (source material)
│   │   ├── Resume_latest.pdf
│   │   └── Resume (1).pdf
│   └── generated_resumes/              ← Tailored PDFs (auto-generated per job)
└── my_first_agent/                     ← Separate agent project
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'google.adk'` | Run `pip install google-adk` |
| `ModuleNotFoundError: No module named 'google.genai'` | Run `pip install google-genai` |
| `ModuleNotFoundError: No module named 'pypdf'` | Run `pip install pypdf` |
| `ModuleNotFoundError: No module named 'reportlab'` | Run `pip install reportlab` |
| Gemini API returns 429 (quota exceeded) | The system auto-falls back to keyword-based templates. Wait or use a different API key |
| Resume contains file paths | The Resume Evaluator agent auto-sanitizes. Run `sanitize_resume_text()` manually if needed |
| Resume quality score is low | Run `evaluate_and_optimize()` to auto-fix via Gemini |
| No jobs found | Check `JOB_SEARCH_QUERY` in `.env`. Try broader terms like `"Python Developer"` |
| Telegram notifications not sending | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Send `/start` to your bot first |
| Email not sending | Use a Gmail App Password (not your regular password). Enable 2FA on Gmail first |
| Browser automation fails | Run `playwright install chromium` to install the browser |
| Database locked error | The system uses WAL mode. Close other connections or delete `copilot.db` to reset |

---

## Quick Start (TL;DR)

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure
cp career_copilot/.env.example career_copilot/.env
# Edit .env with your API keys and personal info

# 3. Add your resume
# Place your PDF in career_copilot/resume/

# 4. Run
adk run career_copilot
# Then type: "Search for Python Developer jobs and build my daily digest"
```
