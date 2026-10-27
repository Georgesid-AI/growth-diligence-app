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
    python scripts/compare_pipelines.py --recorded pages_2026-10-22 [--pass 2] [--md docs/test-runs/pages_2026-10-22_compare.md]
--diagnostic also prints each differing row with the text of its line; it holds deck text, so it runs on the 10 public test decks
only (file name and SHA-256, as consistency_run.py checks them) and refuses any other deck.
--synthetic runs the synthetic pages of backend/tests/test_issue_143/148/151/154.py through both reads and prints their rows.
--recorded <run> (PR B) replays the model's own replies of a live run, backend/tests/fixtures/page_replies/recorded/<run>/pass-<n>/,
one B row set per pass (--pass N: that pass only), then prints per deck the agreement across the passes on (value cell, metric,
period): claims found in every pass / in any pass, the disagreeing claims by kind (metric, period, present in some passes only),
and every unmatched or dropped claim grouped by the check that failed (value, unit, period, no value; dropped:
an axis tick, a line the rules read drops, a cell not on the page), with its deck, page, cell id, metric, value and the number of
passes it appears in. --md also writes these tables as markdown (docs/test-runs). Counts, values, cell ids, types and statuses; no
line of a deck.
"""
import argparse
import asyncio
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from unittest import mock

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


RecordedAdapter = consistency_run.PageReplayAdapter       # one replay adapter for both scripts


def fixtures():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(REPLIES.glob("*.json"))]


def recorded_fixtures(run):
    """{pass number: the recorded replies of that pass} of a live run, or exit when the run is not recorded."""
    folder = consistency_run.RECORDED / run
    passes = sorted(int(p.name.split("-")[1]) for p in folder.glob("pass-*") if p.is_dir()) if folder.is_dir() else []
    if not passes:
        sys.exit(f"no recorded run {run!r} under {consistency_run.RECORDED}")
    return {n: [json.loads(p.read_text(encoding="utf-8")) for p in sorted((folder / f"pass-{n}").glob("*.json"))] for n in passes}


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


CHECKS = ("value", "unit", "period")


def cause(claim, item):
    """Why a checked claim is not matched, as closed words joined by "+": the checks that failed (value, unit, period), "no value" for a
    claim without a figure (a milestone); "matched" when it is. Since 2026-10-23 (George) only the value gates the match, and a metric
    "other" is matched like any other; a unit or period that failed beside a failed value is still named."""
    if item["status"] == page_check_module().MATCHED:
        return "matched"
    if claim.get("value") is None:
        return "no value"
    parts = [k for k in CHECKS if not item["checks"][k]]
    return "+".join(parts)


def page_check_module():
    from app.structures import page_check
    return page_check


def dropped_reason(grid, claim):
    """Why page_check drops a claim before any check: "no cell" (a cell id not on the page), "tick" (an axis tick) or "not_plan"
    (a line the rules read drops); None when it is checked."""
    page_check = page_check_module()
    cell = next((c for c in grid["cells"] if f"r{c['row']}c{c['col']}" == claim["value_cell"]), None)
    if cell is None:
        return "no cell"
    return page_check._dropped(cell)


async def rows_b(db, blocks, file, adapter, audit_id=None):
    """(rows, pages): one row per claim page_check kept (matched or unmatched, with its cause) and one per claim it dropped
    (status "dropped", cause "dropped: <reason>"); pages counts the grids, the pages sent, the batches and how many were read."""
    from app.decks import pages as page_grids
    from app.structures import page_check
    from app.structures import pages as pipeline
    audit_id = audit_id or f"compare-{Path(file).stem}"
    await db["audits"].insert_one({"id": audit_id, "company_name": Path(file).stem, "structure_reading_consent": True})
    grids = page_grids.page_grids(blocks)
    with mock.patch.dict(os.environ, {"DECK_PIPELINE": "ai"}):     # the gateway refuses a page call under the default switch
        reads = await pipeline.read_pages(db, audit_id, "d1", grids, _replay_image, adapter=adapter, sleep=_no_sleep)
    out, statuses = [], []
    for batch, result in reads:
        statuses.append(result.status)
        if result.status != "read":
            continue
        claims_of = page_check.by_page(result.claims)
        for grid in batch:
            page = page_grids.page_number(grid)
            claims = claims_of.get(page, [])
            checked = page_check.check(grid, claims)
            texts = {f"r{c['row']}c{c['col']}": c["text"] for c in grid["cells"]}
            items = iter(checked["items"])
            for claim in claims:                 # check() keeps the claims in order and leaves the dropped ones out
                why = dropped_reason(grid, claim)
                if why:
                    out.append({"page": page, "value": claim["value"], "value_high": claim["value_high"], "unit": claim["unit"],
                                "type": claim["metric"], "target_date": claim["period"], "cell": claim["value_cell"],
                                "status": "dropped", "cause": f"dropped: {why}", "text": texts.get(claim["value_cell"])})
                    continue
                item = next(items)
                out.append({"page": page, "value": item["value"], "value_high": item["value_high"], "unit": item["unit"],
                            "type": item["metric"], "target_date": item["period"], "cell": item["value_cell"],
                            "status": item["status"], "cause": cause(claim, item), "text": texts.get(item["value_cell"])})
    return out, {"pages": len(grids), "sent": len(pipeline.sendable_pages(grids)), "batches": len(reads),
                 "read": statuses.count("read"), "not_read": len(statuses) - statuses.count("read")}


async def _no_sleep(_seconds):
    return None


async def _replay_image(_page):
    """The gateway wants an image with every page; a replay of recorded replies sends nothing, so a 1 x 1 PNG stands in."""
    import base64
    return base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")


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
        kept, pages = await rows_b(db, deck["blocks"], file, adapter)
        b = [r for r in kept if r["status"] != "dropped"]
        only_a, only_b = compare(a, b)
        sa, sb = scores(a, listed[file]["claims"]), scores(b, listed[file]["claims"])
        matched = sum(1 for r in b if r["status"] == "matched")
        row = {"pages": pages, "rows_a": len(a), "rows_b": len(b), "b_matched": matched, "b_unmatched": len(b) - matched,
               "b_dropped": len(kept) - len(b), "a": sa, "b": sb, "only_a": len(only_a), "only_b": len(only_b)}
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


# ---------------------------------------------------------------------------
# --recorded: the model's own replies, pass by pass (PR B)
# ---------------------------------------------------------------------------
DISAGREE = ("metric", "period", "presence")


def _triples(claims):
    """What the run's agreement compares: (value cell, metric, period) of each claim."""
    return {(c["value_cell"], c["metric"], c.get("period")) for c in claims}


