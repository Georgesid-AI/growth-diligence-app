# ruff: noqa: F811, F401
"""Reading consistency, second pass (brief of George, 2026-11-05): compare rules A1-A7 and the token allowance C13. Synthetic maps and pages only;
every provider is a script. The reviewer's stop (C14) is tested in test_reviewer.py, where its helpers are."""
import asyncio
import copy
import logging
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pdfplumber")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import test_llm_gateway as t  # noqa: E402
from app import allowance, access, consistency, report_text, role_engine  # noqa: E402
from app.llm import gateway, guards  # noqa: E402
from app.structures import pages as pipeline  # noqa: E402
from test_reading_consistency import (  # noqa: E402
    AUDIT, SHEET, TwoReads, checks_doc, decide, flow, good_map, held_report, monthly, register, upload, MONTHLY, with_row,
)
from test_role_engine import file_of, metric, row as map_row, run, sheet  # noqa: E402
from test_page_pipeline import claim  # noqa: E402

QUEUES_SHEET_READER = True      # tests/conftest.py: an upload queues the reader
AWAITS = "awaits confirmation"


def map_of(*rows):
    out = copy.deepcopy(good_map())
    out["sheets"][0]["rows"] = [copy.deepcopy(r) for r in rows]
    return out


def a_row(n, **over):
    base = copy.deepcopy(good_map()["sheets"][0]["rows"][0])
    base.update(row=n, label_cell=f"A{n}", cells=f"B{n}:M{n}", **over)
    return base


# ---------------------------------------------------------------------------
# A1  a difference in the segment flag alone is no disagreement
# ---------------------------------------------------------------------------
def test_a1_reads_that_differ_only_in_the_segment_flag_are_not_uncertain():
    first, second = map_of(a_row(4)), map_of(a_row(4, segment="Region A"))
    assert consistency.compare(first, second) == []
    assert consistency.compare(second, first) == []


def test_a1_the_segment_flag_is_not_named_among_the_differing_fields_of_a_row_that_differs_otherwise():
    first, second = map_of(a_row(4)), map_of(a_row(4, segment="Region A", role="arr"))
    (item,) = consistency.compare(first, second)
    assert item["fields"] == ["role"]


# ---------------------------------------------------------------------------
# A2  a period on one read only is accepted with the period
# ---------------------------------------------------------------------------
def test_a2_a_figure_both_reads_agree_on_but_one_gives_a_period_is_accepted_with_the_period():
    with_period = claim("p1r3c1", 150000, period="2025")
    without = claim("p1r3c1", 150000, period=None)
    for first, second in ((with_period, without), (without, with_period)):
        (merged,) = pipeline.merge_reads([first], [second])
        assert not merged.get(pipeline.UNCERTAIN_KEY), "agreed on metric and value"
        assert merged["period"] == "2025", "stored with the period"


def test_a2_two_different_periods_are_still_a_disagreement_and_so_is_another_value():
    a = claim("p1r3c1", 150000, period="2025")
    assert pipeline.merge_reads([a], [claim("p1r3c1", 150000, period="2024")])[0].get(pipeline.UNCERTAIN_KEY)
    assert pipeline.merge_reads([a], [claim("p1r3c1", 160000, period=None)])[0].get(pipeline.UNCERTAIN_KEY)


# ---------------------------------------------------------------------------
# A3  a deck figure with the role "other" is never raised
# ---------------------------------------------------------------------------
def test_a3_a_deck_figure_of_the_metric_other_is_never_uncertain():
    other = claim("p1r2c1", 7, metric="other", unit="count")
    assert not any(c.get(pipeline.UNCERTAIN_KEY) for c in pipeline.merge_reads([other], []))          # only the first read gives it
    assert not any(c.get(pipeline.UNCERTAIN_KEY) for c in pipeline.merge_reads([], [other]))          # only the second read gives it
    assert not any(c.get(pipeline.UNCERTAIN_KEY) for c in pipeline.merge_reads([other], [{**other, "value": 8}]))     # the reads differ on the value
    real = claim("p1r2c1", 7, metric="customers", unit="count")
    assert not any(c.get(pipeline.UNCERTAIN_KEY) for c in pipeline.merge_reads([other], [real]))      # one read calls it other


