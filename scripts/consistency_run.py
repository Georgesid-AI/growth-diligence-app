"""Consistency run for model reading of deck structures (docs/specs/structure-labelling.md sections 6 and 7;
docs/specs/llm-structure-reading.md section 11 for the rest of the method).

MANUAL. It calls the live API and costs money; it is not part of the test suite. It runs the 10 decks
in tests/fixtures/decks/decks/ three times and reports:
- agreement % per structure type: items with the same metric and period in every pass / items Python listed,
  over structures read in every pass. The period is compared as the verifier keeps it (start and end dates),
  and not_a_metric counts as a metric; cells and the item count are fixed by code. Beside it the old method:
  metric, period as written, unit and actual or forecast. The 95% target applies to the figure over all types;
- for every structure whose passes disagree, the fields that differ (metric, period, unit, actual_or_forecast),
  with a count per structure type;
- the verifier's match rate and unverified rate over the labelled items (not_a_metric dropped, milestones
  left out), and the match rate apart for the financial items (outside roadmaps) and the roadmap figures; how
  many periods it corrected, and for every unverified item the reason (period not rebuilt, metric invalid,
  other), with a count per structure type;
- per type the not_a_metric and other labels, the ambiguous readings and the items with a flag;
- roadmap lines apart: "roadmap lines: N, dated by position: P, same pair and category in every pass: M, same date
  and category: D, date rebuilt from cell: K": P the lines with a position date, M the model's pairs alike in every
  pass, D the milestone the analyst sees alike (paired or not, the date Python keeps, the category), K the lines whose
  period Python rebuilds from their own period cells, whatever the pair says;
- tokens and cost per deck, the fixed prompt's tokens and the average structure text plus item list against
  the gateway's 4,000-token cap;
- the cache hit rate on passes 2 and 3.
Passes 2 and 3 look the cache up first to get the hit rate (expected 100%; the lookup never calls the model),
then call the model with the cache bypassed, so agreement measures the model. Target: at least 95% agreement.

Usage (from the repository root, with ANTHROPIC_API_KEY set and a MongoDB to keep the cache in):
    python scripts/consistency_run.py --yes [--passes 3] [--deck 05-zero2hero.pdf ...] [--out report.json]
                                      [--pause 2] [--diagnostic]
It waits --pause seconds (default 2) between structure calls; the gateway retries a 429 or 529 itself. It prints
one line per deck and pass, writes the report to docs/test-runs/consistency_<date>.md (-2, -3, ... for a later
run that day) and ends with the report path, a summary line and the full report; --out also writes it as JSON.
Reports and diagnostics are tracked by git (docs/test-runs/README.md): commit both after a run, so its numbers stay
with the code it measured.
--diagnostic also writes <report>_diagnostic.md beside the report (and prints its path, not its text): for every
unverified item and every item labelled differently between passes, deck, page, type, item id, cell#position,
the cell's text as sent to the model, Python's values, the reason, then per pass the model's metric, period, unit
and actual_or_forecast and the verifier's result; then every line of the roadmaps read in every pass, with its
position date and, in each pass, the date it is paired with (id, cell and text) and its category, or no pair. It holds deck text, so it runs on
the 10 public test decks only:
any other deck, by file name and SHA-256, is refused before anything is read.
A failed model call or token count logs one "structure not read" line to stderr, with its reason, HTTP status
and error type, and for a reply that fails validation the check it failed (check=schema, metric_list, item_count
or other); a structure the daily spend cap or the token cap refuses logs one with reason=spend_cap or
reason=token_cap.
Each deck is read in its own throwaway audit (consent ticked) in the scratch database --db (default
"consistency_run"; any name must start with it), dropped at the end unless --keep-db. At start the run drops
every scratch database an earlier run left, crashed or kept. The audits stay within the 400,000-token cap;
raise LLM_DAILY_SPEND_CAP_USD if the run would pass the daily spend cap.
--fake replays the recorded readings with no network and no MongoDB, to check the script itself; its report goes
to the system temp folder, never to docs/test-runs. It counts 2 characters per token, as measured on the live runs,
so its input tokens and cost are a first estimate of a live run's (its output reads low, see FakeAdapter).
--probe [--page N ...] prints, for each structure of the chosen decks (and pages), what a rule is measured on
before its spec commit (docs/specs/README.md): the structure text with its item lines as sent, each item's values,
header cells and the period Python rebuilds, a roadmap's date direction and each line's adjacent and position
date, then the approval rows the recorded replies give (count, milestones, rows with a Label from). No network,
no MongoDB, no report. It prints cell text, so like --diagnostic it runs on the 10 public test decks only.
"""
import argparse
import asyncio
import datetime
import hashlib
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
    """--fake: no network. Replays the recorded labelling replies of backend/tests/fixtures/structure_replies for
    the structures they were written for; every other structure's listed items are labelled not_a_metric. Its token
    counts and the input and output it bills take CHARS_PER_TOKEN characters per token. Billed input matches a live
    run; billed output reads low, as replayed and not_a_metric replies are shorter than the model's (the 10 test
    decks: about 30,000 output tokens against 40,534 and 44,517 on the two live runs of 2026-10-06)."""

    # Measured on the live runs of 2026-10-06, 3 passes over the 10 test decks: 287,576 input tokens for 570,753
    # characters sent (PR #44's head) and 294,621 for 592,974 (PR #51's), about 2 characters per token.
    CHARS_PER_TOKEN = 2

    def __init__(self):
        folder = BACKEND / "tests" / "fixtures" / "structure_replies"
        self.fixtures = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]

    def count_tokens(self, *, model, system, user_payload, json_schema):
        """A stand-in for the provider's counter: one token per CHARS_PER_TOKEN characters of what would be sent."""
        sent = len(system or "") + len(user_payload) + (len(json.dumps(json_schema)) if json_schema else 0)
        return sent // self.CHARS_PER_TOKEN

    def complete(self, *, model, system, user_payload, max_tokens, temperature, json_schema):
        from app.structures import redact
        sent = json.loads(user_payload)
        reply = next((f["reply"] for f in self.fixtures if f["type"] == sent["type"] and f["match"] in sent["text"]),
                     None)
        if reply is None:
            listed = redact.parse_item_lines(redact.split_items(sent["text"])[1] or []) or {"items": []}
            reply = {"type": sent["type"], "pairs": [], "labels": [
                {"item": i["id"], "metric": "not_a_metric", "period": None, "unit": None, "unit_other": None,
                 "actual_or_forecast": "unknown"} for i in listed["items"]]}
        text = json.dumps(reply)
        billed = self.count_tokens(model=model, system=system, user_payload=user_payload, json_schema=json_schema)
        return text, billed, len(text) // self.CHARS_PER_TOKEN


