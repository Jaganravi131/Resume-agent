"""Evaluation fixtures: synthetic base resume + labeled samples.

IMPORTANT: The base resume is synthetic and contains NO words from
`career_copilot/relevance.py:verified_skill_universe()` beyond the skills it
explicitly claims (python, django, fastapi, postgresql, docker, aws, git, sql,
pandas, sklearn). Planted hallucination samples use kubernetes/rust/terraform/
golang, which are in the universe but deliberately absent from the base.
"""

# ---------------------------------------------------------------------------
# Synthetic base resume (source of truth for all grounding checks)
# ---------------------------------------------------------------------------

BASE_RESUME = """\
Test Candidate
Email: test.candidate@example.com | Phone: +91-0000000000
LinkedIn: https://www.linkedin.com/in/test-candidate/ | GitHub: https://github.com/testcandidate | Portfolio: https://testcandidate.dev

PROFESSIONAL SUMMARY
Software engineer with hands-on experience building web backends and data tools.
Comfortable owning features end to end and communicating clearly within a team.

CORE SKILLS
- Python, Django, FastAPI, REST APIs, SQL
- PostgreSQL, Docker, AWS, Git
- pandas, sklearn, unit testing

EXPERIENCE & IMPACT
- Built REST APIs with FastAPI and PostgreSQL serving 10,000+ requests per day.
- Improved test coverage by 40% using structured testing and code reviews.
- Designed and developed a Django service that reduced manual reporting work by 30%.
- Automated deployment scripts with Docker and AWS, cutting release time in half.

PROJECT HIGHLIGHTS
- Task Board: Designed a Django application with PostgreSQL storage and Docker packaging.
- Data Notes: Built a small pandas and sklearn analysis toolkit with documented results.

EDUCATION
- B.Tech in Computer Science
"""

# ---------------------------------------------------------------------------
# Golden (JD, base-resume) pairs with human fit labels
#   fit: "good" (2) | "mediocre" (1) | "bad" (0)
# ---------------------------------------------------------------------------

GOLDEN_PAIRS = [
    {   # --- backend family ---
        "family": "backend", "fit": "good",
        "title": "Backend Engineer",
        "description": (
            "Build and maintain REST APIs using Python, Django and FastAPI. "
            "Work with PostgreSQL, Docker and AWS. Write unit tests and code reviews."
        ),
    },
    {
        "family": "backend", "fit": "mediocre",
        "title": "Full Stack Engineer",
        "description": (
            "Develop web applications with Python or Java, SQL databases and some "
            "frontend work. Collaboration and communication across teams matter."
        ),
    },
    {
        "family": "backend", "fit": "bad",
        "title": "iOS Mobile Engineer",
        "description": (
            "Swift developer for our mobile team. UIKit, SwiftUI, Core Data, "
            "Objective-C and App Store deployment required."
        ),
    },
    {   # --- data family ---
        "family": "data", "fit": "good",
        "title": "Data Analyst",
        "description": (
            "Analyze datasets with Python, pandas and sklearn. Build SQL reports "
            "with PostgreSQL and automate recurring analysis using REST APIs."
        ),
    },
    {
        "family": "data", "fit": "mediocre",
        "title": "Data Platform Engineer",
        "description": (
            "Own data pipelines with Python and SQL. Some pandas work, larger "
            "systems built in Java. Docker and AWS for deployment."
        ),
    },
    {
        "family": "data", "fit": "bad",
        "title": "Embedded Firmware Engineer",
        "description": (
            "C++ firmware for microcontrollers. Real-time operating systems, "
            "hardware protocols and low-level driver development."
        ),
    },
    {   # --- platform family ---
        "family": "platform", "fit": "good",
        "title": "DevOps Engineer",
        "description": (
            "Automate deployments with Docker and AWS. Scripting in Python and Bash, "
            "Git workflows and unit testing for delivery pipelines."
        ),
    },
    {
        "family": "platform", "fit": "mediocre",
        "title": "Site Reliability Engineer",
        "description": (
            "Keep production services reliable. Python and Bash scripting, AWS, "
            "on-call ownership and clear communication during incidents."
        ),
    },
    {
        "family": "platform", "fit": "bad",
        "title": "Frontend Engineer",
        "description": (
            "React and TypeScript specialist for a design-heavy product. "
            "CSS architecture, browser performance and UI state management."
        ),
    },
]

# ---------------------------------------------------------------------------
# Seeded hallucination samples (planted skills absent from BASE_RESUME)
# ---------------------------------------------------------------------------

