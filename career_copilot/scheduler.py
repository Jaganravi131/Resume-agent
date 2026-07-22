"""Background runner script to execute Career Copilot on a daily cycle at a set time.

Usage:
  python -m career_copilot.scheduler [--query "Python Developer"] [--time "09:00"]
"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
import sys
import time

# Ensure workspace is in path
workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if workspace not in sys.path:
    sys.path.insert(0, workspace)

from career_copilot.config import load_env
from career_copilot import workflow

def run_scheduler(query: str, run_time: str):
    load_env()
    # Support overriding query from env file dynamically
    env_query = os.environ.get("JOB_SEARCH_QUERY")
    if env_query:
        query = env_query
    print(f"[{datetime.now()}] Career Copilot Scheduler started.")
    print(f"Target Query: '{query}' | Scheduled Time: {run_time}")

    try:
        target_hour, target_min = map(int, run_time.split(":"))
    except ValueError:
        print(f"Error: Invalid time format '{run_time}'. Must be HH:MM.")
        sys.exit(1)

    last_run_date = None

    try:
        while True:
            now = datetime.now()
            # Check if it matches target hour and minute, and we haven't run today
            if now.hour == target_hour and now.minute == target_min:
                current_date = now.date()
                if last_run_date != current_date:
                    print(f"[{now}] Launching daily cycle pipeline...")
                    try:
                        result = workflow.run_daily_cycle(query)
                        print(f"[{datetime.now()}] Run completed successfully: {result['notification_status']}")
                    except Exception as exc:
                        print(f"[{datetime.now()}] Run execution failed: {exc}")
                    last_run_date = current_date

            # Sleep 30 seconds to minimize CPU load while remaining accurate to the minute
            time.sleep(30)
    except KeyboardInterrupt:
        print("\nScheduler stopped by user.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Career Copilot Daily Scheduler Service.")
    parser.add_argument("--query", type=str, default="Python Developer", help="Job query keyword (default: 'Python Developer')")
    parser.add_argument("--time", type=str, default="09:00", help="Daily run time in HH:MM format (default: 09:00)")
    args = parser.parse_args()

    run_scheduler(args.query, args.time)
