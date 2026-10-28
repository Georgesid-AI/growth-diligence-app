"""The claim approval is gone (docs/design/simplified-flow.md section 2; CLAUDE.md rule 12). Python enters every claim it matched to its page
and tested against the data; the analyst is asked only where a check failed or a question is open. One failing test per point, on synthetic data.

a which claims wait (a review flag, an unmatched AI suggestion, a Revenue / Volume question open, an Other figure) and which enter
b the register and the deck list read the entry without a write; Run audit's claims stage stores it
c the register row reads "auto" for a Python-entered claim; an edit, a reject or an answer makes the claim the analyst's
d the baseline CSV and the memo's Approval column
e a claim Python entered that a check now asks about is re-opened as a card; a claim the analyst answered is never changed
f the questions are ordered by the selection rule, top-5 questions first
"""
import copy

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from test_claim_matching import RUNS, results_for, settings  # noqa: E402
from test_ic_memo import inputs  # noqa: E402
from test_run_audit import AUDIT, confirm_open_columns, stage, upload_files  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import decks, run_audit  # noqa: E402
from app import ic_memo as im  # noqa: E402
from app import verdict as vd  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402

RUN = RUNS["A"]
NOTE = "Re-opened – a check now asks about it"


def claim(cid, **extra):
    """A pending ARR Feb 2024 claim of 200,000 EUR: 1.1% below the file's 202,125.48, so Verified within tolerance."""
    c = {"id": cid, "status": "pending", "claim_type": "revenue", "value": 200000, "value_high": None, "unit": None, "currency": "EUR",
         "target_date": "2024-02", "period_text": "Feb 2024", "snippet": "ARR of €200,000 in Feb 2024", "label_from": None,
         "file": "deck.pptx", "order": 0, "sources": [{"file": "deck.pptx", "page": 3}], **extra}
    deck_claims.resolve_period(c, RUN["fiscal_year_end"])
    return c


def register(candidates):
    return cm.build_register(candidates, results_for(RUN), settings(RUN, fx={"EUR": 1.0, "USD": 1.1}))


def deck(client, *candidates):
    client.db[decks.TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "d1", "file": "deck.pptx", "ai_status": "read"})
    for n, c in enumerate(candidates):
        client.db[decks.CANDIDATES_COLLECTION].docs.append({**c, "audit_id": AUDIT, "deck_id": "d1", "order": n})


def prepared(client, *candidates):
    upload_files(client)
    confirm_open_columns(client)
    deck(client, *candidates)
    stage(client, "engine")


def stored(client):
    return {c["id"]: c for c in client.db[decks.CANDIDATES_COLLECTION].docs if c["audit_id"] == AUDIT}


def listed(client):
    return {c["id"]: c for c in client.get(f"/api/audits/{AUDIT}/decks").json()["candidates"]}


def registered(client):
    return {r["claim_id"]: r for r in client.get(f"/api/audits/{AUDIT}/claims").json()["register"]}


# --- a. which claims wait and which enter ---------------------------------------------------------------------------------------------
def test_the_rule_reads_the_review_flags_and_the_unmatched_suggestion_not_the_informational_flags_a_scenario_or_a_deck_inconsistency():
    assert run_audit.needs_a_word({"flags": ["axis tick"]}) is True
    assert run_audit.needs_a_word({"flags": []}) is False and run_audit.needs_a_word({}) is False
    assert run_audit.needs_a_word({"flags": ["cell corrected", "currency assumed", "year label below: 2022"]}) is False
    assert run_audit.needs_a_word({"origin": "ai", "ai_status": "unmatched"}) is True
    assert run_audit.needs_a_word({"origin": "ai", "ai_status": "suggestion"}) is True
    assert run_audit.needs_a_word({"origin": "ai", "ai_status": "matched"}) is False and run_audit.needs_a_word({"origin": "ai", "ai_status": "verified"}) is False
    assert run_audit.needs_a_word({"scenario": "worst"}) is False and run_audit.needs_a_word({"inconsistent_dates": ["2023-12-31"]}) is False


def test_a_clean_claim_enters_and_a_flagged_or_unmatched_or_other_claim_waits_for_an_answer(run_api):
    prepared(run_api, claim("plain"), claim("flagged", flags=["axis tick"]), claim("unmatched", origin="ai", ai_status="unmatched"),
             claim("matched", origin="ai", ai_status="matched", flags=["cell corrected"]), claim("other", claim_type="other"))
    res = stage(run_api, "claims")
    got = stored(run_api)
    assert [got[c]["status"] for c in ("plain", "flagged", "unmatched", "matched", "other")] == ["approved", "pending", "pending", "approved", "pending"]
    assert [bool(got[c].get("auto_accepted")) for c in ("plain", "flagged", "matched")] == [True, False, True]
    assert res["entered"] == 2 and res["open"] == 2 and "accepted" not in res, "an Other figure is never a task, so it is not counted"
    assert sorted(res["entered_ids"]) == ["matched", "plain"]
    assert set(registered(run_api)) == {"plain", "matched"}, "only the entered claims are in the register"


