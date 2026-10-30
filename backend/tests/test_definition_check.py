"""The big-gap rule (docs/specs/claim-matching.md section 4.1, George, 2026-10-14): within tolerance Verified; a miss up to 50% of
the claim Contradicted; a beat up to 50% Verified (beat); beyond 50% either way a "Definition check", a status with no evidence
label, until the analyst answers "Same metric and period?" Yes (the normal rule, listed under Worth flagging) or No (Unverified,
"definition mismatch"). The results are synthetic: one customer count and one win rate, read as the engine stores them."""
import pytest

from claim_matching_support import answer_definition
from app import claim_matching as cm
from app import verdict as vd
from app.decks import claims as deck_claims

SOURCE = {"file": "revenue.csv", "sheet": "CSV", "rows": "2-40", "rule": "customers with MRR above 0"}
SETTINGS = {"fiscal_year_end": 12, "as_of_month": "2024-02", "reporting_currency": "EUR", "fx": {"EUR": 1.0}}


def results(customers: float, win_rate_pct: float = 0.40, as_of: str = "2024-02") -> dict:
    return {"as_of_month": as_of, "reporting_currency": "EUR",
            "customers_series": {"months": ["2024-01", "2024-02"], "segments": [], "source": SOURCE,
                                 "data": [{"month": "2024-01", "total": customers}, {"month": "2024-02", "total": customers}]},
            "win_rate": {"win_rate_pct": win_rate_pct, "source": {**SOURCE, "file": "crm.csv", "rule": "won ÷ closed"}}}


def customer_claim(claimed, period="Feb 2024", target="2024-02"):
    c = {"id": "x1", "status": "approved", "claim_type": "customers", "value": claimed, "value_high": None, "unit": "customers",
         "currency": None, "target_date": target, "period_text": period, "snippet": f"{claimed} customers", "label_from": None,
         "file": "deck.pptx", "order": 0, "sources": [{"file": "deck.pptx", "slide": 3}]}
    deck_claims.resolve_period(c, 12)
    return c


def answered(c, answer, observed, res=None, settings=SETTINGS):
    """The claim with `answer` given against the figures of the row as asked now (what the endpoint stores)."""
    res = res or results(observed)
    answer_definition([c], cm.build_register([c], res, settings), c["id"], answer)
    return c


def customers(claimed, observed, answer=None):
    c = customer_claim(claimed)
    if answer:
        answered(c, answer, observed)
    return cm.build_register([c], results(observed), SETTINGS)[0]


def win_rate_claim(claimed):
    c = {"id": "w1", "status": "approved", "claim_type": "sales", "value": claimed, "value_high": None, "unit": "%", "currency": None,
         "target_date": "2024-02", "period_text": "Feb 2024", "snippet": f"Win rate {claimed}%", "label_from": None, "file": "deck.pptx",
         "order": 0, "sources": [{"file": "deck.pptx", "slide": 4}]}
    deck_claims.resolve_period(c, 12)      # a claim with no period is not matched (claim-types-and-correction.md section 2)
    return c


def win_rate(claimed, observed_pct):
    return cm.build_register([win_rate_claim(claimed)], results(5, observed_pct / 100), SETTINGS)[0]


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
    assert vd.flag_text(yes) == ("Customer count, Feb 2024: Verified, 25 customers more (beat). "
                                 "Same metric and period confirmed by the analyst.")
    no = customers(1, 26, "no")
    assert state(no) == ("Unverified", "no", "beat") and no["reason"] == "definition mismatch"
    assert no["gate_needed"] is False and no["gate_status"] == "proposed" and vd.flagged_rows([no]) == [], \
        "a No has a gate written from the claim as any Unverified claim, and is not flagged"
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
    assert state(win_rate(41, 10)) == (None, "ask", "miss"), "31 points under 41: beyond 10 points"
    assert win_rate(41, 10)["definition_question"] == "Observed 10 %, claimed 41 %. Same metric and period?"


def test_a_rate_asks_only_beyond_ten_points_not_beyond_half_of_the_claim():
    assert cm.BIG_GAP_RATE_POINTS == 10
    assert state(win_rate(2, 3.2)) == ("Verified", None, "beat"), "1.2 points: 60% of the claim, but no check for a rate"
    assert state(win_rate(3, 7.6)) == ("Verified", None, "beat"), "4.6 points over 3: 153% of the claim, no check"
    assert state(win_rate(41, 31)) == ("Contradicted", None, "miss"), "exactly 10 points: the normal rule"
    assert state(win_rate(41, 51)) == ("Verified", None, "beat"), "exactly 10 points over: the normal rule"
    asked = win_rate(41, 30.9)
    assert state(asked) == (None, "ask", "miss") and asked["reason"] == "definition check: the gap is beyond 10 percentage points"
    assert state(win_rate(41, 51.1)) == (None, "ask", "beat")
    assert state(win_rate(60, 49)) == (None, "ask", "miss"), "11 points under 60: asked"


