"""Advanced relevance scoring with TF-IDF, skill categories, and experience filtering.

Replaces the basic keyword-counting scorer with a multi-signal engine that
evaluates job-resume fit across several dimensions.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field

from .config import STOPWORDS


# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

def _get_min_match() -> int:
    try:
        return int(os.environ.get("MIN_MATCH_PERCENTAGE", "40"))
    except (ValueError, TypeError):
        return 40


def _get_experience_level() -> str:
    return os.environ.get("EXPERIENCE_LEVEL", "mid").lower().strip()


def _get_exclude_keywords() -> list[str]:
    raw = os.environ.get("EXCLUDE_KEYWORDS", "")
    return [kw.strip().lower() for kw in raw.split(",") if kw.strip()]


# ---------------------------------------------------------------------------
# Skill categories
# ---------------------------------------------------------------------------

SKILL_CATEGORIES: dict[str, set[str]] = {
    "languages": {
        "python", "java", "javascript", "typescript", "golang", "rust", "ruby",
        "kotlin", "swift", "scala", "php", "csharp", "cpp", "sql", "bash",
        "dart", "lua", "perl", "elixir", "haskell", "clojure",
    },
    "frameworks": {
        "react", "angular", "vue", "nextjs", "django", "flask", "fastapi",
        "spring", "rails", "express", "nestjs", "svelte", "nuxt", "remix",
        "streamlit", "gradio", "langchain", "llamaindex", "crewai",
    },
    "cloud": {
        "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ansible",
        "cloudformation", "lambda", "fargate", "ecs", "eks", "s3", "ec2",
        "bigquery", "dataflow", "pubsub", "sagemaker", "vertex",
    },
    "databases": {
        "postgres", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
        "dynamodb", "cassandra", "sqlite", "firestore", "neo4j", "supabase",
        "pinecone", "weaviate", "chromadb", "milvus", "qdrant",
    },
    "ai_ml": {
        "tensorflow", "pytorch", "scikit", "sklearn", "keras", "transformers",
        "huggingface", "openai", "gemini", "claude", "llm", "nlp", "rag",
        "finetuning", "embeddings", "vectordb", "agents", "agentic",
        "machine", "learning", "deep", "neural", "model", "training",
    },
    "devops_tools": {
        "git", "github", "gitlab", "jenkins", "circleci", "actions",
        "prometheus", "grafana", "datadog", "splunk", "nginx", "kafka",
        "rabbitmq", "celery", "airflow", "mlflow",
    },
    "soft_skills": {
        "communication", "leadership", "collaboration", "teamwork",
        "mentoring", "agile", "scrum", "kanban", "stakeholder",
        "cross-functional", "problem-solving", "ownership",
    },
}

# Flatten for quick lookups
_ALL_SKILLS: set[str] = set()
for _cat_skills in SKILL_CATEGORIES.values():
    _ALL_SKILLS.update(_cat_skills)


# ---------------------------------------------------------------------------
# Experience level mapping
# ---------------------------------------------------------------------------

SENIORITY_SIGNALS: dict[str, list[str]] = {
    "intern": [r"\bintern\b", r"\binternship\b", r"\btrainee\b", r"\bapprentice\b", r"\bco-op\b"],
    "junior": [r"\bjunior\b", r"\bjr\b", r"\bentry-level\b", r"\bentry level\b", r"\bassociate\b", r"\bgraduate\b", r"\bnew grad\b"],
    "fresher": [r"\bfresher\b", r"\bfresh graduate\b", r"\b0-1 years?\b", r"\b0 years?\b"],
    "mid": [r"\bmid-level\b", r"\bmid level\b", r"\bintermediate\b", r"\b2\+ years?\b", r"\b3\+ years?\b", r"\b4\+ years?\b"],
    "senior": [r"\bsenior\b", r"\bsr\b", r"\b5\+ years?\b", r"\b6\+ years?\b", r"\b7\+ years?\b", r"\b8\+ years?\b", r"\bexperienced\b"],
    "lead": [r"\blead\b", r"\bprincipal\b", r"\bstaff\b", r"\b9\+ years?\b", r"\b10\+ years?\b", r"\b12\+ years?\b", r"\b15\+ years?\b"],
    "director": [r"\bdirector\b", r"\bvp\b", r"\bvice president\b", r"\bhead of\b", r"\bcto\b", r"\bcio\b", r"\bchief\b"],
}

LEVEL_ORDER = ["intern", "fresher", "junior", "mid", "senior", "lead", "director"]


def _detect_experience_level(text: str) -> str:
    """Detect the most likely seniority level from text using word-boundary matching."""
    text_lower = text.lower()
    scores: dict[str, int] = {level: 0 for level in LEVEL_ORDER}

    for level, patterns in SENIORITY_SIGNALS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                scores[level] += 1

    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "mid"  # default assumption
    return best


def _experience_compatible(job_level: str, target_level: str, tolerance: int = 1) -> bool:
    """Check if a job's seniority is within tolerance of the target level."""
    if job_level not in LEVEL_ORDER or target_level not in LEVEL_ORDER:
        return True  # can't determine, allow it

    job_idx = LEVEL_ORDER.index(job_level)
    target_idx = LEVEL_ORDER.index(target_level)
    return abs(job_idx - target_idx) <= tolerance