HALLUCINATED_SAMPLES = [
    {
        "id": "core-skills-invention",
        "text": (
            "Test Candidate\n"
            "Email: test.candidate@example.com | Phone: +91-0000000000\n"
            "LinkedIn: https://www.linkedin.com/in/test-candidate/\n\n"
            "PROFESSIONAL SUMMARY\nEngineer with strong metrics.\n\n"
            "CORE SKILLS\n- Python, Django, Kubernetes, Terraform\n\n"
            "EXPERIENCE & IMPACT\n- Delivered 3 features that improved speed by 20% using Python.\n- Designed and developed reporting tools with pandas.\n"
        ),
        "planted_skills": ["kubernetes", "terraform"],
    },
    {
        "id": "bullet-invention",
        "text": (
            "Test Candidate\n"
            "Email: test.candidate@example.com | Phone: +91-0000000000\n"
            "LinkedIn: https://www.linkedin.com/in/test-candidate/\n\n"
            "PROFESSIONAL SUMMARY\nEngineer who ships.\n\n"
            "CORE SKILLS\n- Python, Django\n\n"
            "EXPERIENCE & IMPACT\n- Migrated services to Rust and Golang reducing latency by 5x.\n- Implemented and automated builds with FastAPI.\n"
        ),
        "planted_skills": ["rust", "golang"],
    },
    {
        "id": "summary-invention",
        "text": (
            "Test Candidate\n"
            "Email: test.candidate@example.com | Phone: +91-0000000000\n"
            "LinkedIn: https://www.linkedin.com/in/test-candidate/\n\n"
            "PROFESSIONAL SUMMARY\nKubernetes platform engineer with deep Terraform expertise.\n\n"
            "CORE SKILLS\n- Python\n\n"
            "EXPERIENCE & IMPACT\n- Built dashboards using pandas.\n- Improved testing workflows by 15%.\n"
        ),
        "planted_skills": ["kubernetes", "terraform"],
    },
]

# ---------------------------------------------------------------------------
# Truthful samples — must produce ZERO guardrail warnings
# ---------------------------------------------------------------------------

TRUTHFUL_SAMPLES = [
    {
        "id": "rephrased-grounded",
        "text": BASE_RESUME,
    },
    {
        "id": "role-reference-not-a-claim",
        "text": (
            "Test Candidate\n"
            "Email: test.candidate@example.com | Phone: +91-0000000000\n"
            "LinkedIn: https://www.linkedin.com/in/test-candidate/\n\n"
            "PROFESSIONAL SUMMARY\n"
            "Software engineer seeking the Kubernetes Platform Engineer role at CloudCo.\n"
            "Applying for the target role with a Python and AWS background.\n\n"
            "CORE SKILLS\n- Python, Django, FastAPI\n\n"
            "EXPERIENCE & IMPACT\n- Built REST APIs with FastAPI serving 10,000+ requests per day.\n- Improved test coverage by 40%.\n"
        ),
    },
    {
        "id": "soft-skills-prose",
        "text": (
            "Test Candidate\n"
            "Email: test.candidate@example.com | Phone: +91-0000000000\n"
            "LinkedIn: https://www.linkedin.com/in/test-candidate/\n\n"
            "PROFESSIONAL SUMMARY\n"
            "Engineer with strong ownership, collaboration and communication.\n"
            "Confident that the right model of teamwork delivers results.\n\n"
            "CORE SKILLS\n- Python, SQL\n\n"
            "EXPERIENCE & IMPACT\n- Designed and developed a Django service that reduced manual work by 30%.\n- Automated deployment with Docker and AWS.\n"
        ),
    },
]

# ---------------------------------------------------------------------------
# Dirty samples for sanitizer invariants
# ---------------------------------------------------------------------------

DIRTY_SAMPLE = (
    "Jagan Test\n"
    "Email: t@example.com | Phone: +91-0000000000\n"
    "LinkedIn: https://www.linkedin.com/in/x\n"
    "\n"
    "PROFESSIONAL SUMMARY\n"
    "Detail-oriented software engineer.\n"
    "\n"
    "CORE SKILLS\n"
    "- Python, Django\n"
    "\n"
    "EXPERIENCE & IMPACT\n"
    "- Built REST APIs serving 10000+ requests per day.\n"
    "- Improved test coverage by 40%.\n"
    "\n"
    "C:\\PROJECT_FILE\\AI_ML_projects\\adk-workspace\\resume.pdf\n"
    "/home/user/Resume-agent/career_copilot/resume/Resume_latest.pdf\n"
    "file:///tmp/leak.pdf\n"
    "[Tool] Searching job postings for query\n"
    "Keywords: python, flask, docker, aws\n"
    '"resume_pdf": "C:\\some\\path.pdf"\n'
    "```python\n"
    "some code fence\n"
    "```\n"
)

SANITIZER_FORBIDDEN = [
    "C:\\",
    "/home/",
    "file:///",
    "```",
    "[Tool]",
    '"resume_pdf"',
    "Keywords:",
]

# Garbage input the quality gate must reject
GARBAGE_SAMPLE = "lol ok 12345 ???"

# Adversarial job description stuffed with unowned technologies (for the
# grounded-fallback check: none of these may appear as claimed skills)
ADVERSARIAL_JD = (
    "Platform Engineer needed. Kubernetes, Terraform, Golang, Rust, Kafka, Redis, "
    "Elasticsearch and Prometheus. 10+ years shipping distributed systems."
)

# Duplicate-heavy job description (for the category-score bounds regression:
# repeated terms previously pushed category scores to 400%)
DUPLICATE_HEAVY_JD = "Python python python developer with python scripting and python tooling"
