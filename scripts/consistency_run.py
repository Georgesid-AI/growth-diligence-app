"""Consistency run for model reading of deck structures (docs/specs/llm-structure-reading.md section 11).

MANUAL. It calls the live API and costs money; it is not part of the test suite. It runs the 10 decks
in tests/fixtures/decks/decks/ three times and reports:
- agreement % per structure type (items identical in all passes / distinct items);
- the verifier's match rate and unverified rate;
- tokens and cost per deck;
- the cache hit rate on passes 2 and 3.
Passes 2 and 3 read the cache first to get the hit rate (expected 100%), then call the model with the
cache bypassed, so agreement measures the model. Target: at least 95% agreement.

Usage (from the repository root, with ANTHROPIC_API_KEY set and a MongoDB to keep the cache in):
    python scripts/consistency_run.py --yes [--passes 3] [--deck 05-zero2hero.pdf ...] [--out report.json]
Each deck is read in its own throwaway audit (consent ticked) in the database --db (default
"consistency_run"), dropped at the end unless --keep-db. The audits stay within the 200,000-token cap;
raise LLM_DAILY_SPEND_CAP_USD if the run would pass the daily spend cap.
--fake replays empty readings with no network and no MongoDB, to check the script itself.
"""
import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DECKS = ROOT / "tests" / "fixtures" / "decks" / "decks"
sys.path.insert(0, str(BACKEND))


class MemoryDB:
    """Enough of an async Mongo for --fake: find_one, find, insert_one, update_one, count_documents."""

    class _Cursor:
        def __init__(self, docs):
            self._docs = docs

        async def to_list(self, n):
            return self._docs[:n]

    class _Collection:
        def __init__(self):
            self.docs = []

        @staticmethod
        def _match(doc, flt):
            for k, v in flt.items():
                if isinstance(v, dict):
                    if "$ne" in v and doc.get(k) == v["$ne"]:
                        return False
                    if "$gte" in v and not (doc.get(k) is not None and doc.get(k) >= v["$gte"]):
                        return False
                    if "$lt" in v and not (doc.get(k) is not None and doc.get(k) < v["$lt"]):
                        return False
                elif k.startswith("$"):
                    if k == "$and" and not all(MemoryDB._Collection._match(doc, c) for c in v):
                        return False
                    if k == "$or" and not any(MemoryDB._Collection._match(doc, c) for c in v):
                        return False
                elif doc.get(k) != v:
                    return False
            return True

        async def find_one(self, flt, projection=None):
            return next((dict(d) for d in self.docs if self._match(d, flt)), None)

        def find(self, flt, projection=None):
            return MemoryDB._Cursor([dict(d) for d in self.docs if self._match(d, flt)])

        async def insert_one(self, doc):
            self.docs.append(dict(doc))

        async def update_one(self, flt, update, upsert=False):
            for d in self.docs:
                if self._match(d, flt):
                    d.update(update.get("$set", {}))
                    return type("R", (), {"modified_count": 1, "upserted_id": None})()
            if upsert:
                new = {k: v for k, v in flt.items() if not k.startswith("$") and not isinstance(v, dict)}
                new.update(update.get("$setOnInsert", {}))
                new.update(update.get("$set", {}))
                self.docs.append(new)
                return type("R", (), {"modified_count": 0, "upserted_id": 1})()
            return type("R", (), {"modified_count": 0, "upserted_id": None})()

        async def count_documents(self, flt):
            return sum(1 for d in self.docs if self._match(d, flt))

        def aggregate(self, pipeline):
            docs = [d for d in self.docs if self._match(d, pipeline[0].get("$match", {}))]
            return MemoryDB._Cursor([{"_id": None, "total": sum(float(d.get("estimated_cost_usd", 0)) for d in docs)}])

    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        return self._cols.setdefault(name, MemoryDB._Collection())

    def __getattr__(self, name):
        return self[name]


class FakeAdapter:
    """--fake: no network. Replays the recorded replies of backend/tests/fixtures/structure_replies for
    the structures they were written for; every other structure reads as an empty list of items."""

    def __init__(self):
        folder = BACKEND / "tests" / "fixtures" / "structure_replies"
        self.fixtures = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]

    def count_tokens(self, *, model, system, user_payload, json_schema):
        return 1000

    def complete(self, *, model, system, user_payload, max_tokens, temperature, json_schema):
        sent = json.loads(user_payload)
        reply = next((f["reply"] for f in self.fixtures if f["type"] == sent["type"] and f["match"] in sent["text"]),
                     {"type": sent["type"], "items": []})
        return json.dumps(reply), 1000, 20


def _item_key(item):
    """An item as a comparable tuple: every field the model returns."""
    return (item["metric"], item.get("period"), item.get("value"), item.get("unit"), item.get("actual_or_forecast"),
            item["value_cell"], tuple(item.get("period_cells") or ()), tuple(item.get("proposed_flags") or ()))


