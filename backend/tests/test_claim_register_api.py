"""The claim register endpoints (docs/specs/claim-matching.md sections 6 and 7): GET /claims with the register rows
in rank order, the analyst's inputs on the register's rows, and the monitoring baseline CSV."""
import copy
import csv
import io
import logging

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from claim_matching_support import engine_results, fixture  # noqa: E402
from test_claim_matching import RUNS, candidates_for  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import decks  # noqa: E402
from app import verdict as verdict_mod  # noqa: E402

AUDIT = "audit-cm"
RUN = RUNS["A"]


@pytest.fixture()
def api(monkeypatch):
    db = t.FakeDB()
    db["audits"].docs.append({"id": AUDIT, "reporting_currency": "EUR", "fiscal_year_end": 12, "as_of_month": None,
                              "results": copy.deepcopy(engine_results())})
    db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "fx": {}})
    for n, c in enumerate(candidates_for(RUN)):
        db[decks.CANDIDATES_COLLECTION].docs.append({**c, "audit_id": AUDIT, "order": n})
    db[decks.CANDIDATES_COLLECTION].docs.append(
        {"audit_id": AUDIT, "id": "rejected", "status": "rejected", "claim_type": "revenue", "value": 1, "file": "testco_board.pptx"})
    db[decks.CANDIDATES_COLLECTION].docs.append(
        {"audit_id": AUDIT, "id": "pending", "status": "pending", "claim_type": "revenue", "value": 1, "file": "testco_board.pptx"})
    monkeypatch.setattr(server, "db", db)
    return TestClient(server.app, raise_server_exceptions=False), db


def _get(client):
    r = client.get(f"/api/audits/{AUDIT}/claims")
    assert r.status_code == 200, r.text
    return r.json()


def _put(client, claim_id, body):
    return client.put(f"/api/audits/{AUDIT}/claims/{claim_id.replace('#', '%23')}", json=body)


def test_the_claims_endpoint_returns_the_register_in_rank_order_beside_todays_claims(api):
    client, _ = api
    body = _get(client)
    assert len(body["claims"]) == len(candidates_for(RUN)) and "claims" in body
    register = body["register"]
    assert [r["rank"] for r in register] == list(range(1, len(register) + 1))
    expected = {e["claim_id"]: e["expect"] for e in RUN["claims"]}
    assert {r["claim_id"] for r in register} == set(expected), "rejected and unreviewed candidates are not claims"
    for row in register:
        assert (row["evidence_label"], row["rank"]) == (expected[row["claim_id"]]["label"], expected[row["claim_id"]]["rank"])


def test_a_register_row_carries_no_deck_text(api):
    client, _ = api
    row = _get(client)["register"][0]
    assert "snippet" not in row and "label_from" not in row and "sources" not in row and "date_from" not in row


def test_an_audit_with_no_results_has_no_register_rows_but_keeps_its_claims(api):
    client, db = api
    db["audits"].docs[0]["results"] = None
    body = _get(client)
    assert body["register"] == [] and len(body["claims"]) == len(candidates_for(RUN))


def test_an_unknown_audit_is_a_404(api):
    client, _ = api
    assert client.get("/api/audits/nope/claims").status_code == 404
    assert client.get("/api/audits/nope/claims.csv").status_code == 404
    assert client.put("/api/audits/nope/claims/x", json={"segment": WHOLE}).status_code == 404


WHOLE = cm.WHOLE


def test_the_analyst_sets_a_segment_and_the_row_follows(api):
    client, db = api
    r = _put(client, "c17", {"segment": "Enterprise"})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["register"] if x["claim_id"] == "c17")
    assert (row["segment"], row["segment_set_by"], row["observed_value"]) == ("Enterprise", "analyst", 112.68)
    assert row["evidence_label"] == "Contradicted", "NRR 130% against the Enterprise segment's 112.68%"
    stored = next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == "c17")
    assert stored["claim_inputs"]["c17"]["segment"] == "Enterprise"
    assert row == next(x for x in _get(client)["register"] if x["claim_id"] == "c17"), "the next read gives the same row"


def test_the_analyst_sets_the_metric_in_the_claims_unit_or_none(api):
    client, _ = api
    r = _put(client, "c14", {"metric": "none"})
    assert r.status_code == 200 and next(x for x in r.json()["register"] if x["claim_id"] == "c14")["metric_set_by"] == "analyst"
    assert _put(client, "c14", {"metric": "ARR"}).status_code == 200          # TAM €2bn is an amount: ARR fits its unit
    assert _put(client, "c14", {"metric": "Win rate"}).status_code == 400      # a % metric for an amount
    assert _put(client, "c14", {"metric": "Net happiness"}).status_code == 400