def test_a_best_case_a_deck_inconsistency_and_a_claim_in_another_currency_enter_on_their_own(run_api):
    usd = claim("usd", currency="USD", value=181818)
    best = claim("best", basis="scenario", scenario="best")
    inconsistent = claim("incons", inconsistent_dates=["2023-12-31"], inconsistencies=[{"this": {"value": 190000}, "other": {"value": 150000}}])
    prepared(run_api, claim("plain"), usd, best, inconsistent)
    run_api.db["audits"].docs[0]["fx"] = {"EUR": 1.0, "USD": 1.1}
    stage(run_api, "claims")
    assert {c: stored(run_api)[c]["status"] for c in ("usd", "best", "incons")} == {"usd": "approved", "best": "approved", "incons": "approved"}
    row = registered(run_api)["best"]
    assert (row["evidence_label"], row["reason"]) == ("Unverified", cm.SCENARIO_NOTE.format(case="best")), "listed in the register as Unverified, as before"


def test_a_beat_and_a_miss_and_a_definition_check_enter_too_the_tolerance_decides_the_label_not_the_entry(run_api):
    prepared(run_api, claim("beat", value=150000), claim("miss", value=250000), claim("ask", value=1000))
    stage(run_api, "claims")
    assert {c: stored(run_api)[c]["status"] for c in ("beat", "miss", "ask")} == {"beat": "approved", "miss": "approved", "ask": "approved"}
    rows = registered(run_api)
    assert (rows["miss"]["evidence_label"], rows["ask"]["evidence_label"], rows["ask"]["definition_check"]) == ("Contradicted", None, "ask")


def test_a_turnover_claim_waits_for_its_revenue_or_volume_answer_then_enters(run_api):
    prepared(run_api, claim("plain"), claim("gmv", snippet="GMV EUR 900,000", value=900000))
    res = stage(run_api, "claims")
    assert stored(run_api)["gmv"]["status"] == "pending" and stored(run_api)["plain"]["status"] == "approved"
    assert res["turnover_open"] == 1 and res["open"] == 1
    answered = run_api.put(f"/api/audits/{AUDIT}/claims/gmv/turnover", json={"as": "volume", "reason": "deck_says_processed_volume"})
    assert answered.status_code == 200, answered.text
    stage(run_api, "claims")
    assert stored(run_api)["gmv"]["status"] == "approved"


# --- b. the screens read the entry without a write; the claims stage stores it --------------------------------------------------------
def test_the_register_and_the_deck_list_show_an_entered_claim_with_no_stored_change_until_the_claims_stage(run_api):
    prepared(run_api)
    deck(run_api, claim("plain"), claim("flagged", flags=["axis tick"]))      # read after the calculations: nothing has stored them yet
    assert "plain" in registered(run_api), "no Run audit, no click: the clean claim is in the register"
    assert stored(run_api)["plain"]["status"] == "pending", "a read writes nothing"
    on_list = listed(run_api)
    assert (on_list["plain"]["status"], on_list["plain"]["auto_accepted"], on_list["plain"]["auto_approval"]) == ("approved", True, "auto")
    assert on_list["flagged"]["status"] == "pending"
    stage(run_api, "claims")
    assert stored(run_api)["plain"]["status"] == "approved" and stored(run_api)["plain"]["auto_accepted"] is True


def test_no_deck_means_no_claims_stage_counts(run_api):
    upload_files(run_api)
    confirm_open_columns(run_api)
    stage(run_api, "engine")
    res = stage(run_api, "claims")
    assert res["status"] == "done" and (res["entered"], res["open"]) == (0, 0)


# --- c. the mark ----------------------------------------------------------------------------------------------------------------------
def test_a_python_entered_claim_reads_auto_in_the_register_and_an_analyst_approved_one_reads_nothing():
    auto = register([{**claim("a"), "status": "approved", "auto_accepted": True}])[0]
    assert auto["evidence_label"] == "Verified" and auto["auto_approval"] == "auto" and auto["observed_citation"]
    assert register([{**claim("a"), "status": "approved"}])[0]["auto_approval"] is None
    off = register([{**claim("o", value=300000), "status": "approved", "auto_accepted": True}])[0]
    assert off["auto_approval"] == "auto", "the mark says who entered the claim, not whether it matches"
    edited = register([{**claim("e", parsed={"value": 190000}), "status": "edited", "auto_accepted": True}])[0]
    assert edited["auto_approval"] is None, "an edit makes it the analyst's"


