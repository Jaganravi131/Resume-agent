"""Centralized configuration for Career Copilot.

Consolidates env loading, shared stopwords, retry logic, and logging setup
so that every module gets consistent behaviour from one place.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging with a consistent format."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# Auto-configure on import so all loggers emit output
setup_logging()

logger = logging.getLogger("career_copilot.config")


def get_gemini_model() -> str:
    """Return configured Gemini model name (defaulting to gemini-2.5-flash)."""
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()


# ---------------------------------------------------------------------------
# .env loader (single source of truth)
# ---------------------------------------------------------------------------

_ENV_LOADED = False


def load_env(env_path: str | Path | None = None) -> None:
    """Load environment variables from a .env file.

    Handles:
    - Quoted values:  KEY="value with spaces"
    - Inline comments: KEY=value  # comment
    - Blank lines / comment-only lines
    - Idempotent: only loads once unless *force* is True.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    if env_path is None:
        env_path = Path(__file__).resolve().parent / ".env"
    else:
        env_path = Path(env_path)

    if not env_path.exists():
        logger.warning(".env file not found at %s", env_path)
        return

    with open(env_path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()

            # Strip inline comments (but not inside quotes)
            if value and not value.startswith(('"', "'")):
                value = value.split("#", 1)[0].strip()

            # Remove surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]

            os.environ.setdefault(key, value)

    _ENV_LOADED = True
    logger.info("Loaded .env from %s", env_path)


# ---------------------------------------------------------------------------
# Shared stopwords (used by tools.py, relevance.py, profile_optimizer.py)
# ---------------------------------------------------------------------------

STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "your", "you", "are",
    "our", "into", "using", "use", "plus", "required", "experience",
    "responsibilities", "include", "build", "looking", "will", "has", "have",
    "been", "about", "what", "who", "how", "also", "can", "may", "should",
    "not", "but", "all", "any", "each", "other", "more", "than", "very",
    "just", "only", "own", "same", "some", "such", "too", "work", "working",
    "job", "role", "team", "company", "ability", "strong", "good", "great",
    "new", "part", "well", "way", "need", "must", "able", "like", "high",
    "make", "take", "help", "year", "years", "day", "time", "would", "could",
    # HTML/web noise filtered out in profile_optimizer
    "div", "class", "span", "href", "img", "src", "style", "width", "height",
    "http", "https", "www", "com", "html", "css", "padding", "margin",
})


# ---------------------------------------------------------------------------
# HTTP retry helper
# ---------------------------------------------------------------------------

def fetch_with_retry(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
    max_retries: int = 3,
    backoff: float = 1.0,
) -> bytes:
    """Fetch a URL with retries and exponential backoff.

    Returns the raw bytes of the response body.
    Raises the last exception after all retries are exhausted.
    """
    if headers is None:
        headers = {"User-Agent": "Mozilla/5.0"}

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                wait = backoff * (2 ** (attempt - 1))
                logger.warning(
                    "Fetch attempt %d/%d for %s failed: %s (retrying in %.1fs)",
                    attempt, max_retries, url, exc, wait,
                )
                time.sleep(wait)

    raise last_exc  # type: ignore[misc]


def fetch_json(url: str, **kwargs) -> object:
    """Fetch a URL and parse the response as JSON."""
    import json
    data = fetch_with_retry(url, **kwargs)
    return json.loads(data.decode("utf-8", errors="ignore"))


def fetch_page_text(url: str, max_chars: int = 15000) -> str:
    """Fetch a webpage and return its visible text content."""
    import re
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        }
        raw = fetch_with_retry(url, headers=headers, timeout=15, max_retries=2)
        html = raw.decode("utf-8", errors="ignore")

        # Strip script and style blocks, then HTML tags
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&[a-zA-Z]+;", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return ""
