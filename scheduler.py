"""
Scheduler — runs the job bot daily at a configured time.
Run this script once and leave it running in the background:
    python scheduler.py
Or set it up as a cron job / systemd service.
"""

import os
os.makedirs("logs", exist_ok=True)
os.makedirs("config", exist_ok=True)

import schedule, time, json, logging
from pathlib import Path
from datetime import datetime, timedelta

import pytz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SCHEDULER] %(message)s",
    handlers=[
        logging.FileHandler("logs/scheduler.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("scheduler")


def _parse_run_time(run_time: str) -> tuple[int, int]:
    hour_str, minute_str = run_time.split(":", 1)
    return int(hour_str), int(minute_str)


def _next_system_time(run_time: str, timezone_name: str) -> datetime:
    target_tz = pytz.timezone(timezone_name)
    system_tz = datetime.now().astimezone().tzinfo
    now_target = datetime.now(target_tz)
    hour, minute = _parse_run_time(run_time)

    target_run = now_target.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    if target_run <= now_target:
        target_run += timedelta(days=1)

    return target_run.astimezone(system_tz)


def schedule_next_run():
    sched_cfg = load_schedule_config()
    run_time = sched_cfg.get("run_daily_at", "09:00")
    timezone_name = sched_cfg.get("timezone", "UTC")

    next_run_system = _next_system_time(run_time, timezone_name)
    schedule.clear("job_bot")
    schedule.every().day.at(next_run_system.strftime("%H:%M")).do(run_bot).tag("job_bot")

    log.info(
        f"Next run scheduled for {next_run_system.strftime('%Y-%m-%d %H:%M')} "
        f"system time ({run_time} {timezone_name})"
    )


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
    finally:
        schedule_next_run()


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
    timezone_name = sched_cfg.get("timezone", "UTC")

    log.info(f"Scheduler started — will run bot daily at {run_time} {timezone_name}")
    schedule_next_run()

    # Also run immediately on first start (optional)
    log.info("Running immediately on startup...")
    run_bot()

    while True:
        schedule.run_pending()
        time.sleep(60)
