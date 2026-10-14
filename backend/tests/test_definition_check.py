"""The big-gap rule (docs/specs/claim-matching.md section 4.1, George, 2026-10-14): within tolerance Verified; a miss up to 50% of
the claim Contradicted; a beat up to 50% Verified (beat); beyond 50% either way a "Definition check", a status with no evidence
label, until the analyst answers "Same metric and period?" Yes (the normal rule, listed under Worth flagging) or No (Unverified,
"definition mismatch"). The results are synthetic: one customer count and one win rate, read as the engine stores them."""
import pytest

from app import claim_matching as cm
from app import verdict as vd
from app.decks import claims as deck_claims

SOURCE = {"file": "revenue.csv", "sheet": "CSV", "rows": "2-40", "rule": "customers with MRR above 0"}
SETTINGS = {"fiscal_year_end": 12, "as_of_month": "2024-02", "reporting_currency": "EUR", "fx": {"EUR": 1.0}}


def results(customers: float, win_rate_pct: float = 0.40) -> dict:
    return {"as_of_month": "2024-02", "reporting_currency": "EUR",
            "customers_series": {"months": ["2024-02"], "segments": [], "source": SOURCE,
                                 "data": [{"month": "2024-02", "total": customers}]},
            "win_rate": {"win_rate_pct": win_rate_pct, "source": {**SOURCE, "file": "crm.csv", "rule": "won ÷ closed"}}}


def customers(claimed, observed, answer=None):
    c = {"id": "x1", "status": "approved", "claim_type": "customers", "value": claimed, "value_high": None, "unit": "customers",
         "currency": None, "target_date": "2024-02", "period_text": "Feb 2024", "snippet": f"{claimed} customers", "label_from": None,
         "file": "deck.pptx", "order": 0, "sources": [{"file": "deck.pptx", "slide": 3}]}
    if answer:
        c["claim_inputs"] = {"x1": {"definition_check": answer}}
    deck_claims.resolve_period(c, 12)
    return cm.build_register([c], results(observed), SETTINGS)[0]


def win_rate(claimed, observed_pct):
    c = {"id": "w1", "status": "approved", "claim_type": "sales", "value": claimed, "value_high": None, "unit": "%", "currency": None,
         "target_date": None, "period_text": None, "snippet": f"Win rate {claimed}%", "label_from": None, "file": "deck.pptx",
         "order": 0, "sources": [{"file": "deck.pptx", "slide": 4}]}
    return cm.build_register([c], results(5, observed_pct / 100), SETTINGS)[0]


def state(row):
    return row["evidence_label"], row["definition_check"], row["gap_kind"]


def test_claimed_1_observed_26_asks_then_yes_is_a_verified_beat_worth_flagging_and_no_is_a_definition_mismatch():
    asked = customers(1, 26)
    assert state(asked) == (None, "ask", "beat")
    assert asked["definition_question"] == "Observed 26, claimed 1. Same metric and period?"
    assert asked["reason"] == "definition check: the gap is beyond 50% of the claim"
    assert (asked["gate_needed"], cm.label_counts([asked])) == (False, {}), "no label, so no gate and no count by label"
    yes = customers(1, 26, "yes")
    assert state(yes) == ("Verified", "yes", "beat") and cm.is_beat(yes)
    assert vd.flagged_rows([yes]) == [yes]
    assert vd.flag_text(yes) == ("#1 Customer count, Feb 2024: Verified, 25 customers more (beat). "
                                 "Same metric and period confirmed by the analyst.")
    no = customers(1, 26, "no")
    assert state(no) == ("Unverified", "no", "beat") and no["reason"] == "definition mismatch"
    assert no["gate_needed"] is True and vd.flagged_rows([no]) == [], "a No needs a gate as any Unverified claim, and is not flagged"
    assert yes["definition_question"] == no["definition_question"] == asked["definition_question"], "the answered row keeps its question"