def test_a3_a_figure_with_a_real_metric_that_only_one_read_gives_is_still_uncertain():
    real = claim("p1r2c1", 7, metric="customers", unit="count")
    assert pipeline.merge_reads([real], [])[0].get(pipeline.UNCERTAIN_KEY), "one read only"
    assert any(c.get(pipeline.UNCERTAIN_KEY) for c in pipeline.merge_reads([real], [claim("p1r3c1", 9, metric="customers", unit="count")]))


# ---------------------------------------------------------------------------
# A4  an analyst's override settles the fields it sets
# ---------------------------------------------------------------------------
def _override(item_row, field, **over):
    return {"item": f"row:{SHEET}:{item_row}", "path": f"sheets.0.rows.0.{field}", "old": "x", "new": "y", "why": "Change: revenue row", "at": "2026-11-05", **over}


def _record(fields, rows=(4,)):
    item = {"key": consistency.row_key(SHEET, rows[0]), "kind": "row", "sheet": SHEET, "row": rows[0], "rows": list(rows), "fields": fields,
            "first": {"role": "revenue"}, "second": {"role": "arr"}}
    return {"status": "compared", "items": [item]}


def test_a4_an_override_on_the_row_for_every_differing_field_settles_the_item():
    assert consistency.pending(_record(["role"]), [_override(4, "role")]) == []
    assert consistency.pending(_record(["role", "metric"]), [_override(4, "role"), _override(4, "metric")]) == []


def test_a4_an_override_on_one_of_two_differing_fields_leaves_the_other_field_to_decide():
    (left,) = consistency.pending(_record(["role", "metric"]), [_override(4, "role")])
    assert left["fields"] == ["metric"] and left["key"] == consistency.row_key(SHEET, 4)


def test_a4_an_override_of_another_row_or_another_field_settles_nothing():
    assert consistency.pending(_record(["role"]), [_override(5, "role")])[0]["fields"] == ["role"]
    assert consistency.pending(_record(["role"]), [_override(4, "boundary_col")])[0]["fields"] == ["role"]


def test_a4_a_settled_row_is_not_held_out_and_counts_as_no_waiting_item():
    waiting = consistency.pending(_record(["role"]), [_override(4, "role")])
    assert consistency.held_rows(good_map(), waiting) == []


def test_a4_the_register_shows_no_card_for_a_row_the_analyst_already_changed(flow):
    flow.state["adapter"] = TwoReads(with_row(good_map(), role="arr"), good_map())      # the first read takes row 4 for ARR
    upload(flow, MONTHLY, monthly())
    assert len(register(flow)["files"][0]["consistency"]["uncertain"]) == 1
    flow.post(f"/api/audits/{AUDIT}/readings/{checks_doc(flow)['file_hash']}/change", json={"what": "revenue_row", "sheet": SHEET, "row": 4})
    shown = register(flow)["files"][0]["consistency"]["uncertain"]
    assert shown == [], "the analyst's Change set the role: no card for it"


# ---------------------------------------------------------------------------
# A5  rows of one sheet with identical candidate pairs are one item
# ---------------------------------------------------------------------------
def test_a5_rows_with_identical_candidate_pairs_are_one_item_listing_the_row_numbers():
    first = map_of(*[a_row(n, role="revenue", metric="revenue") for n in (6, 7, 8, 9)])
    second = map_of(*[a_row(n, role="arr", metric="arr") for n in (6, 7, 8, 9)])
    (item,) = consistency.compare(first, second)
    assert item["rows"] == [6, 7, 8, 9] and item["row"] == 6 and item["key"] == consistency.row_key(SHEET, 6)
    assert item["fields"] == ["role", "metric"]


def test_a5_rows_whose_pairs_differ_stay_separate_and_a_second_sheet_is_its_own_item():
    first = map_of(a_row(6, role="revenue"), a_row(7, role="revenue"), a_row(8, role="revenue"))
    second = map_of(a_row(6, role="arr"), a_row(7, role="arr"), a_row(8, role="mrr"))
    items = consistency.compare(first, second)
    assert [(i["rows"]) for i in items] == [[6, 7], [8]]


def test_a5_every_row_of_a_group_is_held_out_until_the_group_is_picked():
    first = map_of(*[a_row(n, role="revenue") for n in (6, 7)])
    second = map_of(*[a_row(n, role="arr") for n in (6, 7)])
    items = consistency.compare(first, second)
    assert consistency.held_rows(first, items) == [f"{SHEET}:6", f"{SHEET}:7"]


