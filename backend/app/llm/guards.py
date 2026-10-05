"""Cost and loop guards.

Four independent brakes, all backed by Mongo so they hold across workers:

  * a hard per-run call cap on narrative calls (the 16th is refused, never queued or retried);
  * a per-audit token cap on structure reading calls (200,000 billed tokens, input and output);
  * a daily spend ceiling across all runs;
  * a per-run+step advisory lock, so a second request that arrives while one is
    in flight waits for that result instead of issuing another provider call. Structure
    reading takes one lock per audit (step "structures").

The lock is the circuit breaker against save-triggered regeneration loops: a UI
that re-requests a narrative on every autosave gets the in-flight answer back.
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger("growth.llm")

CALLS_COLLECTION = "llm_calls"
LOCKS_COLLECTION = "llm_locks"

MAX_CALLS_PER_RUN = 15             # narrative calls only
DEFAULT_DAILY_SPEND_CAP_USD = 5.00
STRUCTURE_STEP = "structures"      # the step every structure reading call is logged and locked under
STRUCTURE_TOKEN_CAP = 200_000      # billed input and output tokens per audit, structure calls only
STRUCTURE_CAP_MESSAGE = ("AI reading stopped: this audit reached its 200,000-token limit. The remaining "
                         "structures were read by Python only.")

# How long a lock may be held before it is treated as abandoned, so a worker
# that died mid-call cannot wedge the step forever. Must exceed the worst live
# call: 3 network attempts plus 1 reask at the 60 s request timeout = 240 s,
# plus 2 retry waits of at most gateway.RETRY_AFTER_MAX_SECONDS (20 s) = 280 s.
LOCK_TTL_SECONDS = 300
LOCK_POLL_SECONDS = 0.25


class GuardRefusal(Exception):
    """A guard refused the call. Carries a client-safe reason code."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def daily_spend_cap_usd() -> float:
    """Ceiling from LLM_DAILY_SPEND_CAP_USD, defaulting to $5.00.

    A malformed value falls back to the default rather than disabling the cap -
    a typo must never mean "unlimited spend".
    """
    raw = os.environ.get("LLM_DAILY_SPEND_CAP_USD", "").strip()
    if not raw:
        return DEFAULT_DAILY_SPEND_CAP_USD
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_DAILY_SPEND_CAP_USD
    return value if value >= 0 else DEFAULT_DAILY_SPEND_CAP_USD


async def calls_made(db, run_id: str) -> int:
    """Narrative calls already billed to this run. Cache hits and structure reading calls do not
    count: the token cap governs those."""
    return await db[CALLS_COLLECTION].count_documents(
        {"run_id": run_id, "cache_hit": False, "step": {"$ne": STRUCTURE_STEP}}
    )


async def structure_tokens_used(db, run_id: str) -> int:
    """Billed input and output tokens of this audit's structure reading calls."""
    rows = await db[CALLS_COLLECTION].find(
        {"run_id": run_id, "step": STRUCTURE_STEP, "cache_hit": False},
        {"_id": 0, "input_tokens": 1, "output_tokens": 1}).to_list(100000)
    return sum(int(r.get("input_tokens", 0)) + int(r.get("output_tokens", 0)) for r in rows)


async def check_structure_token_cap(db, run_id: str, input_tokens: int, max_tokens: int) -> None:
    """A call goes out only if the tokens used + its input + its max_tokens fit under the cap."""
    used = await structure_tokens_used(db, run_id)
    if used + input_tokens + max_tokens > STRUCTURE_TOKEN_CAP:
        raise GuardRefusal("structure_token_cap_reached", STRUCTURE_CAP_MESSAGE)


async def check_call_cap(db, run_id: str) -> None:
    used = await calls_made(db, run_id)
    if used >= MAX_CALLS_PER_RUN:
        raise GuardRefusal(
            "call_cap_exceeded",
            f"run {run_id} has used all {MAX_CALLS_PER_RUN} provider calls; "
            "refusing without retry or queue",
        )


