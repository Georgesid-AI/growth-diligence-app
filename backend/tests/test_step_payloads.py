"""The data inventory (A1) and data integrity (A2) narratives: the payload builders, the step guards, the cache and the
spend cap. No test here reaches a model provider: the provider is the gateway tests' FakeAdapter."""
import asyncio
import copy
import json
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import formatting as fmt  # noqa: E402
from app.llm import gateway, guards, schemas, step_payloads as sp  # noqa: E402
import contract_fixtures as cf  # noqa: E402
import test_llm_gateway as t  # noqa: E402

RUN_ID = t.RUN_ID
STEPS = ("data_inventory", "data_integrity")
FILE_NAMES = ("Billing_Export_Q3.xlsx", "Deals_Pipeline.csv", "Mgmt_Accounts.xlsx")
SHEETS = ("Billing Sheet", "Deals Sheet", "Accounts Sheet")
CUSTOMER = "Zeta Holdings GmbH"
MONTHS = [f"2025-{m:02d}" for m in range(1, 13)]


def cite(i=0, rule="rule"):
    return cf.cite(FILE_NAMES[i], SHEETS[i], rows=(2, 3, 4), rule=rule)


def reconciliation(over=True):
    """A stored reconciliation, 12 months: the first month 10% over the P&L (when `over`), the others inside 2%."""
    by_month = []
    for i, m in enumerate(MONTHS):
        pct = 0.10 if (over and i == 0) else 0.01
        by_month.append({"month": m, "revenue_file": 110000.0, "pnl": 100000.0, "gap": 10000.0, "gap_pct": pct,
                         "source": {"revenue_file": cite(0), "pnl": cite(2)}})
    total = (1_100_000.0, 1_000_000.0) if over else (1_010_000.0, 1_000_000.0)
    gap = total[0] - total[1]
    return {"available": True, "first": MONTHS[0], "last": MONTHS[-1], "tolerance_pct": 0.02, "file_total": total[0],
            "pnl_total": total[1], "gap": gap, "gap_pct": round(gap / total[1], 4), "blocker": gap / total[1] > 0.02,
            "by_month": by_month, "source": {"revenue_file": cite(0), "pnl": cite(2)}}


def full_results(over=True, months=18):
    mrr_months = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 7)]
    mrr_months = mrr_months[-months:]
    return cf.stored(
        as_of_month="2026-06",
        arr=cf.arr(3129600.0, 260800.0, source=cite(0)),
        nrr=cf.nrr(1.04, 110, source=cite(0)),
        gross_churn=cf.gross_churn(0.061),
        win_rate=cf.win_rate(0.3, 30, 70, source=cite(1)),
        sales_cycle=cf.sales_cycle(45, 30, source=cite(1)),
        cac_payback=cf.cac_payback({"2026-Q1": cf.cac_quarter()}, headline="2026-Q1", source=cite(2)),
        acv_path=cf.acv_path(source=cite(0)),
        segment_paths=cf.segment_paths(available=True, source=cite(0)),
        anomalies=cf.anomalies(revenue_missing_customer_id={"count": 3, "rows": [5, 6, 7]},
                               revenue_gap_then_resume=[CUSTOMER],
                               deals_close_before_created={"excluded_count": 2, "rows": [9, 10]},
                               deals_source=cite(1), source=cite(0)),
        mrr_series={**cf.series(mrr_months, [], [{"month": m, "total": 1.0} for m in mrr_months]), "source": cite(0)},
        revenue_reconciliation=reconciliation(over),
    )


def db_for(results):
    db = t.FakeDB()
    doc = copy.deepcopy(t.RESULTS_DOC)
    doc["results"] = results
    db["audits"].docs.append(doc)
    return db


def run(db, step, reply=None, **kw):
    adapter = t.FakeAdapter(replies=[json.dumps(reply)] if reply is not None else None)
    result = asyncio.run(gateway.generate_narrative(db, RUN_ID, step, adapter=adapter, sleep=t._noop_sleep, **kw))
    return result, adapter


def payload_of(step, results=None):
    computed = {"metrics": gateway._slice_for_step(results or full_results(), step)}
    return gateway.build_outbound(computed, {})


