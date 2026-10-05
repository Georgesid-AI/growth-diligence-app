"""Consistency run for model reading of deck structures (docs/specs/llm-structure-reading.md section 11).

MANUAL. It calls the live API and costs money; it is not part of the test suite. It runs the 10 decks
in tests/fixtures/decks/decks/ three times and reports:
- agreement % per structure type (items identical in all passes / distinct items);
- the verifier's match rate and unverified rate, and how many periods it corrected (a matched value whose
  model period differed from the one Python rebuilds from its cells; the item counts as verified);
- tokens and cost per deck;
- the cache hit rate on passes 2 and 3.
Passes 2 and 3 read the cache first to get the hit rate (expected 100%), then call the model with the
cache bypassed, so agreement measures the model. Target: at least 95% agreement.

Usage (from the repository root, with ANTHROPIC_API_KEY set and a MongoDB to keep the cache in):
    python scripts/consistency_run.py --yes [--passes 3] [--deck 05-zero2hero.pdf ...] [--out report.json]
It prints one line per deck and pass, writes the report to docs/test-runs/consistency_<date>.md (-2, -3, ...
for a later run that day) and ends with the report path and a summary line; --out also writes it as JSON.
Each deck is read in its own throwaway audit (consent ticked) in the scratch database --db (default
"consistency_run"; any name must start with it), dropped at the end unless --keep-db. At start the run drops
every scratch database an earlier run left, crashed or kept. The audits stay within the 200,000-token cap;
raise LLM_DAILY_SPEND_CAP_USD if the run would pass the daily spend cap.
--fake replays empty readings with no network and no MongoDB, to check the script itself; its report goes to
the system temp folder, never to docs/test-runs.
"""
import argparse
import asyncio
import datetime
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DECKS = ROOT / "tests" / "fixtures" / "decks" / "decks"
REPORTS = ROOT / "docs" / "test-runs"
SCRATCH = "consistency_run"          # a scratch database is named this or starts with it and "_"
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
    stats = {"items": 0, "verified": 0, "unverified": 0, "not_read": 0, "model_reads": 0, "period_corrected": 0}
    per_deck = {}
    hits = {p: [0, 0] for p in range(2, passes + 1)}     # pass -> [cache hits, lookups]
    for d, file in enumerate(decks, 1):
        deck = parser.parse_deck((DECKS / file).read_bytes(), file)
        audit_id = f"consistency-{Path(file).stem}"
        audit = {"id": audit_id, "company_name": Path(file).stem, "client_name": "Consistency run",
                 "engagement_reference": "CONSISTENCY", "structure_reading_consent": True}
        await db["audits"].insert_one(dict(audit))
        usage = per_deck.setdefault(file, {"structures": len(deck["structures"]), "input_tokens": 0, "output_tokens": 0,
                                           "cost_usd": 0.0})
        sent = []                                          # (index, structure, redacted text, page)
        for i, structure in enumerate(deck["structures"]):
            types[(file, i)] = structure["type"]
            cells, _ = redact.redact_structure(structure["cells"], Path(file).stem, {}, redact.withheld_values(audit))
            sent.append((i, structure, redact.structure_text(cells), structure.get("slide") or structure.get("page")))
        for n in range(1, passes + 1):
            read, tokens_before, cost_before = 0, usage["input_tokens"] + usage["output_tokens"], usage["cost_usd"]
            for i, structure, text, page in sent:
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
                read += 1
                readings[(file, i)].append({_item_key(item) for item in result.items})
                checked = verify.verify(structure, result.items)
                stats["period_corrected"] += checked["periods_corrected"]
                for item in checked["items"]:
                    stats["items"] += 1
                    stats["verified" if item["status"] == verify.VERIFIED else "unverified"] += 1
            tokens = usage["input_tokens"] + usage["output_tokens"] - tokens_before
            print(f"[{d}/{len(decks)}] {file} pass {n}/{passes}: {read} of {len(sent)} structures read, "
                  f"{tokens:,} tokens, ${usage['cost_usd'] - cost_before:.4f}", flush=True)
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
        "period_corrected": stats["period_corrected"],
        "per_deck": per_deck,
        "cache_hit_rate_pct": {f"pass_{p}": round(100.0 * h / n, 1) if n else None for p, (h, n) in hits.items()},
        "target_agreement_pct": 95.0,
    }


def _scratch(name):
    return name == SCRATCH or name.startswith(SCRATCH + "_")


def _pct(value):
    return "n/a" if value is None else f"{value:.1f}%"


