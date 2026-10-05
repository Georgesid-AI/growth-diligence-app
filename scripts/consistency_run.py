"""Consistency run for model reading of deck structures (docs/specs/llm-structure-reading.md section 11).

MANUAL. It calls the live API and costs money; it is not part of the test suite. It runs the 10 decks
in tests/fixtures/decks/decks/ three times and reports:
- agreement % per structure type (items identical in all passes / distinct items), an item compared on its
  metric, period, value and value cell after the verifier's normalisation; beside it the old figure, every
  field compared as the model wrote it;
- for every structure whose passes disagree, the fields that differ, with a count per structure type;
- the verifier's match rate and unverified rate over the items outside roadmaps, and how many periods it
  corrected (a matched value whose model period differed from the one Python rebuilds from its cells; the item
  counts as verified);
- for every unverified item outside a roadmap, the reason, with a count per structure type;
- roadmap items apart: how many, and how many of their dates Python rebuilt from the cited cells;
- tokens and cost per deck, the fixed prompt's tokens and the average structure-text tokens;
- the cache hit rate on passes 2 and 3.
Passes 2 and 3 look the cache up first to get the hit rate (expected 100%; the lookup never calls the model),
then call the model with the cache bypassed, so agreement measures the model. Target: at least 95% agreement.

Usage (from the repository root, with ANTHROPIC_API_KEY set and a MongoDB to keep the cache in):
    python scripts/consistency_run.py --yes [--passes 3] [--deck 05-zero2hero.pdf ...] [--out report.json]
                                      [--pause 2] [--diagnostic]
It waits --pause seconds (default 2) between structure calls; the gateway retries a 429 or 529 itself. It prints
one line per deck and pass, writes the report to docs/test-runs/consistency_<date>.md (-2, -3, ... for a later
run that day) and ends with the report path, a summary line and the full report; --out also writes it as JSON.
Reports are untracked and lost on re-import; copy the printed report out before re-importing.
--diagnostic also writes <report>_diagnostic.md beside the report (and prints its path, not its text): for every
unverified item and every disagreeing structure, deck, page, cell id, the cell's text as sent to the model, the
model's metric, value, unit and period in each pass, and the verifier's result. It holds deck text, so it runs on the
10 public test decks only: any other deck, by file name and SHA-256, is refused before anything is read.
A failed model call or token count logs one "structure not read" line to stderr, with its reason, HTTP status
and error type; a structure the daily spend cap or the token cap refuses logs one with reason=spend_cap or
reason=token_cap.
Each deck is read in its own throwaway audit (consent ticked) in the scratch database --db (default
"consistency_run"; any name must start with it), dropped at the end unless --keep-db. At start the run drops
every scratch database an earlier run left, crashed or kept. The audits stay within the 400,000-token cap;
raise LLM_DAILY_SPEND_CAP_USD if the run would pass the daily spend cap.
--fake replays empty readings with no network and no MongoDB, to check the script itself; its report goes to
the system temp folder, never to docs/test-runs.
"""
import argparse
import asyncio
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DECKS = ROOT / "tests" / "fixtures" / "decks" / "decks"
REPORTS = ROOT / "docs" / "test-runs"
SCRATCH = "consistency_run"          # a scratch database is named this or starts with it and "_"
# The 10 public test decks (tests/fixtures/decks/README.md): file name -> SHA-256 of the file. --diagnostic writes
# cell text and runs on these only.
PUBLIC_DECKS = {
    "01-front-b.pptx": "d37b20a89c01b072a0e4300f3811e47811550ed19a67e7314ec3c7fb1ef882b0",
    "02-moz.pdf": "902c1fdbb21210e6611325012fca4b663da32d50493e19cb8ab69b499b51c1e7",
    "03-buffer.pptx": "bb298b81ef4b2b2bf25661674275c24d7964a2223081351aeb761763b28f876f",
    "04-clevergig.docx": "99d18ecc059eb0f5b838ea03d379a0d502d64ca74a4f94fba5386561b0cc5167",
    "05-zero2hero.pdf": "08cf5173c0d9d312d1cb4a984f56b48117d365bcc1e06c37a929560c6e56dfe5",
    "06-uber.pdf": "dd45d5c79cab6a8ada45b0a99e2c4cc21c75447f1b96b7753ffa95a33141d803",
    "07-equals-seed.docx": "ab89bd498f48b0d27dd3d2fe79a963ba1bd9bfd9cfee568cb7c3606b5f35b604",
    "08-genesisai-2021.pdf": "b02df6adc90b2a45ca823466dbdf4c4613e28a909790478606e1de4523f6f93a",
    "09-genesisai-2024.pdf": "4cd9c6e091468faa36a8f1a71bb6ae62ea960bd175adee0c8302b5a3ee5bc458",
    "10-tea.pdf": "db9b0e2bee1e1855dd62df6a359e4a67683459a3fe34fc5fb616e617f26bcad9",
}
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
        """A stand-in for the provider's counter: one token per 4 characters of what would be sent."""
        return (len(system or "") + len(user_payload) + (len(json.dumps(json_schema)) if json_schema else 0)) // 4

    def complete(self, *, model, system, user_payload, max_tokens, temperature, json_schema):
        sent = json.loads(user_payload)
        reply = next((f["reply"] for f in self.fixtures if f["type"] == sent["type"] and f["match"] in sent["text"]),
                     {"type": sent["type"], "items": []})
        return json.dumps(reply), 1000, 20