def words(n):
    return " ".join(["word"] * n)


def inventory_reply(**over):
    reply = {
        "headline": "Revenue and CRM are supplied, the P&L is only partly usable.",
        "what_this_means": "Net revenue retention is computed. Three file types are not ingested yet.",
        "table_rows": [{"label": "Revenue by customer", "value": "Provided", "source_key": "S1",
                        "decision_informed": "Whether retention can be relied on"},
                       {"label": "Headcount", "value": "Not ingested", "source_key": "metrics.inventory.status",
                        "decision_informed": "Execution capacity"}],
        "worth_flagging": ["3 revenue lines without a customer ID, excluded."],
        "next_actions": ["Ask management for the P&L months that complete the 12-month window."],
        "source_keys": ["S1"],
    }
    reply.update(over)
    return reply


def integrity_reply(**over):
    reply = {
        "headline": "Material concerns: the revenue file and the P&L differ by 10% over the window.",
        "what_this_means": "The revenue file is above the P&L. Five checks were not computed.",
        "table_rows": [{"label": "Revenue file against P&L", "value": "10%", "source_key": "S1",
                        "decision_informed": "Whether revenue can be relied on"}],
        "worth_flagging": ["3 revenue lines have no customer ID."],
        "next_actions": ["Ask management to reconcile the revenue file with the P&L."],
        "source_keys": ["S1"],
        "verdict": "Material concerns",
    }
    reply.update(over)
    return reply


GOOD = {"data_inventory": inventory_reply, "data_integrity": integrity_reply}


# --- the inventory payload -------------------------------------------------------------------------------------------------

def rows_by_name(step_slice):
    return {r["category"]: r for r in step_slice["inventory"]}


def test_inventory_status_per_category_months_issues_and_blocked_analyses():
    inv = rows_by_name(sp.build_inventory(full_results(over=False)))
    revenue = inv["Revenue by customer"]
    assert revenue["status"] == "Provided" and revenue["source_key"] == "S1"
    assert (revenue["months_supplied"], revenue["months_required"]) == ("18", "13")
    assert "3 revenue line(s) without a customer ID, excluded" in revenue["quality_issues"]
    assert inv["CRM"]["status"] == "Provided" and inv["CRM"]["source_key"] == "S2"
    assert "2 deal(s) closing before they were created, excluded" in inv["CRM"]["quality_issues"]
    pnl = inv["P&L"]
    assert pnl["status"] == "Provided" and (pnl["months_supplied"], pnl["months_required"]) == ("12", "12")
    assert pnl["analyses_blocked"] == []


def test_a_pnl_that_blocks_an_analysis_is_partial():
    results = full_results(over=False)
    results["cac_payback"] = None
    pnl = rows_by_name(sp.build_inventory(results))["P&L"]
    assert pnl["status"] == "Partial" and pnl["analyses_blocked"] == ["CAC payback"] and pnl["in_request_list"] is True


def test_a_short_revenue_history_is_partial_and_names_what_it_blocks():
    results = full_results(over=False, months=7)
    results["nrr"] = results["gross_churn"] = None
    revenue = rows_by_name(sp.build_inventory(results))["Revenue by customer"]
    assert revenue["status"] == "Partial" and revenue["months_supplied"] == "7"
    assert {"NRR", "Gross revenue churn"} <= set(revenue["analyses_blocked"]) and revenue["in_request_list"] is True


def test_a_missing_category_has_no_source_key_and_no_source_is_listed_for_it():
    results = full_results()
    results.update(win_rate=None, sales_cycle=None, revenue_reconciliation=None, cac_payback=None)
    results["anomalies"].pop("deals_source")
    out = sp.build_inventory(results)
    crm = rows_by_name(out)["CRM"]
    assert crm["status"] == "Missing" and "source_key" not in crm and crm["in_request_list"] is True
    assert crm["analyses_blocked"] == ["Sales cycle", "Win rate"]
    assert [s["source_key"] for s in out["source_list"]] == ["S1"]
    assert out["source_list"][0]["description"] == "revenue by customer file"


