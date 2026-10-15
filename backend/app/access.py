"""Access links for the tester phase (docs/specs/access-links.md).

Identity is possession of a token link. A token is 32 random bytes sent once; only its SHA-256 hash is stored, in
`access_tokens`, with an id, a label and dates. The owner token is a hash in the environment (`OWNER_TOKEN_SHA256`), never in the
repository. Pure of the gateway; it logs nothing, so a token cannot reach a log line (test_gateway_data_boundary.py).
"""
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

COLLECTION = "access_tokens"
TOKEN_DAYS = 30
OWNER, TESTER = "owner", "tester"
# Routes any visitor may call: the health check and the field list (no audit data).
OPEN_PATHS = frozenset({"/api/", "/api", "/api/fields"})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def disabled() -> bool:
    """Access control is on unless the environment says ACCESS_DISABLED (the test session, local development)."""
    return os.environ.get("ACCESS_DISABLED", "").lower() in ("1", "true", "yes")


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def bearer(header: Optional[str]) -> Optional[str]:
    if header and header.lower().startswith("bearer ") and header[7:].strip():
        return header[7:].strip()
    return None


async def principal(db, token: Optional[str]) -> Optional[Tuple[str, Optional[str]]]:
    """(role, tester id) of a valid token, or None: unknown, expired or revoked."""
    if not token:
        return None
    h = digest(token)
    owner = os.environ.get("OWNER_TOKEN_SHA256", "")
    if owner and hmac.compare_digest(h, owner.lower()):
        return OWNER, None
    doc = await db[COLLECTION].find_one({"hash": h})
    if not doc or doc.get("revoked_at"):
        return None
    if datetime.fromisoformat(doc["expires_at"]) <= utcnow():
        return None
    return TESTER, doc["id"]


def new_token() -> str:
    return secrets.token_urlsafe(32)


async def issue(db, label: str) -> Tuple[str, str]:
    """A new tester: (id, token). The token is returned once and never stored."""
    token, now = new_token(), utcnow()
    tester_id = str(uuid.uuid4())
    await db[COLLECTION].insert_one({"id": tester_id, "label": label, "hash": digest(token), "created_at": now.isoformat(),
                                     "expires_at": (now + timedelta(days=TOKEN_DAYS)).isoformat(), "revoked_at": None})
    return tester_id, token


async def revoke(db, tester_id: str) -> bool:
    found = await db[COLLECTION].find_one({"id": tester_id})
    if not found:
        return False
    await db[COLLECTION].update_one({"id": tester_id}, {"$set": {"revoked_at": utcnow().isoformat()}})
    return True


async def reissue(db, tester_id: str) -> Optional[str]:
    """Revoke the old link and return a new token for the same tester id, so the tester keeps their audits."""
    found = await db[COLLECTION].find_one({"id": tester_id})
    if not found:
        return None
    token, now = new_token(), utcnow()
    await db[COLLECTION].update_one({"id": tester_id}, {"$set": {
        "hash": digest(token), "created_at": now.isoformat(), "expires_at": (now + timedelta(days=TOKEN_DAYS)).isoformat(),
        "revoked_at": None}})
    return token


async def testers(db) -> list:
    docs = await db[COLLECTION].find({}, {"_id": 0, "hash": 0}).to_list(1000)
    return [{k: v for k, v in d.items() if k not in ("hash", "_id")} for d in docs]
