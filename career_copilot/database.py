import sqlite3
import logging
import os

logger = logging.getLogger("career_copilot.database")

DB_PATH = os.path.join(os.path.dirname(__file__), "copilot.db")


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
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        conn.commit()


def get_all_jobs():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, company, location, url, description, status, created_at FROM jobs")
        return cursor.fetchall()


def save_application(job_id, apply_url, status, notes):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO applications (job_id, apply_url, status, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                apply_url = excluded.apply_url,
                status = excluded.status,
                notes = excluded.notes,
                created_at = CURRENT_TIMESTAMP
            """,
            (job_id, apply_url, status, notes),
        )
        conn.commit()


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
    """
    import datetime
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
    deleted = {}

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM jobs WHERE status IN ('applied', 'archived') AND created_at < ?",
            (cutoff,),
        )
        deleted["old_jobs"] = cursor.rowcount

        cursor.execute(
            "DELETE FROM daily_reports WHERE created_at < ?",
            (cutoff,),
        )
        deleted["old_reports"] = cursor.rowcount

        conn.commit()

    logger.info("Database cleanup: %s", deleted)
    return deleted


# Initialize DB on load
init_db()
