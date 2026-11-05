"""Reading consistency (commit 2 of the reconciliation and reading-consistency PR; docs/design/reading-consistency.md).

A spreadsheet is read twice on the same input and each deck page is read twice. What both reads give stands; what they do not both give is
stored as uncertain with both candidates, nothing is picked automatically, and an uncertain figure is used by no reconciliation, rating or verdict
until the analyst chooses. Synthetic maps and pages only; every provider is a script."""
import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pdfplumber")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from app import consistency, deck_figures, integrity, readings, role_engine, usage as usage_mod, verdict  # noqa: E402
from app.llm import gateway  # noqa: E402
from app.structures import checker, pages as pipeline  # noqa: E402
from test_page_pipeline import AUDIT as DECK_AUDIT, TITLE, _page_db, claim, deck  # noqa: E402
from test_sheet_reader_flow import COMPANY, MODEL, Router, SHEET, good_map, monthly  # noqa: E402
from test_role_engine import file_of, row as map_row, run, sheet  # noqa: E402
from upload_support import AUDIT, AUDIT_DOC, MONTHLY, upload  # noqa: E402

QUEUES_SHEET_READER = True      # tests/conftest.py: this module tests the reader, so an upload queues it
UNCERTAIN_TEXT = "Reading uncertain – confirm"


# ---------------------------------------------------------------------------
# Spreadsheets
# ---------------------------------------------------------------------------
class TwoReads(Router):
    """A sheet reading answered from two scripts: the first plain call gets `first`, the second plain call `second` (the consistency read), a
    re-read of rejected items `again`. A second of "fail" raises, as a provider error would."""

    def __init__(self, first, second, again=None):
        super().__init__(first, again)
        self.second, self.plain = second, 0

    def complete(self, **kw):
        sent = json.loads(kw["user_payload"])
        if sent["type"] == "sheet_reading" and "recheck" not in sent:
            self.plain += 1
            if self.plain == 2:
                self.sheet_calls += 1
                self.sheet_payloads.append(sent)
                if self.second == "fail":
                    raise gateway.GatewayError("model_refused", "not scripted")
                return json.dumps(self.second), 3100, 410
        return super().complete(**kw)


def with_row(base, **over):
    out = copy.deepcopy(base)
    out["sheets"][0]["rows"][0].update(over)
    return out


@pytest.fixture()
def flow(monkeypatch):
    db = t.FakeDB()
    db["audits"].docs.append({**AUDIT_DOC, "company_name": COMPANY, "usage": usage_mod.empty()})
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setenv("SHEET_READER_MODEL", MODEL)
    monkeypatch.delenv("READER_V1", raising=False)
    state = {"adapter": Router(good_map())}
    monkeypatch.setattr(gateway, "AnthropicAdapter", lambda *a, **k: state["adapter"])
    client = TestClient(server.app, raise_server_exceptions=False)
    client.db, client.state = db, state
    return client


def checks_doc(flow):
    return flow.db[readings.CHECKS].docs[0]


def register(flow):
    return flow.get(f"/api/audits/{AUDIT}/reading").json()


def decide(flow, key, pick):
    return flow.post(f"/api/audits/{AUDIT}/readings/{checks_doc(flow)['file_hash']}/uncertain", json={"key": key, "pick": pick})


def effective_row(flow):
    stored = flow.db[readings.READINGS].docs[0]
    overrides = asyncio.run(readings.overrides_for(flow.db, AUDIT))
    return readings.effective(stored["file_map"], overrides)["sheets"][0]["rows"][0]


def test_two_reads_that_differ_on_one_row_flag_it_with_both_candidates_and_store_the_first_reads_values(flow):
    flow.state["adapter"] = TwoReads(good_map(), with_row(good_map(), metric="mrr"))
    upload(flow, MONTHLY, monthly())
    doc = checks_doc(flow)
    assert doc["consistency"]["status"] == "compared" and len(doc["consistency"]["items"]) == 1
    item = doc["consistency"]["items"][0]
    assert item["key"] == f"uncertain:row:{SHEET}:4" and item["fields"] == ["metric"]
    assert item["first"]["metric"] == "revenue" and item["second"]["metric"] == "mrr", "both candidates"
    assert flow.db[readings.READINGS].docs[0]["file_map"]["sheets"][0]["rows"][0]["metric"] == "revenue", "stored with the first read's values"
    assert len(flow.db[readings.SECOND_READS].docs) == 1 and flow.db[readings.SECOND_READS].docs[0]["file_map"]["sheets"][0]["rows"][0]["metric"] == "mrr"
    shown = register(flow)["files"][0]["consistency"]
    assert shown["label"] == UNCERTAIN_TEXT and [i["key"] for i in shown["uncertain"]] == [item["key"]]
    assert not flow.db[readings.OVERRIDES].docs, "no automatic pick"