def agreement(claims_by_pass):
    """The run's agreement for one deck over the passes given: claims (value cell, metric, period) found in every pass / found in
    any pass, and the claims not found in every pass by kind: "metric" (the cell is claimed in every pass, with another metric in
    some), "period" (the cell and metric in every pass, another period in some), "presence" (the cell is claimed in some passes
    only). None with fewer than two passes."""
    if len(claims_by_pass) < 2:
        return None
    sets = [_triples(c) for c in claims_by_pass.values()]
    union, same = set().union(*sets), set.intersection(*sets)
    cells = [{t[0] for t in s} for s in sets]
    pairs = [{t[:2] for t in s} for s in sets]
    kinds = dict.fromkeys(DISAGREE, 0)
    for triple in union - same:
        if not all(triple[0] in c for c in cells):
            kinds["presence"] += 1
        elif not all(triple[:2] in p for p in pairs):
            kinds["metric"] += 1
        else:
            kinds["period"] += 1
    pages = [{int(t[0].split("r")[0][1:]) for t in s} for s in sets]
    return {"agreed": len(same), "union": len(union), "pct": round(100.0 * len(same) / len(union), 1) if union else 100.0,
            "disagree": kinds, "pages_differ": any(p != pages[0] for p in pages)}


def _place(row):
    return f"p{row['page']} {row['cell']}"


