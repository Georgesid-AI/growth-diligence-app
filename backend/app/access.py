"""Access links for the tester phase (docs/specs/access-links.md): tokens, expiry and the owner token.

Identity is possession of a per-tester token: 32 random bytes from a cryptographic source, sent once in the link, stored
only as its SHA-256 hash in the `access_tokens` collection (one document per tester: id, label, token_hash, created_at,
expires_at, revoked_at). The owner token's hash is the environment variable OWNER_TOKEN_SHA256, never in the repository.
The owner issues, lists, revokes and re-issues tester tokens and uploads prompts; the owner token opens no audit.

A token never reaches a log line: it travels in the Authorization header only, and this module logs nothing.
"""
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, NamedTuple, Optional

COLLECTION = "access_tokens"
EXPIRY_DAYS = 30
MAX_LABEL_CHARS = 80
OWNER, TESTER = "owner", "tester"


class Principal(NamedTuple):
    kind: str            # OWNER or TESTER
    id: str              # the tester id (what `audits.owner` holds), or "owner"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def bearer(header: Optional[str]) -> Optional[str]:
    """The token in an `Authorization: Bearer ...` header, or None."""
    parts = (header or "").split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
        return parts[1].strip()
    return None


def is_owner(token: str) -> bool:
    expected = os.environ.get("OWNER_TOKEN_SHA256", "").strip().lower()
    return bool(expected) and hmac.compare_digest(hash_token(token), expected)


def _when(value: Optional[str]) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    return parsed if parsed is None or parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def status_of(doc: dict) -> str:
    if doc.get("revoked_at"):
        return "revoked"
    expires = _when(doc.get("expires_at"))
    return "expired" if expires is None or expires <= utcnow() else "active"


async def authenticate(db, header: Optional[str]) -> Optional[Principal]:
    """The principal a request's token stands for, or None: no token, an unknown token, a revoked or an expired one."""
    token = bearer(header)
    if not token:
        return None
    if is_owner(token):
        return Principal(OWNER, "owner")
    doc = await db[COLLECTION].find_one({"token_hash": hash_token(token)})
    if not doc or status_of(doc) != "active":
        return None
    return Principal(TESTER, doc["id"])


class Refused(ValueError):
    pass


def _clean_label(label: str) -> str:
    label = " ".join(str(label or "").split())
    if not label:
        raise Refused("the tester needs a name")
    if len(label) > MAX_LABEL_CHARS:
        raise Refused(f"the name is over {MAX_LABEL_CHARS} characters")
    return label


def _expiry(days: Optional[int]) -> str:
    days = EXPIRY_DAYS if days is None else days
    if not 1 <= days <= EXPIRY_DAYS:
        raise Refused(f"the expiry is 1 to {EXPIRY_DAYS} days")
    return (utcnow() + timedelta(days=days)).isoformat()


def link_for(token: str, base: str = "") -> str:
    return f"{base.rstrip('/')}/t/{token}"


async def issue(db, label: str, days: Optional[int] = None) -> dict:
    """A new tester and their token. Returns the tester row and the token, which is shown once and never stored."""
    token = secrets.token_urlsafe(32)
    doc = {"id": str(uuid.uuid4()), "label": _clean_label(label), "token_hash": hash_token(token),
           "created_at": utcnow().isoformat(), "expires_at": _expiry(days), "revoked_at": None}
    await db[COLLECTION].insert_one(dict(doc))
    return {"tester": public(doc), "token": token}


async def revoke(db, tester_id: str) -> Optional[dict]:
    doc = await db[COLLECTION].find_one({"id": tester_id})
    if not doc:
        return None
    if not doc.get("revoked_at"):
        await db[COLLECTION].update_one({"id": tester_id}, {"$set": {"revoked_at": utcnow().isoformat()}})
    return public(await db[COLLECTION].find_one({"id": tester_id}))


async def reissue(db, tester_id: str, days: Optional[int] = None) -> Optional[dict]:
    """Replace the tester's token: the old one stops working, the tester keeps their id and so their audits."""
    doc = await db[COLLECTION].find_one({"id": tester_id})
    if not doc:
        return None
    token = secrets.token_urlsafe(32)
    await db[COLLECTION].update_one({"id": tester_id}, {"$set": {
        "token_hash": hash_token(token), "created_at": utcnow().isoformat(), "expires_at": _expiry(days), "revoked_at": None}})
    return {"tester": public(await db[COLLECTION].find_one({"id": tester_id})), "token": token}


def public(doc: dict) -> dict:
    """A tester as the owner page sees it: never the hash."""
    return {"id": doc["id"], "label": doc["label"], "status": status_of(doc), "created_at": doc.get("created_at"),
            "expires_at": doc.get("expires_at"), "revoked_at": doc.get("revoked_at")}


async def testers(db) -> List[dict]:
    docs = await db[COLLECTION].find({}, {"_id": 0}).to_list(10000)
    return [public(d) for d in sorted(docs, key=lambda d: d.get("created_at") or "", reverse=True)]
