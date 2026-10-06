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
from redis import asyncio as aioredis

from .jobs import RULES_VERSION, InvalidJob, run_job

# Must match the producer's queue name in the API.
QUEUE_NAME = "transliterate"

# While a worker is up it refreshes a key with a short expiry, so a producer can tell "no worker is
# listening" from "the worker is busy" without waiting out a job timeout. BullMQ cannot answer
# that for this worker: Node's `Queue.getWorkers()` looks for client names with the queue name
# base64-encoded, and the Python library registers the plain name. A hung worker stops refreshing
# and drops out after the expiry; several workers share the one key.
HEARTBEAT_INTERVAL_SECONDS = 5
HEARTBEAT_TTL_SECONDS = 15

log = logging.getLogger("transliterator")


def heartbeat_key(prefix: str = "bull") -> str:
    """Must match `workerHeartbeatKey` in apps/api/src/transliteration/queue.ts."""
    return f"{prefix}:{QUEUE_NAME}:heartbeat"


async def beat(client: aioredis.Redis, prefix: str) -> None:
    await client.set(heartbeat_key(prefix), str(RULES_VERSION), ex=HEARTBEAT_TTL_SECONDS)


async def heartbeat(client: aioredis.Redis, prefix: str) -> None:
    """Refreshes the key until cancelled. A failed refresh is logged and retried, never fatal."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        try:
            await beat(client, prefix)
        except Exception as error:
            log.warning("heartbeat failed: %s", error)


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
    client = aioredis.from_url(redis_url)
    # First beat before "ready", so anything that waits for ready can rely on the key being there.
    await beat(client, prefix)
    beating = asyncio.create_task(heartbeat(client, prefix))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    log.info("transliterator ready queue=%s prefix=%s", QUEUE_NAME, prefix)
    await stop.wait()
    log.info("shutting down")
    beating.cancel()
    await worker.close()
    await client.aclose()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        raise SystemExit("REDIS_URL is required")
    asyncio.run(serve(redis_url, os.environ.get("QUEUE_PREFIX", "bull")))