def test_a5_one_pick_applies_to_all_the_rows_of_the_group(flow):
    first = map_of(*[a_row(n, role="revenue", metric="revenue") for n in (4, 5, 6)])
    second = map_of(*[a_row(n, role="arr", metric="arr") for n in (4, 5, 6)])
    flow.state["adapter"] = TwoReads(first, second)
    upload(flow, MONTHLY, monthly())
    (item,) = register(flow)["files"][0]["consistency"]["uncertain"]
    assert item["rows"] == [4, 5, 6]
    assert decide(flow, item["key"], "second").status_code == 200
    stored = flow.db["reading_overrides"].docs
    assert stored, "the pick is an override record"
    from app import readings
    effective = readings.effective(flow.db[readings.READINGS].docs[0]["file_map"], asyncio.run(readings.overrides_for(flow.db, AUDIT)))
    assert [(r["row"], r["role"]) for r in effective["sheets"][0]["rows"]] == [(4, "arr"), (5, "arr"), (6, "arr")]
    assert register(flow)["files"][0]["consistency"]["uncertain"] == []


# ---------------------------------------------------------------------------
# A6  a held row feeds no estimate and the templated lines treat it as absent
# ---------------------------------------------------------------------------
def split_files(held=()):
    from test_role_engine import YEARS, PLAN_YEARS
    plan = {"sales_marketing": (1_000, 1_200), "rnd": (600, 700), "ga": (400, 500), "opex": (2_000, 2_400)}
    rows = [map_row(4, "revenue", [1_000, 1_500, 2_400], YEARS, basis="yearly"), map_row(5, "opex", [800, 1_100, 1_900], YEARS, basis="yearly"),
            map_row(6, "sales_marketing", [200, 300, 900], YEARS, basis="yearly")]
    rows += [map_row(n, role, list(v), PLAN_YEARS, basis="yearly", actual_plan="plan", plan=True) for n, (role, v) in enumerate(plan.items(), start=10)]
    files = [file_of("pnl", [sheet("P&L", rows, granularity="yearly")])]
    files[0]["uncertain"] = [f"P&L:{n}" for n in held]
    return files


def test_a6_the_split_is_estimated_when_nothing_is_held():
    assert metric(run(split_files()), "rnd_expense")["status"] == "computed"


@pytest.mark.parametrize("held", [(11,), (12,), (13,), (10, 11, 12)])
def test_a6_a_held_plan_row_means_no_two_way_estimate_and_the_reason_is_awaits_confirmation(held):
    r = run(split_files(held))
    for name in ("rnd_expense", "ga_expense"):
        m = metric(r, name)
        assert m["status"] == "needs_row" and m["value"] is None and m["estimate"] is False, name
        assert m["reason"] == AWAITS, (name, m["reason"])


def test_a6_a_held_actual_row_means_no_estimate_either():
    r = run(split_files((6,)))
    assert metric(r, "rnd_expense")["reason"] == AWAITS


def test_a6_a_held_row_that_the_estimate_does_not_use_changes_nothing():
    extra = split_files()
    extra[0]["file_map"]["sheets"][0]["rows"].append(map_row(30, "cash", [5, 6, 7], ["2023", "2024", "2025"], basis="yearly", unit="money"))
    extra[0]["uncertain"] = ["P&L:30"]
    assert metric(run(extra), "rnd_expense")["status"] == "computed"


def test_a6_the_trend_table_has_no_estimate_from_a_held_row_and_says_why():
    ok = run(split_files())["role_metrics"]["pnl_trend"]
    assert any(v["estimate"] for rowv in ok["rows"] if rowv["metric"] == "rnd_share" for v in rowv["values"]), "the estimate exists when nothing is held"
    held = run(split_files((11,)))["role_metrics"]["pnl_trend"]
    rnd = next(x for x in held["rows"] if x["metric"] == "rnd_share")
    assert not any(v["estimate"] for v in rnd["values"]) and rnd["reason"] == AWAITS
    revenue = next(x for x in held["rows"] if x["metric"] == "revenue")
    assert revenue["reason"] is None, "a line with nothing held carries no reason"


def test_a6_the_templated_lines_read_a_held_role_as_awaiting_not_as_mapped_or_missing():
    table = role_engine.build_table(held_report())
    assert report_text.role_state(table, "customers") == "awaiting"
    assert report_text.missing_reason(table, ["customers"], "no value at the as-of month") == AWAITS
    again = role_engine.build_table(held_report(held=()))
    assert report_text.role_state(again, "customers") == "mapped"


