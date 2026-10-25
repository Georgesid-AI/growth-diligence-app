"""The gate written from the claim (docs/design/simplified-flow.md section 3): every non-Verified claim has one, proposed from stored data alone,
the analyst's edit wins and reads "set by the analyst", the key gates are those of the non-Verified top-5 rows and never padded. The rule per row
is pinned in test_claim_matching.py; this file runs it through the API, the CSV and the memo. Fake provider, no live run."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from test_run_audit import AUDIT, candidates, memo, ready_for_review  # noqa: E402

from app import claim_matching as cm  # noqa: E402

REVIEW = "2025-06-30"
DECISION = "the Series B hiring plan"


def open_register(client):
    ready_for_review(client)
    for c in candidates(client):                                  # the claims a check asks about: the analyst's one click each
        if c["status"] == "pending":
            client.put(f"/api/audits/{AUDIT}/decks/candidates/{c['id']}", json={"status": "approved"})
    client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"first_quarterly_review": REVIEW})
    return client.get(f"/api/audits/{AUDIT}/claims").json()


def test_every_non_verified_claim_has_a_proposed_gate_dated_no_later_than_the_first_review_and_no_gate_is_needed(run_api):
    data = open_register(run_api)
    assert "gate_prefill" not in data, "the prefill is gone: the gate is in the row"
    needing = [r for r in data["register"] if r["evidence_label"] in cm.NOT_VERIFIED and not cm.is_untested(r) and r["gate_sentence"]]
    assert needing and all(r["gate_status"] == "proposed" and r["gate_date"] <= REVIEW and r["gate_needed"] is False for r in needing)
    assert any(r["gate_date"] == REVIEW for r in needing), "a period past the review is dated at the review"
    assert all(r["gate_sentence"] is None for r in data["register"] if r["evidence_label"] == "Verified")
    assert all(r["gate_needed"] is False for r in data["register"])


def test_a_gate_the_analyst_edits_reads_set_by_the_analyst_and_keeps_its_value_with_the_budget_decision_optional(run_api):
    data = open_register(run_api)
    row = next(r for r in data["register"] if r["gate_status"] == "proposed" and r["metric"] in cm.METRICS)
    cid = row["claim_id"].replace("#", "%23")
    edit = run_api.put(f"/api/audits/{AUDIT}/claims/{cid}", json={"gate_threshold": 123.0, "gate_date": "2024-06-30"})
    assert edit.status_code == 200, edit.text
    saved = next(x for x in edit.json()["register"] if x["claim_id"] == row["claim_id"])
    assert (saved["gate_saved"], saved["gate_status"], saved["gate_threshold"], saved["gate_date"]) == (True, "set by the analyst", 123.0, "2024-06-30")
    assert "Before" not in saved["gate_sentence"], "no budget decision, no prefix"
    decided = run_api.put(f"/api/audits/{AUDIT}/claims/{cid}", json={"gate_budget_decision": DECISION})
    again = next(x for x in decided.json()["register"] if x["claim_id"] == row["claim_id"])
    assert again["gate_sentence"].startswith(f"Before {DECISION}, ")
    cleared = run_api.put(f"/api/audits/{AUDIT}/claims/{cid}", json={"gate_threshold": None, "gate_date": None, "gate_budget_decision": None})
    back = next(x for x in cleared.json()["register"] if x["claim_id"] == row["claim_id"])
    assert (back["gate_saved"], back["gate_status"]) == (False, "proposed"), "clearing the edit gives the proposal back"


def test_the_save_all_gates_endpoint_and_the_key_gate_mark_are_gone(run_api):
    open_register(run_api)
    assert run_api.put(f"/api/audits/{AUDIT}/claim-gates", json={"gates": [{"claim_id": "x"}]}).status_code in (404, 405)
    row = run_api.get(f"/api/audits/{AUDIT}/claims").json()["register"][0]
    cid = row["claim_id"].replace("#", "%23")
    assert run_api.put(f"/api/audits/{AUDIT}/claims/{cid}", json={"key_gate": True}).status_code == 422


def test_the_key_gates_of_the_verdict_are_the_gates_of_the_non_verified_top_5_rows(run_api):
    open_register(run_api)
    body = run_api.get(f"/api/audits/{AUDIT}/verdict").json()
    five = set(body["verdict"]["top5"]["in_force"])
    register = {r["claim_id"]: r for r in run_api.get(f"/api/audits/{AUDIT}/claims").json()["register"]}
    expected = sorted(c for c in five if register[c]["gate_sentence"])
    assert sorted(g["claim_id"] for g in body["key_gates"]["sentences"]) == expected
    assert all(g["text"].endswith(("(proposed)", "(set by the analyst)")) for g in body["key_gates"]["sentences"])
    assert {c for c, r in register.items() if r["key_gate"]} == set(expected), "the register marks the same rows"
    outside = [c for c, r in register.items() if c not in five and r["gate_sentence"]]
    assert outside and not set(outside) & set(expected), "a gate outside the five is not promoted"


def test_the_csv_and_the_memo_show_the_gate_with_its_status(run_api):
    open_register(run_api)
    csv_text = run_api.get(f"/api/audits/{AUDIT}/claims.csv").text
    assert csv_text.splitlines()[0].split(",")[1:len(cm.FIELDS) + 1] == list(cm.FIELDS) and "gate_status" in csv_text.splitlines()[0]
    assert "proposed" in csv_text
    text = memo(run_api).text
    section = text.split("## Key gates and deal terms")[1].split("## Worth flagging")[0]
    assert "(proposed)" in section and "prefill" not in text.lower()


# --- the first quarterly review, an audit set-up field -------------------------------------------------------------------------

def test_a_new_audit_has_a_first_quarterly_review_90_days_after_its_creation(run_api):
    r = run_api.post("/api/audits", json={"company_name": "NewCo"})
    assert r.status_code == 200
    created = r.json()["created_at"][:10]
    from datetime import date, timedelta
    assert r.json()["ic_inputs"]["first_quarterly_review"] == (date.fromisoformat(created) + timedelta(days=90)).isoformat()


def test_the_review_date_is_editable_and_clearing_it_returns_the_default(run_api):
    ready_for_review(run_api)
    assert run_api.put(f"/api/audits/{AUDIT}/ic-inputs", json={"first_quarterly_review": "2027-03-31"}).status_code == 200
    assert run_api.get(f"/api/audits/{AUDIT}").json()["ic_inputs"]["first_quarterly_review"] == "2027-03-31"
    assert run_api.put(f"/api/audits/{AUDIT}/ic-inputs", json={"first_quarterly_review": None}).status_code == 200
    assert run_api.get(f"/api/audits/{AUDIT}").json()["ic_inputs"]["first_quarterly_review"] == "2027-01-09"


def test_a_claim_without_a_period_is_dated_by_the_audits_review_date_and_no_gate_goes_past_it(run_api):
    data = open_register(run_api)
    review = run_api.get(f"/api/audits/{AUDIT}").json()["ic_inputs"]["first_quarterly_review"]
    gated = [r for r in data["register"] if r["gate_status"]]
    assert gated and all(r["gate_date"] and r["gate_date"] <= review for r in gated), "every gate has a date, none after the review"
    assert any(r["gate_date"] == review for r in gated)