def test_the_threshold_is_one_constant(monkeypatch):
    assert cm.BIG_GAP_THRESHOLD == 0.5
    monkeypatch.setattr(cm, "BIG_GAP_THRESHOLD", 0.2)
    asked = customers(100, 70)
    assert state(asked) == (None, "ask", "miss"), "a 30% miss is asked once the threshold is 20%"
    assert asked["reason"] == "definition check: the gap is beyond 20% of the claim"


def test_the_rate_threshold_is_one_constant(monkeypatch):
    monkeypatch.setattr(cm, "BIG_GAP_RATE_POINTS", 5.0)
    assert state(win_rate(41, 34)) == (None, "ask", "miss"), "7 points is asked once the limit is 5"
    assert state(win_rate(41, 36)) == ("Contradicted", None, "miss"), "exactly 5 points: the normal rule"


@pytest.mark.parametrize("claim_ids, kept", [(None, {"x1#2": {"metric": "ARR"}}),
                                             ({"x1#1"}, {"x1#2": {"metric": "ARR", "definition_check": "no", "definition_basis": {"b": 2}}})])
def test_a_re_type_or_a_re_match_drops_the_answer_and_keeps_every_other_input(claim_ids, kept):
    inputs = {"x1#1": {"definition_check": "yes", "definition_basis": {"b": 1}},
              "x1#2": {"metric": "ARR", "definition_check": "no", "definition_basis": {"b": 2}}}
    assert cm.without_definition_answer(inputs, claim_ids) == kept
    assert inputs["x1#1"] == {"definition_check": "yes", "definition_basis": {"b": 1}}, "the stored inputs are not changed in place"


# --- an answer holds only for the figures it was given against (section 4.1) ---------------------------------------------------

def test_a_fiscal_year_end_change_that_moves_the_period_asks_again():
    c = answered(customer_claim(1), "yes", 26)
    assert state(cm.build_register([c], results(26), SETTINGS)[0]) == ("Verified", "yes", "beat")
    moved = {**c, "period_start": "2024-01-01", "period_end": "2024-01-31"}      # what the re-mapping of periods writes: same figures
    again = cm.build_register([moved], results(26), SETTINGS)[0]
    assert (again["claimed_value"], again["observed_value"]) == (1, 26), "only the period differs"
    assert state(again) == (None, "ask", "beat"), "the Yes was for Feb 2024"


def test_an_as_of_month_change_asks_again_with_the_same_figures():
    # a claim with no period is no longer tested at the as-of figure (claim-types-and-correction.md section 2): a dated claim whose
    # figures stay the same while the as-of month moves
    c = answered(customer_claim(1, "Jan 2024", "2024-01"), "no", 26)
    assert state(cm.build_register([c], results(26), SETTINGS)[0])[:2] == ("Unverified", "no")
    again = cm.build_register([c], results(26, as_of="2024-01"), {**SETTINGS, "as_of_month": "2024-01"})[0]
    assert (again["observed_value"], again["claimed_value"]) == (26, 1), "only the as-of month differs"
    assert state(again) == (None, "ask", "beat")


def test_a_recompute_that_changes_the_observed_figure_asks_again():
    c = answered(customer_claim(1), "yes", 26)
    assert state(cm.build_register([c], results(26), SETTINGS)[0])[:2] == ("Verified", "yes")
    assert state(cm.build_register([c], results(27), SETTINGS)[0]) == (None, "ask", "beat"), "26 became 27 after a new file"


def test_an_fx_rate_change_asks_again():
    usd = {"id": "u1", "status": "approved", "claim_type": "revenue", "value": 100.0, "value_high": None, "unit": None, "currency": "USD",
           "target_date": "2026-12", "period_text": "Dec 2026", "snippet": "ARR USD 100", "label_from": None, "file": "deck.pptx",
           "order": 0, "sources": [{"file": "deck.pptx", "slide": 3}]}
    deck_claims.resolve_period(usd, 12)
    res = {"as_of_month": "2026-12", "reporting_currency": "EUR", "mrr_series": {
        "months": ["2026-12"], "segments": [], "source": SOURCE, "data": [{"month": "2026-12", "total": 500.0}]}}
    sets = lambda rate: {"fiscal_year_end": 12, "as_of_month": "2026-12", "reporting_currency": "EUR", "fx": {"USD": rate, "EUR": 1.0}}  # noqa: E731
    asked = cm.build_register([usd], res, sets(0.9))[0]
    assert asked["definition_check"] == "ask" and asked["fx_rate"] == 0.9, "fixture: a USD claim, asked at the saved rate"
    answer_definition([usd], [asked], "u1", "yes")
    assert state(cm.build_register([usd], res, sets(0.9))[0])[:2] == ("Verified", "yes"), "the same rate: the Yes holds"
    assert state(cm.build_register([usd], res, sets(0.95))[0]) == (None, "ask", "beat")


def test_a_gap_that_is_no_longer_big_needs_no_answer_and_an_answer_needs_the_same_basis_to_come_back():
    c = answered(customer_claim(1), "no", 26)
    assert cm.build_register([c], results(1), SETTINGS)[0]["definition_check"] is None, "within tolerance: no check"
    assert cm.build_register([c], results(26), SETTINGS)[0]["definition_check"] == "no", "the figures are back: the answer was for them"
    c["claim_inputs"]["x1"].pop("definition_basis")
    assert cm.build_register([c], results(26), SETTINGS)[0]["definition_check"] == "ask", "an answer with no basis holds for nothing"


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

