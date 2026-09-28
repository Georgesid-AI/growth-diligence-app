"""Idempotency cache for generated narratives.

Key = sha256(run_id + step + prompt_version + model + canonical JSON payload).
Any change to the computed results, the prompt version, or the model produces a
different key, so a stale narrative can never be served for changed numbers.

A hit returns the stored narrative with zero provider calls - this is what makes
repeated dashboard loads free.
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

NARRATIVES_COLLECTION = "llm_narratives"


def canonical_json(payload: Any) -> str:
    """Stable serialisation: sorted keys, no incidental whitespace.

    Key stability depends on this - an unsorted dump would give the same payload
    different hashes across runs and silently defeat the cache.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def cache_key(run_id: str, step: str, prompt_version: str, model: str, payload: Any) -> str:
    digest = hashlib.sha256()
    digest.update(run_id.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(step.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(prompt_version.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(model.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(canonical_json(payload).encode("utf-8"))
    return digest.hexdigest()


async def get(db, key: str) -> Optional[dict]:
    """Return the stored record for `key`, or None.

    The record carries the narrative together with the status it was stored
    under, so a narrative that was flagged for unmatched numbers comes back
    flagged rather than being silently upgraded to "ok" on a cache hit.
    """
    doc = await db[NARRATIVES_COLLECTION].find_one({"key": key}, {"_id": 0})
    if not doc or not doc.get("narrative"):
        return None
    return {
        "narrative": doc["narrative"],
        "narrative_status": doc.get("narrative_status", "ok"),
        "unmatched_numbers": list(doc.get("unmatched_numbers", [])),
        "created_at": doc.get("created_at"),
    }


async def put(
    db,
    key: str,
    run_id: str,
    step: str,
    prompt_version: str,
    model: str,
    narrative: dict,
    narrative_status: str = "ok",
    unmatched_numbers: Optional[list] = None,
) -> None:
    """Store a narrative under `key`.

    Only the finished, re-identified narrative is stored - never the prompt text
    and never the outbound payload.
    """
    await db[NARRATIVES_COLLECTION].update_one(
        {"key": key},
        {"$set": {
            "key": key,
            "run_id": run_id,
            "step": step,
            "prompt_version": prompt_version,
            "model": model,
            "narrative": narrative,
            "narrative_status": narrative_status,
            "unmatched_numbers": list(unmatched_numbers or []),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


async def has_any(db, run_id: str, step: str) -> bool:
    """True when some narrative exists for this run+step under any cache key.

    Used to tell "nobody has written one" apart from "one was written, but for
    numbers that have since changed" — the two need different wording, because
    only the second is a warning that something the reader may remember seeing
    no longer applies.
    """
    doc = await db[NARRATIVES_COLLECTION].find_one(
        {"run_id": run_id, "step": step}, {"_id": 0, "key": 1}
    )
    return doc is not None


async def delete_run(db, run_id: str) -> int:
    """Drop every cached narrative for a run. Used by the delete-audit cleanup."""
    result = await db[NARRATIVES_COLLECTION].delete_many({"run_id": run_id})
    return getattr(result, "deleted_count", 0)
