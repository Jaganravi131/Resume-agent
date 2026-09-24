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