from entry_support import AUDIT, claim  # noqa: E402
from app import decks  # noqa: E402

ANSWER = f"/api/audits/{AUDIT}/claims/{{}}/definition-check"


def _row(client, cid):
    return next(r for r in client.get(f"/api/audits/{AUDIT}/claims").json()["register"] if r["claim_id"] == cid)


def _inputs(db, cid):
    return next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == cid).get("claim_inputs") or {}


def test_the_answer_is_stored_on_the_claims_inputs_can_be_changed_and_is_refused_where_no_check_is_asked(entry_api):
    client, db = entry_api
    db[decks.CANDIDATES_COLLECTION].docs.append(claim("b1", status="approved", value=1000, snippet="Revenue EUR 1,000"))
    assert _row(client, "b1")["definition_check"] == "ask"
    r = client.put(ANSWER.format("b1"), json={"answer": "no"})
    assert r.status_code == 200, r.text
    assert next(x for x in r.json()["register"] if x["claim_id"] == "b1")["reason"] == "definition mismatch"
    stored = _inputs(db, "b1")["b1"]
    assert stored["definition_check"] == "no" and stored["definition_basis"]["observed"] == 187701.05, "kept with the figures it was given against"
    assert client.put(ANSWER.format("b1"), json={"answer": "yes"}).status_code == 200, "an answer can be changed"
    assert (_row(client, "b1")["evidence_label"], _row(client, "b1")["definition_check"]) == ("Verified", "yes")
    assert client.put(ANSWER.format("r1"), json={"answer": "yes"}).status_code == 400, "within tolerance: no check to answer"
    assert client.put(ANSWER.format("nope"), json={"answer": "yes"}).status_code == 404
    assert client.put(ANSWER.format("r3"), json={"answer": "yes"}).status_code == 404, "a rejected claim"
    for body in ({"answer": "maybe"}, {}, {"answer": "yes", "extra": 1}):
        assert client.put(ANSWER.format("b1"), json=body).status_code == 422, body
    db["audits"].docs[0]["results"] = None
    assert client.put(ANSWER.format("b1"), json={"answer": "yes"}).status_code == 409, "no figure before a Calculate"


def test_a_re_match_or_a_re_type_clears_the_answer_so_the_question_is_asked_again(entry_api):
    client, db = entry_api
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


def test_a_metric_change_clears_the_answer_so_the_question_is_asked_again(entry_api):
    client, db = entry_api
    db[decks.CANDIDATES_COLLECTION].docs.append(claim("b1", status="approved", value=1000, snippet="Revenue EUR 1,000"))
    assert client.put(ANSWER.format("b1"), json={"answer": "no"}).status_code == 200
    assert "definition_check" in _inputs(db, "b1")["b1"], "fixture: the answer is stored"
    changed = client.put(f"/api/audits/{AUDIT}/claims/b1", json={"metric": "ARR"})
    assert changed.status_code == 200, changed.text
    assert _inputs(db, "b1")["b1"] == {"metric": "ARR"}, "the answer and its figures are gone, the metric stays"


def test_a_revenue_or_volume_answer_clears_the_answer_so_the_question_is_asked_again(entry_api):
    client, db = entry_api
    db[decks.CANDIDATES_COLLECTION].docs.append(claim("g1", status="approved", snippet="GMV EUR 900,000", value=900000))
    db[decks.CANDIDATES_COLLECTION].docs[-1]["claim_inputs"] = {"g1": {"definition_check": "yes", "definition_basis": {"observed": 1.0}}}
    answered = client.put(f"/api/audits/{AUDIT}/claims/g1/turnover", json={"as": "revenue", "reason": "file_confirms"})
    assert answered.status_code == 200, answered.text
    assert _inputs(db, "g1")["g1"] == {"turnover_as": "revenue", "turnover_reason": "file_confirms"}, "the earlier answer is dropped"
    assert next(r for r in answered.json()["register"] if r["claim_id"] == "g1")["definition_check"] == "ask"


def test_the_baseline_csv_exports_a_row_with_an_open_check_with_its_label_blank(entry_api):
    """claim-matching.md section 4.1: the CSV is not held back while a check is open; the row is kept honest by an empty
    `evidence_label` and `definition_check` ask."""
    import csv
    import io
    client, db = entry_api
    db[decks.CANDIDATES_COLLECTION].docs.append(claim("b1", status="approved", value=1000, snippet="Revenue EUR 1,000"))
    r = client.get(f"/api/audits/{AUDIT}/claims.csv")
    assert r.status_code == 200, r.text
    rows = {x["claim_id"]: x for x in csv.DictReader(io.StringIO(r.text))}
    assert (rows["b1"]["evidence_label"], rows["b1"]["definition_check"]) == ("", "ask")
    assert rows["r4"]["evidence_label"] == "Verified" and rows["r4"]["definition_check"] == ""