FIELDS = ("metric", "period", "value", "unit", "cell", "other", "items")
REASONS = ("value not in cell", "period not rebuilt", "lowest-header rule", "metric invalid", "other")


def _unit(item):
    """The unit as written; for "other", the ISO code the model gave beside it."""
    return item.get("unit_other") if item.get("unit") == "other" else item.get("unit")


def _item_key(item):
    """The old agreement key: every field the model returns, as it wrote it."""
    return (item["metric"], item.get("period"), item.get("value"), _unit(item), item.get("actual_or_forecast"),
            item["value_cell"], tuple(item.get("period_cells") or ()), tuple(item.get("proposed_flags") or ()))


def _normalised_key(item, fiscal_year_end=12):
    """The agreement key: metric, period, value and value cell of an item the verifier has checked. The period is
    the one the verifier keeps (Python's rebuilt period replaces the model's when the value matches), compared as
    its start and end dates, so "FY2023" and "2023" are one period under a December year-end; the value is
    compared as a number. Unit, actual or forecast, period cells and flags are left out."""
    from app.decks import claims
    period, value = item.get("period"), item.get("value")
    return (item["metric"], (claims.period_range(period, fiscal_year_end) or period) if period else None,
            None if value is None else float(value), item["value_cell"])


_COMPARED = {
    "metric": lambda i: i["metric"],
    "period": lambda i: i.get("period"),
    "value": lambda i: None if i.get("value") is None else float(i["value"]),
    "unit": _unit,
    "other": lambda i: (i.get("actual_or_forecast"), tuple(i.get("period_cells") or ()),
                        tuple(i.get("proposed_flags") or ())),
}


def differing_fields(passes):
    """The FIELDS in which the passes' readings of one structure differ, as the model wrote them. Items are lined
    up by value cell: "cell" when a cell is cited in some passes only, "items" when the passes list a different
    number of items; at a cell every pass cites, each of metric, period, value, unit and "other" (actual or
    forecast, period cells, flags) whose values there differ."""
    found = set()
    if len({len(items) for items in passes}) > 1:
        found.add("items")
    cited = [{item["value_cell"] for item in items} for items in passes]
    if any(cells != cited[0] for cells in cited[1:]):
        found.add("cell")
    for cell in set.intersection(*cited):
        for name, get in _COMPARED.items():
            seen = [sorted(repr(get(i)) for i in items if i["value_cell"] == cell) for items in passes]
            if any(s != seen[0] for s in seen[1:]):
                found.add(name)
    return [f for f in FIELDS if f in found]