FIELDS = ("metric", "period", "unit", "actual_or_forecast")
REASONS = ("period not rebuilt", "metric invalid", "other")
COUNTS = ("not_a_metric", "other", "ambiguous", "flags")


def _unit(label):
    """The unit as written; for "other", the ISO code the model gave beside it."""
    return label.get("unit_other") if label.get("unit") == "other" else label.get("unit")


def _item_key(label):
    """The old agreement key: the item, its metric, its period as written, unit and actual or forecast."""
    return (label["item"], label["metric"], label.get("period"), _unit(label), label.get("actual_or_forecast"))


def _normalised_key(label, kept, fiscal_year_end=12):
    """The agreement key: the item, its metric and the period the verifier keeps (`kept`: the checked item, None for
    a not_a_metric label, which counts as a metric), compared as its start and end dates."""
    from app.decks import claims
    period = kept.get("period") if kept else None
    return (label["item"], label["metric"], (claims.period_range(period, fiscal_year_end) or period) if period else None)


_COMPARED = {"metric": lambda l: l["metric"], "period": lambda l: l.get("period"), "unit": _unit,
             "actual_or_forecast": lambda l: l.get("actual_or_forecast")}


def differing_fields(passes):
    """The FIELDS in which the passes' labels of one structure differ, as the model wrote them, lined up by item
    id (every pass labels every listed item once)."""
    by_item = [{label["item"]: label for label in labels} for labels in passes]
    found = {name for item in by_item[0] for name, get in _COMPARED.items()
             if len({repr(get(labels[item])) if item in labels else None for labels in by_item}) > 1}
    return [f for f in FIELDS if f in found]


def unverified_reason(structure, item):
    """(reason, detail) for an item the verifier left unverified: the first that applies.
    - "metric invalid": not a metric the gateway accepts for a deck structure. The gateway rejects such a reply
      whole (one reask, then "Not read by AI"), so a live run counts it under not read, not here.
    - "other", "type Other": labelled other, listed as type Other and never Verified.
    - "period not rebuilt": a model period with nothing to rebuild from, a header period Python cannot rebuild, or
      in a paired roadmap line a pair date the item's own cells do not rebuild."""
    from app.llm import schemas
    if item["metric"] not in schemas.LABEL_METRICS:
        return "metric invalid", None
    if item["metric"] == "other":
        return "other", "type Other"
    if not item["checks"]["period"]:
        return "period not rebuilt", None
    return "other", None


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
    system, schema = prompt_store.load(gateway.STRUCTURE_PROMPT).text, schemas.output_schema("table")
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
    """(% per type, % over all) of items with the same `key` ("raw" or "norm") in every pass / items Python listed;
    a structure not read in some pass is left out."""
    agreement = defaultdict(lambda: [0, 0])                # type -> [same in every pass, listed]
    for where, passes_read in readings.items():
        if any(r is None for r in passes_read):
            continue
        keys = [r[key] for r in passes_read]
        agreement[types[where]][0] += len(set.intersection(*keys)) if keys else 0
        agreement[types[where]][1] += passes_read[0]["listed"]
    return ({t: _rate(a, d) for t, (a, d) in sorted(agreement.items())},
            _rate(sum(a for a, _ in agreement.values()), sum(d for _, d in agreement.values())))


