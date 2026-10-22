"""Side by side: the rules read (A, claims.detect_candidates) against the page read (B, the model reads every sendable page and
page_check checks each claim) on the 10 public test decks (docs/design/ai-reads-rules-check.md section 7, PR A).

No network, no MongoDB, no cost: B replays the recorded page replies of backend/tests/fixtures/page_replies/ (hand-written in the
model's format for the public decks; PR B records the model's own) through the gateway (consent, boundary and redaction checks,
cache, caps) with an in-memory database, then runs page_check. A page with no recorded reply gives no claim. For every deck it
prints: pages (total, with a figure as digits and so sent), rows A, rows B, B matched and unmatched, recall and precision of each
against the answer file (tests/fixtures/decks/expected_claims.json: a company claim is found when a row from the same deck cites
its page and has its value, a percentage only a percentage, a range both ends), rows only in A and rows only in B (by page, value
and high value). The normal output holds counts, values, cell ids, types and statuses, never a line of a deck.

Usage (from the repository root):
    python scripts/compare_pipelines.py [--deck 03-buffer.pptx ...] [--diagnostic] [--synthetic] [--out report.json]
--diagnostic also prints each differing row with the text of its line; it holds deck text, so it runs on the 10 public test decks
only (file name and SHA-256, as consistency_run.py checks them) and refuses any other deck.
--synthetic runs the synthetic pages of backend/tests/test_issue_143/148/151/154.py through both reads and prints their rows.
"""
import argparse
import asyncio
import importlib.util
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))
_spec = importlib.util.spec_from_file_location("consistency_run", Path(__file__).resolve().parent / "consistency_run.py")
consistency_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(consistency_run)
MemoryDB, DECKS, not_public = consistency_run.MemoryDB, consistency_run.DECKS, consistency_run.not_public
REPLIES = BACKEND / "tests" / "fixtures" / "page_replies"
ANSWERS = ROOT / "tests" / "fixtures" / "decks" / "expected_claims.json"
COMPANY = "company claim"
CHARS_PER_TOKEN = 2


class RecordedAdapter:
    """Replays the recorded page replies: a batch's reply holds the claims of every fixture whose match line is in the text sent
    (one fixture per page). Token counts take CHARS_PER_TOKEN characters per token, as the consistency script's fake does."""

    def __init__(self, fixtures):
        self.fixtures = [f for f in fixtures if "match" in f]
        self.calls = 0

    def count_tokens(self, *, model, system, user_payload, json_schema):
        sent = len(system or "") + len(user_payload) + (len(json.dumps(json_schema)) if json_schema else 0)
        return sent // CHARS_PER_TOKEN

    def complete(self, *, model, system, user_payload, max_tokens, temperature, json_schema, cache_system=False):
        self.calls += 1
        sent = json.loads(user_payload)
        claims = [c for f in self.fixtures if f["match"] in sent["text"] for c in f["claims"]]
        text = json.dumps({"type": sent["type"], "claims": claims})
        return text, self.count_tokens(model=model, system=system, user_payload=user_payload, json_schema=json_schema), \
            len(text) // CHARS_PER_TOKEN


def fixtures():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(REPLIES.glob("*.json"))]


def answers():
    return {d["file"]: d for d in json.loads(ANSWERS.read_text(encoding="utf-8"))["decks"]}


# ---------------------------------------------------------------------------
# Rows: one per value, with its page, for both reads
# ---------------------------------------------------------------------------
def rows_a(blocks, file):
    from app.decks import claims
    out = []
    for c in claims.detect_candidates(blocks, file):
        for v in claims.claim_values(c):
            if v["value"] is None and not v.get("target_date"):
                continue
            source = v["sources"][0]
            out.append({"page": source.get("slide") or source.get("page"), "value": v["value"], "value_high": v["value_high"],
                        "unit": c.get("unit"), "type": c["claim_type"], "target_date": v["target_date"],
                        "cell": f"r{source['row']}c{source['col']}" if source.get("row") else None, "status": "rules",
                        "text": c.get("snippet")})
    return out


