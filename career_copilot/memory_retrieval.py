"""Vector retrieval (RAG memory) over scouted jobs, resume versions, and outcomes.

Design goals
------------
1. **Semantic search** over everything the agent has ever seen — jobs, tailored
   resume versions, and application outcomes — so the agent can ground answers
   in its own history ("what resume did I send to Stripe?") instead of only SQL
   lookups.
2. **Zero new infrastructure**: embeddings are generated with the same Gemini
   API key via ``google.genai`` (``gemini-embedding-001``) and cached in the
   existing SQLite database (``embeddings`` table, idempotent migration). The
   index is rebuilt in-process from cached vectors — no vector-store service.
3. **Deterministic fallback**: when no API key is configured (CI, offline) the
   retriever transparently uses TF-IDF cosine similarity (pure Python, NumPy
   optional) over the same corpus, so ``semantic_search`` ALWAYS returns useful
   results. Callers never need to know which mode ran.

The embeddings table stores one row per (entity_type, entity_id, text_hash),
so unchanged rows are never re-embedded (cost control) and edited text is
re-embedded automatically (hash mismatch).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from dataclasses import dataclass

logger = logging.getLogger("career_copilot.memory_retrieval")

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")
EMBED_DIM = 768


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Retrieved:
    entity_type: str  # "job" | "resume_version" | "application"
    entity_id: int
    title: str
    text: str
    score: float
    meta: dict

    def as_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "title": self.title,
            "score": round(self.score, 4),
            "meta": self.meta,
        }


# ---------------------------------------------------------------------------
# Corpus building — the agent's memory, assembled from SQLite
# ---------------------------------------------------------------------------


def _build_corpus() -> list[dict]:
    """Collect the retrievable memory corpus. Never raises."""
    from . import database

    corpus: list[dict] = []
    try:
        for job in database.get_all_jobs():
            job_id, title, company, location, url, description, status, created_at = job
            text = f"{title} {company} {location}\n{description or ''}".strip()
            if not text:
                continue
            corpus.append({
                "entity_type": "job",
                "entity_id": job_id,
                "title": f"{title} — {company}",
                "text": text[:4000],
                "meta": {"url": url, "status": status, "created_at": str(created_at)},
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("corpus: jobs unavailable: %s", exc)

    try:
        conn = database.get_connection()
        try:
            rows = conn.execute(
                "SELECT id, job_id, title, company, resume_text, created_at "
                "FROM resume_versions ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
            for r in rows:
                text = f"{r[2]} {r[3]} resume version\n{r[4] or ''}".strip()
                if not text:
                    continue
                corpus.append({
                    "entity_type": "resume_version",
                    "entity_id": r[0],
                    "title": f"Resume v for {r[2]} — {r[3]}",
                    "text": text[:4000],
                    "meta": {"job_id": r[1], "created_at": str(r[5])},
                })
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("corpus: resume_versions unavailable: %s", exc)

    try:
        conn = database.get_connection()
        try:
            rows = conn.execute(
                "SELECT a.id, a.job_id, a.status, a.notes, a.created_at, j.title, j.company "
                "FROM applications a LEFT JOIN jobs j ON j.id = a.job_id "
                "ORDER BY a.created_at DESC LIMIT 200"
            ).fetchall()
            for r in rows:
                text = (
                    f"application status={r[2]} for {r[5] or 'unknown role'} at {r[6] or 'unknown company'} "
                    f"notes: {r[3] or ''}"
                ).strip()
                corpus.append({
                    "entity_type": "application",
                    "entity_id": r[0],
                    "title": f"Application ({r[2]}) — {r[5] or '?'} @ {r[6] or '?'}",
                    "text": text[:2000],
                    "meta": {"job_id": r[1], "status": r[2], "created_at": str(r[4])},
                })
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("corpus: applications unavailable: %s", exc)

    return corpus


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Embeddings: cached in SQLite
# ---------------------------------------------------------------------------

_EMBEDDING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(entity_type, entity_id, model)
)
"""


def _ensure_embeddings_table() -> None:
    from . import database

    conn = database.get_connection()
    try:
        conn.execute(_EMBEDDING_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


def _load_cached_vectors(corpus: list[dict]) -> tuple[dict[tuple[str, int], list[float]], list[dict]]:
    """Split corpus into cached vectors and rows needing embedding."""
    from . import database

    cached: dict[tuple[str, int], list[float]] = {}
    missing: list[dict] = []
    model = EMBEDDING_MODEL
    try:
        conn = database.get_connection()
        try:
            for item in corpus:
                key = (item["entity_type"], item["entity_id"])
                row = conn.execute(
                    "SELECT text_hash, vector_json FROM embeddings "
                    "WHERE entity_type=? AND entity_id=? AND model=?",
                    (key[0], key[1], model),
                ).fetchone()
                if row and row[0] == _text_hash(item["text"]):
                    cached[key] = json.loads(row[1])
                else:
                    missing.append(item)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding cache read failed — embedding all: %s", exc)
        return {}, list(corpus)
    return cached, missing


def _store_vectors(items: list[dict], vectors: dict[tuple[str, int], list[float]]) -> None:
    if not items:
        return
    from . import database

    conn = database.get_connection()
    try:
        for item in items:
            key = (item["entity_type"], item["entity_id"])
            vec = vectors.get(key)
            if vec is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO embeddings "
                "(entity_type, entity_id, text_hash, model, vector_json) VALUES (?,?,?,?,?)",
                (
                    key[0], key[1], _text_hash(item["text"]),
                    EMBEDDING_MODEL, json.dumps(vec),
                ),
            )
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding cache write failed: %s", exc)
    finally:
        conn.close()