def unmatched_rows(rows_by_deck_pass):
    """Every unmatched or dropped row over all decks and passes, one line per (deck, page, cell, cause, metric, value) with the number
    of passes it appears in, most frequent cause first."""
    seen = {}
    for (file, n), rows in rows_by_deck_pass.items():
        for r in rows:
            if r["status"] == "matched":
                continue
            key = (file, r["page"], r["cell"], r["cause"], r["type"], r["value"])
            seen.setdefault(key, set()).add(n)
    out = [{"deck": f, "page": p, "cell": c, "cause": cause_, "metric": m, "value": v, "passes": len(ns)}
           for (f, p, c, cause_, m, v), ns in seen.items()]
    order = collections_counter(r["cause"] for r in out)
    return sorted(out, key=lambda r: (-order[r["cause"]], r["cause"], r["deck"], r["page"], r["cell"]))


def collections_counter(values):
    from collections import Counter
    return Counter(values)


async def run_recorded(decks, run, passes_wanted=None, out=print):
    """The rules read once per deck and the page read once per recorded pass, from the replies of `run`; then the agreement across
    the passes and the unmatched rows by cause. Counts, cell ids, values, types and statuses only."""
    from app.decks import parser
    recorded = recorded_fixtures(run)
    passes = [n for n in recorded if passes_wanted is None or n in passes_wanted]
    if not passes:
        sys.exit(f"run {run!r} has no pass {sorted(passes_wanted)}; recorded: {sorted(recorded)}")
    db, listed = MemoryDB(), answers()
    report = {"recorded": run, "passes": passes, "decks": {}, "causes": {}, "unmatched_rows": [], "calls": 0}
    rows_of = {}
    header = (f"{'deck':22} {'pass':>4} {'pages':>5} {'sent':>4} | {'A':>4} {'rec':>5} {'prec':>5} | {'B':>4} {'match':>5} {'unm':>4} "
              f"{'drop':>4} {'rec':>5} {'prec':>5} | {'only A':>6} {'only B':>6}")
    out(header)
    out("-" * len(header))
    for file in decks:
        deck = parser.parse_deck((DECKS / file).read_bytes(), file)
        a = rows_a(deck["blocks"], file)
        sa = scores(a, listed[file]["claims"])
        entry = report["decks"][file] = {"rows_a": len(a), "a": sa, "passes": {}, "agreement": None, "pages": None}
        claims_by_pass = {}
        for n in passes:
            adapter = RecordedAdapter([f for f in recorded[n] if f["file"] == file])
            kept, pages = await rows_b(db, deck["blocks"], file, adapter, audit_id=f"compare-{Path(file).stem}-pass{n}")
            report["calls"] += adapter.calls
            entry["pages"] = pages
            rows_of[(file, n)] = kept
            b = [r for r in kept if r["status"] != "dropped"]
            only_a, only_b = compare(a, b)
            sb = scores(b, listed[file]["claims"])
            matched = sum(1 for r in b if r["status"] == "matched")
            row = {"claims": len(kept), "rows_b": len(b), "matched": matched, "unmatched": len(b) - matched, "dropped": len(kept) - len(b),
                   "recall": sb["recall"], "precision": sb["precision"], "found": sb["found"], "only_a": len(only_a), "only_b": len(only_b),
                   "read": pages["read"], "batches": pages["batches"]}
            entry["passes"][n] = row
            claims_by_pass[n] = [c for f in recorded[n] if f["file"] == file for c in f["claims"]]
            out(f"{file:22} {n:>4} {pages['pages']:>5} {pages['sent']:>4} | {len(a):>4} {_pct(sa['recall']):>5} {_pct(sa['precision']):>5} | "
                f"{len(b):>4} {matched:>5} {len(b) - matched:>4} {row['dropped']:>4} {_pct(sb['recall']):>5} {_pct(sb['precision']):>5} | "
                f"{len(only_a):>6} {len(only_b):>6}")
        entry["agreement"] = agreement(claims_by_pass)
    out("-" * len(header))
    totals = {n: {k: sum(d["passes"][n][k] for d in report["decks"].values()) for k in ("claims", "rows_b", "matched", "unmatched", "dropped", "found")}
              for n in passes}
    claims_total = sum(d["a"]["claims"] for d in report["decks"].values())
    for n, t in totals.items():
        t["recall"] = round(t["found"] / claims_total, 3) if claims_total else None
        out(f"{'total':22} {n:>4} {'':>5} {'':>4} | {sum(d['rows_a'] for d in report['decks'].values()):>4} "
            f"{_pct(round(sum(d['a']['found'] for d in report['decks'].values()) / claims_total, 3) if claims_total else None):>5} {'':>5} | "
            f"{t['rows_b']:>4} {t['matched']:>5} {t['unmatched']:>4} {t['dropped']:>4} {_pct(t['recall']):>5} {'':>5} |")
    report["totals"] = {"claims": claims_total, "rows_a": sum(d["rows_a"] for d in report["decks"].values()), "passes": totals}
    if len(passes) > 1:
        out("")
        out(f"{'agreement':22} {'agreed':>6} {'union':>5} {'pct':>6} | " + " ".join(f"{k:>8}" for k in DISAGREE) + " | pages differ")
        for file, d in report["decks"].items():
            g = d["agreement"]
            out(f"{file:22} {g['agreed']:>6} {g['union']:>5} {g['pct']:>5}% | " + " ".join(f"{g['disagree'][k]:>8}" for k in DISAGREE)
                + f" | {'yes' if g['pages_differ'] else 'no'}")
        agreed = sum(d["agreement"]["agreed"] for d in report["decks"].values())
        union = sum(d["agreement"]["union"] for d in report["decks"].values())
        report["agreement_pct_all"] = round(100.0 * agreed / union, 1) if union else None
        out(f"{'all':22} {agreed:>6} {union:>5} {_agree(report['agreement_pct_all']):>6}")
    report["causes"] = dict(collections_counter(r["cause"] for rows in rows_of.values() for r in rows).most_common())
    report["unmatched_rows"] = unmatched_rows(rows_of)
    out("")
    out("claims by cause over all passes: " + ", ".join(f"{k} {v}" for k, v in report["causes"].items()))
    out("unmatched and dropped rows (cause: deck page cell metric value x passes):")
    for r in report["unmatched_rows"]:
        out(f"    {r['cause']}: {r['deck']} {_place(r)} {r['metric']} {r['value']} x{r['passes']}")
    out(f"B replayed the recorded replies of {run} in {report['calls']} calls; a page with no recorded reply gives no row.")
    return report