def unverified_reason(structure, item):
    """(reason, detail) for an item the verifier left unverified: the first that applies.
    - "metric invalid": not a metric the gateway accepts for a deck structure. The gateway rejects such a reply
      whole (one reask, then "Not read by AI"), so a live run counts it under not read, not here.
    - "other", "no value": an item with no value is never verified.
    - "value not in cell": the value is not the number its value cell holds after normalisation.
    - "lowest-header rule": the first period cell is a period header of the value cell but not its lowest one
      (a quarterly value cited against its year header), or the value has period headers above and beside it.
    - "period not rebuilt": any other period miss: the period cells give no period or one with other dates, or
      the period and its cells disagree on whether there is one.
    - "other", "flag not reproduced": value and period match, a proposed flag does not."""
    from app.decks import claims
    from app.llm import schemas
    from app.structures import redact, verify
    if item["metric"] not in schemas.CLAIM_METRICS + ("use_of_funds",):
        return "metric invalid", None
    if item.get("value") is None:
        return "other", "no value"
    if not item["checks"]["value"]:
        return "value not in cell", None
    if not item["checks"]["period"]:
        cited = item.get("period_cells") or []
        cell = next(c for c in structure["cells"] if redact.cell_id(c) == item["value_cell"])
        headers = {redact.cell_id(h) for h in verify.header_cells(structure, cell) if claims.period_cell(h["text"])}
        lowest = [redact.cell_id(h) for h in verify.lowest_period_headers(structure, cell)]
        if cited and cited[0] in headers and lowest != cited[:1]:
            return "lowest-header rule", None
        return "period not rebuilt", None
    return "other", "flag not reproduced"


async def _count(counter, **kwargs):
    """The provider's token count (no call is billed), or None: a failed count never stops a paid run."""
    from app.llm import gateway
    try:
        return int(await asyncio.to_thread(counter.count_tokens, model=gateway.STRUCTURE_MODEL, **kwargs))
    except Exception:
        return None


async def fixed_tokens(counter):
    """The tokens of a structure call with an empty structure text, and of its parts: the system prompt and the
    output schema, each counted with the empty message and less the empty message alone."""
    from app.llm import cache, gateway, prompt_store, schemas
    system, schema = prompt_store.load(gateway.STRUCTURE_PROMPT).text, schemas.structure_output_schema()
    payload = cache.canonical_json({"type": "table", "text": ""})      # as read_structure builds it, text empty
    empty = await _count(counter, system=None, user_payload=payload, json_schema=None)
    prompt = await _count(counter, system=system, user_payload=payload, json_schema=None)
    output = await _count(counter, system=None, user_payload=payload, json_schema=schema)
    fixed = await _count(counter, system=system, user_payload=payload, json_schema=schema)
    less = lambda n: None if n is None or empty is None else n - empty  # noqa: E731
    return {"fixed_prompt": fixed, "system_prompt": less(prompt), "output_schema": less(output), "empty_message": empty}


def _rate(part, whole):
    return round(100.0 * part / whole, 1) if whole else None


def _agreement(readings, types, key):
    """(% per type, % over all) of items identical in all passes / distinct items, items compared by `key`
    ("raw" or "norm"); a structure not read in some pass is left out."""
    agreement = defaultdict(lambda: [0, 0])                # type -> [identical in all passes, distinct]
    for where, passes_read in readings.items():
        if any(r is None for r in passes_read):
            continue
        keys = [r[key] for r in passes_read]
        agreement[types[where]][0] += len(set.intersection(*keys)) if keys else 0
        agreement[types[where]][1] += len(set().union(*keys))
    return ({t: _rate(a, d) for t, (a, d) in sorted(agreement.items())},
            _rate(sum(a for a, _ in agreement.values()), sum(d for _, d in agreement.values())))


def _disagreements(readings, types, pages):
    """The structures read in every pass whose passes differ (every field, as written), with the fields that
    differ, and per structure type the number of such structures and of each field."""
    rows, by_type = [], {}
    for where, passes_read in readings.items():
        if any(r is None for r in passes_read):
            continue
        count = by_type.setdefault(types[where], dict.fromkeys(("structures", "disagreeing") + FIELDS, 0))
        count["structures"] += 1
        if all(r["raw"] == passes_read[0]["raw"] for r in passes_read):
            continue
        fields = differing_fields([r["items"] for r in passes_read])
        count["disagreeing"] += 1
        for field in fields:
            count[field] += 1
        rows.append({"deck": where[0], "page": pages[where], "type": types[where], "fields": fields,
                     "same_after_normalisation": all(r["norm"] == passes_read[0]["norm"] for r in passes_read)})
    return rows, dict(sorted(by_type.items()))


def _verdict(structure, item):
    """The verifier's result for one checked item: verified, or the reason it is not."""
    from app.structures import verify
    if item["status"] == verify.VERIFIED:
        return "verified"
    reason, detail = unverified_reason(structure, item)
    return f"{reason} ({detail})" if detail else reason