def _embed_texts(items: list[dict]) -> dict[tuple[str, int], list[float]]:
    """Embed via Gemini with retry; per-item errors are skipped, not fatal."""
    if not items or not os.environ.get("GOOGLE_API_KEY"):
        return {}
    vectors: dict[tuple[str, int], list[float]] = {}
    try:
        from .config import _get_genai_client
        from google.genai import types

        client = _get_genai_client()
        # Batch in chunks of 50 (API-friendly, bounded memory).
        for start in range(0, len(items), 50):
            chunk = items[start : start + 50]
            texts = [i["text"] for i in chunk]
            try:
                response = client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=texts,
                    config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
                )
                for item, emb in zip(chunk, response.embeddings):
                    vectors[(item["entity_type"], item["entity_id"])] = list(emb.values)
            except Exception as exc:  # noqa: BLE001
                logger.warning("embedding batch failed (%d items): %s", len(chunk), exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding client unavailable: %s", exc)
    return vectors


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1e-9
    db = math.sqrt(sum(y * y for y in b)) or 1e-9
    return num / (da * db)


# ---------------------------------------------------------------------------
# TF-IDF fallback (pure Python — no numpy dependency)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    import re

    from .config import STOPWORDS

    return [
        t for t in re.findall(r"[a-zA-Z][a-zA-Z+#.]{1,}", text.lower())
        if t not in STOPWORDS
    ]


def _tfidf_search(corpus: list[dict], query: str, top_k: int) -> list[Retrieved]:
    """Classic TF-IDF cosine ranking over the corpus (deterministic)."""
    from collections import Counter

    docs_tokens = {i: _tokenize(c["text"]) for i, c in enumerate(corpus)}
    n_docs = max(1, len(corpus))
    df: Counter = Counter()
    for toks in docs_tokens.values():
        df.update(set(toks))

    def idf(term: str) -> float:
        return math.log((n_docs + 1) / (df.get(term, 0) + 1)) + 1.0

    doc_vecs: dict[int, dict[str, float]] = {}
    for i, toks in docs_tokens.items():
        tf = Counter(toks)
        doc_vecs[i] = {t: (c / len(toks or ["x"])) * idf(t) for t, c in tf.items()}

    q_toks = _tokenize(query)
    q_tf = Counter(q_toks)
    q_vec = {t: (c / max(1, len(q_toks))) * idf(t) for t, c in q_tf.items()}

    scored: list[tuple[float, int]] = []
    for i, dvec in doc_vecs.items():
        num = sum(w * q_vec.get(t, 0.0) for t, w in dvec.items())
        da = math.sqrt(sum(w * w for w in dvec.values())) or 1e-9
        dq = math.sqrt(sum(w * w for w in q_vec.values())) or 1e-9
        scored.append((num / (da * dq), i))
    scored.sort(reverse=True)

    return [
        Retrieved(
            entity_type=corpus[i]["entity_type"],
            entity_id=corpus[i]["entity_id"],
            title=corpus[i]["title"],
            text=corpus[i]["text"][:400],
            score=score,
            meta=corpus[i]["meta"],
        )
        for score, i in scored[:top_k]
        if score > 0.01
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def semantic_search(query: str, *, top_k: int = 5, mode: str = "auto") -> dict:
    """Search the agent's memory semantically.

    Returns ``{"mode": "vector" | "tfidf" | "empty", "results": [Retrieved.as_dict()]}``.
    ``mode`` forces one backend; "auto" uses vector embeddings when a key is
    configured and falls back to TF-IDF on any failure.
    """
    query = (query or "").strip()
    corpus = _build_corpus()
    if not corpus or not query:
        return {"mode": "empty", "results": []}

    if mode in ("auto", "vector") and os.environ.get("GOOGLE_API_KEY"):
        try:
            _ensure_embeddings_table()
            cached, missing = _load_cached_vectors(corpus)
            fresh = _embed_texts(missing)
            if fresh:
                _store_vectors(missing, fresh)
            vectors = {**cached, **fresh}
            if vectors:
                try:
                    from .config import _get_genai_client

                    client = _get_genai_client()
                    resp = client.models.embed_content(
                        model=EMBEDDING_MODEL, contents=[query],
                        config={"output_dimensionality": EMBED_DIM},
                    )
                    qvec = list(resp.embeddings[0].values)
                    scored: list[Retrieved] = []
                    for item in corpus:
                        vec = vectors.get((item["entity_type"], item["entity_id"]))
                        if vec:
                            scored.append(Retrieved(
                                entity_type=item["entity_type"],
                                entity_id=item["entity_id"],
                                title=item["title"],
                                text=item["text"][:400],
                                score=_cosine(qvec, vec),
                                meta=item["meta"],
                            ))
                    scored.sort(key=lambda r: r.score, reverse=True)
                    return {
                        "mode": "vector",
                        "results": [r.as_dict() for r in scored[:top_k] if r.score > 0.15],
                    }
                except Exception as exc:  # noqa: BLE001
                    logger.warning("query embedding failed — tfidf fallback: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vector path failed — tfidf fallback: %s", exc)

    return {"mode": "tfidf", "results": [r.as_dict() for r in _tfidf_search(corpus, query, top_k)]}


def memory_stats() -> dict:
    """Counts of retrievable memory items (for the UI telemetry panel)."""
    corpus = _build_corpus()
    by_type: dict[str, int] = {}
    for item in corpus:
        by_type[item["entity_type"]] = by_type.get(item["entity_type"], 0) + 1
    return {"total": len(corpus), **by_type}