async def spend_today_usd(db) -> float:
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    cursor = db[CALLS_COLLECTION].aggregate([
        {"$match": {"timestamp": {"$gte": since.isoformat()}}},
        {"$group": {"_id": None, "total": {"$sum": "$estimated_cost_usd"}}},
    ])
    rows = await cursor.to_list(1)
    return float(rows[0]["total"] or 0.0) if rows else 0.0


async def check_spend_cap(db) -> None:
    cap = daily_spend_cap_usd()
    spent = await spend_today_usd(db)
    if spent >= cap:
        raise GuardRefusal(
            "daily_spend_cap_exceeded",
            f"${spent:.4f} spent today against a ${cap:.2f} cap",
        )


async def acquire(db, run_id: str, step: str) -> Optional[str]:
    """Try to take the advisory lock for run_id+step.

    Returns a token when acquired, or None when another worker holds it. An
    expired lock is stolen so a crashed worker cannot block the step forever.
    """
    now = datetime.now(timezone.utc)
    token = uuid.uuid4().hex
    key = {"run_id": run_id, "step": step}
    stale = (now - timedelta(seconds=LOCK_TTL_SECONDS)).isoformat()
    result = await db[LOCKS_COLLECTION].update_one(
        {"$and": [key, {"$or": [{"held": False}, {"acquired_at": {"$lt": stale}}]}]},
        {"$set": {**key, "held": True, "token": token, "acquired_at": now.isoformat()}},
    )
    if getattr(result, "modified_count", 0) == 1:
        return token
    # Held by someone else, or no document yet. Only an upsert that actually
    # inserts grants the lock; an existing document means another worker holds
    # it. A duplicate-key race on the unique index means another worker won.
    try:
        result = await db[LOCKS_COLLECTION].update_one(
            key,
            {"$setOnInsert": {"held": True, "token": token, "acquired_at": now.isoformat()}},
            upsert=True,
        )
    except DuplicateKeyError:
        return None
    return token if getattr(result, "upserted_id", None) is not None else None


async def ensure_indexes(db) -> None:
    """One lock document per run+step, so concurrent upserts cannot both insert.

    Lock documents are transient, so they are cleared first: duplicates left by
    the old insert race would otherwise block the unique index. If the index
    still cannot be created, refuse to start rather than run without it.
    """
    await db[LOCKS_COLLECTION].delete_many({})
    try:
        await db[LOCKS_COLLECTION].create_index([("run_id", 1), ("step", 1)], unique=True)
    except Exception as exc:
        logger.error("llm_locks unique index failed: %s", type(exc).__name__)
        raise RuntimeError("llm_locks unique index could not be created; refusing to start") from None


async def holds(db, run_id: str, step: str, token: str) -> bool:
    """True while `token` still owns the lock - False once it expired and was taken over."""
    doc = await db[LOCKS_COLLECTION].find_one(
        {"run_id": run_id, "step": step, "token": token, "held": True}, {"_id": 0, "token": 1}
    )
    return doc is not None


async def release(db, run_id: str, step: str, token: str) -> None:
    await db[LOCKS_COLLECTION].update_one(
        {"run_id": run_id, "step": step, "token": token},
        {"$set": {"held": False, "token": None}},
    )


async def wait_for_inflight(
    db, run_id: str, step: str, timeout: float = LOCK_TTL_SECONDS
) -> bool:
    """Block until the in-flight generation for run_id+step finishes.

    Returns True when the lock clears, so the caller can read the result the
    other worker just cached - no second provider call is made.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        doc = await db[LOCKS_COLLECTION].find_one(
            {"run_id": run_id, "step": step}, {"_id": 0, "held": 1}
        )
        if not doc or not doc.get("held"):
            return True
        await asyncio.sleep(LOCK_POLL_SECONDS)
    return False