def test_a_segment_must_be_in_the_data_or_one_of_the_two_markers(api):
    client, _ = api
    for ok in ("Whole company", "Not in the data", "Mid-Market"):
        assert _put(client, "c01", {"segment": ok}).status_code == 200, ok
    assert _put(client, "c01", {"segment": "Public sector"}).status_code == 400


def test_the_gate_is_the_analysts_threshold_budget_decision_and_date(api):
    client, _ = api
    row = next(x for x in _get(client)["register"] if x["claim_id"] == "c01")
    assert (row["gate_sentence"], row["gate_threshold"], row["gate_saved"]) == (None, None, False), "no proposed gate"
    body = {"gate_threshold": 195000, "gate_budget_decision": "the Series B hiring plan", "gate_date": "2024-06-30"}
    r = _put(client, "c01", body)
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["register"] if x["claim_id"] == "c01")
    assert (row["gate_saved"], row["gate_threshold"], row["gate_date"]) == (True, 195000, "2024-06-30")
    assert row["gate_sentence"].startswith("Before the Series B hiring plan, ARR must be at least €195,000 by 2024-06-30.")
    half = _put(client, "c01", {"gate_budget_decision": None})
    row = next(x for x in half.json()["register"] if x["claim_id"] == "c01")
    assert (row["gate_saved"], row["gate_sentence"]) == (False, None)
    cleared = _put(client, "c01", {"gate_threshold": None, "gate_date": None})
    row = next(x for x in cleared.json()["register"] if x["claim_id"] == "c01")
    assert (row["gate_threshold"], row["gate_date"], row["gate_saved"]) == (None, None, False), "the app proposes no date"


def test_a_gate_is_not_saved_without_its_date(api):
    client, _ = api
    r = _put(client, "c01", {"gate_threshold": 195000, "gate_budget_decision": "the Series B hiring plan"})
    row = next(x for x in r.json()["register"] if x["claim_id"] == "c01")
    assert (row["gate_saved"], row["gate_sentence"], row["gate_date"]) == (False, None, None)


@pytest.mark.parametrize("body", [{"gate_budget_decision": "x" * 201}, {"gate_date": "next quarter"}, {"gate_date": "2024-13-40"},
                                  {"gate_threshold": "lots"}, {}, {"unknown_field": 1}])
def test_a_gate_or_input_that_is_not_valid_is_refused(api, body):
    client, db = api
    before = copy.deepcopy(db[decks.CANDIDATES_COLLECTION].docs)
    assert _put(client, "c01", body).status_code in (400, 422)
    assert db[decks.CANDIDATES_COLLECTION].docs == before


def test_a_budget_decision_of_200_characters_is_kept_and_a_blank_one_is_not_a_decision(api):
    client, _ = api
    assert _put(client, "c01", {"gate_budget_decision": "x" * 200, "gate_threshold": 1}).status_code == 200
    r = _put(client, "c01", {"gate_budget_decision": "   "})
    assert next(x for x in r.json()["register"] if x["claim_id"] == "c01")["gate_budget_decision"] is None


def test_inputs_of_a_table_row_value_sit_on_its_row_under_its_own_claim_id(api):
    client, db = api
    assert _put(client, "c19#2", {"segment": "Enterprise"}).status_code == 200
    stored = next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == "c19")
    assert stored["claim_inputs"] == {"c19#2": {"segment": "Enterprise"}}
    rows = {r["claim_id"]: r for r in _get(client)["register"]}
    assert rows["c19#2"]["segment"] == "Enterprise" and rows["c19#1"]["segment"] == "Whole company"


def test_a_claim_that_is_not_in_the_register_has_no_inputs(api):
    client, _ = api
    for claim_id in ("rejected", "pending", "nope", "c19", "c19#9"):
        assert _put(client, claim_id, {"segment": "Whole company"}).status_code == 404, claim_id
    assert _put(client, "c01", {"segment": "Whole company"}).status_code == 200


def test_inputs_need_a_computed_audit(api):
    client, db = api
    db["audits"].docs[0]["results"] = None
    assert _put(client, "c01", {"segment": "Whole company"}).status_code == 409


def test_an_edit_in_the_approval_list_leaves_the_analysts_inputs(api):
    client, db = api
    _put(client, "c01", {"segment": "Enterprise"})
    r = client.put(f"/api/audits/{AUDIT}/decks/candidates/c01", json={"value": 205000})
    assert r.status_code == 200
    stored = next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == "c01")
    assert stored["claim_inputs"]["c01"]["segment"] == "Enterprise" and stored["status"] == "edited"