def _agree(value):
    return "-" if value is None else f"{value}%"


def markdown(report):
    """The --recorded tables as markdown for docs/test-runs: per pass and deck, agreement, causes, unmatched rows. No deck text."""
    passes = report["passes"]
    lines = [f"# Compare: rules read (A) against the page read (B), recorded replies of {report['recorded']}", "",
             "scripts/compare_pipelines.py --recorded: B replays the model's recorded replies of each pass through the gateway and page_check; "
             "A is the rules read (claims.detect_candidates). Recall and precision against the answer file (tests/fixtures/decks/expected_claims.json). "
             "Dropped: claims page_check drops before any check (an axis tick, a line the rules read drops, a cell not on the page).", "",
             "## Per deck and pass", "",
             "| Deck | Pass | Pages | Sent | A rows | A recall | A precision | B rows | Matched | Unmatched | Dropped | B recall | B precision | Only A | Only B |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for file, d in report["decks"].items():
        for n in passes:
            r = d["passes"][n]
            lines.append(f"| {file} | {n} | {d['pages']['pages']} | {d['pages']['sent']} | {d['rows_a']} | {_pct(d['a']['recall'])} | "
                         f"{_pct(d['a']['precision'])} | {r['rows_b']} | {r['matched']} | {r['unmatched']} | {r['dropped']} | {_pct(r['recall'])} | "
                         f"{_pct(r['precision'])} | {r['only_a']} | {r['only_b']} |")
    for n in passes:
        t = report["totals"]["passes"][n]
        lines.append(f"| all | {n} | | | {report['totals']['rows_a']} | | | {t['rows_b']} | {t['matched']} | {t['unmatched']} | {t['dropped']} | "
                     f"{_pct(t['recall'])} | | | |")
    if len(passes) > 1:
        lines += ["", "## Agreement across passes", "",
                  "Claims (value cell, metric, period) found in every pass / found in any pass, from the recorded replies. Disagreeing claims by "
                  "kind: metric (the cell is claimed in every pass, with another metric in some), period (cell and metric in every pass, another "
                  "period in some), presence (the cell is claimed in some passes only). Pages differ: a pass read pages another did not.", "",
                  "| Deck | Agreed | Union | Agreement | Metric | Period | Presence | Pages differ |", "|---|---:|---:|---:|---:|---:|---:|---|"]
        for file, d in report["decks"].items():
            g = d["agreement"]
            lines.append(f"| {file} | {g['agreed']} | {g['union']} | {g['pct']}% | {g['disagree']['metric']} | {g['disagree']['period']} | "
                         f"{g['disagree']['presence']} | {'yes' if g['pages_differ'] else 'no'} |")
        lines.append(f"| all | | | {_agree(report.get('agreement_pct_all'))} | | | | |")
    total = sum(report["causes"].values())
    lines += ["", "## Claims by cause", "",
              "Over all passes. A cause names the checks that failed (value, unit, period), "
              "no value (a milestone), or why the claim was dropped.", "",
              "| Cause | Claims | Share |", "|---|---:|---:|",
              *(f"| {k} | {v} | {_pct(round(v / total, 3)) if total else '-'} |" for k, v in report["causes"].items()),
              "", "## Unmatched and dropped rows", "",
              "One line per deck, page, cell, cause, metric and value; passes: in how many passes it appears.", "",
              "| Cause | Deck | Page | Cell | Metric | Value | Passes |", "|---|---|---:|---|---|---:|---:|",
              *(f"| {r['cause']} | {r['deck']} | {r['page']} | {r['cell']} | {r['metric']} | {r['value']} | {r['passes']} |"
                for r in report["unmatched_rows"]), ""]
    return "\n".join(lines)


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
        text = json.dumps({"type": json.loads(user_payload)["type"], "claims": consistency_run.claims_as_read(self.fixture["claims"])})
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
    ap.add_argument("--recorded", help="replay the recorded replies of this live run (a folder name under the fixtures' recorded/), pass by pass")
    ap.add_argument("--pass", dest="pass_number", type=int, action="append", help="with --recorded: this pass only (repeatable)")
    ap.add_argument("--md", help="with --recorded: also write the tables as markdown to this file")
    args = ap.parse_args(argv)
    decks = args.deck or sorted(p.name for p in DECKS.iterdir() if not p.name.startswith("."))
    if (args.pass_number or args.md) and not args.recorded:
        sys.exit("--pass and --md belong to --recorded.")
    if args.diagnostic:
        outside = not_public(decks)
        if outside:
            sys.exit(f"--diagnostic runs on the 10 public test decks only: {outside} is not one of them")
    if args.recorded:
        report = asyncio.run(run_recorded(decks, args.recorded, set(args.pass_number) if args.pass_number else None))
        if args.md:
            Path(args.md).write_text(markdown(report), encoding="utf-8")
        if args.out:
            Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
        return report
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
