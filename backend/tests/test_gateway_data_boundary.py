"""The gateway's data boundary: what may leave the server, and what never does.

The outbound payload is built from an allowlist. File and sheet names, column
headers and raw cell values stay in Mongo for the dashboard; segment names go
out as stable labels and come back as real names. Every test runs against the
in-memory Mongo stub and the fake adapter - no test can reach a real provider.
"""
import asyncio
import copy
import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app.llm import gateway, redaction  # noqa: E402
import test_llm_gateway as t  # noqa: E402

RUN_ID = t.RUN_ID
FILE = "Revenue_Lines.xlsx"
SHEET = "Billing"
PERSON = "Jane Doe (CEO)"                     # a raw cell value from the founder-involved column
HEADERS = ("Deal Opened On", "Signed Date")   # column headers in the upload

SOURCE = {"file": FILE, "sheet": SHEET, "rows": "rows 2–40 (39 rows)", "row_numbers": [2, 3, 4],
          "rule": "ARR = current-month recurring MRR × 12"}

RESULTS = {
    "as_of_month": "2026-12",
    "reporting_currency": "EUR",
    "arr": {"value": 3129600, "mrr": 260800, "month": "2026-12", "source": SOURCE},
    "nrr": {"overall_pct": 104.0, "nrr_base_customers": 110, "month": "2026-12", "trailing_window_months": 12,
            "by_segment": {"Enterprise": {"nrr_pct": 112.0, "nrr_base_customers": 40},
                           "Mid-Market": {"nrr_pct": 96.0, "nrr_base_customers": 70}},
            "source": {**SOURCE, "rule": "NRR = base-cohort MRR now ÷ MRR 12 months ago"}},
    "win_rate": {"won": 30, "lost": 70, "win_rate_pct": 30.0,
                 "founder_involved_excluded": {"count": 1, "rows": [7], "values": [PERSON]},
                 "source": {"file": "CRM_Deals.csv", "sheet": "Deals", "rule": "Win rate = won ÷ (won + lost)"}},
    "sales_cycle": {"median_days": 45, "n": 30, "status": "Computed - management to explain",
                    "source": {"file": FILE, "sheet": SHEET, "rule": "Median days from created to close",
                               "dataset": "revenue",
                               "columns": {"created_date": HEADERS[0], "close_date": HEADERS[1]}}},
    "segment_paths": {"available": True, "stage_one": {"segments": {
        "Enterprise": {"start_arr": 2000000, "customers": 40},
        "Mid-Market": {"start_arr": 1129600, "customers": 70}}},
        "reverse_solve": {"12": {"window_months": 12, "best_segment": "Enterprise",
                                 "reason": "no landed ACV for Mid-Market"}}},
    "missing_data": [{"metric": "CRM rows with unrecognized founder-involved value", "status": "Missing",
                      "reason": f"1 row(s) have a founder-involved value that isn't yes/no-like ({PERSON})",
                      "unlocked_by": "Use a yes/no style value", "file": "CRM_Deals.csv"}],
    "questions_for_management": [{
        "metric": "Sales cycle", "status": "Computed - management to explain", "result_key": "sales_cycle",
        "dataset": "revenue", "file": FILE,
        "columns": {"created_date": HEADERS[0], "close_date": HEADERS[1]},
        "question": (f"Sales cycle was computed from the revenue upload (created_date = '{HEADERS[0]}', "
                     f"close_date = '{HEADERS[1]}') because it was not available from the crm upload."),
    }],
}

NARRATIVE = {
    "headline": "Segment A retains 112% of its revenue over twelve months.",
    "what_this_means": "Segment A expands while Segment B contracts.",
    "table_rows": [{"label": "Segment A NRR", "value": "112%",
                    "source_key": "metrics.nrr.by_segment.Segment A.nrr_pct"}],
    "worth_flagging": ["Segment B is at 96%."],
    "next_actions": ["Ask why Segment B churns."],
    "source_keys": ["metrics.nrr.by_segment"],
}


def _db():
    db = t.FakeDB()
    doc = copy.deepcopy(t.RESULTS_DOC)
    doc["results"] = copy.deepcopy(RESULTS)
    db["audits"].docs.append(doc)
    return db


