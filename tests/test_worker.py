"""End to end through a real Redis: a producer adds a job, the worker picks it up and answers.

Skipped without `REDIS_URL` (CI's transliterator job provides one). Each run uses its own key
prefix and removes it afterwards, so it can share a Redis with a developer's own queues.
"""

import asyncio
import os
import uuid

import pytest
from bullmq import Job, Queue
from redis import asyncio as aioredis

from transliterator.worker import (
    HEARTBEAT_TTL_SECONDS,
    QUEUE_NAME,
    beat,
    create_worker,
    heartbeat_key,
)

REDIS_URL = os.environ.get("REDIS_URL")
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="REDIS_URL is not set")


async def _settled(queue: Queue, job_id: str, timeout: float = 20.0) -> Job:
    async with asyncio.timeout(timeout):
        while True:
            job = await Job.fromId(queue, job_id)
            if job is not None and job.finishedOn:
                return job
            await asyncio.sleep(0.05)


def _run(scenario):
    async def go():
        prefix = f"test-{uuid.uuid4().hex[:8]}"
        queue = Queue(QUEUE_NAME, {"connection": REDIS_URL, "prefix": prefix})
        worker = create_worker(REDIS_URL, prefix)
        try:
            await scenario(queue)
        finally:
            await worker.close(force=True)
            await queue.obliterate(force=True)
            await queue.close()

    asyncio.run(go())


def test_a_job_is_transliterated_and_returned():
    async def scenario(queue):
        job = await queue.add(
            "transliterate",
            {"texts": ["ఓం శాంతిః", "సంకల్ప"], "scripts": ["sa", "en", "kn"]},
        )
        done = await _settled(queue, job.id)

        assert done.failedReason is None
        assert done.returnvalue["rulesVersion"] == 1
        assert done.returnvalue["scripts"] == {
            "sa": ["ॐ शांतिः", "संकल्प"],
            "en": ["oṃ śāntiḥ", "saṅkalpa"],
            "kn": ["ಓಂ ಶಾಂತಿಃ", "ಸಂಕಲ್ಪ"],
        }

    _run(scenario)


def test_an_invalid_payload_fails_once_without_retrying():
    async def scenario(queue):
        job = await queue.add(
            "transliterate",
            {"texts": ["ఓం"], "scripts": ["fr"]},
            {"attempts": 3, "backoff": {"type": "fixed", "delay": 10}},
        )
        done = await _settled(queue, job.id)

        assert "unknown scripts: fr" in done.failedReason
        assert done.attemptsStarted == 1

    _run(scenario)


def test_a_beat_marks_the_worker_as_alive_for_a_short_while():
    async def go():
        prefix = f"test-{uuid.uuid4().hex[:8]}"
        client = aioredis.from_url(REDIS_URL)
        key = heartbeat_key(prefix)
        try:
            assert await client.exists(key) == 0

            await beat(client, prefix)

            assert key == f"{prefix}:transliterate:heartbeat"
            assert await client.exists(key) == 1
            assert 0 < await client.ttl(key) <= HEARTBEAT_TTL_SECONDS
        finally:
            await client.delete(key)
            await client.aclose()

    asyncio.run(go())
