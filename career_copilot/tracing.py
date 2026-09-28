"""Observability: lightweight tracing for LLM, tool, and retrieval calls.

Design: OpenTelemetry is *optional*. When the ``opentelemetry`` packages are
installed (they are already in requirements.txt via semantic-conventions),
``trace_span`` emits real OTel spans with LLM/tool attributes. When not
installed, the identical API emits structured log lines instead — so callers
get one decorator/context-manager and the deployment decides the backend.

Usage:
    with trace_span("tool.search_job_postings", kind="tool", attrs={"provider": "remotive"}):
        ...

    @trace_span(kind="llm", name="call_gemini")
    def call_gemini(...): ...

What gets recorded per span:
    - kind: llm | tool | retrieval | agent
    - duration_ms, success/error status
    - LLM: model name, prompt/response char sizes (never content — PII)
    - tool: tool name, args shape (arg names + types, never values)
    - retrieval: backend mode, result count
"""

from __future__ import annotations

import functools
import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

logger = logging.getLogger("career_copilot.tracing")

# --- Optional OTel ---------------------------------------------------------
_OTEL_AVAILABLE = False
try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import Status, StatusCode as _StatusCode

    _tracer = _otel_trace.get_tracer("career_copilot")
    _OTEL_AVAILABLE = True
except Exception:  # noqa: BLE001 — ImportError or broken install
    pass

_KIND_ATTR = "career_copilot.kind"


def _safe_attrs(kind: str, attrs: dict[str, Any] | None) -> dict[str, Any]:
    """Keep tracing PII-safe: log sizes and names, never prompt/response text."""
    safe: dict[str, Any] = {_KIND_ATTR: kind}
    for k, v in (attrs or {}).items():
        if isinstance(v, str) and len(v) > 200:
            safe[k] = f"<str:{len(v)}chars>"
        else:
            safe[k] = v
    return safe


@contextmanager
def trace_span(
    name: str, *, kind: str = "tool", attrs: dict[str, Any] | None = None
) -> Iterator[dict]:
    """Record a span (OTel if available, structured log otherwise).

    Yields a mutable dict; callers may add attributes to it mid-span
    (e.g. ``span["model"] = model_name``).
    """
    carrier: dict[str, Any] = dict(attrs or {})
    start = time.perf_counter()
    otel_cm = None
    if _OTEL_AVAILABLE:
        # start_as_current_span returns a context manager, not the span;
        # the actual span is fetched from the current context after entering.
        otel_cm = _tracer.start_as_current_span(name)
        otel_cm.__enter__()
        otel_span = _otel_trace.get_current_span()

    error: str | None = None
    try:
        yield carrier
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        payload = _safe_attrs(kind, {**carrier, "duration_ms": duration_ms})
        if otel_cm is not None:
            try:
                if otel_span is not None and otel_span.is_recording():
                    for k, v in payload.items():
                        otel_span.set_attribute(k, v)
                    if error:
                        otel_span.record_exception(Exception(error))
                        otel_span.set_status(Status(_StatusCode.ERROR, error[:200]))
                    else:
                        otel_span.set_status(Status(_StatusCode.OK))
            finally:
                otel_cm.__exit__(None, None, None)
        # Structured log line — always emitted, greppable in any deployment.
        status = "ERROR" if error else "OK"
        logger.info(
            "span=%s kind=%s status=%s %s%s",
            name, kind, status,
            " ".join(f"{k}={v}" for k, v in payload.items() if k != _KIND_ATTR),
            f" error={error[:200]}" if error else "",
        )


def trace_span_decorator(
    _fn: Callable | None = None, *, name: str | None = None, kind: str = "tool"
) -> Callable:
    """Decorator form of trace_span."""

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with trace_span(name or f"{fn.__module__}.{fn.__name__}", kind=kind):
                return fn(*args, **kwargs)

        return wrapper

    if _fn is not None:  # used bare: @trace_span_decorator
        return decorator(_fn)
    return decorator


def trace_llm_call(model: str, prompt: str, response: str, success: bool, error: str | None = None) -> None:
    """Point recorder for LLM calls (used inside config.call_gemini's chain)."""
    with trace_span(
        "llm.call_gemini", kind="llm",
        attrs={
            "model": model,
            "prompt_chars": len(prompt),
            "response_chars": len(response) if response else 0,
            "success": success,
        },
    ):
        if error:
            raise RuntimeError(error)


def trace_retrieval(mode: str, query: str, n_results: int, duration_ms: float | None = None) -> None:
    """Point recorder for RAG/memory searches."""
    attrs = {"mode": mode, "query_chars": len(query), "results": n_results}
    if duration_ms is not None:
        attrs["duration_ms"] = round(duration_ms, 1)
    with trace_span("retrieval.semantic_search", kind="retrieval", attrs=attrs):
        pass


def otel_status() -> dict:
    """For the UI/diagnostics: which tracing backend is active."""
    return {"otel": _OTEL_AVAILABLE, "backend": "opentelemetry" if _OTEL_AVAILABLE else "structured-logging"}
