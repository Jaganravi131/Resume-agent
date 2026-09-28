"""Tool-using chat bridge between Streamlit (or any UI) and the real ADK agent.

Replaces the "raw Gemini chatbot" surface: messages are routed through
``google.adk.runners.InMemoryRunner`` so the root agent can genuinely select
tools and delegate to the nine sub-agents, with per-session memory held by
ADK's InMemorySessionService.

This module never imports google.adk at module scope guarded-fail: if ADK is
unavailable (e.g. CI stubs), ``chat_reply`` degrades to a plain Gemini call via
``config.call_gemini`` so the UI keeps working offline.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Iterator

logger = logging.getLogger("career_copilot.agent_chat")

_APP_NAME = "career_copilot"
_USER_ID = "streamlit_user"
# Wall-clock cap for a single agent run. A goal that triggers the full
# daily digest (live job APIs + LLM) must not hold the UI spinner forever.
DEFAULT_RUN_TIMEOUT_S = float(os.environ.get("AGENT_CHAT_TIMEOUT_S", "240"))

_lock = threading.Lock()
_runner = None  # type: ignore[var-annotated]
_sessions: dict[str, str] = {}  # conversation key -> session_id


def _get_runner():
    """Create (once) and return the ADK InMemoryRunner wrapping root_agent."""
    global _runner
    if _runner is None:
        from google.adk.runners import InMemoryRunner

        # Imported lazily so importing this module stays cheap and CI-safe.
        from .agent import root_agent

        _runner = InMemoryRunner(agent=root_agent, app_name=_APP_NAME)
    return _runner


def _get_session_id(session_key: str) -> str:
    """Return a stable ADK session id for a conversation key, creating it once."""
    with _lock:
        if session_key not in _sessions:
            session_id = f"chat-{uuid.uuid4().hex[:12]}"
            from google.adk.sessions import InMemorySessionService

            _get_runner().session_service.create_session(
                app_name=_APP_NAME, user_id=_USER_ID, session_id=session_id
            )
            _sessions[session_key] = session_id
        return _sessions[session_key]


def reset_session(session_key: str = "default") -> None:
    """Drop the ADK session for a conversation (e.g. on a 'New chat' button)."""
    with _lock:
        _sessions.pop(session_key, None)


def chat_reply(
    user_message: str,
    session_key: str = "default",
    *,
    timeout_s: float | None = None,
) -> str:
    """Send *user_message* through the ADK root agent and return the final text.

    The agent may call tools (search_job_postings, build_daily_digest, ...)
    and delegate to sub-agents; every intermediate event is logged so tool use
    is observable in the Streamlit expander. The run is bounded by a wall-clock
    timeout (default AGENT_CHAT_TIMEOUT_S, 240s) — on timeout the caller gets
    a friendly message instead of a hanging spinner.
    """
    try:
        from google.genai import types

        session_id = _get_session_id(session_key)
        runner = _get_runner()
        content = types.Content(role="user", parts=[types.Part(text=user_message)])

        final_text: str | None = None
        events = runner.run(
            user_id=_USER_ID, session_id=session_id, new_message=content
        )
        # Bound the whole run: iterate with a deadline rather than trusting
        # every downstream tool to honor its own per-call timeouts.
        import time

        deadline = time.monotonic() + (timeout_s or DEFAULT_RUN_TIMEOUT_S)
        timed_out = False
        for event in events:
            if time.monotonic() > deadline:
                timed_out = True
                break
            # Log function calls so tool use is observable in server logs.
            for call in event.get_function_calls():
                logger.info("agent tool call: %s(%s)", call.name, call.args)
            if event.content and event.content.parts:
                texts = [p.text for p in event.content.parts if getattr(p, "text", None)]
                if texts:
                    final_text = "\n".join(t for t in texts if t.strip())

        if timed_out:
            return (
                "⏱️ The agent hit its time budget before finishing this goal "
                f"({timeout_s or DEFAULT_RUN_TIMEOUT_S:.0f}s). Partial answer below — "
                "try a narrower request (e.g. one tool at a time).\n\n"
                + (final_text or "(no partial text produced)")
            )

        if final_text is None:
            return (
                "The agent finished without producing a text answer. "
                "Try rephrasing, or ask e.g. 'Search for Python Developer jobs'."
            )
        return final_text
    except Exception as exc:  # noqa: BLE001 — chat must never crash the UI
        logger.warning("ADK agent chat failed, falling back to plain Gemini: %s", exc)
        return _fallback_reply(user_message, str(exc))


def chat_reply_stream(
    user_message: str, session_key: str = "default"
) -> Iterator[tuple[str, str]]:
    """Yield (kind, text) pairs: ('event', ...) for tool/agent activity, ('text', ...)
    for the final answer. Lets the UI show what the agent is doing live."""
    try:
        from google.genai import types

        session_id = _get_session_key_safe(session_key)
        runner = _get_runner()
        content = types.Content(role="user", parts=[types.Part(text=user_message)])

        for event in runner.run(
            user_id=_USER_ID, session_id=session_id, new_message=content
        ):
            for call in event.get_function_calls():
                yield "event", f"🔧 tool: {call.name}"
            if event.content and event.content.parts:
                texts = [p.text for p in event.content.parts if getattr(p, "text", None)]
                text = "\n".join(t for t in texts if t.strip())
                if not text:
                    continue
                author = getattr(event, "author", "agent")
                if event.is_final_response():
                    yield "text", text
                else:
                    yield "event", f"🤖 {author}: {text[:300]}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("ADK agent stream failed, falling back: %s", exc)
        yield "text", _fallback_reply(user_message, str(exc))


def _get_session_key_safe(session_key: str) -> str:
    return _get_session_id(session_key)


def _fallback_reply(user_message: str, error: str) -> str:
    """Degraded mode: plain Gemini with the candidate's resume as context.

    Used only when ADK itself is unavailable (stubbed CI, broken install).
    """
    try:
        from .config import call_gemini
        from .tools import _extract_resume_text

        base_resume = _extract_resume_text()[:2000]
        prompt = (
            "You are the Career Copilot AI Agent. Help with job search, interview prep, "
            "resume tailoring and portfolio strategy.\n"
            f"Candidate background:\n{base_resume}\n\n"
            f"(Note: tool use is unavailable in this session.)\n\n"
            f"User question: {user_message}"
        )
        return call_gemini(prompt, temperature=0.7)
    except Exception:  # noqa: BLE001 — nothing left to try
        return (
            f"⚠️ The agent runner is unavailable ({error}). "
            "Check that google-adk is installed and GOOGLE_API_KEY is set."
        )


def agent_status() -> dict:
    """Report whether the tool-using agent surface is live (for the UI badge)."""
    try:
        _get_runner()
        return {"mode": "adk-agent", "tools": True}
    except Exception as exc:  # noqa: BLE001
        return {"mode": "fallback-llm", "tools": False, "error": str(exc)}
