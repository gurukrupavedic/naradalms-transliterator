"""BullMQ worker for the `transliterate` queue.

The API (Node) enqueues jobs on this queue; this process picks them up, runs `jobs.run_job`, and
the result goes back through Redis as the job's return value. It needs Redis and nothing else.
"""

import asyncio
import logging
import os
import signal
import time

from bullmq import Job, UnrecoverableError, Worker

from .jobs import InvalidJob, run_job

# Must match the producer's queue name in the API.
QUEUE_NAME = "transliterate"

log = logging.getLogger("transliterator")


async def process(job: Job, _token: str) -> dict:
    started = time.perf_counter()
    try:
        # Off the event loop: BullMQ renews the job's lock from it, and a large batch would
        # otherwise stall that long enough for the job to be treated as stalled.
        result = await asyncio.to_thread(run_job, job.data)
    except InvalidJob as error:
        raise UnrecoverableError(str(error)) from error
    log.info(
        "job done id=%s texts=%d scripts=%s ms=%.0f",
        job.id,
        len(job.data["texts"]),
        ",".join(result["scripts"]),
        (time.perf_counter() - started) * 1000,
    )
    return result


def create_worker(redis_url: str, prefix: str = "bull") -> Worker:
    worker = Worker(QUEUE_NAME, process, {"connection": redis_url, "prefix": prefix})
    worker.on("failed", lambda job, error: log.error("job failed id=%s: %s", job.id, error))
    worker.on("error", lambda error: log.error("worker error: %s", error))
    return worker


async def serve(redis_url: str, prefix: str = "bull") -> None:
    # Load Aksharamukha's script tables now rather than on the first job, and fail fast if the
    # library is broken.
    run_job({"texts": ["ఓం"], "scripts": ["sa", "en", "kn"]})

    worker = create_worker(redis_url, prefix)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    log.info("transliterator ready queue=%s prefix=%s", QUEUE_NAME, prefix)
    await stop.wait()
    log.info("shutting down")
    await worker.close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        raise SystemExit("REDIS_URL is required")
    asyncio.run(serve(redis_url, os.environ.get("QUEUE_PREFIX", "bull")))
