"""The server-side prompt store: the MongoDB collection `prompts` (docs/specs/prompt-store.md).

Prompt text is never committed to the repository (CLAUDE.md rule 26): the repository is public and Emergent deploys
from it, so the methodology lives in the database and the owner uploads it on the owner page. The gateway reads the
latest version of each named prompt from here and from nowhere else; a prompt that is not loaded means no model call
(`PromptMissing`, shown as NO_PROMPT). This module touches no file: the owner page posts the text.

A document is {name, version, text, uploaded_at, sha256}. Every upload creates the next version of its name ("v1",
"v2", ...); nothing is updated or deleted, so a version names exactly one text and a reading stored under it stays
comparable. The version is part of every cache key and of the stored model output (rule 17), so a new upload makes
earlier narratives "not shown" until they are written again.

Prompt text never leaves the server except into the model request: `list_versions` returns no text, the gateway
surfaces the version string only, and the owner page has no way to read a text back. Rules 16-18 (what may reach the
model) are enforced by the gateway and tests/test_gateway_data_boundary.py, not here.
"""
import hashlib
from datetime import datetime, timezone
from typing import List, NamedTuple, Optional

COLLECTION = "prompts"

# What the narrative endpoint answers when a prompt the step needs is not in the store. No model call is made.
NO_PROMPT = "No prompt loaded — upload prompts on the owner page"

# The prompt names the gateway reads: the enabled narrative steps and the structure path. tests/test_llm_gateway.py
# fails if this list and the gateway's STEP_CONFIG drift apart.
NAMES = ("growth_engine", "data_inventory", "data_integrity", "structure_reading", "file_type", "sheet_structure")

MAX_TEXT_CHARS = 100_000
_VERSION_PREFIX = "v"


class PromptMissing(LookupError):
    """The store holds no version of the prompt (or the name is not one the gateway reads)."""


class PromptRefused(ValueError):
    """An upload the store will not take: an unknown name, empty text or text over the limit."""


class Prompt(NamedTuple):
    name: str
    version: str
    text: str
    sha256: str


def _number(version: str) -> int:
    try:
        return int(str(version).lstrip(_VERSION_PREFIX))
    except ValueError:
        return 0


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _latest_doc(db, name: str) -> Optional[dict]:
    docs = await db[COLLECTION].find({"name": name}, {"_id": 0}).to_list(100000)
    return max(docs, key=lambda d: _number(d.get("version"))) if docs else None


async def load(db, name: str) -> Prompt:
    """The latest version of a named prompt. Raises PromptMissing when the store holds none."""
    doc = await _latest_doc(db, name) if name in NAMES else None
    if not doc or not str(doc.get("text") or "").strip():
        raise PromptMissing(name)
    return Prompt(name=name, version=doc["version"], text=doc["text"], sha256=doc.get("sha256") or _digest(doc["text"]))


async def missing(db) -> List[str]:
    """The names the gateway reads that the store holds no prompt for."""
    return [n for n in NAMES if not await _latest_doc(db, n)]


def tag_for(version: str) -> str:
    """The prompt identity in a cache key for a stored version. A version names one text; the "store:" namespace keeps a record
    written under the retired file prompts (plain "v1", "v7" ...) from matching the key of a store version of the same number."""
    return f"store:{version}"


def cache_tag(prompt: Prompt) -> str:
    return tag_for(prompt.version)


async def list_versions(db) -> List[dict]:
    """Every stored version: name, version, uploaded_at and sha256. Never the text."""
    docs = await db[COLLECTION].find({}, {"_id": 0, "name": 1, "version": 1, "uploaded_at": 1, "sha256": 1}).to_list(100000)
    rows = [{"name": d["name"], "version": d["version"], "uploaded_at": d["uploaded_at"], "sha256": d["sha256"]} for d in docs]
    return sorted(rows, key=lambda r: (NAMES.index(r["name"]) if r["name"] in NAMES else len(NAMES), -_number(r["version"])))


async def upload(db, name: str, text: str) -> dict:
    """Store `text` as the next version of `name`. Returns the new row without the text."""
    if name not in NAMES:
        raise PromptRefused(f"unknown prompt name; the names are {', '.join(NAMES)}")
    text = text.replace("\r\n", "\n")
    if not text.strip():
        raise PromptRefused("the prompt text is empty")
    if len(text) > MAX_TEXT_CHARS:
        raise PromptRefused(f"the prompt text is over {MAX_TEXT_CHARS} characters")
    from pymongo.errors import DuplicateKeyError
    await db[COLLECTION].create_index([("name", 1), ("version", 1)], unique=True)
    for _ in range(5):                      # a second upload at the same moment takes the number: try the next one
        latest = await _latest_doc(db, name)
        doc = {"name": name, "version": f"{_VERSION_PREFIX}{_number(latest['version']) + 1 if latest else 1}", "text": text,
               "uploaded_at": datetime.now(timezone.utc).isoformat(), "sha256": _digest(text)}
        try:
            await db[COLLECTION].insert_one(dict(doc))
        except DuplicateKeyError:
            continue
        return {k: doc[k] for k in ("name", "version", "uploaded_at", "sha256")}
    raise PromptRefused("the upload collided with another upload; try again")