def test_not_ingested_categories_are_marked_and_off_the_request_list():
    inv = rows_by_name(sp.build_inventory(full_results()))
    for name in ("Headcount", "Product usage", "Roadmap"):
        assert inv[name]["status"] == "Not ingested" and inv[name]["in_request_list"] is False
        assert "source_key" not in inv[name]
    assert set(sp.NOT_INGESTED_NAMES) == {"Headcount", "Product usage", "Roadmap"}


def test_the_month_requirements_are_the_engines():
    import growth_engine as ge
    source = Path(ge.__file__).read_text(encoding="utf-8")
    assert f"at least {sp.REVENUE_MONTHS_REQUIRED} months of revenue lines" in source
    assert sp.PNL_MONTHS_REQUIRED == ge.RECONCILIATION_MAX_MONTHS


# --- the integrity payload --------------------------------------------------------------------------------------------------

def checks_by_name(step_slice):
    return {c["check"]: c for c in step_slice["integrity"]}


def test_the_reconciliation_is_the_stored_one_window_total_and_months_over_the_tolerance_only():
    rec = reconciliation()
    check = checks_by_name(sp.build_integrity(full_results()))["Revenue file against P&L"]
    assert check["status"] == "computed" and check["window_over_tolerance"] is True
    assert check["revenue_file_total"] == fmt.fmt_currency(rec["file_total"], "EUR")
    assert check["pnl_total"] == fmt.fmt_currency(rec["pnl_total"], "EUR")
    assert check["gap_pct"] == fmt.fmt_pct(rec["gap_pct"]) and check["tolerance"] == fmt.fmt_pct(0.02)
    assert check["months_over_tolerance"] == [{"month": MONTHS[0], "gap_pct": fmt.fmt_pct(0.10)}], "the 1% months are not listed"
    assert check["source_key"] == "S1"


def test_a_window_inside_the_tolerance_lists_no_month_and_is_not_over():
    check = checks_by_name(sp.build_integrity(full_results(over=False)))["Revenue file against P&L"]
    assert check["window_over_tolerance"] is False and check["months_over_tolerance"] == []


def test_no_pnl_reads_not_computed_with_the_closed_reason():
    results = full_results()
    results["revenue_reconciliation"] = None
    check = checks_by_name(sp.build_integrity(results))["Revenue file against P&L"]
    assert check == {"check": "Revenue file against P&L", "status": "not computed", "reason": sp.REASONS["no_pnl"]}


def test_missing_customer_ids_are_the_stored_count():
    check = checks_by_name(sp.build_integrity(full_results()))["Revenue lines without a customer ID"]
    assert check["status"] == "computed" and check["count"] == "3"
    results = full_results()
    results["anomalies"] = None
    assert checks_by_name(sp.build_integrity(results))["Revenue lines without a customer ID"]["status"] == "not computed"


@pytest.mark.parametrize("name", ["Cohorts starting mid-period", "Quarter-end clustering of deals",
                                  "Figures that differ from an approved deck claim", "Benford test"])
def test_the_checks_the_engine_does_not_store_read_not_computed_and_are_never_estimated(name):
    check = checks_by_name(sp.build_integrity(full_results()))[name]
    assert check["status"] == "not computed" and check["reason"] in sp.REASONS.values()
    assert set(check) == {"check", "status", "reason"}, "no figure"


def _with_series(totals, status="Complete"):
    months = [f"{2023 + i // 12}-{i % 12 + 1:02d}" for i in range(len(totals))]
    results = full_results()
    results["revenue_series"] = {"months": months, "segments": [], "data": [{"month": m, "total": v} for m, v in zip(months, totals)],
                                 "source": cite(0)}
    results["source_period"] = {"month": months[-1], "status": status, "complete_by": None, "evidence_to": months[-1]}
    return results


