"""Profile Optimizer: Company Intelligence + Strategic Projects + Platform Optimization.

Analyzes a target company, suggests portfolio projects aligned with what the
company is building, and generates actionable optimization for LinkedIn,
portfolio website, and GitHub profile.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlparse, quote_plus

from .config import STOPWORDS as _STOPWORDS, fetch_page_text as _fetch_page_text, fetch_with_retry

logger = logging.getLogger("career_copilot.profile_optimizer")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CompanyIntel:
    """Intelligence gathered about a target company."""
    name: str = ""
    domain: str = ""
    mission: str = ""
    products: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    problem_domains: list[str] = field(default_factory=list)
    industry: str = ""
    company_stage: str = ""
    recent_focus: str = ""
    raw_homepage_text: str = ""
    raw_about_text: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "domain": self.domain,
            "mission": self.mission,
            "products": self.products,
            "tech_stack": self.tech_stack,
            "problem_domains": self.problem_domains,
            "industry": self.industry,
            "company_stage": self.company_stage,
            "recent_focus": self.recent_focus,
        }

    def summary(self) -> str:
        lines = [
            f"Company: {self.name}",
            f"Domain: {self.domain}",
            f"Mission: {self.mission}",
            f"Products: {', '.join(self.products) if self.products else 'Unknown'}",
            f"Tech Stack: {', '.join(self.tech_stack) if self.tech_stack else 'Unknown'}",
            f"Problem Domains: {', '.join(self.problem_domains) if self.problem_domains else 'Unknown'}",
            f"Industry: {self.industry}",
            f"Stage: {self.company_stage}",
            f"Recent Focus: {self.recent_focus}",
        ]
        return "\n".join(lines)


@dataclass
class ProjectSuggestion:
    """A strategic portfolio project suggestion."""
    name: str = ""
    what_to_build: str = ""
    why_relevant: str = ""
    tech_stack: list[str] = field(default_factory=list)
    difficulty: str = ""  # "weekend", "1-week", "2-week"
    interview_frame: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "what_to_build": self.what_to_build,
            "why_relevant": self.why_relevant,
            "tech_stack": self.tech_stack,
            "difficulty": self.difficulty,
            "interview_frame": self.interview_frame,
        }


@dataclass
class LinkedInOptimization:
    """LinkedIn profile optimization suggestions."""
    headline: str = ""
    about_section: str = ""
    experience_bullets: list[str] = field(default_factory=list)
    featured_suggestions: list[str] = field(default_factory=list)
    skills_to_add: list[str] = field(default_factory=list)
    connection_note: str = ""

    def to_dict(self) -> dict:
        return {
            "headline": self.headline,
            "about_section": self.about_section,
            "experience_bullets": self.experience_bullets,
            "featured_suggestions": self.featured_suggestions,
            "skills_to_add": self.skills_to_add,
            "connection_note": self.connection_note,
        }


@dataclass
class PortfolioOptimization:
    """Portfolio website optimization suggestions."""
    hero_tagline: str = ""
    hero_subtitle: str = ""
    project_card_updates: list[dict] = field(default_factory=list)
    case_study_angle: str = ""
    case_study_project: str = ""
    tech_badges_order: list[str] = field(default_factory=list)
    cta_text: str = ""

    def to_dict(self) -> dict:
        return {
            "hero_tagline": self.hero_tagline,
            "hero_subtitle": self.hero_subtitle,
            "project_card_updates": self.project_card_updates,
            "case_study_angle": self.case_study_angle,
            "case_study_project": self.case_study_project,
            "tech_badges_order": self.tech_badges_order,
            "cta_text": self.cta_text,
        }


@dataclass
class GitHubOptimization:
    """GitHub profile optimization suggestions."""
    bio: str = ""
    repos_to_pin: list[dict] = field(default_factory=list)
    readme_improvements: list[dict] = field(default_factory=list)
    new_repo_ideas: list[dict] = field(default_factory=list)
    contribution_suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "bio": self.bio,
            "repos_to_pin": self.repos_to_pin,
            "readme_improvements": self.readme_improvements,
            "new_repo_ideas": self.new_repo_ideas,
            "contribution_suggestions": self.contribution_suggestions,
        }


@dataclass
class ProfileOptimizationReport:
    """Full profile optimization report for a target job."""
    company_intel: CompanyIntel = field(default_factory=CompanyIntel)
    project_suggestions: list[ProjectSuggestion] = field(default_factory=list)
    linkedin: LinkedInOptimization = field(default_factory=LinkedInOptimization)
    portfolio: PortfolioOptimization = field(default_factory=PortfolioOptimization)
    github: GitHubOptimization = field(default_factory=GitHubOptimization)

    def to_dict(self) -> dict:
        return {
            "company_intel": self.company_intel.to_dict(),
            "project_suggestions": [p.to_dict() for p in self.project_suggestions],
            "linkedin": self.linkedin.to_dict(),
            "portfolio": self.portfolio.to_dict(),
            "github": self.github.to_dict(),
        }


# ---------------------------------------------------------------------------
# Text utilities (uses shared STOPWORDS from config)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    return [w for w in re.split(r"\W+", text.lower()) if len(w) > 2 and w not in _STOPWORDS]


def _top_keywords(text: str, n: int = 15) -> list[str]:
    tokens = _tokenize(text)
    return [word for word, _ in Counter(tokens).most_common(n)]


# ---------------------------------------------------------------------------
# Known tech & industry patterns
# ---------------------------------------------------------------------------

_TECH_PATTERNS = {
    # Languages
    "python", "java", "javascript", "typescript", "golang", "rust", "ruby",
    "kotlin", "swift", "scala", "php", "sql", "bash", "dart",
    # Frameworks
    "react", "angular", "vue", "nextjs", "next.js", "django", "flask",
    "fastapi", "spring", "rails", "express", "nestjs", "svelte",
    "streamlit", "gradio", "langchain", "llamaindex", "crewai",
    # Cloud
    "aws", "gcp", "azure", "docker", "kubernetes", "k8s", "terraform",
    "lambda", "s3", "ec2", "sagemaker", "vertex", "bigquery",
    # Databases
    "postgres", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "dynamodb", "cassandra", "firestore", "neo4j", "supabase",
    "pinecone", "weaviate", "chromadb", "milvus", "qdrant",
    # AI/ML
    "tensorflow", "pytorch", "scikit-learn", "keras", "transformers",
    "huggingface", "openai", "gemini", "claude", "llm", "nlp", "rag",
    "embeddings", "vectordb", "agents", "machine learning", "deep learning",
    "computer vision", "opencv", "yolo",
    # DevOps
    "git", "github", "gitlab", "jenkins", "circleci", "actions",
    "prometheus", "grafana", "datadog", "nginx", "kafka",
    "rabbitmq", "celery", "airflow", "mlflow",
    # Data
    "spark", "hadoop", "dbt", "snowflake", "databricks", "pandas",
    "numpy", "matplotlib", "plotly", "tableau", "powerbi",
}

_INDUSTRY_PATTERNS = {
    "fintech": ["fintech", "financial", "banking", "payments", "trading", "crypto", "blockchain", "lending"],
    "healthtech": ["health", "healthcare", "medical", "clinical", "pharma", "biotech", "patient", "hipaa"],
    "edtech": ["education", "learning", "edtech", "students", "curriculum", "lms", "courses"],
    "e-commerce": ["e-commerce", "ecommerce", "retail", "marketplace", "shopping", "checkout", "cart"],
    "saas": ["saas", "platform", "subscription", "b2b", "enterprise", "dashboard"],
    "devtools": ["developer", "devtools", "api", "sdk", "infrastructure", "devops", "ci/cd"],
    "iot": ["iot", "sensors", "telemetry", "fleet", "connected", "devices", "hardware", "embedded"],
    "cybersecurity": ["security", "cybersecurity", "threat", "vulnerability", "encryption", "compliance"],
    "ai/ml": ["artificial intelligence", "machine learning", "deep learning", "neural", "llm", "generative ai"],
    "media": ["media", "content", "streaming", "video", "entertainment", "publishing"],
    "logistics": ["logistics", "supply chain", "shipping", "delivery", "warehouse", "fulfillment"],
    "hr/recruiting": ["recruiting", "hiring", "talent", "hr", "human resources", "applicant", "candidate"],
    "marketing": ["marketing", "advertising", "seo", "analytics", "campaign", "engagement"],
    "climate/energy": ["climate", "energy", "sustainability", "carbon", "solar", "renewable", "cleantech"],
}

_STAGE_SIGNALS = {
    "startup": ["startup", "seed", "series a", "early-stage", "founding", "pre-seed", "mvp", "small team"],
    "growth": ["series b", "series c", "scale", "growing", "rapid", "expanding", "hypergrowth"],
    "enterprise": ["fortune 500", "enterprise", "global", "10,000", "publicly traded", "ipo", "nasdaq", "nyse"],
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

# _fetch_page_text is imported from config.py with retry support


def _fetch_github_repos(username: str) -> list[dict]:
    """Fetch public repos from the GitHub API with retry support."""
    if not username:
        return []
    try:
        api_url = f"https://api.github.com/users/{username}/repos?sort=updated&per_page=30"
        raw = fetch_with_retry(
            api_url,
            headers={
                "User-Agent": "CareerCopilot/1.0",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=15,
            max_retries=2,
        )
        repos = json.loads(raw.decode("utf-8"))
        result = []
        for repo in repos:
            if repo.get("fork"):
                continue
            result.append({
                "name": repo.get("name", ""),
                "description": repo.get("description") or "",
                "language": repo.get("language") or "",
                "stars": repo.get("stargazers_count", 0),
                "url": repo.get("html_url", ""),
                "topics": repo.get("topics", []),
                "updated_at": repo.get("updated_at", ""),
            })
        return result
    except Exception as exc:
        logger.warning("Failed to fetch GitHub repos for %s: %s", username, exc)
        return []


# ---------------------------------------------------------------------------
# Company Intelligence Engine
# ---------------------------------------------------------------------------

def _extract_domain_from_url(url: str) -> str:
    """Extract the company domain from a job URL."""
    parsed = urlparse(url)
    host = parsed.hostname or ""

    # Strip common job board prefixes
    for prefix in ("boards.", "jobs.", "careers.", "job-boards.", "apply."):
        if host.startswith(prefix):
            host = host[len(prefix):]

    # Strip known ATS domains
    ats_domains = {"greenhouse.io", "lever.co", "myworkdayjobs.com", "ashbyhq.com",
                   "linkedin.com", "indeed.com", "glassdoor.com"}
    for ats in ats_domains:
        if host.endswith(ats):
            # Try to get company from path
            parts = parsed.path.strip("/").split("/")
            if parts and parts[0]:
                return f"{parts[0]}.com"  # best guess
            return ""

    # Identify job boards/aggregators that are not actual company domains
    job_board_domains = {"jobicy.com", "remotive.com", "remotive.io", "remoteok.com", "remoteok.io"}
    for board in job_board_domains:
        if host.endswith(board):
            return ""  # force fallback to guessing domain from the company name

    return host


def _detect_tech_stack(text: str) -> list[str]:
    """Extract recognized tech terms from text."""
    text_lower = text.lower()
    found: list[str] = []
    for tech in sorted(_TECH_PATTERNS):
        if tech in text_lower:
            found.append(tech)
    return found


def _detect_industry(text: str) -> str:
    """Detect the most likely industry from text."""
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for industry, signals in _INDUSTRY_PATTERNS.items():
        score = sum(1 for s in signals if s in text_lower)
        if score > 0:
            scores[industry] = score
    if not scores:
        return "Technology"
    return max(scores, key=lambda k: scores[k])


def _detect_stage(text: str) -> str:
    """Detect company stage from text."""
    text_lower = text.lower()
    for stage, signals in _STAGE_SIGNALS.items():
        if any(s in text_lower for s in signals):
            return stage
    return "growth"  # default


def _extract_products(text: str, company: str) -> list[str]:
    """Extract likely product/service names from text."""
    products: list[str] = []

    # Look for patterns like "our X platform", "the Y product", "Company's Z"
    patterns = [
        rf"{re.escape(company)}'?s?\s+(\w[\w\s]{{2,25}}?)(?:\s+(?:platform|product|service|tool|solution|system|engine|suite))",
        r"(?:our|the)\s+(\w[\w\s]{2,20}?)\s+(?:platform|product|service|tool|solution|system|engine|suite)",
        r"(?:build|develop|maintain|scale)\s+(?:our|the)\s+(\w[\w\s]{2,20}?)(?:\s|,|\.)",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            product = match.group(1).strip()
            # Filter noise
            if len(product) > 3 and product.lower() not in _STOPWORDS:
                clean = product.strip().title()
                if clean not in products:
                    products.append(clean)

    return products[:6]


def _extract_problem_domains(text: str) -> list[str]:
    """Extract what problems the company is solving."""
    domains: list[str] = []
    patterns = [
        r"(?:we|our team)\s+(?:help|enable|empower|solve|tackle|address)\s+(.{10,60}?)(?:\.|,|;)",
        r"(?:mission|goal|vision)\s+(?:is|to)\s+(.{10,60}?)(?:\.|,|;)",
        r"(?:focused on|specializing in|dedicated to)\s+(.{10,60}?)(?:\.|,|;)",
        r"(?:challenge|problem|opportunity)\s+(?:of|in|around)\s+(.{10,60}?)(?:\.|,|;)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            domain = match.group(1).strip()
            if len(domain) > 10 and domain not in domains:
                domains.append(domain)

    return domains[:5]


def _extract_mission(text: str, company: str) -> str:
    """Extract a mission statement from text."""
    patterns = [
        rf"{re.escape(company)}\s+(?:is|are)\s+(.{{15,120}}?)(?:\.|!)",
        r"(?:our mission|we believe|our goal)\s+(?:is)?\s*(.{15,120}?)(?:\.|!)",
        r"(?:we are|we're)\s+(?:a|an|the)\s+(.{15,120}?)(?:\.|!)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def analyze_company(company: str, job_url: str, description: str) -> CompanyIntel:
    """Analyze a target company from its website and job description.

    Fetches the company homepage and about page, then cross-references
    with the job description to build a comprehensive intelligence profile.
    """
    intel = CompanyIntel(name=company)

    # Determine company domain
    domain = _extract_domain_from_url(job_url)
    if not domain:
        # Guess from company name
        safe_name = re.sub(r"[^a-zA-Z0-9]", "", company.lower())
        domain = f"{safe_name}.com"
    intel.domain = domain

    # Fetch company pages
    homepage_text = ""
    about_text = ""
    base_url = f"https://{domain}"

    homepage_text = _fetch_page_text(base_url)
    intel.raw_homepage_text = homepage_text

    # Try common about page paths — but ONLY when the domain responded at all.
    # When the homepage fetch failed (dead/blocked domain), the about pages on
    # the SAME domain will fail identically; attempting them multiplies digest
    # latency (~15s timeout x 2 retries per attempt = minutes per dead company).
    if homepage_text:
        for about_path in ("/about", "/about-us", "/company", "/about/"):
            about_text = _fetch_page_text(f"{base_url}{about_path}")
            if len(about_text) > 200:
                intel.raw_about_text = about_text
                break

    # Combine all text sources for analysis
    combined = f"{homepage_text} {about_text} {description}"

    # Extract intelligence
    intel.mission = _extract_mission(combined, company)
    if not intel.mission:
        # Fall back to first meaningful sentence from about page or description
        for text_source in [about_text, homepage_text, description]:
            sentences = re.split(r"[.!?]", text_source)
            for sent in sentences:
                sent = sent.strip()
                if len(sent) > 30 and company.lower() in sent.lower():
                    intel.mission = sent[:150]
                    break
            if intel.mission:
                break

    intel.products = _extract_products(combined, company)
    intel.tech_stack = _detect_tech_stack(combined)
    intel.problem_domains = _extract_problem_domains(combined)
    intel.industry = _detect_industry(combined)
    intel.company_stage = _detect_stage(combined)

    # Recent focus — derived from job description specifics
    jd_keywords = _top_keywords(description, n=10)
    jd_tech = _detect_tech_stack(description)
    if jd_tech:
        intel.recent_focus = (
            f"Currently hiring for {jd_tech[0]}-focused roles. "
            f"Key areas: {', '.join(jd_keywords[:5])}."
        )
    elif jd_keywords:
        intel.recent_focus = f"Active hiring in areas related to: {', '.join(jd_keywords[:5])}."

    return intel


# ---------------------------------------------------------------------------
# Strategic Project Suggester
# ---------------------------------------------------------------------------

_PROJECT_TEMPLATES = [
    {
        "trigger_industries": ["iot", "logistics"],
        "name_template": "RealTimePulse — {domain} Telemetry Dashboard",
        "build_template": "Stream mock {domain} sensor data through a pipeline → process and aggregate → display on a live dashboard with WebSocket updates.",
        "difficulty": "1-week",
    },
    {
        "trigger_industries": ["ai/ml", "devtools"],
        "name_template": "SmartAgent — {domain} AI Workflow",
        "build_template": "Build a multi-agent system that automates a core {domain} workflow: intake → analysis → action → reporting.",
        "difficulty": "1-week",
    },
    {
        "trigger_industries": ["fintech", "e-commerce"],
        "name_template": "FlowTrack — {domain} Transaction Pipeline",
        "build_template": "Build a transaction processing pipeline with real-time fraud detection scoring, event streaming, and a monitoring dashboard.",
        "difficulty": "2-week",
    },
    {
        "trigger_industries": ["healthtech", "cybersecurity"],
        "name_template": "SecureVault — {domain} Compliance Engine",
        "build_template": "Build a data handling system with encryption at rest, audit logging, access controls, and compliance reporting for {domain}.",
        "difficulty": "2-week",
    },
    {
        "trigger_industries": ["saas", "hr/recruiting", "marketing"],
        "name_template": "InsightBoard — {domain} Analytics Dashboard",
        "build_template": "Build a full-stack analytics dashboard with data ingestion, aggregation pipelines, and interactive visualizations for {domain} metrics.",
        "difficulty": "1-week",
    },
    {
        "trigger_industries": ["media", "edtech"],
        "name_template": "ContentFlow — {domain} Content Pipeline",
        "build_template": "Build a content management and delivery pipeline with search, recommendations, and user engagement tracking for {domain}.",
        "difficulty": "1-week",
    },
]

_GENERIC_PROJECT_TEMPLATES = [
    {
        "name_template": "{tech1} API with {tech2} — Aligned to {company}",
        "build_template": "Build a production-grade REST API using {tech1} with {tech2} integration, demonstrating the stack {company} uses.",
        "difficulty": "weekend",
    },
    {
        "name_template": "Data Pipeline Demo — {company} Stack",
        "build_template": "Build an ETL pipeline using {tech1} that processes sample {domain} data, stores results in {tech2}, and exposes them via an API.",
        "difficulty": "1-week",
    },
    {
        "name_template": "ML-Powered {domain} Classifier",
        "build_template": "Train a classification model on {domain}-related data, deploy it with FastAPI, and build a simple frontend to demo predictions.",
        "difficulty": "1-week",
    },
]


def suggest_company_aligned_projects(
    intel: CompanyIntel,
    title: str,
    description: str,
    resume_text: str,
) -> list[ProjectSuggestion]:
    """Suggest portfolio projects that align with what the company is building."""
    suggestions: list[ProjectSuggestion] = []
    industry_lower = intel.industry.lower()
    company_tech = intel.tech_stack[:5] if intel.tech_stack else ["python", "apis"]
    resume_tokens = set(_tokenize(resume_text))

    # Find matching industry templates
    for template in _PROJECT_TEMPLATES:
        if any(ind in industry_lower for ind in template["trigger_industries"]):
            domain = intel.industry.replace("/", " & ")
            products_str = intel.products[0] if intel.products else intel.industry

            suggestion = ProjectSuggestion(
                name=template["name_template"].format(domain=domain),
                what_to_build=template["build_template"].format(domain=domain),
                why_relevant=f"Maps directly to {intel.name}'s work in {intel.industry}."
                             + (f" Specifically aligned with their {products_str} product." if intel.products else ""),
                tech_stack=company_tech[:4],
                difficulty=template["difficulty"],
                interview_frame=(
                    f"I built this to explore {domain} systems, "
                    f"which is core to what {intel.name} does"
                    + (f" with {products_str}." if intel.products else ".")
                ),
            )
            suggestions.append(suggestion)

    # Add generic templates with company-specific filling
    for template in _GENERIC_PROJECT_TEMPLATES:
        if len(suggestions) >= 5:
            break
        tech1 = company_tech[0] if company_tech else "python"
        tech2 = company_tech[1] if len(company_tech) > 1 else "postgresql"
        domain = intel.industry or "software"

        suggestion = ProjectSuggestion(
            name=template["name_template"].format(
                tech1=tech1.title(), tech2=tech2.title(),
                company=intel.name, domain=domain
            ),
            what_to_build=template["build_template"].format(
                tech1=tech1, tech2=tech2,
                company=intel.name, domain=domain
            ),
            why_relevant=f"Demonstrates proficiency in {intel.name}'s tech stack ({', '.join(company_tech[:3])}).",
            tech_stack=[tech1, tech2] + company_tech[2:4],
            difficulty=template["difficulty"],
            interview_frame=(
                f"I built this using {tech1} and {tech2} to demonstrate my ability to work "
                f"with the same stack {intel.name} uses in production."
            ),
        )
        suggestions.append(suggestion)

    # Skill gap project — find what's in the JD but not in the resume
    jd_tech = _detect_tech_stack(description)
    missing_tech = [t for t in jd_tech if t.lower() not in resume_tokens]
    if missing_tech:
        gap_tech = missing_tech[:3]
        suggestions.append(ProjectSuggestion(
            name=f"SkillBridge — Learning {', '.join(t.title() for t in gap_tech)}",
            what_to_build=(
                f"Build a focused project using {', '.join(gap_tech)} to close the skill gap "
                f"for the {title} role. Start with a tutorial, then extend with a real use case."
            ),
            why_relevant=(
                f"Your resume doesn't currently mention {', '.join(gap_tech)}, "
                f"but {intel.name}'s job requires them. This project fills that gap visibly."
            ),
            tech_stack=gap_tech,
            difficulty="weekend" if len(gap_tech) <= 2 else "1-week",
            interview_frame=(
                f"I noticed {intel.name}'s stack includes {gap_tech[0]}, so I built this "
                f"project to get hands-on experience with it before applying."
            ),
        ))

    return suggestions[:5]


# ---------------------------------------------------------------------------
# LinkedIn Optimizer
# ---------------------------------------------------------------------------

def optimize_linkedin(
    intel: CompanyIntel,
    title: str,
    description: str,
    resume_text: str,
) -> LinkedInOptimization:
    """Generate LinkedIn profile optimization suggestions."""
    opt = LinkedInOptimization()

    company_tech = intel.tech_stack[:4] if intel.tech_stack else ["Python", "APIs"]
    industry = intel.industry or "Technology"
    candidate_name = os.environ.get("RESUME_NAME", "")
    jd_keywords = _top_keywords(description, n=8)

    # --- Headline (max 120 chars) ---
    tech_str = " & ".join(t.title() for t in company_tech[:2])
    domain_str = intel.problem_domains[0][:30] if intel.problem_domains else industry
    headline = f"{tech_str} Engineer | {domain_str} | Building systems that scale"
    if len(headline) > 120:
        headline = f"{tech_str} Engineer | {industry} | Systems that scale"
    opt.headline = headline[:120]

    # --- About section (3 paragraphs) ---
    resume_highlights = []
    for line in resume_text.splitlines():
        line = line.strip()
        if len(line) > 40 and any(t in line.lower() for t in company_tech[:3]):
            resume_highlights.append(line)
    top_highlights = resume_highlights[:2] if resume_highlights else ["building production systems", "delivering measurable impact"]

    para1 = (
        f"I'm an engineer focused on {', '.join(company_tech[:3])} with a track record of "
        f"shipping production systems in {industry.lower()} and adjacent domains. "
        f"I care about writing clean, tested code that solves real problems."
    )
    para2 = (
        f"My recent work spans {', '.join(jd_keywords[:4])} — from designing backend architectures "
        f"to building end-to-end data pipelines. I'm drawn to teams that value ownership, "
        f"fast iteration, and direct user impact."
    )
    para3 = (
        f"Currently exploring roles in {industry.lower()} where I can combine my engineering "
        f"background with my interest in {', '.join(intel.problem_domains[:2]) if intel.problem_domains else 'solving meaningful problems'}. "
        f"Open to connecting — always happy to discuss {company_tech[0]} and {industry.lower()}."
    )
    opt.about_section = f"{para1}\n\n{para2}\n\n{para3}"

    # --- Experience bullets ---
    opt.experience_bullets = [
        f"Designed and shipped {company_tech[0]}-based systems handling production workloads, "
        f"aligned with the demands of {industry.lower()} environments.",
        f"Built data pipelines and APIs using {', '.join(company_tech[:3])}, "
        f"reducing manual effort and improving reliability for downstream consumers.",
        f"Collaborated cross-functionally to scope, implement, and iterate on features "
        f"that directly impacted user-facing metrics in {industry.lower()} products.",
    ]

    # --- Featured suggestions ---
    opt.featured_suggestions = [
        f"Pin your most relevant portfolio project that demonstrates {', '.join(company_tech[:2])}.",
        f"Share a post or article about a technical challenge you solved in {industry.lower()}.",
        f"Feature your career copilot project as a demonstration of agentic AI systems.",
    ]

    # --- Skills to add ---
    all_skills = list(dict.fromkeys(company_tech + jd_keywords[:6]))
    opt.skills_to_add = [s.title() for s in all_skills[:10]]

    # --- Connection note ---
    opt.connection_note = (
        f"Hi, I came across the {title} role at {intel.name} and was excited by "
        f"your work in {intel.problem_domains[0] if intel.problem_domains else industry.lower()}. "
        f"I've been building {company_tech[0]}-based systems and would love to learn more "
        f"about the team's technical challenges. Would you be open to a quick chat?"
    )

    return opt


# ---------------------------------------------------------------------------
# Portfolio Optimizer
# ---------------------------------------------------------------------------

def optimize_portfolio(
    intel: CompanyIntel,
    title: str,
    description: str,
    resume_text: str,
) -> PortfolioOptimization:
    """Generate portfolio website optimization suggestions."""
    opt = PortfolioOptimization()

    company_tech = intel.tech_stack[:4] if intel.tech_stack else ["Python", "APIs"]
    industry = intel.industry or "Technology"
    domain_focus = intel.problem_domains[0] if intel.problem_domains else industry.lower()

    # --- Hero section ---
    opt.hero_tagline = f"I build {company_tech[0].title()} systems that solve real problems"
    opt.hero_subtitle = (
        f"Engineer with production experience in {', '.join(t.title() for t in company_tech[:3])} — "
        f"focused on {domain_focus.lower() if isinstance(domain_focus, str) else 'impactful software'}."
    )

    # --- Project card updates ---
    opt.project_card_updates = [
        {
            "project": "Career Copilot",
            "updated_description": (
                f"Multi-agent AI system with job scouting, resume tailoring, "
                f"and notification workflows — demonstrates {', '.join(company_tech[:2])} and agentic AI."
            ),
            "tags_to_highlight": ["Python", "AI Agents", "Automation"] + [t.title() for t in company_tech[:2]],
        },
        {
            "project": "Most relevant portfolio project",
            "updated_description": (
                f"Reframe this project's description to emphasize its connection to "
                f"{intel.industry}: mention {', '.join(company_tech[:2])} prominently, "
                f"add metrics (latency, throughput, users), and link it to {domain_focus}."
            ),
            "tags_to_highlight": [t.title() for t in company_tech[:3]],
        },
    ]

    # --- Case study ---
    opt.case_study_project = "Career Copilot (or most complex project)"
    opt.case_study_angle = (
        f"Frame as: 'How I built an AI-powered pipeline to automate {domain_focus}' — "
        f"emphasize the technical decisions ({', '.join(company_tech[:3])}), "
        f"the architecture (multi-agent, async), and measurable outcomes. "
        f"This resonates with {intel.name}'s focus on {industry.lower()}."
    )

    # --- Tech badges ---
    all_tech = list(dict.fromkeys(company_tech + ["python", "fastapi", "react"]))
    opt.tech_badges_order = [t.title() for t in all_tech[:8]]

    # --- CTA ---
    opt.cta_text = (
        f"Interested in {industry.lower()} engineering? "
        f"Let's build something together → [Contact / LinkedIn]"
    )

    return opt


# ---------------------------------------------------------------------------
# GitHub Optimizer
# ---------------------------------------------------------------------------

def optimize_github(
    intel: CompanyIntel,
    title: str,
    description: str,
    resume_text: str,
) -> GitHubOptimization:
    """Generate GitHub profile optimization suggestions."""
    opt = GitHubOptimization()

    company_tech = intel.tech_stack[:4] if intel.tech_stack else ["python", "apis"]
    industry = intel.industry or "Technology"
    github_username = os.environ.get("GITHUB_USERNAME", "")
    if not github_username:
        # Try to extract from RESUME_GITHUB
        github_url = os.environ.get("RESUME_GITHUB", "")
        if github_url:
            parts = github_url.rstrip("/").split("/")
            github_username = parts[-1] if parts else ""

    # --- Bio ---
    opt.bio = (
        f"{company_tech[0].title()}/{company_tech[1].title() if len(company_tech) > 1 else 'ML'} "
        f"Engineer → {industry.lower()} & production systems"
    )

    # --- Fetch real repos ---
    repos = _fetch_github_repos(github_username)

    if repos:
        # Score repos by relevance to the role
        jd_tokens = set(_tokenize(f"{title} {description}"))
        scored_repos: list[tuple[int, dict]] = []
        for repo in repos:
            repo_text = f"{repo['name']} {repo['description']} {repo['language']} {' '.join(repo.get('topics', []))}"
            repo_tokens = set(_tokenize(repo_text))
            score = len(jd_tokens & repo_tokens)
            # Boost for matching language
            if repo["language"] and repo["language"].lower() in [t.lower() for t in company_tech]:
                score += 3
            # Boost for recent activity
            if repo.get("stars", 0) > 0:
                score += 1
            scored_repos.append((score, repo))

        scored_repos.sort(key=lambda x: x[0], reverse=True)

        # Top 6 to pin
        for score, repo in scored_repos[:6]:
            opt.repos_to_pin.append({
                "name": repo["name"],
                "description": repo["description"],
                "relevance_score": score,
                "language": repo["language"],
                "url": repo["url"],
                "reason": f"Relevant to {title} role" if score > 2 else "Shows active development",
            })

        # README improvements for top 3
        for score, repo in scored_repos[:3]:
            improvements = []
            if not repo["description"]:
                improvements.append(f"Add a description mentioning {', '.join(company_tech[:2])}")
            improvements.append(
                f"Add a 'Built With' section listing {', '.join(company_tech[:3])}"
            )
            improvements.append(
                f"Add a 'Why I Built This' section connecting it to {industry.lower()} problems"
            )
            improvements.append("Add screenshots or a demo GIF to the README")
            if not repo.get("topics"):
                improvements.append(
                    f"Add topics: {', '.join(company_tech[:4])}"
                )
            opt.readme_improvements.append({
                "repo": repo["name"],
                "url": repo["url"],
                "improvements": improvements,
            })
    else:
        # No repos fetched — provide generic advice
        opt.repos_to_pin = [
            {"name": "career-copilot", "reason": "Demonstrates agentic AI and automation"},
            {"name": "portfolio", "reason": "Shows full-stack capability"},
        ]

    # --- New repo ideas ---
    company_domain = intel.problem_domains[0] if intel.problem_domains else industry.lower()
    opt.new_repo_ideas = [
        {
            "name": f"{company_tech[0]}-{intel.industry.lower().replace('/', '-').replace(' ', '-')}-demo",
            "description": (
                f"A focused demo using {company_tech[0]} for {company_domain}. "
                f"Small, clean, well-documented — shows you can work in {intel.name}'s problem space."
            ),
            "tech_stack": company_tech[:3],
            "effort": "weekend",
        },
    ]
    if len(company_tech) > 1:
        opt.new_repo_ideas.append({
            "name": f"{company_tech[0]}-{company_tech[1]}-starter",
            "description": (
                f"A starter template combining {company_tech[0]} and {company_tech[1]} — "
                f"the core stack {intel.name} uses. Add tests, CI, and docs."
            ),
            "tech_stack": company_tech[:2],
            "effort": "weekend",
        })

    # --- Contribution suggestions ---
    opt.contribution_suggestions = [
        f"Contribute to an open-source {company_tech[0]} project in the {industry.lower()} space.",
        f"Open issues or PRs in tools {intel.name} likely uses ({', '.join(company_tech[:3])}).",
        "Add GitHub Actions CI to your top repos to show DevOps awareness.",
        "Write clear commit messages and use PRs even in personal repos to show collaboration habits.",
    ]

    return opt


# ---------------------------------------------------------------------------
# Full Profile Optimization Pipeline
# ---------------------------------------------------------------------------

def generate_full_profile_optimization(
    title: str,
    company: str,
    description: str,
    job_url: str,
    resume_text: str,
) -> ProfileOptimizationReport:
    """Run the complete profile optimization pipeline.

    1. Analyze the company
    2. Suggest strategic projects
    3. Optimize LinkedIn
    4. Optimize portfolio
    5. Optimize GitHub

    Returns a comprehensive ProfileOptimizationReport.
    """
    # Step 1: Company Intelligence
    intel = analyze_company(company, job_url, description)

    # Step 2: Strategic Projects
    projects = suggest_company_aligned_projects(intel, title, description, resume_text)

    # Step 3: LinkedIn
    linkedin = optimize_linkedin(intel, title, description, resume_text)

    # Step 4: Portfolio
    portfolio = optimize_portfolio(intel, title, description, resume_text)

    # Step 5: GitHub
    github = optimize_github(intel, title, description, resume_text)

    return ProfileOptimizationReport(
        company_intel=intel,
        project_suggestions=projects,
        linkedin=linkedin,
        portfolio=portfolio,
        github=github,
    )


def format_optimization_report(report: ProfileOptimizationReport) -> str:
    """Format a ProfileOptimizationReport as a human-readable string."""
    lines: list[str] = []
    sep = "=" * 55

    # Company Intel
    lines.append(f"\n{sep}")
    lines.append(f" COMPANY INTELLIGENCE: {report.company_intel.name}")
    lines.append(sep)
    lines.append(report.company_intel.summary())

    # Project Suggestions
    lines.append(f"\n{sep}")
    lines.append(" STRATEGIC PROJECT SUGGESTIONS")
    lines.append(sep)
    for i, proj in enumerate(report.project_suggestions, 1):
        lines.append(f"\n  {i}. {proj.name}")
        lines.append(f"     Build: {proj.what_to_build}")
        lines.append(f"     Why: {proj.why_relevant}")
        lines.append(f"     Stack: {', '.join(proj.tech_stack)}")
        lines.append(f"     Effort: {proj.difficulty}")
        lines.append(f"     Interview frame: \"{proj.interview_frame}\"")

    # LinkedIn
    lines.append(f"\n{sep}")
    lines.append(" LINKEDIN OPTIMIZATION")
    lines.append(sep)
    lines.append(f"  Headline: {report.linkedin.headline}")
    lines.append(f"\n  About:\n{report.linkedin.about_section}")
    lines.append(f"\n  Experience bullets:")
    for bullet in report.linkedin.experience_bullets:
        lines.append(f"    • {bullet}")
    lines.append(f"\n  Featured:")
    for feat in report.linkedin.featured_suggestions:
        lines.append(f"    • {feat}")
    lines.append(f"\n  Skills: {', '.join(report.linkedin.skills_to_add)}")
    lines.append(f"\n  Connection note:\n    {report.linkedin.connection_note}")

    # Portfolio
    lines.append(f"\n{sep}")
    lines.append(" PORTFOLIO OPTIMIZATION")
    lines.append(sep)
    lines.append(f"  Hero tagline: {report.portfolio.hero_tagline}")
    lines.append(f"  Hero subtitle: {report.portfolio.hero_subtitle}")
    for card in report.portfolio.project_card_updates:
        lines.append(f"\n  Project: {card['project']}")
        lines.append(f"    Update: {card['updated_description']}")
        lines.append(f"    Tags: {', '.join(card.get('tags_to_highlight', []))}")
    lines.append(f"\n  Case study: {report.portfolio.case_study_project}")
    lines.append(f"    Angle: {report.portfolio.case_study_angle}")
    lines.append(f"  Tech badges: {', '.join(report.portfolio.tech_badges_order)}")
    lines.append(f"  CTA: {report.portfolio.cta_text}")

    # GitHub
    lines.append(f"\n{sep}")
    lines.append(" GITHUB OPTIMIZATION")
    lines.append(sep)
    lines.append(f"  Bio: {report.github.bio}")
    lines.append(f"\n  Repos to pin:")
    for repo in report.github.repos_to_pin:
        name = repo.get("name", "unknown")
        reason = repo.get("reason", "")
        lines.append(f"    • {name} — {reason}")
    if report.github.readme_improvements:
        lines.append(f"\n  README improvements:")
        for item in report.github.readme_improvements:
            lines.append(f"    {item['repo']}:")
            for imp in item.get("improvements", []):
                lines.append(f"      - {imp}")
    if report.github.new_repo_ideas:
        lines.append(f"\n  New repo ideas:")
        for idea in report.github.new_repo_ideas:
            lines.append(f"    • {idea['name']}: {idea['description']}")
    lines.append(f"\n  Contribution suggestions:")
    for sug in report.github.contribution_suggestions:
        lines.append(f"    • {sug}")

    return "\n".join(lines)