def test_claimed_100_observed_1_asks_then_yes_is_contradicted_and_no_is_unverified():
    assert state(customers(100, 1)) == (None, "ask", "miss")
    yes = customers(100, 1, "yes")
    assert state(yes) == ("Contradicted", "yes", "miss") and yes["reason"] == "outside ±5%: a miss"
    assert vd.flagged_rows([yes]) == [yes], "a confirmed miss is listed under Worth flagging too"
    no = customers(100, 1, "no")
    assert (state(no), no["reason"]) == (("Unverified", "no", "miss"), "definition mismatch")


def test_a_gap_up_to_50_percent_takes_the_normal_rule_and_asks_nothing():
    beat = customers(20, 26)                                    # 30% beat
    assert state(beat) == ("Verified", None, "beat") and cm.is_beat(beat) and beat["definition_question"] is None
    miss = customers(100, 70)                                   # 30% miss
    assert state(miss) == ("Contradicted", None, "miss")
    assert state(customers(100, 50)) == ("Contradicted", None, "miss"), "exactly 50%: the normal rule"
    assert state(customers(100, 150)) == ("Verified", None, "beat"), "exactly 50% beat: the normal rule"
    assert state(customers(100, 49)) == (None, "ask", "miss"), "just beyond 50%: asked"
    assert customers(100, 49, "maybe")["definition_check"] == "ask", "only yes or no answers it"


def test_a_rate_beyond_one_point_is_read_by_its_direction():
    assert state(win_rate(41, 43)) == ("Verified", None, "beat")          # 2 pp, 4.9% of the claim
    assert state(win_rate(41, 39.0)) == ("Contradicted", None, "miss")
    assert state(win_rate(41, 42)) == ("Verified", None, "beat") and not cm.is_beat(win_rate(41, 42)), "within ±1 pp"
    assert state(win_rate(41, 10)) == (None, "ask", "miss"), "31 points under 41: beyond 50% of the claim"
    assert win_rate(41, 10)["definition_question"] == "Observed 10.0%, claimed 41.0%. Same metric and period?"


def test_the_threshold_is_one_constant(monkeypatch):
    assert cm.BIG_GAP_THRESHOLD == 0.5
    monkeypatch.setattr(cm, "BIG_GAP_THRESHOLD", 0.2)
    asked = customers(100, 70)
    assert state(asked) == (None, "ask", "miss"), "a 30% miss is asked once the threshold is 20%"
    assert asked["reason"] == "definition check: the gap is beyond 20% of the claim"


@pytest.mark.parametrize("claim_ids, kept", [(None, {"x1#2": {"metric": "ARR"}}), ({"x1#1"}, {"x1#2": {"metric": "ARR", "definition_check": "no"}})])
def test_a_re_type_or_a_re_match_drops_the_answer_and_keeps_every_other_input(claim_ids, kept):
    inputs = {"x1#1": {"definition_check": "yes"}, "x1#2": {"metric": "ARR", "definition_check": "no"}}
    assert cm.without_definition_answer(inputs, claim_ids) == kept
    assert inputs["x1#1"] == {"definition_check": "yes"}, "the stored inputs are not changed in place"


def test_the_deck_list_views_hold_the_question_for_a_pending_claim_and_nothing_before_a_calculate():
    pending = {"id": "p1", "status": "pending", "claim_type": "customers", "value": 1, "value_high": None, "unit": "customers",
               "currency": None, "target_date": "2024-02", "period_text": "Feb 2024", "snippet": "1 customer", "label_from": None,
               "file": "deck.pptx", "order": 0, "sources": [{"file": "deck.pptx", "slide": 3}]}
    deck_claims.resolve_period(pending, 12)
    rejected = {**pending, "id": "p2", "status": "rejected"}
    views = cm.definition_views([pending, rejected], results(26), SETTINGS)
    assert views == {"p1": [{"claim_id": "p1", "period": "Feb 2024", "definition_check": "ask",
                             "definition_question": "Observed 26, claimed 1. Same metric and period?"}]}
    assert cm.open_definition_ids(views) == {"p1"}
    assert cm.definition_views([pending], None, SETTINGS) == {}