def test_smoothness_is_the_integrity_modules_reading_not_not_computed():
    """Decision of 15 Oct 2026: the data-integrity narrative is told the smoothness result (docs/specs/smoothness.md), with the
    provisional label, as display strings; the number comes from integrity.smoothness, the function the Dashboard block reads."""
    from app import integrity
    results = _with_series([10000 * 1.01 ** i for i in range(24)])
    check = checks_by_name(sp.build_integrity(results))["Month-on-month revenue smoothness"]
    read = integrity.smoothness(results)
    assert check == {"check": "Month-on-month revenue smoothness", "status": "computed", "source_key": "S1",
                     "first_month": read["first"], "last_month": read["last"], "deviation_points": "0.0 points",
                     "limit_points": "0.5 points", "result": "Amber", "threshold_note": "provisional threshold, 3 synthetic series"}
    noisy = checks_by_name(sp.build_integrity(_with_series([100, 108, 103, 121, 118, 131, 127, 149, 141, 160, 158, 181, 170, 196])))
    assert noisy["Month-on-month revenue smoothness"]["result"] == "Green"


def test_smoothness_stays_not_computed_with_a_closed_reason_when_the_window_is_short_or_the_last_month_is_partial():
    short = checks_by_name(sp.build_integrity(_with_series([10000 * 1.01 ** i for i in range(12)])))["Month-on-month revenue smoothness"]
    assert short == {"check": "Month-on-month revenue smoothness", "status": "not computed",
                     "reason": "the revenue file has fewer than 13 consecutive months of revenue"}
    thirteen_partial = checks_by_name(sp.build_integrity(_with_series([10000 * 1.01 ** i for i in range(13)], "Possibly partial")))
    assert thirteen_partial["Month-on-month revenue smoothness"]["status"] == "not computed", "the partial month is left out"


def test_bank_data_is_not_ingested():
    assert checks_by_name(sp.build_integrity(full_results()))["Bank data"] == {"check": "Bank data", "status": "Not ingested"}


# --- what leaves the server -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("step", STEPS)
def test_payload_allowlist_holds_no_file_sheet_customer_row_or_raw_block(step):
    out = payload_of(step)
    blob = json.dumps(out, ensure_ascii=False)
    for secret in (*FILE_NAMES, *SHEETS, CUSTOMER, "Zeta"):
        assert secret not in blob, f"{secret!r} reached the payload"
    keys = set(_keys(out))
    assert keys <= gateway.OUTBOUND_FIELDS | {"metrics"}, sorted(keys - gateway.OUTBOUND_FIELDS)
    for dropped in ("file", "sheet", "rows", "row_numbers", "columns", "by_month", "revenue_reconciliation", "anomalies",
                    "revenue_gap_then_resume", "unlocked_by", "values"):
        assert dropped not in keys, dropped
    assert set(out["metrics"]) == {"source_list", "evidence_to", "last_month_status", "inventory" if step == "data_inventory" else "integrity"}


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for i in node:
            yield from _keys(i)


@pytest.mark.parametrize("step", STEPS)
def test_the_provider_receives_the_payload_and_the_source_keys_it_may_cite(step):
    result, adapter = run(db_for(full_results()), step, GOOD[step]())
    sent = json.loads(adapter.payloads[0])
    assert result.narrative_status == "ok", result.reason
    assert {"S1", "S2", "S3"} & set(sent["valid_source_keys"]) == {"S1", "S2", "S3"}
    assert sent["metrics"]["source_list"][0] == {"source_key": "S1", "description": "revenue by customer file"}
    for secret in (*FILE_NAMES, *SHEETS, CUSTOMER):
        assert secret not in adapter.payloads[0]


# --- the guards (same as growth_engine, plus the step guards) -----------------------------------------------------------------

@pytest.mark.parametrize("step", STEPS)
def test_a_number_the_engine_did_not_produce_in_the_headline_discards_the_narrative(step):
    reply = GOOD[step](headline="Material concerns: the files differ by 77.7% over the window.")
    result, adapter = run(db_for(full_results()), step, reply)
    assert adapter.calls == 1 and result.narrative_status == "unavailable" and "77.7" in result.unmatched_numbers


@pytest.mark.parametrize("step", STEPS)
def test_a_number_the_engine_did_not_produce_in_prose_flags_the_narrative(step):
    reply = GOOD[step](what_this_means="The gap is 4,242 EUR a month.")
    result, _ = run(db_for(full_results()), step, reply)
    assert result.narrative_status == "flagged" and "4242" in result.unmatched_numbers


