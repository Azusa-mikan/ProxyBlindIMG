from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
import time

from src.util import CounterService
from src.edncrypt import encrypt_image_path
from src.log import logger

def delete_five_minutes_image():
    cutoff = time.time() - (5 * 60)
    deleted_count = 0

    for file_path in encrypt_image_path.iterdir():
        if not file_path.is_file():
            continue
        try:
            if file_path.stat().st_birthtime <= cutoff:
                file_path.unlink()
                deleted_count += 1
        except FileNotFoundError:
            # File may be removed by another worker between listing and unlinking.
            continue
        except Exception:
            logger.exception(f"Failed to delete expired image: {file_path.name}")

    if deleted_count:
        logger.info(f"Deleted {deleted_count} expired image files")

async def reset_today_requests(app: FastAPI) -> None:
    counter: CounterService = app.state.counter
    await counter.reset()

def init_scheduler(app: FastAPI):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        reset_today_requests,
        trigger=CronTrigger(hour=0, minute=0),
        args=[app],
        id="reset_today_requests",
        replace_existing=True,
    )
    scheduler.add_job(
        delete_five_minutes_image,
        trigger=IntervalTrigger(minutes=5),
        id="delete_five_minutes_image",
        replace_existing=True,
    )
    return scheduler