def _at_cell(reading, structure, cell):
    """What one pass read at a value cell: None when the structure was not read in it, else for every item citing
    the cell the model's metric, value, unit and period as written, and the verifier's result."""
    if reading is None:
        return None
    return [{"metric": item["metric"], "value": item.get("value"), "unit": _unit(item), "period": item.get("period"),
             "verifier": _verdict(structure, checked)}
            for item, checked in zip(reading["items"], reading["checked"]) if item["value_cell"] == cell]


def _cell_order(cell):
    return tuple(int(n) for n in re.findall(r"\d+", cell))


def diagnostic_rows(readings, unverified, types, pages, texts, structures):
    """--diagnostic: one row per unverified item outside a roadmap (the report's list), then one per cell of each
    disagreeing structure whose readings differ between passes as the model wrote them. A row carries the cell's
    text as sent to the model, so it goes to the diagnostic file only, never to the report."""
    def row(section, where, cell, reason):
        return {"section": section, "deck": where[0], "page": pages[where], "type": types[where], "cell": cell,
                "cell_text": texts[where].get(cell, ""), "reason": reason,
                "passes": [_at_cell(r, structures[where], cell) for r in readings[where]]}
    rows = [row("unverified", (f, i), cell, f"{reason} ({detail})" if detail else reason)
            for f, i, cell, reason, detail in unverified]
    for where, passes_read in readings.items():
        if any(r is None for r in passes_read) or all(r["raw"] == passes_read[0]["raw"] for r in passes_read):
            continue
        for cell in sorted({item["value_cell"] for r in passes_read for item in r["items"]}, key=_cell_order):
            seen = [sorted(repr(_item_key(i)) for i in r["items"] if i["value_cell"] == cell) for r in passes_read]
            if any(s != seen[0] for s in seen[1:]):
                rows.append(row("disagreeing", where, cell, None))
    return rows


