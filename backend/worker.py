"""Optional Celery worker; the database remains the durable queue of record.

celery -A backend.worker.celery_app worker --beat --loglevel=info
"""

import asyncio
from celery import Celery
from backend.config import get_settings
from backend.workflows import claim_task, run_task

celery_app = Celery(
    "atlas", broker=get_settings().redis_url, backend=get_settings().redis_url
)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    beat_schedule={
        "recover-durable-atlas-tasks": {"task": "atlas.poll_queue", "schedule": 15.0}
    },
)


@celery_app.task(name="atlas.execute_task")
def execute_task(task_id):
    claimed = claim_task(task_id)
    if claimed:
        asyncio.run(run_task(claimed))


@celery_app.task(name="atlas.poll_queue")
def poll_queue():
    # One bounded recovery batch; beat will retry queued/expired leases on subsequent ticks.
    for _ in range(4):
        task_id = claim_task()
        if not task_id:
            break
        asyncio.run(run_task(task_id))