# --- section 7: the monitoring baseline ----------------------------------------------------------------------------------

def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, dict):
        return f"{value['file']} · {value['sheet']} · {value['rows']}"
    return str(value)


def _baseline(client):
    r = client.get(f"/api/audits/{AUDIT}/claims.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and ".csv" in r.headers["content-disposition"]
    return r.text


def test_the_csv_is_the_register_in_rank_order_then_the_data_gaps_with_the_header_of_the_verdict_spec(api):
    client, _ = api
    register = _get(client)["register"]
    rows = list(csv.reader(io.StringIO(_baseline(client))))
    assert rows[0] == ["row_type", *cm.FIELDS, "in_top5", "gap_item", "gap_why", "gap_requested", "gap_target_date",
                       "first_quarterly_review"]
    claims = [r for r in rows[1:] if r[0] == "claim"]
    gaps = [r for r in rows[1:] if r[0] == "data_gap"]
    assert len(claims) == len(register) and rows[1:] == claims + gaps and gaps, "claims first, then the gaps"
    for line, row in zip(claims, register):
        assert line[1:1 + len(cm.FIELDS)] == [verdict_mod._cell(row[f]) for f in cm.FIELDS], row["claim_id"]
    assert [int(line[1 + cm.FIELDS.index("rank")]) for line in claims] == list(range(1, len(register) + 1))
    top = {line[1] for line in claims if line[1 + len(cm.FIELDS)] == "true"}
    assert top == {r["claim_id"] for r in register[:5]}, "before the analyst confirms, the proposal is the top 5"
    assert all(line[1 + len(cm.FIELDS) + 1] and line[-5] for line in gaps), "a gap row names its item and why"


def test_the_csv_holds_numbers_unformatted_and_dates_in_iso(api):
    client, _ = api
    rows = list(csv.DictReader(io.StringIO(_baseline(client))))
    one = next(r for r in rows if r["claim_id"] == "c01")
    assert one["claimed_value"] == "200000" and one["observed_value"] == "202125.48" and one["gap"] == "-2125.48"
    assert one["period_start"] == "2024-02-01" and one["gate_date"] == "" and one["gate_saved"] == "false"
    assert one["observed_source"].startswith("revenue.csv · CSV · rows 2")
    assert one["as_of_defaulted"] == "true" and one["value_at_stake_arr"] == "" and one["overlaps_with"]
    assert "€" not in one["gap"] and "," not in one["observed_value"]
    assert one["evidence_source_key"] == "mrr_series.data.total" and one["evidence_analysis"] == "Monthly MRR by Segment"


def test_the_csv_round_trips_every_field_of_every_row_and_writes_the_same_bytes(api):
    client, _ = api
    _put(client, "c01", {"gate_threshold": 195000, "gate_budget_decision": "the Series B, \"hiring\"\nplan", "gate_date": "2024-06-30"})
    _put(client, "c01", {"key_gate": True})
    client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"first_quarterly_review": "2024-09-30"})
    text = _baseline(client)
    register = _get(client)["register"]
    claims, gaps, review = verdict_mod.parse_baseline(text)
    assert review == "2024-09-30" and len(claims) == len(register) and gaps
    for parsed, row in zip(claims, register):
        assert {k: v for k, v in parsed.items() if k != "in_top5"} == {f: row[f] for f in cm.FIELDS}, row["claim_id"]
        assert isinstance(parsed["rank"], int) and isinstance(parsed["gate_saved"], bool)
    assert verdict_mod.rewrite_baseline(claims, gaps, review) == text, "the same bytes"


def test_the_register_log_line_holds_counts_per_label_never_a_value_or_gate_text(api, caplog):
    client, _ = api
    _put(client, "c01", {"gate_threshold": 195000, "gate_budget_decision": "the Series B hiring plan"})
    with caplog.at_level(logging.DEBUG):
        _get(client)
        client.get(f"/api/audits/{AUDIT}/claims.csv")
    text = caplog.text
    assert "claim register" in text and "Verified" in text, "the counts per label are logged"
    for needle in ("202125", "198142", "Series B", "Before ", "must be at", "testco_board", "Enterprise", "AI suggestion"):
        assert needle not in text, f"{needle!r} reached a log line"


def test_the_screens_metric_table_is_pinned_to_the_matching_module():
    """frontend/src/lib/claim_metrics.json lists each metric and its unit for the metric select; it is the module's table 2a."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "claim_metrics.json"
    shown = json.loads(path.read_text(encoding="utf-8"))["metrics"]
    assert shown == {name: spec["unit"] for name, spec in cm.METRICS.items()}
    assert list(shown) == list(cm.METRICS), "same order: the select lists them in it"