@pytest.mark.parametrize("step", STEPS)
def test_a_number_in_decision_informed_is_checked_in_prose_tier(step):
    reply = GOOD[step]()
    reply["table_rows"][0]["decision_informed"] = "Whether 8,888 EUR can be trusted"
    result, _ = run(db_for(full_results()), step, reply)
    assert result.narrative_status == "flagged" and "8888" in result.unmatched_numbers


@pytest.mark.parametrize("step", STEPS)
def test_a_row_citing_an_unknown_source_key_discards_the_narrative(step):
    reply = GOOD[step]()
    reply["table_rows"][0]["source_key"] = "S9"
    result, _ = run(db_for(full_results()), step, reply)
    assert result.narrative_status == "unavailable" and "S9" in result.reason


@pytest.mark.parametrize("step,limit", [("data_inventory", 250), ("data_integrity", 300)])
def test_the_word_limit_is_250_for_the_inventory_and_300_for_the_integrity(step, limit):
    base = GOOD[step](what_this_means="")
    used = sum(len(x.split()) for x in [base["headline"], *base["worth_flagging"], *base["next_actions"]])
    ok, _ = run(db_for(full_results()), step, GOOD[step](what_this_means=words(limit - used)))
    assert ok.narrative_status == "ok", ok.reason
    over, adapter = run(db_for(full_results()), step, GOOD[step](what_this_means=words(limit - used + 1)))
    assert adapter.calls == 1 and over.narrative_status == "unavailable" and str(limit) in over.reason


@pytest.mark.parametrize("step", STEPS)
def test_an_evidence_row_without_a_decision_informed_is_refused_by_the_schema_and_the_guard(step):
    schema = schemas.narrative_output_schema(decision=True, verdicts=gateway.STEP_CONFIG[step]["verdicts"])
    assert "decision_informed" in schema["$defs"]["TableRow"]["required"]
    reply = GOOD[step]()
    reply["table_rows"][0]["decision_informed"] = "  "
    result, _ = run(db_for(full_results()), step, reply)
    assert result.narrative_status == "unavailable" and "decision informed" in result.reason


@pytest.mark.parametrize("step,text", [("data_inventory", "Tier 2 evidence only"), ("data_integrity", "Only T1 rows reconcile")])
def test_a_tier_code_discards_the_narrative(step, text):
    result, _ = run(db_for(full_results()), step, GOOD[step](what_this_means=text))
    assert result.narrative_status == "unavailable" and "tier code" in result.reason


def test_a_not_ingested_category_is_never_on_the_request_list():
    reply = inventory_reply(next_actions=["Ask management for the headcount history."])
    result, _ = run(db_for(full_results()), "data_inventory", reply)
    assert result.narrative_status == "unavailable" and "Headcount" in result.reason
    fine, _ = run(db_for(full_results()), "data_inventory", inventory_reply(worth_flagging=["Headcount is not ingested."]))
    assert fine.narrative_status == "ok", "naming it outside the request list is allowed"


def test_the_integrity_verdict_is_one_of_three_labels_and_agrees_with_the_reconciliation():
    db = db_for(full_results(over=True))
    bad_label, _ = run(db, "data_integrity", integrity_reply(verdict="Fine"))
    assert bad_label.narrative_status == "unavailable" and "verdict" in bad_label.reason
    soft, _ = run(db_for(full_results(over=True)), "data_integrity", integrity_reply(verdict="Needs clarification"))
    assert soft.narrative_status == "unavailable" and "Material concerns" in soft.reason, "a window over the tolerance is Material concerns"
    clean = full_results(over=False)
    reliable, _ = run(db_for(clean), "data_integrity", integrity_reply(verdict="Reliable", headline="Reliable: the files agree.",
                                                                          table_rows=[{**integrity_reply()["table_rows"][0], "value": "1%"}]))
    assert reliable.narrative_status == "ok", reliable.reason
    clean["revenue_reconciliation"] = None
    unrun, _ = run(db_for(clean), "data_integrity", integrity_reply(verdict="Reliable", headline="Reliable: nothing found."))
    assert unrun.narrative_status == "unavailable" and "Reliable" in unrun.reason, "Reliable needs a computed reconciliation"


