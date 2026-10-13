"""Gate prefill (docs/specs/verdict-and-memo.md section 3): the starting values of a gate come from stored data alone, show on the
review screen only, are saved in one call, and leave no trace in the register, the CSV or the memo. Fake provider, no live run."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from test_run_audit import AUDIT, RATINGS, THESIS, api, candidates, memo, ready_for_review  # noqa: E402,F401

from app import claim_matching as cm  # noqa: E402
from app import verdict  # noqa: E402

REVIEW = "2025-06-30"
DECISION = "the Series B hiring plan"


def row(cid, label="Contradicted", **kw):
    base = dict.fromkeys(cm.FIELDS)
    base.update(claim_id=cid, evidence_label=label, claim_type="revenue", gate_saved=False, key_gate=False, reason="gap",
                claimed_value=100.0, value_at_stake_arr=1.0)
    base.update(kw)
    return base


# --- prefill per rule ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("label", ["Unverified", "Unsupported", "Contradicted"])
def test_every_gate_needing_label_is_prefilled(label):
    assert "a" in verdict.gate_prefill([row("a", label)], REVIEW)


def test_verified_saved_and_untested_rows_get_no_prefill():
    rows = [row("v", "Verified"), row("s", gate_saved=True), row("u", claim_type="use_of_funds")]
    assert verdict.gate_prefill(rows, REVIEW) == {}


def test_threshold_is_the_claimed_value_in_the_claims_unit_and_the_converted_figure_when_converted():
    out = verdict.gate_prefill([row("a", claimed_value=250.0, unit="%"), row("b", claimed_value=100.0, claimed_converted=108.0, currency="USD"),
                                row("c", claimed_value=None, claim_direction="positive")], REVIEW)
    assert out["a"]["gate_threshold"] == 250.0 and out["b"]["gate_threshold"] == 108.0 and "gate_threshold" not in out["c"]


def test_date_is_the_end_of_the_claims_period_or_the_first_review_when_it_has_none():
    out = verdict.gate_prefill([row("a", period_end="2025-03-31"), row("b")], REVIEW)
    assert out["a"]["gate_date"] == "2025-03-31" and out["b"]["gate_date"] == REVIEW


def test_date_is_never_later_than_the_first_review():
    out = verdict.gate_prefill([row("a", period_end="2026-12-31")], REVIEW)
    assert out["a"]["gate_date"] == REVIEW


def test_date_stays_blank_when_there_is_neither_a_period_nor_a_review():
    assert "gate_date" not in verdict.gate_prefill([row("a")], None)["a"]
    assert verdict.gate_prefill([row("a", period_end="2025-03-31")], None)["a"]["gate_date"] == "2025-03-31"


def test_metric_name_is_prefilled_on_every_row_whose_gate_the_server_saves_only_with_the_analysts_metric():
    """2026-10-13 (George): the screen asks for the metric and its direction wherever the server needs them, and the prefill follows
    the same rule (claim_matching.needs_metric_name): no metric set (a direction only, a turnover question, a qualified Users
    count) or one that does not fit the claim's unit."""
    qualified = cm.QUALIFIED_REASON.format(label="registered institutions")
    rows = [row("q", "Unsupported", reason=qualified, claim_type="users", period="Y/E 24"),
            row("d", "Unverified", reason=cm.DIRECTION_ONLY, claim_type="ebitda", period="Q2 2024"),
            row("f", "Unsupported", reason="metric does not fit the claim's unit", metric="ARR", period="2025"),
            row("m", metric="ARR", reason="outside ±5%: a miss")]
    out = verdict.gate_prefill(rows, REVIEW)
    assert (out["q"]["gate_metric_name"], out["d"]["gate_metric_name"], out["f"]["gate_metric_name"]) == \
        ("Users, Y/E 24", "Ebitda, Q2 2024", "ARR, 2025")
    assert "gate_metric_name" not in out["m"]
    assert [cm.needs_metric_name(r) for r in rows] == [True, True, True, False]


def test_metric_name_is_prefilled_only_where_the_gate_needs_the_analysts_metric():
    out = verdict.gate_prefill([row("a", reason="no metric", claim_type="nps", period="2025"), row("b", metric="ARR")], REVIEW)
    assert out["a"]["gate_metric_name"] == "Nps, 2025" and "gate_metric_name" not in out["b"]