def _disagreements(readings, types, pages):
    """The structures read in every pass whose labels differ (the old key), with the fields that differ, and per
    structure type the number of such structures and of each field."""
    rows, by_type = [], {}
    for where, passes_read in readings.items():
        if any(r is None for r in passes_read):
            continue
        count = by_type.setdefault(types[where], dict.fromkeys(("structures", "disagreeing") + FIELDS, 0))
        count["structures"] += 1
        if all(r["raw"] == passes_read[0]["raw"] for r in passes_read):
            continue
        fields = differing_fields([r["labels"] for r in passes_read])
        count["disagreeing"] += 1
        for field in fields:
            count[field] += 1
        rows.append({"deck": where[0], "page": pages[where], "type": types[where], "fields": fields,
                     "same_after_normalisation": all(r["norm"] == passes_read[0]["norm"] for r in passes_read)})
    return rows, dict(sorted(by_type.items()))


def _verdict(structure, item):
    """The verifier's result for one checked item: verified, or the reason it is not."""
    from app.structures import verify
    if item is None:
        return "dropped (not_a_metric)"
    if item["status"] == verify.VERIFIED:
        return "verified"
    reason, detail = unverified_reason(structure, item)
    return f"{reason} ({detail})" if detail else reason


def _at_item(reading, structure, item_id):
    """What one pass read for an item: None when the structure was not read in it, else the model's metric, period,
    unit and actual_or_forecast as written, and the verifier's result."""
    if reading is None:
        return None
    label = next(label for label in reading["labels"] if label["item"] == item_id)
    return {"metric": label["metric"], "period": label.get("period"), "unit": _unit(label),
            "actual_or_forecast": label.get("actual_or_forecast"),
            "verifier": _verdict(structure, reading["checked"].get(item_id))}


def _cell_ref(item):
    return f"{item['cell']}#{item['position']}"


def _kept(structure, line, reading, listing):
    """The milestone the analyst sees for a roadmap line in one pass: None when the model left it unpaired, else
    (the period Python keeps for it, the category): its position date, else the paired date cell's period
    (structure-labelling.md section 2)."""
    from app.structures import redact, verify
    pair = next((p for p in reading["pairs"] if p["line"] == line["id"]), None)
    if pair is None:
        return None
    cells = {redact.cell_id(c): c for c in structure["cells"]}
    placed = verify.position_date(structure, cells[line["cell"]])
    date = next(d["cell"] for d in listing["dates"] if d["id"] == pair["date"])
    return (placed[0] if placed else verify.date_period(cells[date]["text"]), pair["category"])


def _pairs_of(line, reading, listing, texts):
    """What one pass paired a roadmap line with: the date's id, cell and text as sent and the category, or {}."""
    dates = {d["id"]: d["cell"] for d in listing["dates"]}
    return next(({"date": p["date"], "date_cell": dates[p["date"]], "date_text": texts.get(dates[p["date"]], ""),
                  "category": p["category"]} for p in reading["pairs"] if p["line"] == line["id"]), {})