@pytest.mark.parametrize("step", STEPS)
def test_the_second_request_is_served_from_the_cache_with_no_provider_call(step):
    db = db_for(full_results())
    first, adapter = run(db, step, GOOD[step]())
    assert first.narrative_status == "ok" and not first.cache_hit and adapter.calls == 1
    second, again = run(db, step, GOOD[step]())
    assert second.cache_hit and again.calls == 0 and second.narrative == first.narrative
    read = asyncio.run(gateway.read_cached_narrative(db, RUN_ID, step))
    assert read.narrative_status == "ok" and read.narrative.headline == first.narrative.headline


@pytest.mark.parametrize("step", STEPS)
def test_the_two_steps_cache_separately(step):
    db = db_for(full_results())
    run(db, "data_inventory", inventory_reply())
    assert asyncio.run(gateway.read_cached_narrative(db, RUN_ID, "data_integrity")).narrative_status == "not_generated"


@pytest.mark.parametrize("step", STEPS)
def test_a_changed_result_makes_the_stored_narrative_superseded(step):
    db = db_for(full_results())
    run(db, step, GOOD[step]())
    changed = full_results()
    changed["anomalies"]["revenue_missing_customer_id"]["count"] = 9
    db["audits"].docs[0]["results"] = changed
    read = asyncio.run(gateway.read_cached_narrative(db, RUN_ID, step))
    assert read.narrative_status == "not_generated" and read.superseded and read.superseded_reason == "data_changed"


@pytest.mark.parametrize("step", STEPS)
def test_the_spend_cap_refuses_before_the_provider_and_the_metrics_still_come_back(step, monkeypatch):
    async def refuse(db):
        raise guards.GuardRefusal("daily_spend_cap_exceeded", "daily spend cap reached")
    monkeypatch.setattr(guards, "check_spend_cap", refuse)
    result, adapter = run(db_for(full_results()), step, GOOD[step]())
    assert adapter.calls == 0 and result.narrative_status == "unavailable" and result.metrics, "rule 20: degrade, not die"


@pytest.mark.parametrize("step", STEPS)
def test_a_provider_failure_degrades_to_unavailable_with_the_step_slice(step):
    adapter = t.FakeAdapter(raise_with=gateway.GatewayError("provider_error", "boom", 400, "invalid_request_error"))
    result = asyncio.run(gateway.generate_narrative(db_for(full_results()), RUN_ID, step, adapter=adapter, sleep=t._noop_sleep))
    assert result.narrative_status == "unavailable"
    assert "inventory" in result.metrics or "integrity" in result.metrics


@pytest.mark.parametrize("step", STEPS)
def test_a_payload_that_breaks_the_contract_reaches_no_provider(step):
    bad = cf.broken(full_results(), "contract_version", 1)
    result, adapter = run(db_for(bad), step, GOOD[step]())
    assert adapter.calls == 0 and result.reason == gateway.NARRATIVE_NOT_GENERATED


@pytest.mark.parametrize("step", STEPS)
def test_the_calls_are_logged_with_the_step_and_the_prompt_version_and_no_payload(step):
    db = db_for(full_results())
    run(db, step, GOOD[step]())
    call = db["llm_calls"].docs[0]
    assert call["step"] == step and call["prompt_version"] == "v1" and call["status"] == "ok"
    assert FILE_NAMES[0] not in json.dumps(call, default=str)


def test_the_growth_engine_schema_is_unchanged_by_the_two_steps():
    schema = schemas.narrative_output_schema()
    assert "verdict" not in schema["properties"] and "decision_informed" not in schema["$defs"]["TableRow"]["properties"]
    inv = schemas.narrative_output_schema(decision=True)
    assert "verdict" not in inv["properties"] and "decision_informed" in inv["$defs"]["TableRow"]["required"]
    integ = schemas.narrative_output_schema(decision=True, verdicts=sp.DATA_INTEGRITY_VERDICTS)
    assert integ["properties"]["verdict"]["enum"] == list(sp.DATA_INTEGRITY_VERDICTS) and "verdict" in integ["required"]
    for s in (schema, inv, integ):
        assert re.search(r'"additionalProperties": false', json.dumps(s)), "sealed"