def test_editing_an_entered_claim_makes_it_an_analyst_edited_claim_and_removes_the_mark(run_api):
    prepared(run_api, claim("plain"))
    stage(run_api, "claims")
    r = run_api.put(f"/api/audits/{AUDIT}/decks/candidates/plain", json={"value": 189000})
    assert r.status_code == 200, r.text
    assert not stored(run_api)["plain"].get("auto_accepted") and stored(run_api)["plain"]["status"] == "edited"
    assert registered(run_api)["plain"]["auto_approval"] is None


@pytest.mark.parametrize("path", [("rejected", "approved"), ("rejected", "pending", "approved"), ("pending", "approved")])
def test_rejecting_or_reopening_an_entered_claim_clears_the_mark_so_a_later_answer_reads_analyst(run_api, path):
    prepared(run_api, claim("plain"))
    stage(run_api, "claims")
    for status in path:
        r = run_api.put(f"/api/audits/{AUDIT}/decks/candidates/plain", json={"status": status})
        assert r.status_code == 200, r.text
    assert stored(run_api)["plain"]["status"] == "approved" and not stored(run_api)["plain"].get("auto_accepted")
    assert registered(run_api)["plain"]["auto_approval"] is None


def test_a_rejected_claim_stays_stored_and_leaves_the_register_the_exclusion_control(run_api):
    prepared(run_api, claim("plain"), claim("other_one", value=199000))
    stage(run_api, "claims")
    assert run_api.put(f"/api/audits/{AUDIT}/decks/candidates/plain", json={"status": "rejected"}).status_code == 200
    assert stored(run_api)["plain"]["status"] == "rejected" and "plain" not in registered(run_api) and "other_one" in registered(run_api)
    stage(run_api, "claims")
    assert stored(run_api)["plain"]["status"] == "rejected", "Python never enters a rejected claim again"


# --- d. CSV and memo ------------------------------------------------------------------------------------------------------------------
def test_the_baseline_csv_and_the_memo_register_show_auto(run_api):
    import csv
    import io
    prepared(run_api, claim("plain"))
    stage(run_api, "claims")
    table = list(csv.reader(io.StringIO(run_api.get(f"/api/audits/{AUDIT}/claims.csv").text)))
    assert table[1][table[0].index("auto_approval")] == "auto"
    rows = copy.deepcopy(inputs()["rows"])
    rows[0]["auto_approval"] = cm.AUTO_LABEL
    memo = im.build_memo(**{**inputs(), "rows": rows})
    appendix = memo.split("## Appendix A")[1].split("## Appendix B")[0]
    table = [[c.strip() for c in line.strip("|").split("|")] for line in appendix.splitlines() if line.startswith("| ")]
    header, body = table[0], table[1:]
    assert tuple(header[:4]) == vd.FOUR_COLUMNS and "Approval" in header
    ref, result, who = header.index("Ref"), header.index("Result"), header.index("Approval")
    approval = {r[ref]: (r[result], r[who]) for r in body}
    assert approval[f"#{rows[0]['rank']}"][0].startswith(rows[0]["evidence_label"]) and approval[f"#{rows[0]['rank']}"][1] == cm.AUTO_LABEL
    assert {v[1] for k, v in approval.items() if k != f"#{rows[0]['rank']}"} == {cm.ANALYST_LABEL}


# --- e. a claim a check now asks about goes back to a card; an analyst's answer is never changed -------------------------------------------
def test_an_entered_claim_a_check_now_asks_about_is_re_opened_with_a_note_and_an_answered_one_is_never_changed(run_api):
    prepared(run_api, claim("auto"), claim("manual"))
    stage(run_api, "claims")
    for status in ("rejected", "approved"):             # the analyst's own answer on the second claim
        assert run_api.put(f"/api/audits/{AUDIT}/decks/candidates/manual", json={"status": status}).status_code == 200
    stored(run_api)["auto"]["flags"] = ["axis tick"]     # a re-read, a new file or a changed as-of month: a check now flags it
    stored(run_api)["manual"]["flags"] = ["axis tick"]
    res = stage(run_api, "claims")
    got = stored(run_api)
    assert got["auto"]["status"] == "pending" and not got["auto"].get("auto_accepted") and got["auto"]["auto_note"] == NOTE
    assert got["manual"]["status"] == "approved", "an analyst's answer is never changed"
    assert res["reopened"] == 1 and listed(run_api)["auto"]["auto_note"] == NOTE
    assert "auto" not in registered(run_api)
    got["auto"]["flags"] = []
    stage(run_api, "claims")
    again = stored(run_api)["auto"]
    assert again["status"] == "approved" and again["auto_accepted"] is True and not again.get("auto_note"), "a later pass enters it again"