async def run(decks, passes, db, adapter=None, pause=0.0, sleep=None, diagnostic=None):
    """`pause` seconds between structure calls, so a burst does not hit the provider's rate limit. A `diagnostic`
    list gets the rows of diagnostic_rows; the report itself is the same either way."""
    from app.decks import parser
    from app.llm import gateway
    from app.structures import redact, verify

    sleep = sleep or asyncio.sleep
    counter = adapter or gateway.AnthropicAdapter()       # token counts only; read_structure gets `adapter`
    tokens = await fixed_tokens(counter)
    text_tokens = []                                       # per structure sent, the gateway's 3,000-token measure
    readings = defaultdict(list)    # (deck, index) -> per pass None (not read) or {"raw", "norm", "items", "checked"}
    types, pages = {}, {}
    texts, structures = {}, {}                           # (deck, index) -> {cell id: text as sent}, the structure
    stats = {"items": 0, "verified": 0, "unverified": 0, "not_read": 0, "model_reads": 0, "period_corrected": 0,
             "roadmap_items": 0, "roadmap_dates_rebuilt": 0}
    reasons = {}                                           # type -> {reason: unverified items over all passes}
    unverified = {}                                        # (deck, index, cell, reason, detail) -> {passes}
    per_deck = {}
    hits = {p: [0, 0] for p in range(2, passes + 1)}     # pass -> [cache hits, lookups]
    keys = {}                                              # (deck, index) -> the cache key of its last reading
    calls = 0
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
            pages[(file, i)] = structure.get("slide") or structure.get("page")
            cells, _ = redact.redact_structure(structure["cells"], Path(file).stem, {}, redact.withheld_values(audit))
            texts[(file, i)], structures[(file, i)] = {redact.cell_id(c): c["text"] for c in cells}, structure
            sent.append((i, structure, redact.structure_text(cells), pages[(file, i)]))
            text_tokens.append(await _count(counter, system=None, user_payload=sent[-1][2], json_schema=None))
        for n in range(1, passes + 1):
            read, tokens_before, cost_before = 0, usage["input_tokens"] + usage["output_tokens"], usage["cost_usd"]
            for i, structure, text, page in sent:
                if n > 1:                   # the cache only: a miss must not call the model a second time
                    key = keys.get((file, i))
                    hits[n][0] += int(bool(key) and await gateway.stored_structure(db, audit_id, key) is not None)
                    hits[n][1] += 1
                if calls and pause:
                    await sleep(pause)
                calls += 1
                result = await gateway.read_structure(db, audit_id, text, structure["type"], deck_id=file, page=page,
                                                      adapter=adapter, use_cache=n == 1)
                keys[(file, i)] = result.key
                stats["model_reads"] += int(not result.cache_hit)       # agreement needs the model, not the cache
                usage["input_tokens"] += result.input_tokens
                usage["output_tokens"] += result.output_tokens
                usage["cost_usd"] = round(usage["cost_usd"] + result.estimated_cost_usd, 6)
                if result.status != "read":
                    stats["not_read"] += 1
                    readings[(file, i)].append(None)
                    continue
                read += 1
                checked = verify.verify(structure, result.items)
                readings[(file, i)].append({"raw": {_item_key(item) for item in result.items},
                                            "norm": {_normalised_key(item) for item in checked["items"]},
                                            "items": result.items, "checked": checked["items"]})
                stats["period_corrected"] += checked["periods_corrected"]
                for item in checked["items"]:
                    if structure["type"] == "roadmap":          # apart from the rates: a milestone has no value
                        stats["roadmap_items"] += 1
                        stats["roadmap_dates_rebuilt"] += int(item.get("period") is not None
                                                              and item["checks"]["period"])
                        continue
                    stats["items"] += 1
                    if item["status"] == verify.VERIFIED:
                        stats["verified"] += 1
                        continue
                    stats["unverified"] += 1
                    reason, detail = unverified_reason(structure, item)
                    reasons.setdefault(structure["type"], dict.fromkeys(REASONS, 0))[reason] += 1
                    unverified.setdefault((file, i, item["value_cell"], reason, detail), set()).add(n)
            spent = usage["input_tokens"] + usage["output_tokens"] - tokens_before
            print(f"[{d}/{len(decks)}] {file} pass {n}/{passes}: {read} of {len(sent)} structures read, "
                  f"{spent:,} tokens, ${usage['cost_usd'] - cost_before:.4f}", flush=True)
    if diagnostic is not None:
        diagnostic.extend(diagnostic_rows(readings, unverified, types, pages, texts, structures))
    agreement, agreement_all = _agreement(readings, types, "norm")
    agreement_old, agreement_all_old = _agreement(readings, types, "raw")
    disagreements, disagreement_fields = _disagreements(readings, types, pages)
    counted = [t for t in text_tokens if t is not None]
    tokens["structure_text_avg"] = round(sum(counted) / len(counted), 1) if counted else None
    tokens["structures_counted"] = len(counted)
    tokens["billed_input_per_model_read"] = (round(sum(u["input_tokens"] for u in per_deck.values())
                                                   / stats["model_reads"], 1) if stats["model_reads"] else None)
    return {
        "agreement_pct": agreement,
        "agreement_pct_all": agreement_all,
        "agreement_pct_old": agreement_old,
        "agreement_pct_all_old": agreement_all_old,
        "disagreements": disagreements,
        "disagreement_fields": disagreement_fields,
        "verifier_match_rate_pct": _rate(stats["verified"], stats["items"]),
        "unverified_rate_pct": _rate(stats["unverified"], stats["items"]),
        "unverified_reasons": dict(sorted(reasons.items())),
        "unverified_items": [{"deck": f, "page": pages[(f, i)], "type": types[(f, i)], "value_cell": cell,
                              "reason": reason, "detail": detail, "passes": len(seen)}
                             for (f, i, cell, reason, detail), seen in unverified.items()],
        "roadmap_items": stats["roadmap_items"],
        "roadmap_dates_rebuilt": stats["roadmap_dates_rebuilt"],
        "not_read": stats["not_read"],
        "model_reads": stats["model_reads"],
        "period_corrected": stats["period_corrected"],
        "tokens": tokens,
        "per_deck": per_deck,
        "cache_hit_rate_pct": {f"pass_{p}": round(100.0 * h / n, 1) if n else None for p, (h, n) in hits.items()},
        "target_agreement_pct": 95.0,
    }


def _scratch(name):
    return name == SCRATCH or name.startswith(SCRATCH + "_")