def test_two_identical_reads_flag_nothing(flow):
    upload(flow, MONTHLY, monthly())
    assert flow.state["adapter"].sheet_calls == 2
    assert checks_doc(flow)["consistency"]["items"] == []
    assert register(flow)["files"][0]["consistency"]["uncertain"] == []


def test_a_differing_sheet_level_field_is_flagged_on_the_detected_layout_block(flow):
    flow.state["adapter"] = TwoReads(good_map(), {**good_map(), "sheets": [{**good_map()["sheets"][0], "granularity": "quarterly", "header_row": 2}]})
    upload(flow, MONTHLY, monthly())
    items = {i["key"]: i for i in checks_doc(flow)["consistency"]["items"]}
    assert {f"uncertain:field:{SHEET}:granularity", f"uncertain:field:{SHEET}:header_row"} <= set(items), "each differing field is its own item"
    assert (items[f"uncertain:field:{SHEET}:granularity"]["first"], items[f"uncertain:field:{SHEET}:granularity"]["second"]) == ("monthly", "quarterly")
    assert register(flow)["files"][0]["consistency"]["uncertain"], "listed with the file for the layout block"


def test_the_analyst_picks_one_candidate_and_the_pick_is_an_override_not_an_edit(flow):
    flow.state["adapter"] = TwoReads(good_map(), with_row(good_map(), metric="mrr"))
    upload(flow, MONTHLY, monthly())
    key = checks_doc(flow)["consistency"]["items"][0]["key"]
    got = decide(flow, key, "second")
    assert got.status_code == 200
    assert effective_row(flow)["metric"] == "mrr"
    assert flow.db[readings.READINGS].docs[0]["file_map"]["sheets"][0]["rows"][0]["metric"] == "revenue", "the stored reading is never edited"
    override, = flow.db[readings.OVERRIDES].docs
    assert override["item"] == key and override["why"] == consistency.WHY_SECOND and override["who"] == "analyst"
    assert register(flow)["files"][0]["consistency"]["uncertain"] == [], "decided: no longer waiting"
    assert decide(flow, key, "second").status_code == 400, "an item is decided once"


def test_picking_the_first_reading_records_the_decision_and_changes_nothing(flow):
    flow.state["adapter"] = TwoReads(good_map(), with_row(good_map(), metric="mrr"))
    upload(flow, MONTHLY, monthly())
    key = checks_doc(flow)["consistency"]["items"][0]["key"]
    assert decide(flow, key, "first").status_code == 200
    assert effective_row(flow)["metric"] == "revenue" and flow.db[readings.OVERRIDES].docs[0]["why"] == consistency.WHY
    assert register(flow)["files"][0]["consistency"]["uncertain"] == []


def test_a_row_only_one_read_gives_is_flagged_and_the_second_reads_row_can_be_picked(flow):
    extra = copy.deepcopy(good_map())
    extra["sheets"][0]["rows"].append({**extra["sheets"][0]["rows"][0], "row": 5, "role": "customers", "metric": "customers", "unit": "count", "cells": "B5:M5"})
    flow.state["adapter"] = TwoReads(good_map(), extra)
    upload(flow, MONTHLY, monthly())
    item, = checks_doc(flow)["consistency"]["items"]
    assert item["key"] == f"uncertain:row:{SHEET}:5" and item["first"] is None and item["second"]["role"] == "customers"
    assert decide(flow, item["key"], "second").status_code == 200
    stored = flow.db[readings.READINGS].docs[0]
    rows = readings.effective(stored["file_map"], asyncio.run(readings.overrides_for(flow.db, AUDIT)))["sheets"][0]["rows"]
    assert [r["row"] for r in rows] == [4, 5] and len(stored["file_map"]["sheets"][0]["rows"]) == 1


