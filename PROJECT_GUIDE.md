# Career Copilot — Complete Build Guide & Progress Documentation

> **Objective**: This document is a living log of everything done to build this project — the initial plan, mistakes made, fixes applied, enhancements added, and key lessons learned. After reading this, you should be able to rebuild the project from scratch entirely on your own.

---

## Table of Contents
1. [Project Vision & What It Does](#1-project-vision--what-it-does)
2. [System Architecture](#2-system-architecture)
3. [File & Module Map](#3-file--module-map)
4. [Step-by-Step Build Walkthrough](#4-step-by-step-build-walkthrough)
5. [Bugs We Found & Fixed](#5-bugs-we-found--fixed)
6. [Logical Flaws & Enhancements Applied](#6-logical-flaws--enhancements-applied)
7. [Why a Database is Needed](#7-why-a-database-is-needed)
8. [Key Concepts & How They Work](#8-key-concepts--how-they-work)
9. [Your Doubts, Answered](#9-your-doubts-answered)
10. [How to Run the App](#10-how-to-run-the-app)
11. [Environment Configuration (.env)](#11-environment-configuration-env)
12. [Mistakes to Avoid](#12-mistakes-to-avoid)
13. [Lessons Learned](#13-lessons-learned)
14. [Future Roadmap](#14-future-roadmap)

---

## 1. Project Vision & What It Does

**Career Copilot** is an **autonomous multi-agent AI system** built with Google's Agent Development Kit (ADK) and Gemini. It automates the most tedious parts of a job search:

| What it automates | How |
|---|---|
| Job scouting | Fetches real live jobs from Remotive, Jobicy, RemoteOK, Greenhouse, Lever, Ashby every day |
| Resume tailoring | Uses Gemini to rewrite your resume targeting each specific job description |
| ATS scoring | Evaluates your resume against the job with a quality score (0-100) |
| PDF generation | Creates a professionally formatted PDF resume for each job |
| Interview prep | Generates a 7-day preparation plan with Q&A for each role |
| Profile optimization | Suggests LinkedIn, GitHub, and portfolio updates for each target company |
| Notifications | Sends daily digest via Telegram, WhatsApp, and Email |
| Application tracking | SQLite database tracks every scouted job and application status |
| Browser autofill | Playwright automation fills real job application forms for you |
| Interactive AI chat | A conversational Gemini-powered copilot inside the Streamlit UI |

---

## 2. System Architecture

```
Career Copilot — Multi-Agent Architecture
──────────────────────────────────────────────────────
 [Scheduler / Trigger]
       |
       v
 workflow.run_daily_cycle(query)
       |
       +──► tools.build_daily_digest(query)
       |         |
       |         +──► search_job_postings() ──► Remotive API
       |         |                          ──► Jobicy API
       |         |                          ──► RemoteOK API
       |         |                          ──► DuckDuckGo HTML (Greenhouse/Lever/Ashby)
       |         |
       |         +──► relevance.compute_relevance_score()  [TF-IDF + Gemini scoring]
       |         |                          ──► Filter jobs below MIN_MATCH_PERCENTAGE
       |         |
       |         +──► database.add_job()   [SQLite: copilot.db]
       |         |
       |         +──► (On-demand) generate_tailored_resume() ──► Gemini API
       |                          |
       |                          +──► resume_evaluator.evaluate_and_optimize() [Quality Gate]
       |                          +──► _export_resume_pdf_from_text() [ReportLab PDF]
       |
       +──► notifier.send_telegram_message()
                  notifier.send_whatsapp_message()
                  notifier.send_email()

 [Streamlit Web App: app.py]
       |
       +-- Tab 1: Architecture Showcase + Live Pipeline Test
       +-- Tab 2: Job Scout & Matcher (search + score + store)
       +-- Tab 3: ATS Resume Evaluator
       +-- Tab 4: Resume Tailor & PDF Download
       +-- Tab 5: Interview Prep & Profile Optimizer
       +-- Tab 6: Application Tracker (database viewer + status updater)
       +-- Tab 7: Interactive AI Copilot (Gemini conversational chat)
```

### The 9 Specialized Agents

| # | Agent | Role | Primary Tools |
|---|---|---|---|
| 1 | Job_scout_agent | Scouts jobs across multiple boards with seniority expansion | `search_job_postings`, `database.add_job` |
| 2 | Resume_optimizer_agent | Tailors resumes with strict anti-hallucination guardrails | `generate_tailored_resume`, `export_resume_pdf_from_markdown` |
| 3 | Resume_evaluator_agent | Quality Gate: Evaluates, sanitizes, and auto-fixes resumes | `evaluate_resume_quality`, `sanitize_resume_text` |
| 4 | Application_agent | Records application drafts and tracks submission status | `record_application` |
| 5 | Project_recommender_agent | Suggests portfolio projects aligned with target roles | `recommend_projects` |
| 6 | Preparation_agent | Builds 7-day interview preparation plans and Q&A guides | `create_preparation_plan` |
| 7 | Profile_optimizer_agent | Optimizes LinkedIn, GitHub, and Portfolio profiles | `generate_profile_updates` |
| 8 | Daily_monitor_agent | Sends automated alerts via Telegram, WhatsApp, and Email | `notify_user_of_matches` |
| 9 | Browser_application_agent | Automates browser form-filling via Playwright | `run_application_flow` |

---

## 3. File & Module Map

```
adk-workspace/
├── career_copilot/
│   ├── __init__.py           # Package init; exposes root_agent
│   ├── agent.py              # Google ADK agent & sub-agent definitions
│   ├── app.py                # Streamlit web dashboard (7 tabs)
│   ├── apply.py              # CLI entry point for browser auto-apply
│   ├── autofill_helpers.py   # Site-specific ATS form selectors
│   ├── browser_runner.py     # Playwright browser automation engine
│   ├── config.py             # Env loading, API key management, HTTP helpers
│   ├── copilot.db            # SQLite database (auto-created at first run)
│   ├── database.py           # All SQLite CRUD operations
│   ├── notifier.py           # Telegram / WhatsApp / Email notification senders
│   ├── profile_optimizer.py  # Company intel + LinkedIn/GitHub/Portfolio optimizer
│   ├── relevance.py          # TF-IDF + Gemini-based relevance scoring engine
│   ├── resume_evaluator.py   # Quality gate: ATS scoring + sanitizer
│   ├── resume/               # Directory: place your Resume_latest.pdf here
│   ├── generated_resumes/    # Auto-created: tailored PDF resumes saved here
│   ├── scheduler.py          # Windows Task Scheduler integration helper
│   ├── tools.py              # Core tool functions used by agents (1045 lines)
│   ├── workflow.py           # High-level pipeline orchestrator
│   └── test_*.py             # Unit tests
├── requirements.txt          # Python dependencies
├── .env                      # Your private secrets (NOT committed to Git)
├── .env.example              # Template showing which keys to fill in
└── PROJECT_GUIDE.md          # This document
```

---

## 4. Step-by-Step Build Walkthrough

### Phase 0 — Project Bootstrap

**What existed at start**: A rough skeleton with `agent.py`, `tools.py`, `app.py`, `notifier.py`, and `scheduler.py` — but no tests, no database layer, and multiple runtime crashes.

**Setup steps**:
```powershell
# Step 1: Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Step 2: Install core dependencies
pip install google-adk google-genai streamlit pypdf reportlab pandas

# Step 3: Create .env from template
copy career_copilot\.env.example career_copilot\.env
# Then fill in your API keys and personal details

# Step 4: Place your resume PDF
# Copy your resume PDF to: career_copilot/resume/Resume_latest.pdf
```

---

### Phase 1 — Dependency & Configuration Fixes

#### Problem: `pandas` was missing from requirements.txt
The Streamlit `app.py` used `pd.DataFrame(...)` but `pandas` was not in `requirements.txt`.

**Fix**: Added `pandas>=2.0.0` to `requirements.txt`, then ran `pip install pandas`.

#### Problem: API Key detection was inconsistent
`app.py` was only checking for `GEMINI_API_KEY` but the `config.py` used `GOOGLE_API_KEY`. This meant the sidebar showed "No key" even when the key was set.

**Fix**: Updated `app.py` to check both:
```python
configured_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
```
And when the user enters a key in the sidebar, set both env vars:
```python
os.environ["GOOGLE_API_KEY"] = user_api_key
os.environ["GEMINI_API_KEY"] = user_api_key
```

---

### Phase 2 — Core Bug Fixes in tools.py

#### Bug: `database.store_job` doesn't exist → should be `database.add_job`
In `app.py` Tab 2 (Job Scout), the code called `database.store_job(...)` but the actual function in `database.py` is `database.add_job(...)`.

**Fix**:
```python
# Before (wrong):
database.store_job(title, company, location, url, description)

# After (correct):
database.add_job(job_title, job.get("company",""), job.get("location",""), job.get("url",""), job_desc)
```

#### Bug: `compute_match_percentage` parameter order was swapped
The function signature is `compute_match_percentage(title, description)` but the call was passing them in the wrong order.

**Fix**: Verified signature and corrected call order at all call sites.

#### Bug: `generate_tailored_resume` was called with wrong number of args
The function takes exactly `(title, company, description)` — 3 args. Several call sites were passing only 2.

**Fix**: Ensured all call sites pass all 3 required arguments.

#### Bug: `export_resume_pdf` path leak — absolute paths exposed in UI
The old `export_resume_pdf` returned the full absolute path like `C:\Users\jagan\...`, which was shown directly to the user. That's ugly and a privacy risk.

**Fix**: Updated all display locations to use `Path(pdf_path).name` which returns only the filename.

#### Bug: Resume source deduplication — multiple PDFs concatenated
The `_get_resume_sources()` function was globbing ALL PDFs in `career_copilot/resume/` and concatenating them, which caused duplicate content in the resume text.

**Fix**:
```python
def _get_resume_sources() -> list[Path]:
    latest = resume_dir / "Resume_latest.pdf"
    if latest.exists():
        return [latest]  # Use only the canonical latest version
    pdfs = sorted(resume_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [pdfs[0]] if pdfs else []  # Fallback: only the newest one
```

---

### Phase 3 — Logical Flaw Resolution

After the crashes were fixed, we ran a deep logic review and found 6 fundamental design problems:

#### Flaw 1: ALL jobs were getting filtered out (0 matches)
**Root cause**: The experience level in `.env` was set to `junior` or `fresher`, but search queries were generic like "Python Developer". Job boards return senior-level results for generic queries. The seniority filter in `relevance.py` then rejected 100% of them.

**Fix — Seniority-Aware Query Expansion**:
```python
def _expand_query_for_experience(sub_queries: list[str]) -> list[str]:
    exp_level = os.environ.get("EXPERIENCE_LEVEL", "mid").lower()
    is_junior = any(term in exp_level for term in ("fresher", "junior", "entry", "intern"))
    if not is_junior:
        return sub_queries
    expanded = []
    for q in sub_queries:
        expanded.append(q)
        if not any(k in q.lower() for k in ("junior", "entry level", "graduate")):
            expanded.append(f"{q} junior")  # Automatically appends "junior" variant
    return expanded
```

#### Flaw 2: Resume tailoring ran for ALL jobs during the daily digest
**Root cause**: The original `build_daily_digest()` called `generate_tailored_resume()` for every matched job, burning ~10x LLM token budget even if you never looked at most of them.

**Fix — On-Demand Tailoring Pipeline**:
Added a `generate_full_packets: bool = False` parameter:
```python
def build_daily_digest(query: str, generate_full_packets: bool = False) -> dict:
    ...
    if generate_full_packets:
        resume_text = generate_tailored_resume(job["title"], job["company"], job["description"])
    else:
        resume_text = "Available on demand via Application Tracker"
```

#### Flaw 3: LLM was hallucinating skills in tailored resumes
**Root cause**: No explicit rules preventing Gemini from adding technologies not in your real resume.

**Fix — Anti-Hallucination Guardrail** added to prompt:
```python
"CRITICAL ANTI-HALLUCINATION & TRUTH RULES:\n"
"- STRICT FACTUAL GROUNDING: You must NEVER invent technologies, programming languages, "
"libraries, cloud tools, employers, or degrees not in the Candidate's Base Resume.\n"
"- If the job requires tools the candidate lacks (e.g. Kubernetes), DO NOT add them.\n"
"- Instead, emphasize actual verified skills that are transferable.\n"
```

#### Flaw 4: Resume evaluator was appending debug info into the PDF
**Root cause**: `sanitize_resume_text()` was not stripping internal metadata like `[DEBUG] Keywords: python, fastapi...` or evidence lines with file paths.

**Fix**: Strengthened `sanitize_resume_text()` with regex patterns that strip any line starting with common debug prefixes, file paths, or evidence markers.

#### Flaw 5: DuckDuckGo job search was blocking (no timeout)
**Root cause**: DDG HTML scraper used `urllib.request.urlopen` with no timeout.

**Fix**: Added `timeout=12` to all HTTP calls and retry logic:
```python
with urllib.request.urlopen(req, timeout=12) as response:
    raw_html = response.read().decode("utf-8", errors="ignore")
```

#### Flaw 6: The Application Tracker tab was missing from Streamlit UI
**Root cause**: Tab 6 was completely absent. No way to view scouted jobs or trigger on-demand tailoring.

**Fix**: Added full Application Tracker tab with job table, status update dropdown, on-demand "Generate Resume & PDF" button, and download button.

---

### Phase 4 — Enhancements Added

1. **Interactive AI Copilot Tab (Tab 7)**: Conversational Gemini chat with your resume as context.
2. **`generate_application_packet_for_job()`**: One-call function that generates resume, PDF, projects, prep plan, and profile updates for any selected job.
3. **On-demand PDF download**: Using Streamlit's `st.download_button`.
4. **WAL mode for SQLite**: Prevents lock contention between scheduler and UI.
5. **Database cleanup scheduler**: `cleanup_old_records(days=90)` runs alongside daily cycle.

---

## 5. Bugs We Found & Fixed

| Bug | File | Root Cause | Fix Applied |
|---|---|---|---|
| `AttributeError: module 'database' has no attribute 'store_job'` | `app.py` | Wrong function name | Renamed to `add_job` |
| Resume match always 0% | `tools.py` | `compute_match_percentage` args swapped | Fixed arg order |
| PDF contained debug metadata | `tools.py`, `resume_evaluator.py` | Sanitizer didn't strip evidence lines | Enhanced regex sanitizer |
| API key not detected in UI | `app.py` | Only checked `GEMINI_API_KEY` | Check both env vars |
| PDF path exposed to user | `app.py` | Used raw path instead of filename | Use `Path(p).name` |
| Resume concatenated duplicates | `tools.py` | Returned all PDFs in directory | Return only `Resume_latest.pdf` |
| `TypeError: export_resume_pdf() takes 2 args but 3 were given` | `app.py` | Wrong arg count | Fixed call signatures |
| Streamlit crashed: `pandas not installed` | `app.py` | Missing from `requirements.txt` | Added to deps |
| Pipeline hung indefinitely | `tools.py` | DDG search had no HTTP timeout | Added `timeout=12` + retry |
| 10 resumes generated unwanted daily | `tools.py` | Digest always called LLM per job | Added `generate_full_packets=False` |

---

## 6. Logical Flaws & Enhancements Applied

| Flaw # | Problem | Impact | Enhancement Applied |
|---|---|---|---|
| 1 | Junior/fresher gets 0 job matches | Pipeline sent empty digests daily | Seniority-aware query expander |
| 2 | 10 resumes generated unnecessarily | ~80% wasted LLM tokens per day | On-demand tailoring pipeline |
| 3 | LLM hallucinated skills in resume | Resume could list tools you don't know | Anti-hallucination prompt guardrail |
| 4 | Debug info leaked into PDF output | Unprofessional PDFs sent to employers | Strengthened sanitizer |
| 5 | DDG scraper could block forever | UI/pipeline froze on network issues | Timeout + retry with backoff |
| 6 | No way to view/act on scouted jobs | Users couldn't use the tracker | Added full Application Tracker tab |

---

## 7. Why a Database is Needed

**Your Doubt**: "Why do we need a database? Can't we just store jobs in memory?"

**Answer**: Memory is lost when the program restarts. The Career Copilot runs daily on a schedule. Without a database:
- Every day, it would re-scout the same jobs and notify you about the same ones repeatedly.
- You could never track which jobs you've already applied to.
- You couldn't view the history of scouted jobs in the Streamlit UI.
- The daily cleanup and deduplication logic couldn't function.

**What `copilot.db` (SQLite) stores**:

```sql
-- jobs: Every scouted job, with status lifecycle
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    url TEXT UNIQUE NOT NULL,  -- UNIQUE prevents duplicate scouting
    description TEXT,
    status TEXT DEFAULT 'found', -- found → notified → applied → archived
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- applications: Tracks when/how you applied
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    apply_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'drafted',
    notes TEXT,
    ...
);

-- daily_reports: History of every digest sent
CREATE TABLE daily_reports (...);

-- company_intel: Cached company analysis (avoids re-calling Gemini)
CREATE TABLE company_intel (...);
```

**Key pattern**: `url TEXT UNIQUE` means if the same job URL appears in two different daily scouting runs, `INSERT` raises `IntegrityError`, and `add_job()` catches it and returns `False` — silently skipping it. This prevents duplicate notifications.

---

## 8. Key Concepts & How They Work

### TF-IDF Relevance Scoring (`relevance.py`)
TF-IDF stands for **Term Frequency–Inverse Document Frequency**.

- **TF**: How often a keyword appears in one specific job description.
- **IDF**: How rare that keyword is across ALL job descriptions fetched that day.
- **Combined**: A keyword rare in the batch but frequent in one job means that job is specifically about that technology.

The `compute_relevance_score()` function:
1. Extracts keywords from your resume (your actual skills).
2. Extracts keywords from the job title + description.
3. Computes TF-IDF weighted overlap.
4. Checks for experience-level mismatch.
5. Returns a score 0–100, category breakdowns, and top matching/missing skills.

Jobs below `MIN_MATCH_PERCENTAGE` (default: 40%) are filtered before any LLM is called.

### Anti-Hallucination Guardrail
When Gemini tailors a resume, without explicit rules it tends to "bridge the gap" by inventing skills you don't have. Our guardrail:
1. **In the prompt**: Explicit forbiddance rules ("NEVER invent technologies not in the base resume").
2. **Post-generation**: `validate_no_hallucinated_skills()` checks if technical terms in the tailored resume exist in the base resume.

### Quality Gate Pattern (`resume_evaluator.py`)
The `evaluate_and_optimize()` function is a **quality gate** — it intercepts the generated resume before returning it to the user:
1. Score the resume (0-100) on contact info, formatting, keywords, length.
2. If score < 60, apply auto-fixes.
3. Log warnings if it still scores low.
4. Return the (possibly fixed) resume and the evaluation report.

This "guardrail" pattern — an automated checkpoint that prevents bad output from propagating — is fundamental to production AI engineering.

---

## 9. Your Doubts, Answered

**Q: Does this project make sense? Does it have logical flaws?**

Yes, when we first analyzed it, there were 6 logical flaws. The biggest was **ALL jobs filtered out** — the entire pipeline ran daily but sent empty notifications. The second was **burning LLM tokens on resumes nobody asked for**. Both are now fixed (see Section 6).

**Q: Do we need a database?**

Yes — see Section 7 for the full explanation. TL;DR: Without a database, every daily run is stateless. You get duplicate notifications, can't track applications, and the Application Tracker tab can't work.

**Q: What is ADK (Agent Development Kit)?**

Google ADK is a framework for building **multi-agent AI systems** where each agent has:
- A name and description
- A set of "tools" (Python functions it can call)
- A Gemini model powering its reasoning
- The ability to delegate to sub-agents

In this project, `agent.py` defines all 9 agents using the ADK. Each agent wraps a specific set of tools from `tools.py`. The `root_agent` is the orchestrator.

**Q: What is TF-IDF and why not just use Gemini for matching?**

TF-IDF is fast (milliseconds, no API cost). Gemini matching costs tokens and takes seconds. We use TF-IDF as a **first-pass filter** (cheap, fast) and optionally Gemini as a **second-pass deep scorer** only for jobs that passed the threshold. This is the standard "coarse-to-fine" pipeline pattern in production AI systems.

**Q: Why does the resume evaluator auto-fix the output?**

Because LLMs are non-deterministic. Even with a perfect prompt, sometimes the output is missing a section header or has extra blank lines. The quality gate catches and corrects these automatically, so you never send a malformed resume.

---

## 10. How to Run the App

### Start the Streamlit Web Dashboard
```powershell
& "c:\PROJECT_FILE\AI_ML_projects\adk-workspace\.venv\Scripts\streamlit.exe" run career_copilot\app.py
```
Opens at: http://localhost:8501

### Run the Daily Pipeline Manually (CLI)
```powershell
& "c:\PROJECT_FILE\AI_ML_projects\adk-workspace\.venv\Scripts\python.exe" -c "
from career_copilot.workflow import run_daily_cycle
result = run_daily_cycle('Python Developer')
print(result['notification_status'])
"
```

### Run the ATS Evaluator Test
```powershell
& "c:\PROJECT_FILE\AI_ML_projects\adk-workspace\.venv\Scripts\python.exe" career_copilot\test_evaluator.py
```

### Verify All Files Compile (No Syntax Errors)
```powershell
& "c:\PROJECT_FILE\AI_ML_projects\adk-workspace\.venv\Scripts\python.exe" -m compileall career_copilot
```

### Set Up Windows Task Scheduler (Automated Daily Run)
```powershell
& "c:\PROJECT_FILE\AI_ML_projects\adk-workspace\.venv\Scripts\python.exe" career_copilot\scheduler.py
```

---

## 11. Environment Configuration (.env)

Create `career_copilot/.env` from `.env.example` and fill in all values:

```env
# ── AI Provider ─────────────────────────────────────────────────────
GOOGLE_API_KEY=your_google_gemini_api_key_here
GEMINI_MODEL=gemini-2.0-flash    # or gemini-1.5-pro for higher quality

# ── Candidate Profile ────────────────────────────────────────────────
RESUME_NAME=Jagan Babu R
RESUME_EMAIL=jaganravi131@gmail.com
RESUME_PHONE=+91-8124819503
RESUME_LINKEDIN=https://www.linkedin.com/in/jagan-babu-r/
RESUME_GITHUB=https://github.com/Jaganravi131
RESUME_PORTFOLIO=https://portfolio-ygig.vercel.app/

# ── Job Search Config ────────────────────────────────────────────────
JOB_SEARCH_QUERY=Python Developer, ML Engineer, Backend Developer
EXPERIENCE_LEVEL=junior         # fresher | junior | mid | senior
MIN_MATCH_PERCENTAGE=40         # Filter threshold (0-100)

# ── Notification Channels ────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
WHATSAPP_API_KEY=your_callmebot_api_key
WHATSAPP_PHONE_NUMBER=+91xxxxxxxxxx
EMAIL_SENDER=your_gmail@gmail.com
EMAIL_PASSWORD=your_gmail_app_password   # Use Gmail App Password, not real password
EMAIL_RECIPIENT=your_email@gmail.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
```

> **Important**: Never commit `.env` to Git. It's already in `.gitignore`.

---

## 12. Mistakes to Avoid

1. **Don't use `GEMINI_API_KEY` inconsistently** — always set both `GOOGLE_API_KEY` and `GEMINI_API_KEY`, or update all checks.
2. **Don't place multiple PDFs in `career_copilot/resume/`** — rename your real resume to `Resume_latest.pdf`.
3. **Don't call `generate_tailored_resume()` with only 2 arguments** — it requires `(title, company, description)`.
4. **Don't pass an absolute path to the user** — always use `Path(pdf_path).name` for display.
5. **Don't skip `database.init_db()`** — it's called on import, but in isolated test scripts you may need to call it manually.
6. **Don't set `EXPERIENCE_LEVEL=junior` with generic queries** — junior + generic = 0 matches. Let the query expander handle it automatically.
7. **Don't use raw `sqlite3` directly in `app.py`** — always use the `database.py` module functions.
8. **Don't modify `copilot.db` manually while Streamlit is running** — WAL mode helps, but conflicting writes can still cause issues.

---

## 13. Lessons Learned

### On AI Engineering
- **Prompt guardrails are not optional** — LLMs hallucinate by default. Every prompt that generates structured output needs explicit rules about what NOT to do.
- **Quality gates are a fundamental pattern** — Never trust raw LLM output. Always run it through a verification/scoring layer.
- **TF-IDF + LLM is the right architecture** — Use TF-IDF for fast, cheap first-pass filtering. Use LLM only for what TF-IDF can't do (generation, deep Q&A).
- **Coarse-to-fine pipelines save money** — Always filter cheap before running expensive.

### On System Design
- **Decouple scouting from generation** — The scout (search + score + store) and the generator (tailored resume + PDF) are different concerns. They should not be forced to run together.
- **On-demand > batch for expensive operations** — Don't pre-generate 10 PDFs nobody asked for. Generate exactly what the user selects.
- **Databases solve state problems** — Whenever you need to remember something between runs, a database is the right tool.

### On Python / ADK
- **`UNIQUE` constraints in SQLite are your deduplication layer** — Use them aggressively.
- **WAL mode in SQLite** prevents concurrency errors when multiple processes touch the same DB.
- **Module-level function name consistency matters** — `store_job` vs `add_job` is a class of bug that only shows at runtime. Write unit tests that import every public function by name.
- **`Path(p).name` for user-facing file display** — Never show absolute paths to users.

### On Streamlit
- **Use `st.session_state` for chat history** — Streamlit reruns the entire script on every interaction. Without `session_state`, chat history vanishes on each message.
- **`st.download_button` needs `bytes`** — Read the file with `open(..., "rb")` before passing to `st.download_button`.
- **API key in sidebar → set in `os.environ`** — This way all downstream functions pick it up without needing it passed explicitly.

---

## 14. Future Roadmap

| Enhancement | Priority | Complexity |
|---|---|---|
| Vector embedding search (FAISS/ChromaDB) instead of TF-IDF | High | Medium |
| Resume version history in DB (track each tailored version) | High | Low |
| Multi-resume support (different base resumes for different tracks) | Medium | Medium |
| LinkedIn Easy Apply automation via Playwright | Medium | High |
| Job application email drafter | Medium | Low |
| Interview mock practice with voice input | Low | High |
| Company culture sentiment analysis from Glassdoor | Low | Medium |
| Deployed cloud version (Google Cloud Run or Railway) | Medium | Medium |

---

*Career Copilot v1.1 — Built September 2026 — Google ADK + Gemini*