# --- the endpoint and the answer's life: PUT /claims/{id}/definition-check, cleared by a re-type or a re-match -------------------

from test_approve_all import AUDIT, api, claim  # noqa: E402,F401  (the fixture)
from app import decks  # noqa: E402

ANSWER = f"/api/audits/{AUDIT}/claims/{{}}/definition-check"


def _row(client, cid):
    return next(r for r in client.get(f"/api/audits/{AUDIT}/claims").json()["register"] if r["claim_id"] == cid)


def _inputs(db, cid):
    return next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == cid).get("claim_inputs") or {}


def test_the_answer_is_stored_on_the_claims_inputs_can_be_changed_and_is_refused_where_no_check_is_asked(api):  # noqa: F811
    client, db = api
    db[decks.CANDIDATES_COLLECTION].docs.append(claim("b1", status="approved", value=1000, snippet="Revenue EUR 1,000"))
    assert _row(client, "b1")["definition_check"] == "ask"
    r = client.put(ANSWER.format("b1"), json={"answer": "no"})
    assert r.status_code == 200, r.text
    assert next(x for x in r.json()["register"] if x["claim_id"] == "b1")["reason"] == "definition mismatch"
    assert _inputs(db, "b1") == {"b1": {"definition_check": "no"}}
    assert client.put(ANSWER.format("b1"), json={"answer": "yes"}).status_code == 200, "an answer can be changed"
    assert (_row(client, "b1")["evidence_label"], _row(client, "b1")["definition_check"]) == ("Verified", "yes")
    assert client.put(ANSWER.format("r1"), json={"answer": "yes"}).status_code == 400, "within tolerance: no check to answer"
    assert client.put(ANSWER.format("nope"), json={"answer": "yes"}).status_code == 404
    assert client.put(ANSWER.format("r3"), json={"answer": "yes"}).status_code == 404, "a rejected claim"
    for body in ({"answer": "maybe"}, {}, {"answer": "yes", "extra": 1}):
        assert client.put(ANSWER.format("b1"), json=body).status_code == 422, body
    db["audits"].docs[0]["results"] = None
    assert client.put(ANSWER.format("b1"), json={"answer": "yes"}).status_code == 409, "no figure before a Calculate"


def test_a_re_match_or_a_re_type_clears_the_answer_so_the_question_is_asked_again(api):  # noqa: F811
    client, db = api
    db[decks.CANDIDATES_COLLECTION].docs.append(claim("b1", status="approved", value=1000, snippet="Revenue EUR 1,000"))
    assert client.put(ANSWER.format("b1"), json={"answer": "no"}).status_code == 200
    rematched = client.put(f"/api/audits/{AUDIT}/claims/b1", json={"segment": "Whole company"})
    assert rematched.status_code == 200, rematched.text
    assert _row(client, "b1")["definition_check"] == "ask" and "definition_check" not in _inputs(db, "b1").get("b1", {})
    assert client.put(ANSWER.format("b1"), json={"answer": "yes"}).status_code == 200
    gate = {"gate_threshold": 1.0, "gate_budget_decision": "the plan", "gate_date": "2030-01-01"}
    assert client.put(f"/api/audits/{AUDIT}/claims/b1", json=gate).status_code == 200
    assert _row(client, "b1")["definition_check"] == "yes", "a gate is no re-match: the answer stays"
    retyped = client.put(f"/api/audits/{AUDIT}/decks/candidates/b1", json={"value": 2000})
    assert retyped.status_code == 200, retyped.text
    assert _row(client, "b1")["definition_check"] == "ask", "a re-typed claim is asked again"
    assert _inputs(db, "b1") == {"b1": {"segment": "Whole company", **gate}}, "every other input stays"