def summary(report):
    """One line: the agreement against its target, then the verifier, cache and cost figures."""
    agreement, target = report["agreement_pct_all"], report["target_agreement_pct"]
    verdict = "not measured" if agreement is None else "met" if agreement >= target else "missed"
    hits = ", ".join(f"{p.replace('_', ' ')} {_pct(r)}" for p, r in report["cache_hit_rate_pct"].items())
    cost = sum(d["cost_usd"] for d in report["per_deck"].values())
    return (f"Agreement {_pct(agreement)} (target {_pct(target)}: {verdict}); "
            f"verified {_pct(report['verifier_match_rate_pct'])}, "
            f"unverified {_pct(report['unverified_rate_pct'])}, {report['not_read']} not read, "
            f"{report['period_corrected']} periods corrected; cache hits {hits or 'n/a'}; cost ${cost:.4f}.")


def write_report(report, folder, passes, fake=False):
    """folder/consistency_<date>.md; a later run that day gets -2, -3, ... so a paid report is never overwritten."""
    from app.llm import gateway, prompt_store
    day = datetime.date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f"consistency_{day}.md", 1
    while path.exists():
        n += 1
        path = folder / f"consistency_{day}-{n}.md"
    decks = report["per_deck"]
    total = {k: sum(d[k] for d in decks.values()) for k in ("structures", "input_tokens", "output_tokens", "cost_usd")}
    lines = [
        f"# Consistency run {day}", "",
        f"{'Fake run: recorded replies, no live API.' if fake else 'Live API.'} Decks: {len(decks)}. "
        f"Passes: {passes}. Model: {gateway.STRUCTURE_MODEL}. "
        f"Prompt: {gateway.STRUCTURE_PROMPT} {prompt_store.load(gateway.STRUCTURE_PROMPT).version}. "
        "Method: docs/specs/llm-structure-reading.md section 11.", "",
        summary(report), "",
        "## Agreement per structure type", "", "| Type | Agreement |", "|---|---:|",
        *(f"| {t} | {_pct(a)} |" for t, a in report["agreement_pct"].items()),
        f"| all | {_pct(report['agreement_pct_all'])} |", "",
        "## Verifier", "",
        f"- Match rate: {_pct(report['verifier_match_rate_pct'])}",
        f"- Unverified rate: {_pct(report['unverified_rate_pct'])}",
        f"- Periods corrected: {report['period_corrected']}",
        f"- Not read: {report['not_read']}; model reads: {report['model_reads']}", "",
        "## Cache hit rate", "", "| Pass | Hit rate |", "|---|---:|",
        *(f"| {p.split('_')[1]} | {_pct(r)} |" for p, r in report["cache_hit_rate_pct"].items()), "",
        "## Tokens and cost per deck", "", "| Deck | Structures | Input tokens | Output tokens | Cost USD |",
        "|---|---:|---:|---:|---:|",
        *(f"| {f} | {d['structures']} | {d['input_tokens']:,} | {d['output_tokens']:,} | {d['cost_usd']:.4f} |"
          for f, d in decks.items()),
        f"| all | {total['structures']} | {total['input_tokens']:,} | {total['output_tokens']:,} | "
        f"{total['cost_usd']:.4f} |",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def live(args, decks):
    """The whole live run in one event loop. Motor binds a client to the loop of its first call, so a drop in a
    second asyncio.run found that loop closed ("Event loop is closed") and the report was never written."""
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    try:
        for name in await client.list_database_names():
            if _scratch(name):
                await client.drop_database(name)
                print(f"Dropped scratch database {name} left by an earlier run", flush=True)
        try:
            report = await run(decks, args.passes, client[args.db])
            return report, write_report(report, REPORTS, args.passes)     # before the drop: a failed drop keeps it
        finally:
            if not args.keep_db:
                await client.drop_database(args.db)
    finally:
        client.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--deck", action="append", help="a deck file name in tests/fixtures/decks/decks/ (default: all 10)")
    ap.add_argument("--db", default=SCRATCH, help=f"the scratch database: {SCRATCH} or a name starting {SCRATCH}_")
    ap.add_argument("--keep-db", action="store_true", help="keep the scratch database until the next run")
    ap.add_argument("--out", help="also write the report as JSON to this file")
    ap.add_argument("--yes", action="store_true", help="confirm the live API may be called and billed")
    ap.add_argument("--fake", action="store_true", help="no network, no MongoDB: check the script itself")
    args = ap.parse_args(argv)
    decks = args.deck or sorted(p.name for p in DECKS.iterdir() if not p.name.startswith("."))
    if args.fake:
        report = asyncio.run(run(decks, args.passes, MemoryDB(), FakeAdapter()))
        path = write_report(report, Path(tempfile.gettempdir()), args.passes, fake=True)
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY is not set: this script calls the live API.")
        if not args.yes:
            sys.exit("This run calls the live API and costs money. Re-run with --yes to confirm.")
        if not _scratch(args.db):
            sys.exit(f"--db must be {SCRATCH} or start with {SCRATCH}_: the run drops it at the end.")
        report, path = asyncio.run(live(args, decks))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {path}")
    print(summary(report))
    return report


if __name__ == "__main__":
    main()
