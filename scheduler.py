"""
Scheduler — runs the job bot daily at a configured time.
Run this script once and leave it running in the background:
    python scheduler.py
Or set it up as a cron job / systemd service.
"""

import schedule, time, json, logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SCHEDULER] %(message)s",
    handlers=[
        logging.FileHandler("logs/scheduler.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("scheduler")


def run_bot():
    log.info("Starting daily job application run...")
    try:
        from bot import run
        report = run()
        log.info(
            f"Run complete — scraped {report['scraped']}, "
            f"applied to {report['applied']} jobs."
        )
    except Exception as e:
        log.error(f"Bot run failed: {e}", exc_info=True)


def load_schedule_config():
    try:
        with open("config/config.json") as f:
            cfg = json.load(f)
        return cfg.get("schedule", {})
    except Exception:
        return {}


if __name__ == "__main__":
    sched_cfg = load_schedule_config()
    run_time = sched_cfg.get("run_daily_at", "09:00")

    log.info(f"Scheduler started — will run bot daily at {run_time}")
    schedule.every().day.at(run_time).do(run_bot)

    # Also run immediately on first start (optional)
    log.info("Running immediately on startup...")
    run_bot()

    while True:
        schedule.run_pending()
        time.sleep(60)
