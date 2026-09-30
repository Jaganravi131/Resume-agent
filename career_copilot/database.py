import sqlite3
import logging
import os

logger = logging.getLogger("career_copilot.database")

DB_PATH = os.path.join(os.path.dirname(__file__), "copilot.db")

# Job lifecycle: found -> notified -> applied -> interviewing -> archived
ALLOWED_JOB_STATUSES = ("found", "notified", "applied", "interviewing", "archived")

# Application lifecycle (human-in-the-loop: the user always clicks final submit):
# drafted -> ready_to_submit -> submitted -> interviewing -> offer | rejected
ALLOWED_APPLICATION_STATUSES = (
    "drafted", "ready_to_submit", "submitted", "interviewing", "offer", "rejected",
)


def get_connection():
    """Return a new connection with WAL mode and a 10s timeout for concurrency."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def close_idle_resources() -> None:
    """Checkpoint and release WAL sidecar files for the current DB path.

    On Windows, an open -wal/-shm handle blocks os.unlink() of the database
    (tests and temp-DB users hit WinError 32). Running a TRUNCATE checkpoint
    and opening/closing a fresh connection lets SQLite release the sidecars.
    Safe to call at any time; failures are swallowed (best-effort).
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    except sqlite3.Error:
        pass


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                url TEXT UNIQUE NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'found',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                apply_url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'drafted',
                notes TEXT,
                resume_text TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(job_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS company_intel (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                domain TEXT,
                intel_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(company)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS resume_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                title TEXT DEFAULT '',
                company TEXT DEFAULT '',
                version INTEGER NOT NULL,
                resume_text TEXT DEFAULT '',
                pdf_path TEXT DEFAULT '',
                ats_score INTEGER,
                generator TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(job_id, version)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS application_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                notes TEXT DEFAULT '',
                resume_version INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

    # Migration for legacy databases created before the resume_text column
    try:
        with get_connection() as conn:
            conn.cursor().execute("ALTER TABLE applications ADD COLUMN resume_text TEXT DEFAULT ''")
            conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists


def add_job(title, company, location, url, description):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO jobs (title, company, location, url, description) VALUES (?, ?, ?, ?, ?)",
                (title, company, location, url, description)
            )
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        # Job already exists (unique URL violation)
        return False


def get_jobs_by_status(status):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, company, location, url, description, status, created_at FROM jobs WHERE status = ?", (status,))
        return cursor.fetchall()


def get_actionable_jobs():
    """Return only jobs that haven't been applied to or archived yet.

    This replaces get_all_jobs() in pipeline contexts to avoid
    re-processing old/applied/archived entries.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, company, location, url, description, status, created_at "
            "FROM jobs WHERE status IN ('found', 'notified') "
            "ORDER BY created_at DESC"
        )
        return cursor.fetchall()


def update_job_status(job_id, status):
    """Update a job's status. Rejects values outside ALLOWED_JOB_STATUSES."""
    if status not in ALLOWED_JOB_STATUSES:
        logger.warning(
            "Rejected invalid job status %r for job %s (allowed: %s)",
            status, job_id, ALLOWED_JOB_STATUSES,
        )
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        conn.commit()
        return True


def update_job_status_by_url(url, status):
    """Update a job's status by its unique URL (used by digest/notify flows)."""
    if status not in ALLOWED_JOB_STATUSES:
        logger.warning(
            "Rejected invalid job status %r for url %s (allowed: %s)",
            status, url, ALLOWED_JOB_STATUSES,
        )
        return 0
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET status = ? WHERE url = ?", (status, url))
        conn.commit()
        return cursor.rowcount


def get_all_jobs():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, company, location, url, description, status, created_at FROM jobs")
        return cursor.fetchall()


def get_job_count() -> int:
    with get_connection() as conn:
        return conn.cursor().execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def get_application_count() -> int:
    with get_connection() as conn:
        return conn.cursor().execute("SELECT COUNT(*) FROM applications").fetchone()[0]


def get_application(job_id):
    """Return the application record for a job as a dict, or None."""
    with get_connection() as conn:
        row = conn.cursor().execute(
            "SELECT job_id, apply_url, status, notes, created_at FROM applications WHERE job_id=?",
            (job_id,),
        ).fetchone()
    if not row:
        return None
    return {"job_id": row[0], "apply_url": row[1], "status": row[2],
            "notes": row[3], "created_at": row[4]}


def save_application(job_id, apply_url, status, notes, resume_text=""):
    """Upsert an application record. `notes` holds free-form notes; the resume
    payload lives in its own `resume_text` column (legacy callers that stuffed
    the resume into `notes` are preserved as-is for old rows)."""
    if status not in ALLOWED_APPLICATION_STATUSES:
        logger.warning(
            "Unknown application status %r for job_id=%s — stored as 'drafted' (allowed: %s)",
            status, job_id, ALLOWED_APPLICATION_STATUSES,
        )
        status = "drafted"
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO applications (job_id, apply_url, status, notes, resume_text)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                apply_url = excluded.apply_url,
                status = excluded.status,
                notes = excluded.notes,
                resume_text = excluded.resume_text
            """,
            (job_id, apply_url, status, notes, resume_text or ""),
        )
        conn.commit()


def update_application_status(job_id, status, apply_url=None):
    """Advance an application's status (drafted -> ready_to_submit -> submitted -> ...).

    Rejects values outside ALLOWED_APPLICATION_STATUSES — previously nothing
    ever moved an application past 'drafted' and any string was accepted (§8.11).
    Returns True when a row was actually updated.
    """
    if status not in ALLOWED_APPLICATION_STATUSES:
        logger.warning(
            "Refusing invalid application status %r for job_id=%s (allowed: %s)",
            status, job_id, ALLOWED_APPLICATION_STATUSES,
        )
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        if apply_url:
            cursor.execute(
                "UPDATE applications SET status=? WHERE job_id=? AND apply_url=?",
                (status, job_id, apply_url),
            )
        else:
            cursor.execute(
                "UPDATE applications SET status=? WHERE job_id=?",
                (status, job_id),
            )
        conn.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Application outcomes (the agent learning loop)
# ---------------------------------------------------------------------------

ALLOWED_OUTCOMES = (
    "applied", "auto_rejected", "recruiter_screen", "interview",
    "onsite", "offer", "rejected", "ghosted", "withdrawn",
)


def record_outcome(job_id: int, outcome: str, notes: str = "",
                   resume_version: int | None = None) -> bool:
    """Append an outcome event for an application (interview, rejection, ...).

    Immutable event log: multiple outcomes per application are allowed and
    form a timeline (applied -> recruiter_screen -> interview -> offer).
    """
    if outcome not in ALLOWED_OUTCOMES:
        logger.warning(
            "Refusing invalid outcome %r for job_id=%s (allowed: %s)",
            outcome, job_id, ALLOWED_OUTCOMES,
        )
        return False
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO application_outcomes (job_id, outcome, notes, resume_version)
            VALUES (?, ?, ?, ?)
            """,
            (job_id, outcome, notes, resume_version),
        )
        # Keep the applications.status column in sync with the latest outcome.
        conn.execute(
            "UPDATE applications SET status=? WHERE job_id=?", (outcome, job_id)
        )
        conn.commit()
    return True


