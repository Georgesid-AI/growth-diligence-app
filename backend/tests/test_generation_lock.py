"""The per-run+step generation lock: one provider call per concurrent burst, and a
holder whose lock expired cannot overwrite the result of the worker that took over.

Stub Mongo and a fake adapter only - no test here can reach a real provider.
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import test_llm_gateway as t  # noqa: E402
from app.llm import cache, gateway, guards  # noqa: E402

STEP = "growth_engine"
NEWER = {**t.GOOD_NARRATIVE, "headline": "Ending ARR stands at 3,129,600 EUR with NRR at 104%."}


def test_concurrent_generate_requests_make_one_provider_call():
    async def run():
        db = t.make_db()
        adapter = t.FakeAdapter()
        results = await asyncio.gather(*(
            gateway.generate_narrative(db, t.RUN_ID, STEP, adapter=adapter, sleep=t._noop_sleep)
            for _ in range(2)
        ))
        return adapter, results

    adapter, results = asyncio.run(run())
    assert adapter.calls == 1, "two concurrent requests must share one provider call"
    assert [r.narrative_status for r in results] == ["ok", "ok"], [r.reason for r in results]


def test_expired_holder_cannot_overwrite_the_newer_result():
    class SlowAdapter(t.FakeAdapter):
        """While this holder is mid-call its lock expires and a second request takes over."""

        def __init__(self, loop, db):
            super().__init__()
            self.loop, self.db = loop, db

        def complete(self, **kwargs):
            lock = self.db[guards.LOCKS_COLLECTION].docs[0]
            expired = datetime.now(timezone.utc) - timedelta(seconds=guards.LOCK_TTL_SECONDS + 1)
            lock["acquired_at"] = expired.isoformat()
            newer = gateway.generate_narrative(
                self.db, t.RUN_ID, STEP, adapter=t.FakeAdapter([json.dumps(NEWER)]),
                sleep=t._noop_sleep,
            )
            self.newer = asyncio.run_coroutine_threadsafe(newer, self.loop).result(timeout=10)
            return super().complete(**kwargs)

    async def run():
        db = t.make_db()
        slow = SlowAdapter(asyncio.get_running_loop(), db)
        stale = await gateway.generate_narrative(db, t.RUN_ID, STEP, adapter=slow, sleep=t._noop_sleep)
        stored = [d["narrative"]["headline"] for d in db[cache.NARRATIVES_COLLECTION].docs]
        return slow.newer, stale, stored

    newer, stale, stored = asyncio.run(run())
    assert newer.narrative_status == "ok", newer.reason
    assert stored == [NEWER["headline"]], "the expired holder overwrote the newer result"
    assert stale.narrative is None or stale.narrative.headline == NEWER["headline"]


def test_lock_ttl_covers_the_worst_case_call():
    attempts = 1 + gateway.MAX_PROVIDER_RETRIES + gateway.MAX_PARSE_RETRIES
    assert guards.LOCK_TTL_SECONDS > attempts * gateway.REQUEST_TIMEOUT_SECONDS


def test_unique_lock_index_exists_after_startup(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("motor")
    pytest.importorskip("pandas")
    import os
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "generation_lock_test")
    from fastapi.testclient import TestClient
    import server

    db = t.make_db()
    db["audits"].docs.append({"id": "seeded", "seed_version": 3})  # skip demo seeding
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "client", type("Client", (), {"close": lambda self: None})())
    with TestClient(server.app):
        pass
    assert {"keys": [("run_id", 1), ("step", 1)], "unique": True} in db[guards.LOCKS_COLLECTION].indexes
