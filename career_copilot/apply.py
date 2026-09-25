"""CLI tool to apply for a job using its database ID.

Usage:
  python -m career_copilot.apply <job_id> [--headless]
"""

from __future__ import annotations

import argparse
import os
import sys

# Ensure workspace is in path
workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if workspace not in sys.path:
    sys.path.insert(0, workspace)

from career_copilot.config import load_env
from career_copilot import database
from career_copilot.workflow import run_browser_application


def main():
    parser = argparse.ArgumentParser(description="Apply for a scouted job by its database ID.")
    parser.add_argument("job_id", type=int, help="The database ID of the job you want to apply for.")
    parser.add_argument("--headless", action="store_true", help="Run the browser in headless mode.")
    args = parser.parse_args()

    load_env()

    # Fetch job details from the database
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, company, url, description, status FROM jobs WHERE id = ?",
            (args.job_id,),
        )
        job = cursor.fetchone()

    if not job:
        print(f"Error: No job found in the database with ID {args.job_id}.")
        print("Run a search or query the database to find valid job IDs.")
        sys.exit(1)

    job_id, title, company, url, description, status = job

    print(f"\n[Apply CLI] Found job #{job_id}:")
    print(f"  Title:   {title}")
    print(f"  Company: {company}")
    print(f"  URL:     {url}")
    print(f"  Status:  {status}")

    # Run the interactive browser application flow
    try:
        result = run_browser_application(
            title=title,
            company=company,
            description=description,
            apply_url=url,
            headless=args.headless,
        )

        # Safely handle user cancellation (returned at the TOP level, not inside browser_result)
        if result.get("status") == "cancelled":
            print("\n[Apply CLI] Cancelled by user — no form autofill performed.")
            sys.exit(0)

        browser_result = result.get("browser_result") or {}
        status_result = browser_result.get("status", "unknown")

        if status_result == "cancelled":
            print("\n[Apply CLI] Cancelled by user — no form autofill performed.")
            sys.exit(0)

        # FILLED ≠ SUBMITTED: the application status machine tracks the real
        # lifecycle. Mark 'applied' on the JOB only when the user confirms they
        # actually clicked Submit (previously set unconditionally on fill — §8.11).
        if status_result in ("filled", "filled_generic"):
            print("\n[Apply CLI] Form filled successfully.")
            if not database.update_application_status(job_id, "ready_to_submit"):
                # No application row yet (record_application not called) — create one
                database.save_application(
                    job_id, url, "ready_to_submit", "Filled via browser runner; submit pending."
                )
                print("[Apply CLI] Application recorded with status 'ready_to_submit'.")
            else:
                print("[Apply CLI] Application status: 'ready_to_submit'.")

            try:
                confirm = input("Did you click Submit in the browser? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                confirm = "n"
                print()

            if confirm == "y":
                database.update_application_status(job_id, "submitted")
                database.update_job_status(job_id, "applied")
                print(f"[Apply CLI] Confirmed — application marked 'submitted'; job #{job_id} marked 'applied'.")
            else:
                print(
                    f"[Apply CLI] Not confirmed — application stays 'ready_to_submit'; "
                    f"job #{job_id} left as '{status}' (advance it later from the dashboard)."
                )

    except Exception as exc:
        print(f"\nError executing application flow: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