async def rows_b(db, blocks, file, adapter):
    from app.decks import pages as page_grids
    from app.structures import page_check
    from app.structures import pages as pipeline
    audit_id = f"compare-{Path(file).stem}"
    await db["audits"].insert_one({"id": audit_id, "company_name": Path(file).stem, "structure_reading_consent": True})
    grids = page_grids.page_grids(blocks)
    by_page = {page_grids.page_number(g): g for g in grids}
    reads = await pipeline.read_pages(db, audit_id, "d1", grids, Path(file).stem, {}, adapter=adapter, sleep=_no_sleep)
    out, statuses = [], []
    for batch, result in reads:
        statuses.append(result.status)
        if result.status != "read":
            continue
        claims_of = page_check.by_page(result.claims)
        for grid in batch:
            page = page_grids.page_number(grid)
            checked = page_check.check(grid, claims_of.get(page, []))
            texts = {f"r{c['row']}c{c['col']}": c["text"] for c in grid["cells"]}
            for item in checked["items"]:
                out.append({"page": page, "value": item["value"], "value_high": item["value_high"], "unit": item["unit"],
                            "type": item["metric"], "target_date": item["period"], "cell": item["value_cell"],
                            "status": item["status"], "text": texts.get(item["value_cell"])})
    return out, {"pages": len(grids), "sent": len(pipeline.redacted_pages(grids, Path(file).stem, {})), "batches": len(reads),
                 "read": statuses.count("read"), "not_read": len(statuses) - statuses.count("read")}


async def _no_sleep(_seconds):
    return None


# ---------------------------------------------------------------------------
# Recall and precision against the answer file (as tests/test_deck_recall.py counts them)
# ---------------------------------------------------------------------------
def _same(a, b):
    return a is not None and b is not None and math.isclose(float(a), float(b), rel_tol=1e-9)


def found(row, claim):
    if row["page"] != claim["page"]:
        return False
    if claim["value"] is not None and (row["unit"] == "%") != (claim["unit"] == "%"):
        return False
    if claim["value"] is None:
        return row["value"] is None and row["target_date"] == claim["target_date"]
    if claim.get("value_high") is not None:
        return _same(row["value"], claim["value"]) and _same(row.get("value_high"), claim["value_high"])
    return _same(row["value"], claim["value"]) or _same(row.get("value_high"), claim["value"])


def scores(rows, listed):
    company = [c for c in listed if c["status"] == COMPANY]
    hits = sum(1 for c in company if any(found(r, c) for r in rows))
    precise = sum(1 for r in rows if any(found(r, c) for c in company))
    return {"claims": len(company), "found": hits, "recall": round(hits / len(company), 3) if company else None,
            "precision": round(precise / len(rows), 3) if rows else None}


def _key(row):
    return (row["page"], row["value"], row.get("value_high"))


def compare(a, b):
    keys_a, keys_b = {_key(r) for r in a}, {_key(r) for r in b}
    return [r for r in a if _key(r) not in keys_b], [r for r in b if _key(r) not in keys_a]


def _row_line(row, diagnostic):
    line = (f"p{row['page']} {row['type']} value={row['value']} high={row['value_high']} date={row['target_date']} "
            f"cell={row['cell']} {row['status']}")
    return line + (f" | {row['text']!r}" if diagnostic else "")


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
async def run(decks, diagnostic=False, out=print):
    from app.decks import parser
    db, adapter, listed = MemoryDB(), RecordedAdapter(fixtures()), answers()
    report = {"decks": {}}
    header = f"{'deck':22} {'pages':>5} {'sent':>4} | {'A':>4} {'rec':>5} {'prec':>5} | {'B':>4} {'match':>5} {'unm':>4} {'rec':>5} {'prec':>5} | {'only A':>6} {'only B':>6}"
    out(header)
    out("-" * len(header))
    for file in decks:
        deck = parser.parse_deck((DECKS / file).read_bytes(), file)
        a = rows_a(deck["blocks"], file)
        b, pages = await rows_b(db, deck["blocks"], file, adapter)
        only_a, only_b = compare(a, b)
        sa, sb = scores(a, listed[file]["claims"]), scores(b, listed[file]["claims"])
        matched = sum(1 for r in b if r["status"] == "matched")
        row = {"pages": pages, "rows_a": len(a), "rows_b": len(b), "b_matched": matched, "b_unmatched": len(b) - matched,
               "a": sa, "b": sb, "only_a": len(only_a), "only_b": len(only_b)}
        report["decks"][file] = row
        out(f"{file:22} {pages['pages']:>5} {pages['sent']:>4} | {len(a):>4} {_pct(sa['recall']):>5} {_pct(sa['precision']):>5} | "
            f"{len(b):>4} {matched:>5} {len(b) - matched:>4} {_pct(sb['recall']):>5} {_pct(sb['precision']):>5} | "
            f"{len(only_a):>6} {len(only_b):>6}")
        if diagnostic:
            for name, rows in (("only in A", only_a), ("only in B", only_b)):
                for r in rows:
                    out(f"    {name}: {_row_line(r, True)}")
    totals = {k: sum(d[k] for d in report["decks"].values()) for k in ("rows_a", "rows_b", "b_matched", "b_unmatched", "only_a", "only_b")}
    claims_total = sum(d["a"]["claims"] for d in report["decks"].values())
    found_a = sum(d["a"]["found"] for d in report["decks"].values())
    found_b = sum(d["b"]["found"] for d in report["decks"].values())
    report["totals"] = {**totals, "claims": claims_total, "found_a": found_a, "found_b": found_b,
                        "recall_a": round(found_a / claims_total, 3) if claims_total else None,
                        "recall_b": round(found_b / claims_total, 3) if claims_total else None,
                        "pages": sum(d["pages"]["pages"] for d in report["decks"].values()),
                        "sent": sum(d["pages"]["sent"] for d in report["decks"].values()), "calls": adapter.calls,
                        "recorded_pages": len([f for f in fixtures() if "match" in f])}
    t = report["totals"]
    out("-" * len(header))
    out(f"{'total':22} {t['pages']:>5} {t['sent']:>4} | {t['rows_a']:>4} {_pct(t['recall_a']):>5} {'':>5} | {t['rows_b']:>4} "
        f"{t['b_matched']:>5} {t['b_unmatched']:>4} {_pct(t['recall_b']):>5} {'':>5} | {t['only_a']:>6} {t['only_b']:>6}")
    out(f"B replayed {t['recorded_pages']} recorded page replies in {t['calls']} calls; a page with no recorded reply gives no row.")
    return report