def test_budget_decision_is_never_prefilled_and_the_dropdown_lists_the_decisions_already_used_once_each():
    rows = [row("a"), row("b", gate_saved=True, gate_budget_decision="Series B"), row("c", gate_saved=True, gate_budget_decision="Series B"),
            row("d", gate_saved=True, gate_budget_decision="Hiring plan")]
    assert all("gate_budget_decision" not in v for v in verdict.gate_prefill(rows, REVIEW).values())
    assert verdict.budget_decisions(rows) == ["Series B", "Hiring plan"]


# --- key gates ----------------------------------------------------------------------------------------------------------------

def test_the_three_highest_value_at_stake_gates_are_pre_marked_key():
    rows = [row(c, value_at_stake_arr=v) for c, v in zip("abcde", (5, 50, 1, 40, 30))]
    out = verdict.gate_prefill(rows, REVIEW)
    assert sorted(c for c, v in out.items() if v.get("key_gate")) == ["b", "d", "e"]


def test_pre_marks_leave_room_under_the_limit_of_five_key_gates():
    rows = [row(c) for c in "abc"] + [row(c, gate_saved=True, key_gate=True) for c in "xyz"]
    assert sum(1 for v in verdict.gate_prefill(rows, REVIEW).values() if v.get("key_gate")) == 2


# --- through the API ----------------------------------------------------------------------------------------------------------

def open_register(client):
    ready_for_review(client)
    for c in candidates(client):
        if c["status"] == "pending":
            client.put(f"/api/audits/{AUDIT}/decks/candidates/{c['id']}", json={"status": "approved"})
    client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"first_quarterly_review": REVIEW})
    return client.get(f"/api/audits/{AUDIT}/claims").json()


def fill(body, blank_budget=DECISION):
    return {**body, "gate_budget_decision": blank_budget}


def prefilled_gates(data):
    """What Save all sends: the prefill, the budget decision the analyst picks, and the direction a no-metric row also needs."""
    reasons = {r["claim_id"]: r["reason"] for r in data["register"]}
    return [{"claim_id": cid, **fill(v), **({"gate_direction": "at least"} if reasons[cid] in cm.NO_APP_METRIC else {})}
            for cid, v in data["gate_prefill"].items() if "gate_threshold" in v and "gate_date" in v]


def test_the_claims_endpoint_carries_prefill_beside_the_register_not_in_it(api):  # noqa: F811
    data = open_register(api)
    assert data["gate_prefill"] and all(set(r) <= set(cm.FIELDS) for r in data["register"])
    assert all(r["gate_threshold"] is None and not r["gate_saved"] for r in data["register"] if r["claim_id"] in data["gate_prefill"])
    assert all(v.get("gate_date", REVIEW) <= REVIEW for v in data["gate_prefill"].values())


def test_save_all_saves_every_filled_gate_in_one_call_and_the_key_marks_ride_along(api):  # noqa: F811
    data = open_register(api)
    gates = prefilled_gates(data)
    assert len(gates) >= 3
    r = api.put(f"/api/audits/{AUDIT}/claim-gates", json={"gates": gates})
    assert r.status_code == 200, r.text
    saved = {x["claim_id"]: x for x in r.json()["register"]}
    assert all(saved[g["claim_id"]]["gate_saved"] and saved[g["claim_id"]]["gate_budget_decision"] == DECISION for g in gates)
    assert sorted(c for c, x in saved.items() if x["key_gate"]) == sorted(g["claim_id"] for g in gates if g.get("key_gate"))


def test_save_all_is_refused_as_a_whole_when_one_gate_is_incomplete_or_a_sixth_key_gate(api):  # noqa: F811
    data = open_register(api)
    gates = prefilled_gates(data)
    bad = [{**gates[0], "gate_budget_decision": None}, {"claim_id": gates[1]["claim_id"], "gate_threshold": 1.0, "key_gate": True}]
    assert api.put(f"/api/audits/{AUDIT}/claim-gates", json={"gates": bad}).status_code == 400
    assert not any(r["gate_saved"] for r in api.get(f"/api/audits/{AUDIT}/claims").json()["register"]), "nothing is saved"
    six = [{**g, "key_gate": True} for g in gates[:6]]
    if len(six) == 6:
        assert api.put(f"/api/audits/{AUDIT}/claim-gates", json={"gates": six}).status_code == 400


def test_an_edited_gate_saves_with_the_same_call_and_keeps_the_analysts_value(api):  # noqa: F811
    data = open_register(api)
    gates = prefilled_gates(data)
    gates[0]["gate_threshold"] = 123.0
    assert api.put(f"/api/audits/{AUDIT}/claim-gates", json={"gates": gates}).status_code == 200
    saved = {x["claim_id"]: x for x in api.get(f"/api/audits/{AUDIT}/claims").json()["register"]}
    assert saved[gates[0]["claim_id"]]["gate_threshold"] == 123.0