def test_an_uncertain_row_waits_in_the_role_table_and_counts_as_awaiting_confirmation(flow):
    flow.state["adapter"] = TwoReads(good_map(), with_row(good_map(), metric="mrr"))
    upload(flow, MONTHLY, monthly())
    inputs = asyncio.run(server._role_inputs(AUDIT, flow.db["audits"].docs[0]))
    assert [r["uncertain"] for r in inputs["table"] if r["role"] == "revenue"] == [True]
    assert role_engine.awaiting_confirmation(inputs["table"], [])["count"] == 1
    decide(flow, f"uncertain:row:{SHEET}:4", "first")
    inputs = asyncio.run(server._role_inputs(AUDIT, flow.db["audits"].docs[0]))
    assert [r["uncertain"] for r in inputs["table"] if r["role"] == "revenue"] == [False]


def test_re_read_reuses_the_stored_first_read_and_does_one_new_read_not_two(flow):
    upload(flow, MONTHLY, monthly())
    router = flow.state["adapter"]
    assert router.sheet_calls == 2
    file_hash = checks_doc(flow)["file_hash"]
    assert flow.post(f"/api/audits/{AUDIT}/datasets/{file_hash}/reread").status_code == 200
    assert router.sheet_calls == 2, "both reads are stored: nothing new is read"
    flow.db[readings.SECOND_READS].docs.clear()          # a file read before the second read existed
    assert flow.post(f"/api/audits/{AUDIT}/datasets/{file_hash}/reread").status_code == 200
    assert router.sheet_calls == 3, "one new read, not two"
    assert len(flow.db[readings.SECOND_READS].docs) == 1 and len(flow.db[readings.READINGS].docs) == 1


def test_the_token_usage_of_both_reads_is_logged_per_file(flow):
    flow.state["adapter"] = TwoReads(good_map(), good_map())
    upload(flow, MONTHLY, monthly())
    calls = [c for c in flow.db["llm_calls"].docs if c.get("structure_type") == "sheet_reading"]
    assert [(c["read_no"], c["file_hash"] == checks_doc(flow)["file_hash"], c["input_tokens"] > 0) for c in calls] == [(1, True, True), (2, True, True)]
    assert checks_doc(flow)["consistency"]["reads"]["second"]["input_tokens"] > 0


def test_a_second_read_that_fails_leaves_the_first_reading_standing_and_flags_nothing(flow):
    flow.state["adapter"] = TwoReads(good_map(), "fail")
    upload(flow, MONTHLY, monthly())
    doc = checks_doc(flow)
    assert doc["status"] == "read" and doc["consistency"]["status"] == "not_compared" and doc["consistency"]["items"] == []
    assert doc["consistency"]["reason"].startswith("second read not completed")
    assert flow.db[readings.READINGS].docs[0].get("status") != readings.NOT_READ and not flow.db[readings.SECOND_READS].docs


def test_delete_audit_removes_the_second_reads_with_the_reading(flow):
    upload(flow, MONTHLY, monthly())
    assert flow.db[readings.SECOND_READS].docs
    asyncio.run(readings.purge_audit(flow.db, AUDIT))
    assert not flow.db[readings.READINGS].docs and not flow.db[readings.SECOND_READS].docs


# ---------------------------------------------------------------------------
# Deck pages
# ---------------------------------------------------------------------------
LINES = [(50, 500, 12, "800 Paying Users"), (50, 480, 12, "$150,000 annual revenue FY2025"), (50, 460, 12, "97% margins")]


def reply(*claims):
    return json.dumps({"type": "page_claims", "claims": list(claims)})


FIRST = reply(claim("p1r2c1", 800, metric="customers", unit="count"), claim("p1r3c1", 150000, period="2025"),
              claim("p1r4c1", 97, metric="gross_margin", unit="%"))
SAME = FIRST
DIFFERENT = reply(claim("p1r2c1", 800, metric="customers", unit="count"), claim("p1r3c1", 160000, period="2025"))     # another revenue, no margin