def test_an_entered_claim_that_still_passes_stays_entered_after_a_re_run(run_api):
    prepared(run_api, claim("auto"))
    stage(run_api, "claims")
    stage(run_api, "engine")
    stage(run_api, "claims")
    assert stored(run_api)["auto"]["status"] == "approved" and stored(run_api)["auto"]["auto_accepted"] is True


# --- f. the questions in the order of the selection rule -----------------------------------------------------------------------------
def test_the_questions_come_ordered_by_the_selection_rule_the_top_5_ones_first(run_api):
    prepared(run_api, *[claim(f"plain{n}", value=190000 + n, target_date="2023", period_text="FY2023") for n in range(5)],
             claim("q_small", flags=["axis tick"], claim_type="cac_payback", unit="months", currency=None, value=14),
             claim("q_big", flags=["axis tick"], value=250000))
    body = run_api.get(f"/api/audits/{AUDIT}/decks").json()
    order = body["attention"]
    assert [q["id"] for q in order][:1] == ["q_big"] and [q["id"] for q in order] == ["q_big", "q_small"]
    assert order[0]["in_top5"] is True and "in_top5" in order[1]


def test_the_verdict_endpoint_counts_the_waiting_claims_and_the_open_definition_checks_and_the_rule_line_ends_with_the_count(run_api):
    """simplified-flow.md section 1: an open question is a count on the explanation line, not a state; the count is the cards plus the open checks."""
    prepared(run_api, claim("plain", value=150000), claim("ask", value=1000), claim("flagged", flags=["axis tick"]),
             claim("unmatched", origin="ai", ai_status="unmatched"))
    stage(run_api, "claims")
    assert registered(run_api)["ask"]["definition_check"] == "ask"
    body = run_api.get(f"/api/audits/{AUDIT}/verdict").json()
    assert body["verdict"]["status"] == "ok"
    assert body["verdict"]["rule"] == ("No selected claim is Contradicted; 1 of 2 are Verified, 1 untested. 3 questions open. "
                                       "Top 2 (the register has 2 claims)."), "two claims wait for an answer and one Definition check is open"
    assert "3 claim questions open on the Audit page." in body["unresolved_questions"]


# --- g. a row whose reason asks the analyst to set something is a question (George, 2026-10-25) --------------------------------------------
def test_an_untested_row_that_asks_the_analyst_to_set_something_is_a_card_and_an_open_question(run_api):
    prepared(run_api, claim("plain", value=150000), claim("noperiod", target_date=None, period_text=None, snippet="ARR of €200,000"))
    stage(run_api, "claims")
    row = registered(run_api)["noperiod"]
    assert (row["evidence_label"], row["reason"]) == ("Unverified", cm.PERIOD_NOT_READ)
    attention = run_api.get(f"/api/audits/{AUDIT}/decks").json()["attention"]
    assert [(q["id"], q.get("set")) for q in attention] == [("noperiod", cm.PERIOD_NOT_READ)], "the verified claim is no card"
    body = run_api.get(f"/api/audits/{AUDIT}/verdict").json()
    assert body["verdict"]["open_questions"] == 1 and "1 question open." in body["verdict"]["rule"]
    # the analyst sets the period in the claim's editor: the card and the question go
    assert run_api.put(f"/api/audits/{AUDIT}/decks/candidates/noperiod", json={"target_date": "2024-02"}).status_code == 200
    assert run_api.get(f"/api/audits/{AUDIT}/decks").json()["attention"] == []
    assert run_api.get(f"/api/audits/{AUDIT}/verdict").json()["verdict"]["open_questions"] == 0


# --- g. High confidence is accepted without a click, before any audit result exists (George, 2026-10-28) ---------------------------------
def test_a_high_confidence_page_read_claim_is_accepted_before_the_first_calculate_medium_and_low_wait(run_api):
    """Live bug: every candidate of an audit with no results stayed pending, High ones too ("Needs your attention")."""
    high = claim("high", origin="ai", ai_status="matched", flags=[], cell="r9c8")
    medium = claim("medium", origin="ai", ai_status="matched", flags=[], cell="r9c9", target_date=None, period_text=None)
    low = claim("low", origin="ai", ai_status="unmatched", flags=[])
    deck(run_api, high, medium, low)
    assert not run_api.db["audits"].docs[0].get("results"), "fixture: no audit result yet"
    listed = {c["id"]: c for c in run_api.get(f"/api/audits/{AUDIT}/decks").json()["candidates"]}
    assert [listed[c]["confidence"]["level"] for c in ("high", "medium", "low")] == ["High", "Medium", "Low"]
    assert [listed[c]["status"] for c in ("high", "medium", "low")] == ["approved", "pending", "pending"]
    assert [c for c, d in listed.items() if d["status"] == "pending"] == ["medium", "low"], "the count of what waits leaves the High one out"