def diagnostic_rows(readings, unverified, types, pages, texts, structures, listings):
    """--diagnostic: one row per unverified item (the report's list), then one per item whose labels differ between
    passes as the model wrote them, then one per line of a roadmap read in every pass (the lines the report counts),
    with its position date, whether the milestone the analyst sees is the same in every pass (_kept), and its pair
    and category in each pass. A row carries the cell's text as sent to the model, so it goes to the diagnostic file
    only, never to the report."""
    from app.structures import verify

    def row(section, where, item_id, reason):
        item = next(i for i in listings[where]["items"] if i["id"] == item_id)
        return {"section": section, "deck": where[0], "page": pages[where], "type": types[where], "item": item_id,
                "cell": _cell_ref(item), "cell_text": texts[where].get(item["cell"], ""),
                "values": [v["value"] for v in item["values"]], "reason": reason,
                "passes": [_at_item(r, structures[where], item_id) for r in readings[where]]}
    rows = [row("unverified", (f, i), item, f"{reason} ({detail})" if detail else reason)
            for f, i, item, reason, detail in unverified]
    for where, passes_read in readings.items():
        if any(r is None for r in passes_read) or all(r["raw"] == passes_read[0]["raw"] for r in passes_read):
            continue
        for item in listings[where]["items"]:
            seen = [next(_item_key(label) for label in r["labels"] if label["item"] == item["id"]) for r in passes_read]
            if any(s != seen[0] for s in seen[1:]):
                rows.append(row("disagreeing", where, item["id"], None))
    for where, passes_read in readings.items():
        if structures[where]["type"] != "roadmap" or any(r is None for r in passes_read):
            continue
        cells = {f"r{c['row']}c{c['col']}": c for c in structures[where]["cells"]}
        for line in listings[where]["lines"]:
            paired = [_pairs_of(line, r, listings[where], texts[where]) for r in passes_read]
            kept = [_kept(structures[where], line, r, listings[where]) for r in passes_read]
            placed = verify.position_date(structures[where], cells[line["cell"]])
            rows.append({"section": "roadmap", "deck": where[0], "page": pages[where], "type": types[where],
                         "line": line["id"], "cell": line["cell"], "cell_text": texts[where].get(line["cell"], ""),
                         "position_date": placed[0] if placed else None, "same": all(k == kept[0] for k in kept),
                         "passes": paired})
    return rows


def _roadmap_lines(readings, structures, listings):
    """(lines, lines with a position date, lines with the same pair and category in every pass, lines whose milestone
    the analyst sees is the same in every pass (_kept), lines whose period Python rebuilds from their own period
    cells, whatever the pair says) over the roadmaps read in every pass."""
    from app.structures import redact, verify
    lines = positioned = same = same_date = rebuilt = 0
    for where, passes_read in readings.items():
        if structures[where]["type"] != "roadmap" or any(r is None for r in passes_read):
            continue
        cells = {redact.cell_id(c): c for c in structures[where]["cells"]}
        for line in listings[where]["lines"]:
            lines += 1
            paired = [next(((p["date"], p["category"]) for p in r["pairs"] if p["line"] == line["id"]), None)
                      for r in passes_read]
            same += int(all(p == paired[0] for p in paired))
            kept = [_kept(structures[where], line, r, listings[where]) for r in passes_read]
            same_date += int(all(k == kept[0] for k in kept))
            positioned += int(verify.position_date(structures[where], cells[line["cell"]]) is not None)
            rebuilt += int(verify.rebuild(structures[where], cells[line["cell"]]) is not None)
    return lines, positioned, same, same_date, rebuilt