def get_outcomes(job_id: int) -> list[dict]:
    """Outcome timeline for one application, oldest first."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, outcome, notes, resume_version, created_at
            FROM application_outcomes WHERE job_id=? ORDER BY created_at ASC, id ASC
            """,
            (job_id,),
        ).fetchall()
    return [
        {"id": r[0], "outcome": r[1], "notes": r[2],
         "resume_version": r[3], "created_at": str(r[4])}
        for r in rows
    ]


def get_outcome_stats() -> dict:
    """Aggregate outcome counts across ALL applications — the system's
    report card, e.g. {'applied': 42, 'interview': 6, 'ghosted': 11,...}."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT outcome, COUNT(*) FROM application_outcomes GROUP BY outcome"
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def get_best_performing_resumes(limit: int = 5) -> list[dict]:
    """Resume versions that led to interviews/offers — the tailoring signal.

    Joins application_outcomes to resume_versions on (job_id, version) and
    ranks by best outcome achieved. Only counts outcomes that indicate
    traction (recruiter_screen and beyond).
    """
    positive = ("recruiter_screen", "interview", "onsite", "offer")
    placeholders = ",".join("?" * len(positive))
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT rv.job_id, rv.version, rv.title, rv.company, rv.ats_score,
                   rv.generator, MAX(o.outcome) AS best_outcome, COUNT(*) AS n_positive
            FROM application_outcomes o
            JOIN resume_versions rv
              ON rv.job_id = o.job_id AND rv.version = o.resume_version
            WHERE o.outcome IN ({placeholders})
            GROUP BY rv.job_id, rv.version
            ORDER BY
                CASE MAX(o.outcome)
                    WHEN 'offer' THEN 5 WHEN 'onsite' THEN 4
                    WHEN 'interview' THEN 3 WHEN 'recruiter_screen' THEN 2
                    ELSE 1 END DESC,
                n_positive DESC
            LIMIT ?
            """,
            (*positive, max(1, int(limit))),
        ).fetchall()
    return [
        {"job_id": r[0], "version": r[1], "title": r[2], "company": r[3],
         "ats_score": r[4], "generator": r[5], "best_outcome": r[6]}
        for r in rows
    ]


