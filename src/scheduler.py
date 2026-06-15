import asyncio
import random
import sys
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.run_cycle import run_cycle


async def jittered_run(config):
    jitter = random.uniform(0, config.jitter_minutes * 60)
    print(
        f"[{datetime.now().isoformat()}] Scheduled cycle triggered, "
        f"sleeping {jitter:.0f}s of jitter before starting..."
    )
    await asyncio.sleep(jitter)
    await run_cycle(config)


async def main():
    config = load_config()
    scheduler = AsyncIOScheduler(timezone=config.timezone)

    for time_str in config.schedule_times:
        hour, minute = time_str.split(":")
        scheduler.add_job(
            jittered_run,
            CronTrigger(
                hour=int(hour),
                minute=int(minute),
                timezone=config.timezone,
            ),
            args=[config],
        )

    print(
        f"Scheduler started. Cycles at {config.schedule_times} "
        f"({config.timezone}) with up to {config.jitter_minutes}min jitter."
    )

    scheduler.start()

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