def test_the_csv_and_the_memo_show_a_gate_as_saved_with_no_trace_of_prefill(api):  # noqa: F811
    data = open_register(api)
    before = api.get(f"/api/audits/{AUDIT}/claims.csv").text
    assert api.get(f"/api/audits/{AUDIT}/claims").status_code == 200
    assert api.get(f"/api/audits/{AUDIT}/claims.csv").text == before, "reading the prefill changes nothing"
    assert before.splitlines()[0].split(",")[1:len(cm.FIELDS) + 1] == list(cm.FIELDS), "same columns as before"
    gates = prefilled_gates(data)
    api.put(f"/api/audits/{AUDIT}/claim-gates", json={"gates": gates})
    after = api.get(f"/api/audits/{AUDIT}/claims.csv").text
    ids = api.get(f"/api/audits/{AUDIT}/verdict").json()["verdict"]["top5"]["proposed"]
    api.put(f"/api/audits/{AUDIT}/ic-inputs", json={"top5": ids, "thesis": THESIS, "ratings": RATINGS})
    text = memo(api).text
    for out in (after, text):
        assert "prefill" not in out.lower() and "confirm" not in out.lower().replace("confirmed", "")
    assert DECISION in after


def test_a_gate_saved_by_save_all_equals_the_same_gate_saved_alone(api):  # noqa: F811
    data = open_register(api)
    g = prefilled_gates(data)[0]
    body = {k: v for k, v in g.items() if k != "claim_id"}
    api.put(f"/api/audits/{AUDIT}/claim-gates", json={"gates": [g]})
    via_all = next(x for x in api.get(f"/api/audits/{AUDIT}/claims").json()["register"] if x["claim_id"] == g["claim_id"])
    cid = g["claim_id"].replace("#", "%23")
    api.put(f"/api/audits/{AUDIT}/claims/{cid}", json={**body, "gate_threshold": body["gate_threshold"] + 1})
    api.put(f"/api/audits/{AUDIT}/claims/{cid}", json=body)
    alone = next(x for x in api.get(f"/api/audits/{AUDIT}/claims").json()["register"] if x["claim_id"] == g["claim_id"])
    assert alone == via_all


# --- the first quarterly review, an audit set-up field -------------------------------------------------------------------------

def test_a_new_audit_has_a_first_quarterly_review_90_days_after_its_creation(api):  # noqa: F811
    r = api.post("/api/audits", json={"company_name": "NewCo", "client_name": "Fund"})
    assert r.status_code == 200
    created = r.json()["created_at"][:10]
    from datetime import date, timedelta
    assert r.json()["ic_inputs"]["first_quarterly_review"] == (date.fromisoformat(created) + timedelta(days=90)).isoformat()


def test_the_review_date_is_editable_and_clearing_it_returns_the_default(api):  # noqa: F811
    ready_for_review(api)
    assert api.put(f"/api/audits/{AUDIT}/ic-inputs", json={"first_quarterly_review": "2027-03-31"}).status_code == 200
    assert api.get(f"/api/audits/{AUDIT}").json()["ic_inputs"]["first_quarterly_review"] == "2027-03-31"
    assert api.put(f"/api/audits/{AUDIT}/ic-inputs", json={"first_quarterly_review": None}).status_code == 200
    assert api.get(f"/api/audits/{AUDIT}").json()["ic_inputs"]["first_quarterly_review"] == "2027-01-09"


def test_a_claim_without_a_period_is_dated_by_the_audits_review_date_and_no_period_goes_past_it(api):  # noqa: F811
    ready_for_review(api)
    for c in candidates(api):
        if c["status"] == "pending":
            api.put(f"/api/audits/{AUDIT}/decks/candidates/{c['id']}", json={"status": "approved"})
    data = api.get(f"/api/audits/{AUDIT}/claims").json()
    review = api.get(f"/api/audits/{AUDIT}").json()["ic_inputs"]["first_quarterly_review"]
    assert data["gate_prefill"] and all(v.get("gate_date") for v in data["gate_prefill"].values()), "every gate has a date"
    assert all(v["gate_date"] <= review for v in data["gate_prefill"].values())
    assert any(v["gate_date"] == review for v in data["gate_prefill"].values())