async def run(decks, passes, db, adapter=None, pause=0.0, sleep=None, diagnostic=None):
    """`pause` seconds between structure calls, so a burst does not hit the provider's rate limit. A `diagnostic`
    list gets the rows of diagnostic_rows; the report itself is the same either way."""
    from app.decks import parser
    from app.llm import gateway
    from app.structures import items as structure_items
    from app.structures import redact, verify

    sleep = sleep or asyncio.sleep
    counter = adapter or gateway.AnthropicAdapter()       # token counts only; read_structure gets `adapter`
    tokens = await fixed_tokens(counter)
    text_tokens = []                                       # per structure, the gateway's 4,000-token measure
    readings = defaultdict(list)    # (deck, index) -> per pass None (not read) or {"raw", "norm", "labels", ...}
    types, pages = {}, {}
    texts, structures, listings = {}, {}, {}             # (deck, index) -> {cell id: text as sent}, structure, items
    stats = {"items": 0, "verified": 0, "unverified": 0, "not_read": 0, "model_reads": 0, "period_corrected": 0}
    rates = {"financial": [0, 0], "roadmap": [0, 0]}      # [verified, items]: outside roadmaps, figures in roadmaps
    reasons = {}                                           # type -> {reason: unverified items over all passes}
    counts = {}                                            # type -> {COUNTS: over all passes}
    unverified = {}                                        # (deck, index, item, reason, detail) -> {passes}
    per_deck = {}
    hits = {p: [0, 0] for p in range(2, passes + 1)}     # pass -> [cache hits, lookups]
    keys = {}                                              # (deck, index) -> the cache key of its last reading
    calls = 0
    for d, file in enumerate(decks, 1):
        deck = parser.parse_deck((DECKS / file).read_bytes(), file)
        audit_id = f"consistency-{Path(file).stem}"
        audit = {"id": audit_id, "company_name": Path(file).stem, "client_name": "Consistency run",
                 "structure_reading_consent": True}
        await db["audits"].insert_one(dict(audit))
        usage = per_deck.setdefault(file, {"structures": len(deck["structures"]), "input_tokens": 0, "output_tokens": 0,
                                           "cost_usd": 0.0})
        sent = []                                          # (index, structure, text with its item list, page)
        for i, structure in enumerate(deck["structures"]):
            where = (file, i)
            types[where], pages[where] = structure["type"], structure.get("slide") or structure.get("page")
            cells, _ = redact.redact_structure(structure["cells"], Path(file).stem, {}, redact.withheld_values(audit))
            redacted = {**structure, "cells": cells}
            listings[where] = structure_items.list_items(redacted)
            texts[where], structures[where] = {redact.cell_id(c): c["text"] for c in cells}, structure
            sent.append((i, structure, structure_items.text(redacted, listings[where]), pages[where]))
            text_tokens.append(await _count(counter, system=None, user_payload=sent[-1][2], json_schema=None))
        for n in range(1, passes + 1):
            read, tokens_before, cost_before = 0, usage["input_tokens"] + usage["output_tokens"], usage["cost_usd"]
            for i, structure, text, page in sent:
                where = (file, i)
                if n > 1:                   # the cache only: a miss must not call the model a second time
                    key = keys.get(where)
                    hits[n][0] += int(bool(key) and await gateway.stored_structure(db, audit_id, key) is not None)
                    hits[n][1] += 1
                if calls and pause:
                    await sleep(pause)
                calls += 1
                result = await gateway.read_structure(db, audit_id, text, structure["type"], deck_id=file, page=page,
                                                      adapter=adapter, use_cache=n == 1)
                keys[where] = result.key
                stats["model_reads"] += int(not result.cache_hit)       # agreement needs the model, not the cache
                usage["input_tokens"] += result.input_tokens
                usage["output_tokens"] += result.output_tokens
                usage["cost_usd"] = round(usage["cost_usd"] + result.estimated_cost_usd, 6)
                if result.status != "read":
                    stats["not_read"] += 1
                    readings[where].append(None)
                    continue
                read += 1
                listed = listings[where]
                checked = verify.verify(structure, listed, result.labels, result.pairs)
                kept = {c["item"]: c for c in checked["items"] if "line" not in c}
                readings[where].append({"raw": {_item_key(label) for label in result.labels},
                                        "norm": {_normalised_key(label, kept.get(label["item"])) for label in result.labels},
                                        "labels": result.labels, "pairs": result.pairs, "checked": kept,
                                        "listed": len(listed["items"])})
                stats["period_corrected"] += checked["periods_corrected"]
                count = counts.setdefault(structure["type"], dict.fromkeys(COUNTS, 0))
                count["not_a_metric"] += checked["not_a_metric"]
                count["ambiguous"] += sum(1 for item in listed["items"] if len(item["values"]) > 1)
                for item in kept.values():
                    count["other"] += int(item["metric"] == verify.OTHER)
                    count["flags"] += int(bool(item["proposed_flags"]))
                    stats["items"] += 1
                    group = rates["roadmap" if structure["type"] == "roadmap" else "financial"]
                    group[1] += 1
                    if item["status"] == verify.VERIFIED:
                        stats["verified"] += 1
                        group[0] += 1
                        continue
                    stats["unverified"] += 1
                    reason, detail = unverified_reason(structure, item)
                    reasons.setdefault(structure["type"], dict.fromkeys(REASONS, 0))[reason] += 1
                    unverified.setdefault((file, i, item["item"], reason, detail), set()).add(n)
            spent = usage["input_tokens"] + usage["output_tokens"] - tokens_before
            print(f"[{d}/{len(decks)}] {file} pass {n}/{passes}: {read} of {len(sent)} structures read, "
                  f"{spent:,} tokens, ${usage['cost_usd'] - cost_before:.4f}", flush=True)
    if diagnostic is not None:
        diagnostic.extend(diagnostic_rows(readings, unverified, types, pages, texts, structures, listings))
    agreement, agreement_all = _agreement(readings, types, "norm")
    agreement_old, agreement_all_old = _agreement(readings, types, "raw")
    disagreements, disagreement_fields = _disagreements(readings, types, pages)
    lines, positioned, same_pair, same_date, rebuilt = _roadmap_lines(readings, structures, listings)
    counted = [t for t in text_tokens if t is not None]
    tokens["text_and_items_avg"] = round(sum(counted) / len(counted), 1) if counted else None
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
        "verifier_match_rate_financial_pct": _rate(*rates["financial"]),
        "verifier_match_rate_roadmap_pct": _rate(*rates["roadmap"]),
        "unverified_rate_pct": _rate(stats["unverified"], stats["items"]),
        "unverified_reasons": dict(sorted(reasons.items())),
        "unverified_items": [{"deck": f, "page": pages[(f, i)], "type": types[(f, i)], "item": item,
                              "cell": _cell_ref(next(x for x in listings[(f, i)]["items"] if x["id"] == item)),
                              "reason": reason, "detail": detail, "passes": len(seen)}
                             for (f, i, item, reason, detail), seen in unverified.items()],
        "counts": dict(sorted(counts.items())),
        "roadmap_lines": lines,
        "roadmap_dated_by_position": positioned,
        "roadmap_same_pair": same_pair,
        "roadmap_same_date": same_date,
        "roadmap_dates_rebuilt": rebuilt,
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
        "Structures read in every pass whose labels differ in any field, as the model wrote it (the old method). "
        "Labels are lined up by item id; cells and the item count are fixed by code. Each count is a number of "
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
        "One reason per unverified item: period not rebuilt (a model period with nothing to rebuild from, a header "
        "period Python cannot rebuild, or a pair date the item's own cells do not rebuild), metric invalid, other "
        "(type Other). Counts are over all passes. Metric invalid stays 0 on a live run: the gateway rejects a reply "
        "with such a metric whole, and the structure counts as not read.", "",
        "| Type | " + " | ".join(REASONS) + " | Unverified |", "|---|" + "---:|" * (len(REASONS) + 1),
        *(f"| {t} | " + " | ".join(str(c[r]) for r in REASONS) + f" | {sum(c.values())} |" for t, c in by_type.items()),
        "| all | " + " | ".join(str(total[r]) for r in REASONS) + f" | {sum(total.values())} |", "",
        *(["| Deck | Page | Type | Item | Cell | Reason | Passes |", "|---|---:|---|---|---|---|---:|",
           *(f"| {r['deck']} | {r['page']} | {r['type']} | {r['item']} | {r['cell']} | {_reason(r)} | {r['passes']} |"
             for r in rows)]
          if rows else ["No unverified item."]), "",
    ]


