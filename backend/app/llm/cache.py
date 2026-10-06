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
        "model": doc.get("model"),
        "prompt_version": doc.get("prompt_version"),
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
    prompt_release: Optional[str] = None,
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
            "prompt_release": prompt_release,
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


async def records_for(db, run_id: str, step: str) -> list:
    """Every stored narrative for a run+step, whatever key it was written under.

    Used only to explain why the current key found nothing (see gateway.supersession);
    it never serves one of them.
    """
    cursor = db[NARRATIVES_COLLECTION].find(
        {"run_id": run_id, "step": step},
        {"_id": 0, "key": 1, "prompt_version": 1, "prompt_release": 1, "model": 1, "created_at": 1},
    )
    return await cursor.to_list(1000)


async def delete_run(db, run_id: str) -> int:
    """Drop every cached narrative for a run. Used by the delete-audit cleanup."""
    result = await db[NARRATIVES_COLLECTION].delete_many({"run_id": run_id})
    return getattr(result, "deleted_count", 0)


# ---------------------------------------------------------------------------
# Structure readings (docs/specs/llm-structure-reading.md sections 8 and 9)
# ---------------------------------------------------------------------------
# Key = sha256 of the structure text (with its item list), its type, the prompt cache tag, the model and the hash
# of its type's output schema (gateway.structure_key). Looked up by (audit id, key), so no audit is served
# another audit's result. A record holds the model's JSON output, the item list Python sent without its raw text
# (ids, cells, positions, values, header ids: docs/specs/structure-labelling.md section 5), so every label
# resolves to a value with its cell reference, the verifier status of each item, the prompt version, the model,
# the content hash, tokens, cost, deck and page, Python's type and the model's when it differs. Never the text
# that was sent.
STRUCTURES_COLLECTION = "llm_structures"


async def get_structure(db, audit_id: str, key: str) -> Optional[dict]:
    """The stored reading for this audit and key, or None. A hit makes no provider call."""
    return await db[STRUCTURES_COLLECTION].find_one(
        {"audit_id": audit_id, "key": key},
        {"_id": 0, "output": 1, "model_type": 1, "type": 1, "items": 1, "prompt_version": 1})


async def put_structure(db, audit_id: str, key: str, record: dict) -> None:
    """Store a reading under (audit id, key), with the time it was written."""
    await db[STRUCTURES_COLLECTION].update_one(
        {"audit_id": audit_id, "key": key},
        {"$set": {**record, "audit_id": audit_id, "key": key,
                  "created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )


async def set_structure_statuses(db, audit_id: str, key: str, statuses: list, dropped: int = 0,
                                 periods_corrected: int = 0, items: Optional[dict] = None) -> None:
    """The verifier status of each item, next to the output it checks, how many of its periods Python
    corrected (the output keeps the model's own periods) and, when given, the item list it was checked
    against, without raw text."""
    fields = {"statuses": list(statuses), "dropped": int(dropped), "periods_corrected": int(periods_corrected),
              "verified_at": datetime.now(timezone.utc).isoformat()}
    if items is not None:
        fields["items"] = items
    await db[STRUCTURES_COLLECTION].update_one({"audit_id": audit_id, "key": key}, {"$set": fields})


async def delete_structures(db, audit_id: str) -> int:
    """Drop every stored reading for an audit. Used by the delete-audit cleanup."""
    result = await db[STRUCTURES_COLLECTION].delete_many({"audit_id": audit_id})
    return getattr(result, "deleted_count", 0)