def _generate(db, reply=NARRATIVE):
    adapter = t.FakeAdapter(replies=[json.dumps(reply)])
    result = asyncio.run(gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=adapter, sleep=t._noop_sleep))
    assert adapter.calls == 1
    return result, json.loads(adapter.payloads[0])


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for i in node:
            yield from _keys(i)


def test_outbound_payload_has_no_file_sheet_header_or_raw_cell_value():
    db = _db()
    _, sent = _generate(db)
    blob = json.dumps(sent, ensure_ascii=False)
    for secret in (FILE, "CRM_Deals.csv", SHEET, "Deals", *HEADERS, PERSON, "Jane Doe"):
        assert secret not in blob, f"{secret!r} reached the provider"
    keys = set(_keys(sent))
    for dropped in ("file", "sheet", "columns", "rows", "row_numbers", "unlocked_by", "run_id", "computed_at"):
        assert dropped not in keys, dropped
    assert "values" not in sent["metrics"]["win_rate"]["founder_involved_excluded"]
    # What the model needs is still there.
    assert sent["metrics"]["arr"]["source"] == {"rule": "ARR = current-month recurring MRR × 12"}
    assert sent["metrics"]["win_rate"]["founder_involved_excluded"]["count"] == "1"
    question = sent["metrics"]["questions_for_management"][0]["question"]
    assert "close_date, created_date" in question and "revenue upload" in question
    assert sent["metrics"]["missing_data"][0]["reason"] == (
        "1 row(s) have a founder_involved value that isn't yes/no-like — excluded from the founder split, not guessed")


def test_full_versions_stay_in_mongo_for_the_dashboard():
    db = _db()
    _generate(db)
    stored = db["audits"].docs[0]["results"]
    assert stored == RESULTS
    assert HEADERS[0] in stored["questions_for_management"][0]["question"]


def test_segment_names_are_labelled_outbound_and_restored_in_the_reply():
    db = _db()
    result, sent = _generate(db)
    blob = json.dumps(sent)
    assert "Enterprise" not in blob and "Mid-Market" not in blob
    assert set(sent["metrics"]["nrr"]["by_segment"]) == {"Segment A", "Segment B"}
    assert set(sent["metrics"]["segment_paths"]["stage_one"]["segments"]) == {"Segment A", "Segment B"}
    assert sent["metrics"]["segment_paths"]["reverse_solve"]["12"]["best_segment"] == "Segment A"
    assert sent["metrics"]["segment_paths"]["reverse_solve"]["12"]["reason"] == "no landed ACV for Segment B"

    assert result.narrative_status == "ok", result.reason
    n = result.narrative
    assert n.headline == "Enterprise retains 112% of its revenue over twelve months."
    assert n.what_this_means == "Enterprise expands while Mid-Market contracts."
    assert n.table_rows[0].label == "Enterprise NRR"
    assert n.table_rows[0].source_key == "metrics.nrr.by_segment.Enterprise.nrr_pct"
    assert n.worth_flagging == ["Mid-Market is at 96%."]


def test_segment_labels_are_stable_for_a_run():
    db = _db()
    computed = asyncio.run(gateway.load_computed_results(db, RUN_ID, "growth_engine"))
    first = asyncio.run(redaction.get_or_create_map(db, RUN_ID, computed))
    second = asyncio.run(redaction.get_or_create_map(db, RUN_ID, computed))
    assert first == second
    assert first["Enterprise"] == "Segment A" and first["Mid-Market"] == "Segment B"


def test_identifier_12_never_changes_a_date_or_a_number():
    mapping = {"12": "Customer_01", "Acme": "Customer_02"}
    payload = {"month": "2026-12", "target_date": "2027-12-31", "trailing_window_months": "12",
               "value": "1,212 EUR", "nrr_pct": "112%", "ratio": "1.12x", "window": "12-month NRR",
               "reason": "Acme churned in 2026-12", "series": ["12", "2026-12"], "n": 12}
    out = redaction.redact(payload, mapping)
    assert out == {**payload, "reason": "Customer_02 churned in 2026-12"}
    assert redaction.substitute("2026-12", mapping) == "2026-12"
    assert redaction.find_leaks(out, mapping) == []


def test_field_name_keys_are_never_rewritten():
    mapping = {"arr": "Customer_01", "value": "Customer_02"}
    payload = {"arr": {"value": "1 EUR"}, "by_segment": {"arr": {"value": "2 EUR"}}}
    out = redaction.redact(payload, mapping)
    assert set(out) == {"arr", "by_segment"} and set(out["arr"]) == {"value"}
    assert set(out["by_segment"]) == {"Customer_01"}, "only segment-container keys are data"