def get_stale_applications(days: int = 14) -> list[dict]:
    """Submitted applications with no outcome recorded in *days* — follow-up
    candidates. Considers the LATEST outcome event per application."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.job_id, j.title, j.company, a.apply_url, a.status,
                   MAX(o.created_at) AS last_outcome_at
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            LEFT JOIN application_outcomes o ON o.job_id = a.job_id
            WHERE a.status = 'submitted'
            GROUP BY a.job_id
            HAVING last_outcome_at IS NULL
                OR last_outcome_at < datetime('now', '-' || ? || ' days')
            """,
            (int(days),),
        ).fetchall()
    return [
        {"job_id": r[0], "title": r[1], "company": r[2],
         "apply_url": r[3], "status": r[4], "last_outcome_at": str(r[5])}
        for r in rows
    ]


def save_resume_version(job_id, title, company, resume_text, pdf_path="",
                        ats_score=None, generator=""):
    """Append a new resume version for a job (immutable history — versions are
    never overwritten, so every resume sent for an application stays
    auditable). Returns the new version number (per-job, starting at 1)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM resume_versions WHERE job_id=?",
            (job_id,),
        ).fetchone()
        version = row[0]
        cursor.execute(
            """
            INSERT INTO resume_versions
                (job_id, title, company, version, resume_text, pdf_path, ats_score, generator)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, title or "", company or "", version, resume_text or "",
             pdf_path or "", ats_score, generator or ""),
        )
        conn.commit()
        return version


def get_resume_versions(job_id):
    """Return all resume versions for a job, newest first, as dicts."""
    with get_connection() as conn:
        rows = conn.cursor().execute(
            """
            SELECT version, title, company, ats_score, generator, pdf_path,
                   LENGTH(resume_text), created_at
            FROM resume_versions WHERE job_id=? ORDER BY version DESC
            """,
            (job_id,),
        ).fetchall()
    return [
        {"version": r[0], "title": r[1], "company": r[2], "ats_score": r[3],
         "generator": r[4], "pdf_path": r[5], "text_length": r[6], "created_at": r[7]}
        for r in rows
    ]


def get_latest_resume_version(job_id):
    """Return {version, resume_text, ...} for the newest version, or None."""
    with get_connection() as conn:
        row = conn.cursor().execute(
            """
            SELECT version, title, company, resume_text, pdf_path, ats_score,
                   generator, created_at
            FROM resume_versions WHERE job_id=? ORDER BY version DESC LIMIT 1
            """,
            (job_id,),
        ).fetchone()
    if not row:
        return None
    return {"version": row[0], "title": row[1], "company": row[2],
            "resume_text": row[3], "pdf_path": row[4], "ats_score": row[5],
            "generator": row[6], "created_at": row[7]}


def save_daily_report(report_text):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO daily_reports (report_text) VALUES (?)",
            (report_text,),
        )
        conn.commit()


def save_company_intel(company, domain, intel_json):
    """Cache company intel analysis results."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO company_intel (company, domain, intel_json)
            VALUES (?, ?, ?)
            ON CONFLICT(company) DO UPDATE SET
                domain = excluded.domain,
                intel_json = excluded.intel_json,
                created_at = CURRENT_TIMESTAMP
            """,
            (company, domain, intel_json),
        )
        conn.commit()


def get_company_intel(company):
    """Retrieve cached company intel. Returns (domain, intel_json, created_at) or None."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT domain, intel_json, created_at FROM company_intel WHERE company = ?",
            (company,),
        )
        return cursor.fetchone()


def cleanup_old_records(days: int = 90) -> dict:
    """Archive old records to keep the database manageable.

    Deletes:
    - Jobs older than *days* that are already 'applied' or 'archived'
    - Daily reports older than *days*
    Returns a summary dict with counts of deleted rows.

    Date handling: SQLite CURRENT_TIMESTAMP is UTC ('YYYY-MM-DD HH:MM:SS'),
    so the cutoff is computed in UTC with the SAME format (naive local-time
    ISO strings with 'T' previously compared incorrectly and deleted rows
    from the cutoff day prematurely). 'T' separators in stored values are
    normalized defensively.
    """
    import datetime
    cutoff_dt = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    cutoff = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
    deleted = {}

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM jobs WHERE status IN ('applied', 'archived') "
            "AND replace(created_at, 'T', ' ') < ?",
            (cutoff,),
        )
        deleted["old_jobs"] = cursor.rowcount

        cursor.execute(
            "DELETE FROM daily_reports WHERE replace(created_at, 'T', ' ') < ?",
            (cutoff,),
        )
        deleted["old_reports"] = cursor.rowcount

        conn.commit()

    logger.info("Database cleanup (cutoff %s UTC): %s", cutoff, deleted)
    return deleted


# Initialize DB on load
init_db()

# Vector-memory table (created here so it exists before first semantic_search;
# import-local to avoid a circular dependency with memory_retrieval).
try:
    with get_connection() as _conn:
        _conn.execute("""
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
        """)
        _conn.commit()
except sqlite3.Error:
    pass  # non-fatal: memory_retrieval lazily retries via _ensure_embeddings_table