# ---------------------------------------------------------------------------
# Text processing
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens, filtering short words and stopwords."""
    return [w for w in re.split(r"\W+", text.lower()) if len(w) > 2 and w not in STOPWORDS]


def _extract_bigrams(tokens: list[str]) -> list[str]:
    """Extract relevant bigrams from token list."""
    return [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)]


# ---------------------------------------------------------------------------
# TF-IDF scoring
# ---------------------------------------------------------------------------

def _compute_tf(tokens: list[str]) -> dict[str, float]:
    """Compute term frequency for a token list."""
    counts = Counter(tokens)
    total = len(tokens) if tokens else 1
    return {term: count / total for term, count in counts.items()}


def _compute_idf(term: str, all_documents: list[list[str]]) -> float:
    """Compute inverse document frequency for a term across documents."""
    if not all_documents:
        return 1.0
    doc_count = sum(1 for doc in all_documents if term in doc)
    if doc_count == 0:
        return 1.0
    return math.log(len(all_documents) / doc_count) + 1


def _tfidf_score(job_tokens: list[str], resume_tokens: list[str],
                 all_job_token_sets: list[list[str]]) -> tuple[float, list[tuple[str, float]]]:
    """Compute TF-IDF weighted match score between job and resume.

    Returns (normalized_score, [(term, contribution), ...]).
    """
    job_tf = _compute_tf(job_tokens)
    resume_set = set(resume_tokens)

    term_scores: list[tuple[str, float]] = []
    total_weight = 0.0
    match_weight = 0.0

    for term, tf in job_tf.items():
        idf = _compute_idf(term, all_job_token_sets)
        weight = tf * idf
        total_weight += weight

        if term in resume_set:
            match_weight += weight
            term_scores.append((term, weight))

    normalized = (match_weight / total_weight * 100) if total_weight > 0 else 0
    term_scores.sort(key=lambda x: x[1], reverse=True)
    return normalized, term_scores


# ---------------------------------------------------------------------------
# Category scoring
# ---------------------------------------------------------------------------

def _score_categories(job_tokens: list[str], resume_tokens: list[str]) -> dict[str, int]:
    """Compute per-category match percentage."""
    resume_set = set(resume_tokens)
    scores: dict[str, int] = {}

    for category, skills in SKILL_CATEGORIES.items():
        job_skills = [t for t in job_tokens if t in skills]
        if not job_skills:
            continue  # category not relevant for this job

        matched = sum(1 for s in job_skills if s in resume_set)
        unique_job = len(set(job_skills))
        scores[category] = int(round((matched / unique_job) * 100)) if unique_job else 0

    return scores


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class RelevanceResult:
    """Result of a relevance scoring computation."""
    score: int = 0
    tfidf_score: float = 0.0
    category_scores: dict[str, int] = field(default_factory=dict)
    experience_level_detected: str = "mid"
    experience_match: bool = True
    top_matching_skills: list[str] = field(default_factory=list)
    top_missing_skills: list[str] = field(default_factory=list)
    rejection_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "tfidf_score": round(self.tfidf_score, 1),
            "category_scores": self.category_scores,
            "experience_level_detected": self.experience_level_detected,
            "experience_match": self.experience_match,
            "top_matching_skills": self.top_matching_skills,
            "top_missing_skills": self.top_missing_skills,
            "rejection_reason": self.rejection_reason,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_relevance_score(
    title: str,
    description: str,
    resume_text: str,
    all_job_descriptions: list[str] | None = None,
) -> RelevanceResult:
    """Compute a multi-signal relevance score for a job against a resume.

    Tries to use Gemini for semantic agentic scoring, falling back to
    TF-IDF keyword heuristics if the API is unavailable or quota is exhausted.
    """
    result = RelevanceResult()

    # --- Negative keyword check ---
    exclude_kw = _get_exclude_keywords()
    title_lower = title.lower()
    for kw in exclude_kw:
        if kw in title_lower:
            result.rejection_reason = f"Title contains excluded keyword: '{kw}'"
            result.score = 0
            return result

    # --- Experience level check ---
    target_level = _get_experience_level()
    job_text = f"{title} {description}"
    detected_level = _detect_experience_level(job_text)
    result.experience_level_detected = detected_level
    result.experience_match = _experience_compatible(detected_level, target_level)

    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        try:
            import json
            from google import genai
            from google.genai import types
            
            client = genai.Client(api_key=api_key)
            
            prompt = (
                f"You are a Career Relevance Agent. Evaluate if the candidate is a good semantic fit for the job listing.\n\n"
                f"Candidate Resume:\n{resume_text}\n\n"
                f"Job Title: {title}\n"
                f"Job Description:\n{description}\n\n"
                f"Target candidate experience level: {target_level}\n\n"
                f"You must return a JSON object with the following fields:\n"
                f"- 'score': integer (0 to 100 representing job fit)\n"
                f"- 'experience_level_detected': string ('intern', 'fresher', 'junior', 'mid', 'senior', 'lead', or 'director')\n"
                f"- 'experience_match': boolean (true if detected level is within +/- 1 tier of target level, false otherwise)\n"
                f"- 'top_matching_skills': list of strings\n"
                f"- 'top_missing_skills': list of strings\n"
                f"- 'rejection_reason': string or null (provide a reason if experience_match is false or fit is extremely poor)\n\n"
                f"Return ONLY the raw JSON object. Do not include markdown formatting."
            )
            
            from .config import get_gemini_model
            response = client.models.generate_content(
                model=get_gemini_model(),
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            
            text = response.text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-zA-Z]*\n", "", text)
                text = re.sub(r"\n```$", "", text)
                
            data = json.loads(text.strip())
            
            # Populate results from LLM
            result.score = int(data.get("score", 0))
            result.experience_level_detected = str(data.get("experience_level_detected", detected_level))
            result.experience_match = bool(data.get("experience_match", result.experience_match))
            result.top_matching_skills = list(data.get("top_matching_skills", []))[:8]
            result.top_missing_skills = list(data.get("top_missing_skills", []))[:8]
            result.rejection_reason = data.get("rejection_reason")
            
            # If rejected by LLM, override score to 0
            if result.rejection_reason:
                result.score = 0
                
            return result
        except Exception as exc:
            # Under quota issues (like 429), fall back silently to TF-IDF
            pass

    # --- FALLBACK: TF-IDF & Keyword Heuristics ---
    if not result.experience_match:
        result.rejection_reason = (
            f"Experience mismatch: job is '{detected_level}' level, "
            f"target is '{target_level}' (tolerance: ±1 level)"
        )
        result.score = 0
        return result

    # --- Tokenize ---
    job_tokens = _tokenize(job_text)
    resume_tokens = _tokenize(resume_text)

    if not job_tokens:
        result.score = 0
        result.rejection_reason = "Job posting has no meaningful content to score."
        return result

    # --- Build IDF corpus ---
    all_job_token_sets: list[list[str]] = []
    if all_job_descriptions:
        all_job_token_sets = [_tokenize(desc) for desc in all_job_descriptions]
    if not all_job_token_sets:
        all_job_token_sets = [job_tokens]

    # --- TF-IDF score ---
    tfidf_raw, term_contributions = _tfidf_score(job_tokens, resume_tokens, all_job_token_sets)
    result.tfidf_score = tfidf_raw

    # --- Category scores ---
    result.category_scores = _score_categories(job_tokens, resume_tokens)

    # --- Identify matching and missing skills ---
    resume_set = set(resume_tokens)
    job_skills = [t for t in job_tokens if t in _ALL_SKILLS]
    unique_job_skills = list(dict.fromkeys(job_skills))  # preserve order, deduplicate

    result.top_matching_skills = [s for s in unique_job_skills if s in resume_set][:8]
    result.top_missing_skills = [s for s in unique_job_skills if s not in resume_set][:8]

    # --- Composite score ---
    category_avg = 0.0
    if result.category_scores:
        category_avg = sum(result.category_scores.values()) / len(result.category_scores)

    experience_bonus = 10 if result.experience_match else 0
    title_match_bonus = 0
    title_tokens = _tokenize(title)
    title_matches = sum(1 for t in title_tokens if t in resume_set)
    if title_tokens:
        title_match_bonus = (title_matches / len(title_tokens)) * 15

    composite = (
        tfidf_raw * 0.55
        + category_avg * 0.25
        + experience_bonus
        + title_match_bonus
    )
    result.score = max(0, min(100, int(round(composite))))

    return result


def passes_minimum_threshold(result: RelevanceResult) -> bool:
    """Check if a RelevanceResult meets the minimum match threshold."""
    if result.rejection_reason:
        return False
    return result.score >= _get_min_match()


def filter_jobs_by_relevance(
    jobs: list[dict],
    resume_text: str,
) -> tuple[list[dict], list[dict]]:
    """Filter a list of jobs by relevance score.

    Returns (passed, filtered_out) tuples.
    Each job dict gets a 'relevance' key with the RelevanceResult dict.
    """
    all_descriptions = [j.get("description", "") for j in jobs]
    passed: list[dict] = []
    filtered_out: list[dict] = []

    for job in jobs:
        result = compute_relevance_score(
            title=job.get("title", ""),
            description=job.get("description", ""),
            resume_text=resume_text,
            all_job_descriptions=all_descriptions,
        )
        job_with_relevance = dict(job)
        job_with_relevance["relevance"] = result.to_dict()
        job_with_relevance["match_percentage"] = result.score

        if passes_minimum_threshold(result):
            passed.append(job_with_relevance)
        else:
            filtered_out.append(job_with_relevance)

    # Sort passed jobs by score descending
    passed.sort(key=lambda j: j.get("match_percentage", 0), reverse=True)

    return passed, filtered_out
