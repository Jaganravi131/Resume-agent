"""Career Copilot package.

Anti-short-circuit note: importing the package must NOT hard-require the ADK
agent layer. Tool/workflow/eval modules stay usable when google-adk is missing
(tests, evals, CLI tools); ``root_agent`` is simply None in that case.
"""

from .config import load_env

# Ensure .env is loaded before any other module accesses os.environ
load_env()

try:
    from . import agent
    from .agent import root_agent
except ImportError as _exc:  # pragma: no cover - depends on optional google-adk
    import logging as _logging
    _logging.getLogger("career_copilot").warning(
        "ADK agent layer unavailable (%s). Tool/workflow layers still work; "
        "root_agent is None until google-adk is installed.", _exc,
    )
    agent = None
    root_agent = None

from .workflow import run_daily_cycle, run_browser_application, run_profile_optimization
from .resume_evaluator import (
    sanitize_resume_text,
    evaluate_resume_quality,
    evaluate_and_optimize,
    validate_pdf_output,
    check_anti_hallucination_guardrail,
)

__all__ = [
    "agent",
    "root_agent",
    "run_daily_cycle",
    "run_browser_application",
    "run_profile_optimization",
    "sanitize_resume_text",
    "evaluate_resume_quality",
    "evaluate_and_optimize",
    "validate_pdf_output",
    "check_anti_hallucination_guardrail",
]