async def run(decks, passes, db, adapter=None):
    from app.decks import parser
    from app.llm import gateway
    from app.structures import redact, verify

    readings = defaultdict(list)          # (deck, index) -> [set of item keys per pass]
    types = {}
    stats = {"items": 0, "verified": 0, "unverified": 0, "not_read": 0, "model_reads": 0}
    per_deck = {}
    hits = {p: [0, 0] for p in range(2, passes + 1)}     # pass -> [cache hits, lookups]
    for file in decks:
        deck = parser.parse_deck((DECKS / file).read_bytes(), file)
        audit_id = f"consistency-{Path(file).stem}"
        await db["audits"].insert_one({"id": audit_id, "company_name": Path(file).stem, "client_name": "Consistency run",
                                       "engagement_reference": "CONSISTENCY", "structure_reading_consent": True})
        usage = per_deck.setdefault(file, {"structures": len(deck["structures"]), "input_tokens": 0, "output_tokens": 0,
                                           "cost_usd": 0.0})
        for i, structure in enumerate(deck["structures"]):
            types[(file, i)] = structure["type"]
            cells, _ = redact.redact_structure(structure["cells"], Path(file).stem, {})
            text = redact.structure_text(cells)
            page = structure.get("slide") or structure.get("page")
            for n in range(1, passes + 1):
                if n > 1:
                    cached = await gateway.read_structure(db, audit_id, text, structure["type"], deck_id=file, page=page,
                                                          adapter=adapter)
                    hits[n][0] += int(cached.cache_hit)
                    hits[n][1] += 1
                result = await gateway.read_structure(db, audit_id, text, structure["type"], deck_id=file, page=page,
                                                      adapter=adapter, use_cache=n == 1)
                stats["model_reads"] += int(not result.cache_hit)       # agreement needs the model, not the cache
                usage["input_tokens"] += result.input_tokens
                usage["output_tokens"] += result.output_tokens
                usage["cost_usd"] = round(usage["cost_usd"] + result.estimated_cost_usd, 6)
                if result.status != "read":
                    stats["not_read"] += 1
                    readings[(file, i)].append(None)
                    continue
                readings[(file, i)].append({_item_key(item) for item in result.items})
                checked = verify.verify(structure, result.items)
                for item in checked["items"]:
                    stats["items"] += 1
                    stats["verified" if item["status"] == verify.VERIFIED else "unverified"] += 1
    agreement = defaultdict(lambda: [0, 0])                # type -> [identical in all passes, distinct]
    for key, passes_read in readings.items():
        if any(r is None for r in passes_read):
            continue
        distinct = set().union(*passes_read)
        same = set.intersection(*passes_read) if passes_read else set()
        agreement[types[key]][0] += len(same)
        agreement[types[key]][1] += len(distinct)
    return {
        "agreement_pct": {t: round(100.0 * a / d, 1) if d else None for t, (a, d) in sorted(agreement.items())},
        "agreement_pct_all": (round(100.0 * sum(a for a, _ in agreement.values()) / sum(d for _, d in agreement.values()), 1)
                              if sum(d for _, d in agreement.values()) else None),
        "verifier_match_rate_pct": round(100.0 * stats["verified"] / stats["items"], 1) if stats["items"] else None,
        "unverified_rate_pct": round(100.0 * stats["unverified"] / stats["items"], 1) if stats["items"] else None,
        "not_read": stats["not_read"],
        "model_reads": stats["model_reads"],
        "per_deck": per_deck,
        "cache_hit_rate_pct": {f"pass_{p}": round(100.0 * h / n, 1) if n else None for p, (h, n) in hits.items()},
        "target_agreement_pct": 95.0,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--deck", action="append", help="a deck file name in tests/fixtures/decks/decks/ (default: all 10)")
    ap.add_argument("--db", default="consistency_run")
    ap.add_argument("--keep-db", action="store_true")
    ap.add_argument("--out", help="write the report as JSON to this file")
    ap.add_argument("--yes", action="store_true", help="confirm the live API may be called and billed")
    ap.add_argument("--fake", action="store_true", help="no network, no MongoDB: check the script itself")
    args = ap.parse_args(argv)
    decks = args.deck or sorted(p.name for p in DECKS.iterdir() if not p.name.startswith("."))
    if args.fake:
        report = asyncio.run(run(decks, args.passes, MemoryDB(), FakeAdapter()))
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY is not set: this script calls the live API.")
        if not args.yes:
            sys.exit("This run calls the live API and costs money. Re-run with --yes to confirm.")
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = client[args.db]
        try:
            report = asyncio.run(run(decks, args.passes, db))
        finally:
            if not args.keep_db:
                asyncio.run(client.drop_database(args.db))
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    main()