# ---------------------------------------------------------------------------
# A7  no mapping flag for the role "other"
# ---------------------------------------------------------------------------
def test_a7_two_rows_of_the_role_other_raise_no_mapping_flag():
    rows = [map_row(4, "other", [1, 2, 3], ["2023", "2024", "2025"], basis="yearly"), map_row(5, "other", [1, 2, 3], ["2023", "2024", "2025"], basis="yearly"),
            map_row(6, "customers", [1, 2, 3], ["2023", "2024", "2025"], basis="yearly", unit="count"),
            map_row(7, "customers", [1, 2, 3], ["2023", "2024", "2025"], basis="yearly", unit="count")]
    table = role_engine.build_table([file_of("f", [sheet("S", rows, granularity="yearly")])])
    flags = role_engine.mapping_flags(table)
    assert [f["role"] for f in flags] == ["customers"], "the customers pair is flagged as before; the other pair is not"


# ---------------------------------------------------------------------------
# C13  the allowance and the per-audit cap count the first and the second read apart
# ---------------------------------------------------------------------------
def test_c13_the_tester_ledger_counts_the_first_and_the_second_read_apart_and_the_total_as_before():
    db = t.make_db()
    db[access.COLLECTION].docs.append({"id": "t1", "label": "T", "hash": "x", "created_at": "2026-10-01T00:00:00+00:00", "expires_at": "2099-01-01T00:00:00+00:00",
                                       "revoked_at": None})
    for a in db["audits"].docs:
        a["owner"] = "t1"
    for no, tokens in ((1, 1000), (2, 600), (None, 50)):
        asyncio.run(gateway.log_call(db, run_id=t.RUN_ID, step="structures", prompt_version="v", model="m", input_tokens=tokens, output_tokens=0,
                                     estimated_cost_usd=0.01, cache_hit=False, status="ok", read_no=no))
    month = db[access.COLLECTION].docs[0]["ledger"][allowance.month_key()]
    assert month["tokens"] == 1650, "the total, as before"
    assert (month["read1_tokens"], month["read2_tokens"]) == (1050, 600), "a call without a read number is a first read"
    assert allowance._bucket(db[access.COLLECTION].docs[0]["ledger"], allowance.month_key())["tokens"] == 1650


def test_c13_read_tokens_used_splits_an_audits_billed_tokens_by_read():
    db = t.make_db()
    db["llm_calls"].docs += [
        {"run_id": "r1", "step": "structures", "structure_type": "page_claims", "cache_hit": False, "input_tokens": 100, "output_tokens": 10, "read_no": 1},
        {"run_id": "r1", "step": "structures", "structure_type": "page_claims", "cache_hit": False, "input_tokens": 70, "output_tokens": 5, "read_no": 2},
        {"run_id": "r1", "step": "structures", "structure_type": "page_claims", "cache_hit": True, "input_tokens": 999, "output_tokens": 0, "read_no": 2},
        {"run_id": "r2", "step": "structures", "structure_type": "page_claims", "cache_hit": False, "input_tokens": 5, "output_tokens": 5, "read_no": 2}]
    assert asyncio.run(guards.read_tokens_used(db, "r1")) == {"first": 110, "second": 75}


def test_c13_a_cap_refusal_logs_both_reads_on_its_one_line(caplog):
    db = t.make_db()
    db["llm_calls"].docs += [
        {"run_id": "r1", "step": "structures", "structure_type": "page_claims", "cache_hit": False, "input_tokens": 500_000, "output_tokens": 0, "read_no": 1},
        {"run_id": "r1", "step": "structures", "structure_type": "page_claims", "cache_hit": False, "input_tokens": 90_000, "output_tokens": 0, "read_no": 2}]
    with pytest.raises(guards.GuardRefusal) as caught:
        asyncio.run(guards.check_structure_token_cap(db, "r1", 5_000, 16_000))
    assert caught.value.reason == "structure_token_cap_reached" and caught.value.used == 590_000
    assert (caught.value.first, caught.value.second) == (500_000, 90_000)
    caplog.set_level(logging.INFO)
    gateway.log_refusal("page_claims", "r1", caught.value)
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("ai call refused:")]
    assert line.endswith("used=590000 cap=600000 input=- first=500000 second=90000"), line