def _count_lines(report):
    return [
        "## Labels per type", "",
        "Over all passes: labels not_a_metric (dropped) and other (type Other, never Verified), items Python listed "
        "with two readings, and Verified items with a flag Python computed.", "",
        "| Type | not_a_metric | other | ambiguous readings | flags |", "|---|---:|---:|---:|---:|",
        *(f"| {t} | " + " | ".join(str(c[k]) for k in COUNTS) + " |" for t, c in report["counts"].items()), "",
    ]


def _roadmap_line(report):
    return (f"roadmap lines: {report['roadmap_lines']}, dated by position: {report['roadmap_dated_by_position']}, "
            f"same pair and category in every pass: {report['roadmap_same_pair']}, same date and category: "
            f"{report['roadmap_same_date']}, date rebuilt from cell: {report['roadmap_dates_rebuilt']}")


def summary(report):
    """One line: the agreement against its target and the old figure, then the verifier, cache and cost figures."""
    agreement, target = report["agreement_pct_all"], report["target_agreement_pct"]
    verdict = "not measured" if agreement is None else "met" if agreement >= target else "missed"
    hits = ", ".join(f"{p.replace('_', ' ')} {_pct(r)}" for p, r in report["cache_hit_rate_pct"].items())
    cost = sum(d["cost_usd"] for d in report["per_deck"].values())
    return (f"Agreement {_pct(agreement)} (target {_pct(target)}: {verdict}; "
            f"old method {_pct(report['agreement_pct_all_old'])}); "
            f"verified {_pct(report['verifier_match_rate_pct'])} (financial "
            f"{_pct(report['verifier_match_rate_financial_pct'])}, roadmap {_pct(report['verifier_match_rate_roadmap_pct'])}), "
            f"unverified {_pct(report['unverified_rate_pct'])}, {report['not_read']} not read; "
            f"{_roadmap_line(report)}; "
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
        "Method: docs/specs/structure-labelling.md sections 6 and 7.", "",
        summary(report), "",
        "## Agreement per structure type", "",
        "Items with the same metric and period in every pass / items Python listed, over structures read in every "
        "pass. The period is the one the verifier keeps, compared as its start and end dates; not_a_metric counts as "
        "a metric. The old method compares metric, period as written, unit and actual or forecast.", "",
        "| Type | Agreement | Old method |", "|---|---:|---:|",
        *(f"| {t} | {_pct(a)} | {_pct(report['agreement_pct_old'].get(t))} |"
          for t, a in report["agreement_pct"].items()),
        f"| all | {_pct(report['agreement_pct_all'])} | {_pct(report['agreement_pct_all_old'])} |", "",
        *_disagreement_lines(report),
        "## Verifier", "",
        "Rates over the labelled items (not_a_metric dropped, roadmap milestones left out), then the match rate apart "
        "for the financial items (outside roadmaps) and the roadmap figures. A roadmap line is dated by position when "
        "Python gives it a date by its place (its date line, or the date box beside it); same pair compares the model's "
        "pairs, same date the milestone the analyst sees (paired or not, the date Python keeps, the category). A "
        "roadmap line's date is rebuilt from cell when Python rebuilds its period from its own period cells, whatever "
        "the pair says.", "",
        f"- Match rate: {_pct(report['verifier_match_rate_pct'])}",
        f"- Match rate, financial (outside roadmaps): {_pct(report['verifier_match_rate_financial_pct'])}",
        f"- Match rate, roadmap (figures in roadmaps, milestones left out): "
        f"{_pct(report['verifier_match_rate_roadmap_pct'])}",
        f"- Unverified rate: {_pct(report['unverified_rate_pct'])}",
        f"- Periods corrected: {report['period_corrected']}",
        f"- {_roadmap_line(report)[0].upper()}{_roadmap_line(report)[1:]}",
        f"- Not read: {report['not_read']}; model reads: {report['model_reads']}", "",
        *_reason_lines(report),
        *_count_lines(report),
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
        "text; its parts are each counted with the empty message, less the empty message alone. The gateway caps "
        "the structure text plus its item list at 4,000 tokens.", "",
        f"- Fixed prompt: {_tokens(tokens['fixed_prompt'])} (system prompt {_tokens(tokens['system_prompt'])}, "
        f"output schema {_tokens(tokens['output_schema'])}, empty message {_tokens(tokens['empty_message'])})",
        f"- Structure text and item list, average of {tokens['structures_counted']} structures: "
        f"{_tokens(tokens['text_and_items_avg'])} against the gateway's 4,000-token cap",
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
    """One pass for an item: the model's metric, period, unit and actual_or_forecast, then the verifier's result."""
    if found is None:
        return "not read"
    return (f"{found['metric']} {found['period'] or 'null'} {found['unit'] or 'null'} "
            f"{found['actual_or_forecast'] or 'null'}: {found['verifier']}")


def diagnostic_path(report_path):
    return report_path.with_name(f"{report_path.stem}_diagnostic.md")


def write_diagnostic(rows, report_path, passes):
    """<report>_diagnostic.md beside the report, from diagnostic_rows. It holds the text of cells as sent to the
    model, so main writes it for the 10 public test decks only; the boundary test leaves it out by this name."""
    path = diagnostic_path(report_path)
    head = ("| Deck | Page | Type | Item | Cell | Cell text | Python's values | Reason | "
            + " | ".join(f"Pass {n}" for n in range(1, passes + 1)) + " |")
    rule = "|---|---:|---|---|---|---|---|---|" + "---|" * passes

    def line(row):
        cells = [row["deck"], row["page"], row["type"], row["item"], row["cell"], _md(row["cell_text"]),
                 " or ".join(_number(v) for v in row["values"]), _md(row["reason"] or ""),
                 *(_md(_pass_text(found)) for found in row["passes"])]
        return "| " + " | ".join(str(c) for c in cells) + " |"
    unverified = [line(r) for r in rows if r["section"] == "unverified"]
    disagreeing = [line(r) for r in rows if r["section"] == "disagreeing"]
    paired = lambda p: f"{p['date']} {p['date_cell']} {_md(p['date_text'])}: {p['category']}" if p else "no pair"  # noqa: E731
    roadmap = ["| " + " | ".join(str(c) for c in (r["deck"], r["page"], r["line"], r["cell"], _md(r["cell_text"]),
                                                   r["position_date"] or "none", "yes" if r["same"] else "no",
                                                   *map(paired, r["passes"]))) + " |"
               for r in rows if r["section"] == "roadmap"]
    roadmap_head = ("| Deck | Page | Line | Cell | Line text | Python's date | Same | "
                    + " | ".join(f"Pass {n}" for n in range(1, passes + 1)) + " |")
    lines = [
        f"# Consistency run {report_path.stem.split('_', 1)[1]}: diagnostic", "",
        "Public test decks only: --diagnostic refuses any other deck. This file holds the text of cells as sent to "
        "the model; the report beside it holds none. A pass gives the model's metric, period, unit and "
        "actual_or_forecast as written, then the verifier's result: verified, the reason, or dropped (not_a_metric). "
        "Not read: the structure was not read in that pass.", "",
        "## Unverified items", "", "Every unverified item, as listed in the report.", "",
        *([head, rule, *unverified] if unverified else ["No unverified item."]), "",
        "## Disagreeing items", "",
        "Every item whose labels differ between passes, as the model wrote them.", "",
        *([head, rule, *disagreeing] if disagreeing else ["Every structure read in every pass was read the same way in each."]),
        "", "## Roadmap lines", "",
        "Every text line of the roadmaps read in every pass (the lines the report counts): Python's date, the date it "
        "gives the line by its place (none: the line keeps the date the model pairs it with); then per pass the date "
        "the model paired it with (id, cell, text) and the category; no pair: the model left the line out. Same: the "
        "milestone the analyst sees is the same in every pass (paired or not, the date Python keeps, the category).", "",
        *([roadmap_head, "|---|---:|---|---|---|---|---|" + "---|" * passes, *roadmap] if roadmap
          else ["No roadmap was read in every pass."]),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def probe(decks, pages=None, out=print):
    """--probe: one block per structure. The structure text and item lines as the model would read them, then per
    item its values (Python's default first), header cells and the period Python rebuilds from its cells
    (verify.rebuild); for a roadmap the date direction and, per text line, its adjacent date line and position
    date (structure-labelling.md section 2); then the approval rows the recorded replies give under FakeAdapter
    (a structure with no recorded reply is labelled not_a_metric throughout and gives none)."""
    from app.decks import parser
    from app.llm import gateway
    from app.structures import approval_items, candidate_from_item, redact, verify
    from app.structures import items as structure_items
    db, adapter = MemoryDB(), FakeAdapter()
    for file in decks:
        deck = parser.parse_deck((DECKS / file).read_bytes(), file)
        audit = {"id": f"probe-{Path(file).stem}", "company_name": Path(file).stem, "client_name": "Probe",
                 "structure_reading_consent": True}
        await db["audits"].insert_one(dict(audit))
        for structure in deck["structures"]:
            page = structure.get("slide") or structure.get("page")
            if pages and page not in pages:
                continue
            cells, _ = redact.redact_structure(structure["cells"], Path(file).stem, {}, redact.withheld_values(audit))
            redacted = {**structure, "cells": cells}
            listed = structure_items.list_items(redacted)
            text = structure_items.text(redacted, listed)
            by_id = {redact.cell_id(c): c for c in structure["cells"]}
            lines, dates = listed.get("lines") or (), listed.get("dates") or ()
            out(f"== {file} p{page} {structure['type']}: {len(listed['items'])} items, {len(lines)} text lines, "
                f"{len(dates)} date cells")
            out(text)
            for item in listed["items"]:
                rebuilt = verify.rebuild(structure, by_id[item["cell"]])
                out(f"  {item['id']} {item['cell']}#{item['position']} values={[v['value'] for v in item['values']]} "
                    f"headers={item['headers']} period={rebuilt[0] if rebuilt else None}")
            if structure["type"] == "roadmap":
                out(f"  date direction: {verify.date_direction(structure)}")
                for line in listed["lines"]:
                    cell = by_id[line["cell"]]
                    adjacent = verify.adjacent_date_line(structure, cell)
                    placed = verify.position_date(structure, cell)
                    out(f"  {line['id']} {line['cell']} adjacent date={adjacent['text'] if adjacent else None!r} "
                        f"position date={placed[0] if placed else None}")
            result = await gateway.read_structure(db, audit["id"], text, structure["type"], deck_id=file, page=page,
                                                  adapter=adapter)
            if result.status != "read":
                out(f"  not read under the recorded replies: {result.reason}")
                continue
            checked = verify.verify(structure, listed, result.labels, result.pairs)
            rows = [candidate_from_item(row, structure, {"file": file}, result.model_type, 12)
                    for row in approval_items(checked["items"])]
            out(f"  approval rows under the recorded replies: {len(rows)} (milestones "
                f"{sum(1 for c in checked['items'] if 'line' in c)}, with Label from "
                f"{sum(1 for r in rows if r['label_from'])})")
            for row in rows:
                out(f"    {row['ai_status']} {row['claim_type']} value={row['value']} high={row['value_high']} "
                    f"date={row['target_date']} cell={row['cell']} label_from={row['label_from']!r} "
                    f"date_from={row['date_from']!r}")


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
    ap.add_argument("--probe", action="store_true",
                    help="print each structure as sent, its items' periods and its approval rows under the recorded "
                         "replies; no run, no report (the 10 public test decks only)")
    ap.add_argument("--page", type=int, action="append", help="with --probe: only this slide or page (repeatable)")
    args = ap.parse_args(argv)
    decks = args.deck or sorted(p.name for p in DECKS.iterdir() if not p.name.startswith("."))
    outside = not_public(decks) if args.diagnostic or args.probe else None
    if outside is not None:
        sys.exit(f"{'--probe' if args.probe else '--diagnostic'} runs on the 10 public test decks only: {outside} is "
                 "not one of them (checked by file name and SHA-256).")
    if args.probe:
        asyncio.run(probe(decks, args.page))
        return None
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
    print(path.read_text(encoding="utf-8"), end="", flush=True)     # also on screen; the file is committed
    return report


if __name__ == "__main__":
    main()