def _pct(value):
    return "n/a" if value is None else f"{value:.1f}%"


def _tokens(value):
    return "n/a" if value is None else f"{value:,}"


def _disagreement_lines(report):
    rows, by_type = report["disagreements"], report["disagreement_fields"]
    return [
        "## Where passes disagree", "",
        "Structures read in every pass whose readings differ in any field, as the model wrote it (the old method). "
        "Items are lined up by value cell: cell = a cell cited in some passes only; items = the passes list a "
        "different number of items; other = actual or forecast, period cells or flags. Each count is a number of "
        "structures.", "",
        "| Type | Structures | Disagreeing | " + " | ".join(FIELDS) + " |", "|---|" + "---:|" * (len(FIELDS) + 2),
        *(f"| {t} | {c['structures']} | {c['disagreeing']} | " + " | ".join(str(c[f]) for f in FIELDS) + " |"
          for t, c in by_type.items()), "",
        *(["| Deck | Page | Type | Fields that differ | Same after normalisation |", "|---|---:|---|---|---|",
           *(f"| {r['deck']} | {r['page']} | {r['type']} | {', '.join(r['fields'])} | "
             f"{'yes' if r['same_after_normalisation'] else 'no'} |" for r in rows)]
          if rows else ["Every structure read in every pass was read the same way in each."]), "",
    ]


def _reason(row):
    return f"{row['reason']} ({row['detail']})" if row["detail"] else row["reason"]


def _reason_lines(report):
    by_type, rows = report["unverified_reasons"], report["unverified_items"]
    total = {r: sum(c[r] for c in by_type.values()) for r in REASONS}
    return [
        "## Unverified items: reasons", "",
        "One reason per unverified item outside a roadmap, the first that applies: metric invalid, other (no value), "
        "value not in cell, lowest-header rule, period not rebuilt, other (flag not reproduced). Counts are over all "
        "passes. "
        "Metric invalid stays 0 on a live run: the gateway rejects a reply with such a metric whole, and the "
        "structure counts as not read.", "",
        "| Type | " + " | ".join(REASONS) + " | Unverified |", "|---|" + "---:|" * (len(REASONS) + 1),
        *(f"| {t} | " + " | ".join(str(c[r]) for r in REASONS) + f" | {sum(c.values())} |" for t, c in by_type.items()),
        "| all | " + " | ".join(str(total[r]) for r in REASONS) + f" | {sum(total.values())} |", "",
        *(["| Deck | Page | Type | Cell | Reason | Passes |", "|---|---:|---|---|---|---:|",
           *(f"| {r['deck']} | {r['page']} | {r['type']} | {r['value_cell']} | {_reason(r)} | {r['passes']} |"
             for r in rows)]
          if rows else ["No unverified item."]), "",
    ]