def test_word_boundary_matching_does_not_touch_longer_words():
    mapping = {"Acme": "Customer_01"}
    assert redaction.substitute("Acme, Acmes and AcmeCorp", mapping) == "Customer_01, Acmes and AcmeCorp"
    assert redaction.restore("Customer_01 and Customer_010", {"Acme": "Customer_01"}) == "Acme and Customer_010"


def test_numeric_guard_allowed_set_is_unchanged_by_redaction():
    db = _db()
    computed = asyncio.run(gateway.load_computed_results(db, RUN_ID, "growth_engine"))
    mapping = {**asyncio.run(redaction.get_or_create_map(db, RUN_ID, computed)), "12": "Customer_01"}
    windows = gateway.STEP_CONFIG["growth_engine"]["windows"]
    plain = gateway.build_outbound(computed, {})
    redacted = gateway.build_outbound(computed, mapping)
    assert redacted != plain, "segments were relabelled"
    assert gateway.allowed_numerals(redacted, windows) == gateway.allowed_numerals(plain, windows)
    assert gateway.allowed_numerals(redaction.redact(plain, mapping), windows) == gateway.allowed_numerals(plain, windows)


def test_demo_upload_leaks_no_file_sheet_header_or_cell_value():
    """A real engine run over the demo upload, renamed to carry identifying strings."""
    pytest.importorskip("pandas")
    pytest.importorskip("fastapi")
    pytest.importorskip("motor")
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "data_boundary_test")
    import demo_data
    import growth_engine as ge
    import server

    file, sheet, header, cell = "Acme_Revenue.xlsx", "Acme Data", "Acme Segment", "Jane Doe (CEO)"
    spec = demo_data.DEMO_AUDITS[0]
    datasets, meta = demo_data.build(spec)
    uploads = {}
    for dtype, (df, mapping) in datasets.items():
        rows, mapping = server.df_to_records(df), dict(mapping)
        if dtype == "revenue":
            for r in rows:
                r[header] = r.pop(mapping["segment"])
            mapping["segment"] = header
            rows[0][mapping["currency"]] = cell            # a currency cell the engine quotes in a reason
        if dtype == "crm":
            rows[0][mapping["founder_involved"]] = cell    # a founder cell the engine quotes in a reason
        name, tab = (file, sheet) if dtype == "revenue" else (meta[dtype]["file"], meta[dtype]["sheet"])
        uploads[dtype] = {"file": name, "sheet": tab, "columns": list(rows[0]), "rows": rows, "mapping": mapping}

    norm = {d: server.normalize(u["rows"], d, u["mapping"]) for d, u in uploads.items()}
    fx = {k.upper(): v for k, v in meta.get("fx", {}).items()}
    fx[spec["reporting_currency"].upper()] = 1.0
    cfg = {"reporting_currency": spec["reporting_currency"], "target_arr": spec["target_arr"],
           "target_date": spec["target_date"], "fx": fx, "billing_terms": {}, "default_l": 1, "as_of_month": None}
    sources = {d: {"file": u["file"], "sheet": u["sheet"]} for d, u in uploads.items()}
    results = server.sanitize(ge.compute_all(norm["revenue"], norm["crm"], norm["pnl"], cfg, sources,
                                             files=server.candidate_views(uploads)))

    stored = json.dumps(results, ensure_ascii=False).lower()
    # The header is stored only when a management question cites it; that path is covered above.
    for needle in (file, sheet, cell):
        assert needle.lower() in stored, f"fixture did not exercise {needle!r}"

    db = t.FakeDB()
    db["audits"].docs.append({"id": RUN_ID, "results": results, "reporting_currency": spec["reporting_currency"],
                              "target_arr": spec["target_arr"], "target_date": spec["target_date"]})
    adapter = t.FakeAdapter()
    asyncio.run(gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=adapter, sleep=t._noop_sleep))
    assert adapter.calls == 1
    sent = adapter.payloads[0].lower()
    for needle in (file, sheet, header, cell, "jane doe", "acme"):
        assert needle.lower() not in sent, f"{needle!r} reached the provider"
    assert json.dumps(db["audits"].docs[0]["results"], ensure_ascii=False).lower() == stored, "Mongo keeps the full text"