def read_deck(monkeypatch, replies):
    from app import structures
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    db = _page_db(deck([TITLE, *LINES]))
    adapter = t.FakeAdapter(replies=replies)
    asyncio.run(structures.process_deck(db, DECK_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    return db, adapter


def rows_of(db):
    from app.decks import CANDIDATES_COLLECTION
    return sorted(db[CANDIDATES_COLLECTION].docs, key=lambda r: r["order"])


def test_two_identical_page_reads_accept_every_figure_as_now(monkeypatch, second_page_read):
    db, adapter = read_deck(monkeypatch, [SAME])
    assert adapter.calls == 2, "the page was read twice"
    assert len(rows_of(db)) == 3 and all(checker.READING_UNCERTAIN not in r["flags"] for r in rows_of(db))
    assert [c["read_no"] for c in db["llm_calls"].docs if c.get("structure_type") == "page_claims"] == [1, 2], "the tokens of both reads are logged"


def test_a_figure_the_reads_disagree_on_or_only_one_read_gives_is_uncertain_with_both_candidates(monkeypatch, second_page_read):
    db, adapter = read_deck(monkeypatch, [FIRST, DIFFERENT])
    by_type = {r["claim_type"]: r for r in rows_of(db)}
    assert checker.READING_UNCERTAIN not in by_type["customers"]["flags"], "agreed: accepted as now"
    revenue, margin = by_type["revenue"], by_type["gross_margin"]
    assert checker.READING_UNCERTAIN in revenue["flags"] and revenue["value"] == 150000, "stored with the first read's value"
    entry, = [e for e in revenue["corrections"] if e["reason"] == checker.READING_UNCERTAIN]
    assert entry["state"] == "choose" and [o["set"]["value"] for o in entry["options"]] == [150000, 160000], "both candidates"
    assert checker.READING_UNCERTAIN in margin["flags"] and [o["set"]["value"] for o in margin["corrections"][-1]["options"]] == [97], "present in one read only"
    assert revenue["status"] == "pending", "nothing is chosen for the analyst"


def test_merge_reads_marks_only_what_both_reads_do_not_give_with_the_same_metric_period_and_value():
    a, b = json.loads(FIRST)["claims"], json.loads(DIFFERENT)["claims"]
    assert not any(c.get(pipeline.UNCERTAIN_KEY) for c in pipeline.merge_reads(a, a))
    assert [c["metric"] for c in pipeline.merge_reads(a, b) if c.get(pipeline.UNCERTAIN_KEY)] == ["revenue", "gross_margin"]
    assert pipeline.merge_reads(a, None) == a, "no second read, nothing marked"
    moved = [{**a[1], "period": "2024"}]
    assert [c["metric"] for c in pipeline.merge_reads([a[1]], moved) if c.get(pipeline.UNCERTAIN_KEY)] == ["revenue"], "another period is not the same figure"


def synthetic_pnl(value=150_000):
    return [file_of("pnl", [sheet("P&L", [map_row(4, "revenue", [value], ["2025"], basis="yearly")], granularity="yearly")])]


def engine_deck(db):
    checked = asyncio.run(deck_figures.checked(db, DECK_AUDIT))
    return [{**f, "file": d["file"], "page": f["source"]["page"], "actual_plan": "actual"} for d in checked for f in d["figures"] if f["outcome"] != "rejected"]


def test_an_uncertain_deck_figure_is_held_out_of_the_reconciliation_and_the_ratings_say_it_awaits_confirmation(monkeypatch, second_page_read):
    db, _ = read_deck(monkeypatch, [FIRST, DIFFERENT])
    figures = engine_deck(db)
    revenue = next(f for f in figures if f["metric"] == "revenue")
    assert revenue["uncertain"] is True and revenue["period"] == "2025"
    results = run(synthetic_pnl(), as_of="2025-12", deck=figures)
    assert results["role_metrics"]["reconciliation"] == [], "the uncertain figure is no source"
    assert results["role_metrics"]["awaiting_confirmation"] == {"count": 2, "rows": 0, "figures": 2}, "every uncertain figure counts, whatever its metric"
    rated = verdict.ratings(results, integrity.assess(results, 0, []), lambda v: f"{v:.0%}", lambda v: f"{v} months")
    assert rated["data_reliability"]["line"].endswith("2 figures await confirmation") and rated["growth_engine"]["line"].endswith("2 figures await confirmation")
    assert rated["data_reliability"]["rule"].endswith("2 figures await confirmation")
    two = verdict.ratings({"role_metrics": {"awaiting_confirmation": {"count": 3}}}, None, lambda v: v, lambda v: v)
    assert two["data_reliability"]["line"].endswith("– 3 figures await confirmation")
    plain = verdict.ratings(run(synthetic_pnl(), as_of="2025-12"), integrity.assess(run(synthetic_pnl(), as_of="2025-12"), 0, []), lambda v: v, lambda v: v)
    assert "confirmation" not in plain["data_reliability"]["line"] + plain["growth_engine"]["line"]


def test_the_memo_summary_says_it_once_and_each_rating_line_says_it(monkeypatch, second_page_read):
    from test_memo_role_metrics import build
    db, _ = read_deck(monkeypatch, [FIRST, DIFFERENT])
    maps = synthetic_pnl()
    memo = build(run(maps, as_of="2025-12", deck=engine_deck(db)), maps)
    summary = memo.split("## Summary")[1].split("## Scorecard")[0]
    scorecard = memo.split("## Scorecard")[1].split("##")[0]
    assert summary.count("await confirmation") + summary.count("awaits confirmation") == 1
    assert scorecard.count("confirmation") == 2, "Data reliability and Growth engine"
    clean = build(run(maps, as_of="2025-12"), maps)
    assert "confirmation" not in clean.split("## Summary")[1].split("## Appendix A")[0]


def test_confirming_the_figure_includes_it(monkeypatch, second_page_read):
    db, _ = read_deck(monkeypatch, [FIRST, DIFFERENT])
    monkeypatch.setattr(server, "db", db)
    client = TestClient(server.app, raise_server_exceptions=False)
    revenue = next(r for r in rows_of(db) if r["claim_type"] == "revenue")
    # Nothing is chosen for the analyst: Keep is not the way out, a candidate is.
    got = client.post(f"/api/audits/{DECK_AUDIT}/decks/candidates/{revenue['id']}/correction", json={"index": len(revenue["corrections"]) - 1, "action": "choose", "option": 0})
    assert got.status_code == 200, got.text
    after = got.json()
    assert checker.READING_UNCERTAIN not in after["flags"] and after["value"] == 150000 and after["status"] == "approved"
    figures = engine_deck(db)
    assert next(f for f in figures if f["metric"] == "revenue")["uncertain"] is False
    results = run(synthetic_pnl(), as_of="2025-12", deck=figures)
    rec, = results["role_metrics"]["reconciliation"]
    assert rec["status"] == "agrees" and {s["kind"] for s in rec["sources"]} == {"file", "deck"}, "confirmed: the figure is a source"
    assert results["role_metrics"]["awaiting_confirmation"] == {"count": 1, "rows": 0, "figures": 1}, "only the margin still awaits"
    undone = client.post(f"/api/audits/{DECK_AUDIT}/decks/candidates/{revenue['id']}/correction", json={"index": len(revenue["corrections"]) - 1, "action": "undo"})
    assert undone.status_code == 200 and checker.READING_UNCERTAIN in undone.json()["flags"] and undone.json()["value"] == 150000 and undone.json()["status"] == "pending"


def test_a_second_page_read_that_fails_leaves_the_page_unflagged(monkeypatch, second_page_read):
    from app import structures
    monkeypatch.setenv("DECK_PIPELINE", "ai")
    db = _page_db(deck([TITLE, *LINES]))

    class Failing(t.FakeAdapter):
        def complete(self, **kw):
            if self.calls >= 1:
                self.calls += 1
                raise gateway.GatewayError("model_refused", "no second read")
            return super().complete(**kw)
    adapter = Failing(replies=[FIRST])
    asyncio.run(structures.process_deck(db, DECK_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert len(rows_of(db)) == 3 and all(checker.READING_UNCERTAIN not in r["flags"] for r in rows_of(db))


def test_the_second_page_reads_reply_is_never_a_page_reply_the_normaliser_would_check_again(monkeypatch, second_page_read):
    db, _ = read_deck(monkeypatch, [FIRST, DIFFERENT])
    stored = db["llm_structures"].docs
    assert sorted(d["type"] for d in stored) == ["page_claims", "page_claims_second"]
    first = next(d for d in stored if d["type"] == "page_claims")
    assert first["second_key"] == next(d for d in stored if d["type"] == "page_claims_second")["key"]


# ---------------------------------------------------------------------------
# Uncertain sheet rows are held out of the engine; every uncertain row and figure counts
# ---------------------------------------------------------------------------
def held_report(held=("Report:8",), extra_rows=()):
    from test_role_engine import monthly_report
    files = monthly_report(list(extra_rows))
    files[0]["uncertain"] = list(held)
    return files


def test_an_uncertain_sheet_row_is_held_out_of_the_engine_and_its_metric_awaits_confirmation():
    r = run(held_report(), as_of="2026-06")
    customers = next(m for m in r["role_metrics"]["metrics"] if m["metric"] == "customers")
    assert customers["status"] == "needs_row" and customers["reason"] == "awaits confirmation" and customers["value"] is None
    assert r["customers_series"]["data"] == [], "not computed from the held row"
    arr = next(m for m in r["role_metrics"]["metrics"] if m["metric"] == "ending_arr")
    assert arr["status"] == "computed", "the other rows are used as before"
    assert run(held_report(held=()), as_of="2026-06")["customers_series"]["data"], "the same row, agreed, is used"


def test_a_held_row_is_not_reported_as_a_missing_row_by_the_report_text():
    from app import report_text, role_engine
    files = held_report()
    results = run(files, as_of="2026-06")
    table = role_engine.build_table(files)
    again = report_text.apply_reasons(results, table)
    customers = next(m for m in again["role_metrics"]["metrics"] if m["metric"] == "customers")
    assert customers["reason"] == "awaits confirmation"


def test_every_uncertain_row_and_figure_counts_whatever_its_role_or_metric():
    from test_role_engine import row as map_row_, MONTHS
    cash = map_row_(9, "cash", [10] * 18, MONTHS[:18], unit="money")
    rows = run(held_report(held=("Report:9",), extra_rows=[cash]), as_of="2026-06")["role_metrics"]["awaiting_confirmation"]
    assert rows == {"count": 1, "rows": 1, "figures": 0}, "a cash row is no role a rating reads, and still counts"
    deck = [{"metric": "ebitda", "period": "2025", "value": 5.0, "uncertain": True, "file": "d", "page": 1}]
    assert run(held_report(held=()), as_of="2026-06", deck=deck)["role_metrics"]["awaiting_confirmation"] == {"count": 1, "rows": 0, "figures": 1}


# ---------------------------------------------------------------------------
# Review of commit 2 (2026-11-05): a sheet-level item holds the sheet's rows; picking the second read of a sheet it lacks removes the sheet;
# a confirmed deck reading survives a Re-read of the deck
# ---------------------------------------------------------------------------
def second_without_the_sheet():
    return {**good_map(), "figures": [], "sheets": []}


def test_the_rows_of_a_sheet_only_the_first_read_gives_are_held_out_of_the_engine_until_the_sheet_is_confirmed(flow):
    flow.state["adapter"] = TwoReads(good_map(), second_without_the_sheet())
    upload(flow, MONTHLY, monthly())
    item, = checks_doc(flow)["consistency"]["items"]
    assert item["kind"] == "sheet" and item["second"] is None
    inputs = asyncio.run(server._role_inputs(AUDIT, flow.db["audits"].docs[0]))
    assert [r["uncertain"] for r in inputs["table"] if r["role"] == "revenue"] == [True], "a row the second read did not give is uncertain"
    assert role_engine.awaiting_confirmation(inputs["table"], [])["rows"] == 1
    assert decide(flow, item["key"], "first").status_code == 200
    inputs = asyncio.run(server._role_inputs(AUDIT, flow.db["audits"].docs[0]))
    assert [r["uncertain"] for r in inputs["table"] if r["role"] == "revenue"] == [False]


def test_the_rows_of_a_sheet_whose_layout_the_reads_disagree_on_are_held_until_the_layout_is_confirmed(flow):
    # The last actual column: the as-of month and the actual/plan split come from it, and a difference flags no row of its own.
    boundary = {"column": "F", "period": "2025-05", "evidence": []}
    flow.state["adapter"] = TwoReads(good_map(), {**good_map(), "sheets": [{**good_map()["sheets"][0], "last_actual": boundary}]})
    upload(flow, MONTHLY, monthly())
    item, = checks_doc(flow)["consistency"]["items"]
    assert item["kind"] == "field" and item["name"] == "last_actual"
    inputs = asyncio.run(server._role_inputs(AUDIT, flow.db["audits"].docs[0]))
    assert [r["uncertain"] for r in inputs["table"] if r["role"] == "revenue"] == [True], "the row's series and the as-of month are read under the layout"
    assert decide(flow, item["key"], "first").status_code == 200
    inputs = asyncio.run(server._role_inputs(AUDIT, flow.db["audits"].docs[0]))
    assert [r["uncertain"] for r in inputs["table"] if r["role"] == "revenue"] == [False]


def test_picking_the_second_reading_of_a_sheet_the_second_read_does_not_give_removes_the_sheet(flow):
    flow.state["adapter"] = TwoReads(good_map(), second_without_the_sheet())
    upload(flow, MONTHLY, monthly())
    item, = checks_doc(flow)["consistency"]["items"]
    assert decide(flow, item["key"], "second").status_code == 200
    stored = flow.db[readings.READINGS].docs[0]
    effective = readings.effective(stored["file_map"], asyncio.run(readings.overrides_for(flow.db, AUDIT)))
    assert effective["sheets"] == [], "the second reading: no such sheet"
    assert len(stored["file_map"]["sheets"]) == 1, "the stored reading is never edited"
    assert register(flow)["files"][0]["consistency"]["uncertain"] == []


def test_a_confirmed_deck_reading_survives_a_re_read_of_the_deck(monkeypatch, second_page_read):
    from app import structures
    db, adapter = read_deck(monkeypatch, [FIRST, DIFFERENT])
    monkeypatch.setattr(server, "db", db)
    client = TestClient(server.app, raise_server_exceptions=False)
    revenue = next(r for r in rows_of(db) if r["claim_type"] == "revenue")
    got = client.post(f"/api/audits/{DECK_AUDIT}/decks/candidates/{revenue['id']}/correction",
                      json={"index": len(revenue["corrections"]) - 1, "action": "choose", "option": 1})
    assert got.status_code == 200 and got.json()["value"] == 160000 and got.json()["status"] == "approved"
    # Re-read: both stored reads are served, no call is made, and the analyst's choice stands as the one revenue row.
    asyncio.run(structures.process_deck(db, DECK_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert adapter.calls == 2, "both reads of the page are stored: nothing is read again"
    again = [r for r in rows_of(db) if r["claim_type"] == "revenue"]
    assert [(r["value"], r["status"], checker.READING_UNCERTAIN in r["flags"]) for r in again] == [(160000, "approved", False)], \
        "the uncertain card does not come back beside the confirmed figure"
    margin = [r for r in rows_of(db) if r["claim_type"] == "gross_margin"]
    assert [checker.READING_UNCERTAIN in r["flags"] for r in margin] == [True], "what was not chosen still waits"
    # Undo, then Re-read: the card comes back once, with both readings, and nothing beside it.
    kept, = again
    undone = client.post(f"/api/audits/{DECK_AUDIT}/decks/candidates/{kept['id']}/correction", json={"index": len(kept["corrections"]) - 1, "action": "undo"})
    assert undone.status_code == 200 and undone.json()["status"] == "pending"
    asyncio.run(structures.process_deck(db, DECK_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    back = [r for r in rows_of(db) if r["claim_type"] == "revenue"]
    assert [(r["value"], r["status"], checker.READING_UNCERTAIN in r["flags"]) for r in back] == [(150000, "pending", True)]
    assert [o["set"]["value"] for o in back[0]["corrections"][-1]["options"]] == [150000, 160000] and adapter.calls == 2


@pytest.mark.parametrize("field, other", [("unit", "count"), ("currency", "USD"), ("basis", "yearly")])
def test_two_reads_that_differ_on_a_rows_unit_currency_or_basis_flag_the_row_with_both_candidates(flow, field, other):
    """George, 2026-11-05: a difference in unit, currency or basis is read into the figures (the fx, the form of the series), so it is a
    disagreement like one on the role or the metric."""
    flow.state["adapter"] = TwoReads(good_map(), with_row(good_map(), **{field: other}))
    upload(flow, MONTHLY, monthly())
    item, = checks_doc(flow)["consistency"]["items"]
    assert item["key"] == f"uncertain:row:{SHEET}:4" and item["fields"] == [field]
    assert (item["first"][field], item["second"][field]) == (good_map()["sheets"][0]["rows"][0][field], other), "both candidates carry the field"
    inputs = asyncio.run(server._role_inputs(AUDIT, flow.db["audits"].docs[0]))
    assert [r["uncertain"] for r in inputs["table"] if r["role"] == "revenue"] == [True]
    assert decide(flow, item["key"], "second").status_code == 200 and effective_row(flow)[field] == other