def _pct(value):
    return "-" if value is None else f"{round(value * 100)}%"


SYNTHETIC = ("issue_143", "issue_148", "issue_151", "issue_154")


def synthetic_blocks():
    """The synthetic pages of the issue tests, built by their own builders (the tests import the server, so the dummy settings
    of backend/conftest.py are set first)."""
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "growth_diligence_test")
    os.environ.setdefault("ACCESS_DISABLED", "1")
    import test_issue_143 as t143
    import test_issue_148 as t148
    import test_issue_151 as t151
    import test_issue_154 as t154
    return {
        "issue_143": t143.page("Average revenue per account (EUR)"),
        "issue_148": t148.deck()["blocks"],
        "issue_151": t151.deck(t151.MRR_LINE, t151.REVENUE_LINE)["blocks"],
        "issue_154": t154.parsed([(50, 560, 20, t154.TITLE), (50, 520, 12, t154.SENTENCE), *t154.AXIS, t154.BAR])["blocks"],
    }


class SyntheticAdapter(RecordedAdapter):
    """Replays the one recorded reply of a synthetic page, chosen by name."""

    def __init__(self, fixture):
        super().__init__([])
        self.fixture = fixture

    def complete(self, *, model, system, user_payload, max_tokens, temperature, json_schema, cache_system=False):
        self.calls += 1
        text = json.dumps({"type": json.loads(user_payload)["type"], "claims": self.fixture["claims"]})
        return text, self.count_tokens(model=model, system=system, user_payload=user_payload, json_schema=json_schema), \
            len(text) // CHARS_PER_TOKEN


async def run_synthetic(out=print):
    """Both reads on the synthetic pages of test_issue_143/148/151/154: their rows, with the text of each line (the pages are the
    tests' own, no deck)."""
    recorded = {f["synthetic"]: f for f in fixtures() if "synthetic" in f}
    report = {}
    for name, blocks in synthetic_blocks().items():
        a = rows_a(blocks, "deck.pdf")
        b, pages = await rows_b(MemoryDB(), blocks, f"{name}.pdf", SyntheticAdapter(recorded[name]))
        report[name] = {"rows_a": a, "rows_b": b, "pages": pages}
        out(f"{name}: A {len(a)} rows, B {len(b)} rows ({sum(1 for r in b if r['status'] == 'matched')} matched)")
        for label, rows in (("A", a), ("B", b)):
            for r in rows:
                out(f"    {label} {_row_line(r, True)}")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--deck", action="append", help="a deck of tests/fixtures/decks/decks/ (default: all 10)")
    ap.add_argument("--diagnostic", action="store_true", help="also print each differing row with the text of its line (public decks only)")
    ap.add_argument("--synthetic", action="store_true", help="also run the synthetic pages of test_issue_143/148/151/154")
    ap.add_argument("--out", help="also write the report as JSON")
    args = ap.parse_args(argv)
    decks = args.deck or sorted(p.name for p in DECKS.iterdir() if not p.name.startswith("."))
    if args.diagnostic:
        outside = not_public(decks)
        if outside:
            sys.exit(f"--diagnostic runs on the 10 public test decks only: {outside} is not one of them")
    report = asyncio.run(run(decks, diagnostic=args.diagnostic))
    if args.synthetic:
        report["synthetic"] = asyncio.run(run_synthetic())
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


if __name__ == "__main__":
    import logging
    logging.getLogger("growth").setLevel(logging.WARNING)       # the gateway's info lines (hashes and tokens) stay out of the table
    main()