def test_c13_the_per_file_cap_counts_both_reads_of_the_file_and_names_them():
    db = t.make_db()
    db["llm_calls"].docs += [
        {"run_id": "r1", "step": "structures", "structure_type": "sheet_reading", "cache_hit": False, "input_tokens": 30_000, "output_tokens": 0, "file_hash": "h1", "read_no": 1},
        {"run_id": "r1", "step": "structures", "structure_type": "sheet_reading", "cache_hit": False, "input_tokens": 25_000, "output_tokens": 0, "file_hash": "h1", "read_no": 2}]
    import os
    os.environ["FILE_TOKEN_CAP"] = "50000"
    try:
        with pytest.raises(guards.GuardRefusal) as caught:
            asyncio.run(guards.check_file_token_cap(db, "r1", "h1", 1_000, 1_000))
    finally:
        del os.environ["FILE_TOKEN_CAP"]
    assert caught.value.used == 55_000 and (caught.value.first, caught.value.second) == (30_000, 25_000)


def test_c13_the_allowance_refusal_still_names_no_amount(caplog):
    caplog.set_level(logging.INFO)
    gateway.log_refusal("page_claims", "r1", guards.GuardRefusal("monthly_allowance_reached"))
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("ai call refused:")]
    assert line.endswith("reason=allowance used=- cap=- input=-"), line


# ---------------------------------------------------------------------------
# The Uncertain list needs, for a deck figure, its cell and the fields of each reading (item 9)
# ---------------------------------------------------------------------------
def test_a_deck_figure_that_waits_carries_its_cell_and_the_fields_of_each_reading(monkeypatch, second_page_read):
    from test_reading_consistency import DIFFERENT, FIRST, read_deck
    from app import register
    from test_page_pipeline import AUDIT as DECK_AUDIT
    db, _ = read_deck(monkeypatch, [FIRST, DIFFERENT])
    shown = asyncio.run(register.build(db, DECK_AUDIT))
    deck = next(f for f in shown["files"] if f["kind"] == "deck")
    revenue = next(f for f in deck["figures"] if f["metric"] == "revenue")
    assert revenue["uncertain"] and revenue["cell"] == "r3c1"
    assert revenue["reading"]["details"] == [{"metric": "revenue", "value": "150,000", "period": "2025"}, {"metric": "revenue", "value": "160,000", "period": "2025"}]
    assert revenue["reading"]["options"] == ["revenue · 150,000 · 2025", "revenue · 160,000 · 2025"]


# ---------------------------------------------------------------------------
# Data boundary (rule 14): what this pass adds to a log line or a results key holds closed words and numbers only
# ---------------------------------------------------------------------------
def test_the_new_reason_and_log_suffix_hold_closed_words_and_numbers_only(caplog):
    import re
    caplog.set_level(logging.INFO)
    refusal = guards.GuardRefusal("file_token_cap_reached", "text that must not be logged", used=55_000, cap=50_000, first=30_000, second=25_000)
    gateway.log_refusal("sheet_reading", "r1", refusal)
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("ai call refused:")]
    assert re.fullmatch(r"ai call refused: step=sheet_reading run_id=r1 reason=token_cap used=55000 cap=50000 input=- first=30000 second=25000", line)
    assert "must not be logged" not in line
    held = run(split_files((11,)))["role_metrics"]["pnl_trend"]
    assert {row["reason"] for row in held["rows"]} <= {None, "awaits confirmation"}


def test_the_tc_shape_on_synthetic_rows_13_segment_only_rows_raise_nothing_and_17_revenue_rows_group_to_fewer_lines():
    """The shape of the brief, not the client's file: 13 P&L rows the reads give a different segment flag, and 17 revenue-file rows whose candidate
    pairs are four distinct pairs. Before: 30 items. After: 4."""
    pnl_first = [a_row(n, role="cost_of_revenue", metric="cogs") for n in range(20, 33)]
    pnl_second = [a_row(n, role="cost_of_revenue", metric="cogs", segment="Region") for n in range(20, 33)]
    pairs = [("customers", "logos")] * 6 + [("mrr", "arr")] * 5 + [("churn", "attrition")] * 4 + [("cash", "bookings")] * 2
    rev_first = [a_row(40 + i, role=a, metric=a) for i, (a, b) in enumerate(pairs)]
    rev_second = [a_row(40 + i, role=a, metric=b) for i, (a, b) in enumerate(pairs)]
    items = consistency.compare(map_of(*pnl_first, *rev_first), map_of(*pnl_second, *rev_second))
    assert len(rev_first) == 17 and len(items) == 4 < 17
    assert sorted(len(i["rows"]) for i in items) == [2, 4, 5, 6]