def summary(report):
    """One line: the agreement against its target and the old figure, then the verifier, cache and cost figures."""
    agreement, target = report["agreement_pct_all"], report["target_agreement_pct"]
    verdict = "not measured" if agreement is None else "met" if agreement >= target else "missed"
    hits = ", ".join(f"{p.replace('_', ' ')} {_pct(r)}" for p, r in report["cache_hit_rate_pct"].items())
    cost = sum(d["cost_usd"] for d in report["per_deck"].values())
    return (f"Agreement {_pct(agreement)} (target {_pct(target)}: {verdict}; "
            f"old method {_pct(report['agreement_pct_all_old'])}); "
            f"verified {_pct(report['verifier_match_rate_pct'])}, "
            f"unverified {_pct(report['unverified_rate_pct'])}, {report['not_read']} not read; "
            f"roadmap items: {report['roadmap_items']}, date rebuilt from cell: {report['roadmap_dates_rebuilt']}; "
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
    decks, tokens = report["per_deck"], report["tokens"]
    total = {k: sum(d[k] for d in decks.values()) for k in ("structures", "input_tokens", "output_tokens", "cost_usd")}
    lines = [
        f"# Consistency run {day}", "",
        f"{'Fake run: recorded replies, no live API.' if fake else 'Live API.'} Decks: {len(decks)}. "
        f"Passes: {passes}. Model: {gateway.STRUCTURE_MODEL}. "
        f"Prompt: {gateway.STRUCTURE_PROMPT} {prompt_store.load(gateway.STRUCTURE_PROMPT).version}. "
        "Method: docs/specs/llm-structure-reading.md section 11.", "",
        summary(report), "",
        "## Agreement per structure type", "",
        "Items identical in all passes / distinct items. Agreement compares an item's metric, period, value and "
        "value cell after the verifier's normalisation: the period the verifier keeps, as its start and end dates, "
        "and the value as a number. The old method compares every field as the model wrote it.", "",
        "| Type | Agreement | Old method |", "|---|---:|---:|",
        *(f"| {t} | {_pct(a)} | {_pct(report['agreement_pct_old'].get(t))} |"
          for t, a in report["agreement_pct"].items()),
        f"| all | {_pct(report['agreement_pct_all'])} | {_pct(report['agreement_pct_all_old'])} |", "",
        *_disagreement_lines(report),
        "## Verifier", "",
        "Rates over the items outside roadmaps. A roadmap item's date is rebuilt from cell when Python rebuilds "
        "its period from the cited period cells and it matches.", "",
        f"- Match rate: {_pct(report['verifier_match_rate_pct'])}",
        f"- Unverified rate: {_pct(report['unverified_rate_pct'])}",
        f"- Periods corrected: {report['period_corrected']}",
        f"- Roadmap items: {report['roadmap_items']}, date rebuilt from cell: {report['roadmap_dates_rebuilt']}",
        f"- Not read: {report['not_read']}; model reads: {report['model_reads']}", "",
        *_reason_lines(report),
        "## Cache hit rate", "", "| Pass | Hit rate |", "|---|---:|",
        *(f"| {p.split('_')[1]} | {_pct(r)} |" for p, r in report["cache_hit_rate_pct"].items()), "",
        "## Tokens and cost per deck", "", "| Deck | Structures | Input tokens | Output tokens | Cost USD |",
        "|---|---:|---:|---:|---:|",
        *(f"| {f} | {d['structures']} | {d['input_tokens']:,} | {d['output_tokens']:,} | {d['cost_usd']:.4f} |"
          for f, d in decks.items()),
        f"| all | {total['structures']} | {total['input_tokens']:,} | {total['output_tokens']:,} | "
        f"{total['cost_usd']:.4f} |", "",
        "## Tokens per call", "",
        "By the provider's token counter, which bills nothing. The fixed prompt is a call with an empty structure "
        "text; its parts are each counted with the empty message, less the empty message alone.", "",
        f"- Fixed prompt: {_tokens(tokens['fixed_prompt'])} (system prompt {_tokens(tokens['system_prompt'])}, "
        f"output schema {_tokens(tokens['output_schema'])}, empty message {_tokens(tokens['empty_message'])})",
        f"- Structure text, average of {tokens['structures_counted']} structures: "
        f"{_tokens(tokens['structure_text_avg'])} (the gateway's 3,000-token measure: the text alone)",
        f"- Billed input per model read: {_tokens(tokens['billed_input_per_model_read'])}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _md(text):
    """A markdown table cell: line breaks as spaces, a pipe escaped."""
    return " ".join(str(text).splitlines()).replace("|", "\\|")


def _number(value):
    return "null" if value is None else str(int(value)) if float(value).is_integer() else repr(float(value))


def _pass_text(found):
    """One pass at a cell: each item as metric, value, unit, period, then the verifier's result."""
    if found is None:
        return "not read"
    return "; ".join(f"{s['metric']} {_number(s['value'])} {s['unit'] or 'null'} {s['period'] or 'null'}: "
                     f"{s['verifier']}" for s in found) or "no item"


def diagnostic_path(report_path):
    return report_path.with_name(f"{report_path.stem}_diagnostic.md")


def write_diagnostic(rows, report_path, passes):
    """<report>_diagnostic.md beside the report, from diagnostic_rows. It holds the text of cells as sent to the
    model, so main writes it for the 10 public test decks only; the boundary test leaves it out by this name."""
    path = diagnostic_path(report_path)
    heads = " | ".join(f"Pass {n}" for n in range(1, passes + 1))

    def line(row, reason):
        cells = [row["deck"], row["page"], row["type"], row["cell"], _md(row["cell_text"]),
                 *([_md(row["reason"])] if reason else []), *(_md(_pass_text(found)) for found in row["passes"])]
        return "| " + " | ".join(str(c) for c in cells) + " |"
    unverified = [line(r, True) for r in rows if r["section"] == "unverified"]
    disagreeing = [line(r, False) for r in rows if r["section"] == "disagreeing"]
    lines = [
        f"# Consistency run {report_path.stem.split('_', 1)[1]}: diagnostic", "",
        "Public test decks only: --diagnostic refuses any other deck. This file holds the text of cells as sent to "
        "the model; the report beside it holds none. A pass gives, for every item citing the cell, the model's "
        "metric, value, unit and period as written, then the verifier's result: verified or the reason. "
        "No item: the pass cited nothing there; not read: the structure was not read in that pass.", "",
        "## Unverified items", "", "Every unverified item outside a roadmap, as listed in the report.", "",
        *([f"| Deck | Page | Type | Cell | Cell text | Reason | {heads} |",
           "|---|---:|---|---|---|---|" + "---|" * passes, *unverified] if unverified else ["No unverified item."]), "",
        "## Disagreeing structures", "",
        "Every cell whose readings differ between passes, as the model wrote them.", "",
        *([f"| Deck | Page | Type | Cell | Cell text | {heads} |", "|---|---:|---|---|---|" + "---|" * passes,
           *disagreeing] if disagreeing else ["Every structure read in every pass was read the same way in each."]),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def not_public(decks):
    """The first deck that is not one of the 10 public test decks, by file name and SHA-256, or None."""
    for name in decks:
        path = DECKS / name
        if name not in PUBLIC_DECKS or not path.is_file() or \
                hashlib.sha256(path.read_bytes()).hexdigest() != PUBLIC_DECKS[name]:
            return name
    return None


async def live(args, decks, rows=None):
    """The whole live run in one event loop. Motor binds a client to the loop of its first call, so a drop in a
    second asyncio.run found that loop closed ("Event loop is closed") and the report was never written. `rows`
    (--diagnostic) collects the diagnostic, written beside the report, before the drop too."""
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    try:
        for name in await client.list_database_names():
            if _scratch(name):
                await client.drop_database(name)
                print(f"Dropped scratch database {name} left by an earlier run", flush=True)
        try:
            report = await run(decks, args.passes, client[args.db], pause=args.pause, diagnostic=rows)
            path = write_report(report, REPORTS, args.passes)            # before the drop: a failed drop keeps it
            if rows is not None:
                write_diagnostic(rows, path, args.passes)
            return report, path
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
    ap.add_argument("--pause", type=float, default=2.0,
                    help="seconds between structure calls on a live run (default 2; --fake does not pause)")
    ap.add_argument("--yes", action="store_true", help="confirm the live API may be called and billed")
    ap.add_argument("--fake", action="store_true", help="no network, no MongoDB: check the script itself")
    ap.add_argument("--diagnostic", action="store_true",
                    help="also write <report>_diagnostic.md with each cell's text (the 10 public test decks only)")
    args = ap.parse_args(argv)
    decks = args.deck or sorted(p.name for p in DECKS.iterdir() if not p.name.startswith("."))
    outside = not_public(decks) if args.diagnostic else None
    if outside is not None:
        sys.exit(f"--diagnostic runs on the 10 public test decks only: {outside} is not one of them "
                 "(checked by file name and SHA-256).")
    rows = [] if args.diagnostic else None
    if args.fake:
        report = asyncio.run(run(decks, args.passes, MemoryDB(), FakeAdapter(), diagnostic=rows))
        path = write_report(report, Path(tempfile.gettempdir()), args.passes, fake=True)
        if rows is not None:
            write_diagnostic(rows, path, args.passes)
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY is not set: this script calls the live API.")
        if not args.yes:
            sys.exit("This run calls the live API and costs money. Re-run with --yes to confirm.")
        if not _scratch(args.db):
            sys.exit(f"--db must be {SCRATCH} or start with {SCRATCH}_: the run drops it at the end.")
        report, path = asyncio.run(live(args, decks, rows))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {path}")
    if rows is not None:
        print(f"Diagnostic: {diagnostic_path(path)}")                  # its path only: its cell text stays in the file
    print(summary(report))
    print(path.read_text(encoding="utf-8"), end="", flush=True)     # untracked: lost on re-import, copy it out
    return report


if __name__ == "__main__":
    main()
