"""Issue #155: the claims Run audit approves on its own (claim-matching.md section 4.1, amended 2026-10-22, George's option c).

Already in place before this issue and not retested here (test_run_audit.py): the step approves a pending claim the register labels Verified
within tolerance, not a beat, with no open Definition check; Approve all touches only pending claims, so it skips an approved one.
The gap, one failing test per point on synthetic data:

a three claims are never approved on their own: Analyst-entered or Analyst-edited, flagged as a deck inconsistency, in a currency other than the audit's
b a claim approved on its own reads "Auto-approved – matches revenue file (Δ x.x%)" in the register row, with its citation beside it
c an edit takes the mark away; a claim that stops matching loses it
d the deck list carries the status text and the citation
e the baseline CSV and the memo's register show it as "auto"

Review of PR 157 (George, 2026-10-22), one failing test per point:

f a claim the analyst added from a deck line ("Add from deck", origin deck_analyst) is never approved on its own, on any path
g a status the analyst sets (reject, back to pending, approve) clears the mark: a later manual approval reads analyst
h an auto-approved claim that stops matching (re-run, as-of month, FX) goes back to "To review" with a note; a manual approval is never changed
i the review page's within-tolerance count and the deck list's "(z auto)" count read the same field
"""
import copy

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from test_claim_matching import RUNS, results_for, settings  # noqa: E402
from test_ic_memo import inputs  # noqa: E402
from test_run_audit import AUDIT, confirm_open_columns, review, stage, upload_files  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import decks, run_audit  # noqa: E402
from app import ic_memo as im  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402

RUN = RUNS["A"]
TEXT = "Auto-approved – matches revenue file (Δ 1.1%)"          # ARR Feb 2024 claimed 200,000 against 202,125.48


def claim(cid, **extra):
    """A pending ARR Feb 2024 claim of 200,000 EUR: 1.1% below the file's 202,125.48, so Verified within tolerance (a beat inside ±5% is plain Verified)."""
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


# --- a. what is never approved on its own -----------------------------------------------------------------------------------------
def test_a_row_of_an_analyst_edited_or_analyst_entered_claim_or_in_another_currency_is_not_within_tolerance_for_the_step():
    plain = {"claim_id": "a", "evidence_label": "Verified", "reason": "within ±5% of the claim", "definition_check": None,
             "deck_reading": "parser", "claimed_converted": None}
    rows = [plain, {**plain, "claim_id": "b", "deck_reading": "edited"}, {**plain, "claim_id": "c", "deck_reading": cm.ANALYST_ENTERED},
            {**plain, "claim_id": "d", "claimed_converted": 209000.0}]
    assert run_audit.within_tolerance_ids(rows, list("abcd")) == ["a"]


def test_a_claim_flagged_as_a_deck_inconsistency_is_not_approved_on_its_own_and_the_others_are(run_api):
    prepared(run_api, claim("plain"), claim("flagged", inconsistent_dates=["2023-12-31"],
                                            inconsistencies=[{"this": {"value": 190000}, "other": {"value": 150000}}]))
    res = stage(run_api, "claims")
    got = stored(run_api)
    assert (got["plain"]["status"], got["plain"].get("auto_accepted")) == ("approved", True)
    assert (got["flagged"]["status"], got["flagged"].get("auto_accepted")) == ("pending", None)
    assert res["accepted"] == 1 and res["open"] == 1


def test_a_claim_the_analyst_edited_before_the_step_is_not_approved_on_its_own(run_api):
    edited = claim("edited", parsed={"value": 189000})
    prepared(run_api, claim("plain"), edited)
    stage(run_api, "claims")
    assert stored(run_api)["edited"]["status"] == "pending" and not stored(run_api)["edited"].get("auto_accepted")


def test_a_claim_in_another_currency_is_not_approved_on_its_own_however_close_it_is_at_the_saved_rate(run_api):
    usd = claim("usd", currency="USD", value=181818)
    prepared(run_api, claim("plain"), usd)
    run_api.db["audits"].docs[0]["fx"] = {"EUR": 1.0, "USD": 1.1}
    stage(run_api, "claims")
    got = stored(run_api)
    assert got["plain"].get("auto_accepted") is True and got["usd"]["status"] == "pending" and not got["usd"].get("auto_accepted")


# --- b. the status text and the citation in the register ---------------------------------------------------------------------------
def test_an_auto_approved_claim_reads_the_status_text_with_its_delta_and_keeps_its_citation():
    plain = register([{**claim("a"), "status": "approved", "auto_accepted": True}])[0]
    assert plain["evidence_label"] == "Verified" and plain["auto_approval"] == TEXT
    assert plain["observed_citation"], "the observed figure's own citation sits beside the text"
    assert register([{**claim("a"), "status": "approved"}])[0]["auto_approval"] is None, "approved by the analyst: no mark"
    assert "auto_approval" in cm.FIELDS


def test_a_rate_reads_its_delta_in_points_and_a_row_that_no_longer_matches_loses_the_mark():
    rate = {**claim("r", claim_type="sales", snippet="Win rate 40%", unit="%", currency=None, value=40.5, target_date="2024-02",
                    period_text="Feb 2024"), "status": "approved", "auto_accepted": True}
    row = register([rate])[0]
    assert row["evidence_label"] == "Verified" and row["auto_approval"] == "Auto-approved – matches revenue file (Δ 0.5 pp)"
    off = {**claim("o", value=300000), "status": "approved", "auto_accepted": True}
    assert register([off])[0]["evidence_label"] != "Verified" and register([off])[0]["auto_approval"] is None
    flagged = {**claim("f", currency="USD", value=181818), "status": "approved", "auto_accepted": True}
    assert register([flagged])[0]["auto_approval"] is None, "a claim in another currency never reads auto"


# --- c. an edit takes the mark away --------------------------------------------------------------------------------------------------
def test_editing_an_auto_approved_claim_makes_it_an_analyst_edited_claim_and_removes_the_mark(run_api):
    prepared(run_api, claim("plain"))
    stage(run_api, "claims")
    assert stored(run_api)["plain"]["auto_accepted"] is True
    r = run_api.put(f"/api/audits/{AUDIT}/decks/candidates/plain", json={"value": 189000})
    assert r.status_code == 200, r.text
    assert not stored(run_api)["plain"].get("auto_accepted") and stored(run_api)["plain"]["status"] == "edited"
    assert review(run_api)["claims"]["auto_accepted"] == 0


# --- d. the deck list -----------------------------------------------------------------------------------------------------------
def test_the_deck_list_carries_the_status_text_and_the_citation_of_an_auto_approved_claim_only(run_api):
    prepared(run_api, claim("plain"), claim("beat", value=150000))
    stage(run_api, "claims")
    listed = {c["id"]: c for c in run_api.get(f"/api/audits/{AUDIT}/decks").json()["candidates"]}
    assert listed["plain"]["auto_approval"] == TEXT and listed["plain"]["auto_citation"]
    assert listed["beat"]["status"] == "pending" and not listed["beat"].get("auto_approval")


# --- e. CSV and memo -------------------------------------------------------------------------------------------------------------------
def test_the_baseline_csv_and_the_memo_register_show_auto(run_api):
    import csv
    import io
    prepared(run_api, claim("plain"))
    stage(run_api, "claims")
    text = run_api.get(f"/api/audits/{AUDIT}/claims.csv").text
    table = list(csv.reader(io.StringIO(text)))
    cell = table[1][table[0].index("auto_approval")]
    assert cell == TEXT, cell

    # George (PR 157): the Label column stays the plain evidence label; a separate Approval column reads auto or analyst.
    rows = copy.deepcopy(inputs()["rows"])
    rows[0]["auto_approval"] = TEXT
    memo = im.build_memo(**{**inputs(), "rows": rows})
    appendix = memo.split("## Appendix A")[1].split("## Appendix B")[0]
    table = [[c.strip() for c in line.strip("|").split("|")] for line in appendix.splitlines() if line.startswith("| ")]
    header, body = table[0], table[1:]
    assert header[:4] == ["#", "Claim", "Label", "Approval"]
    approval = {r[0]: (r[2], r[3]) for r in body}
    assert approval[f"#{rows[0]['rank']}"] == (rows[0]["evidence_label"], cm.AUTO_LABEL)
    assert {v[1] for k, v in approval.items() if k != f"#{rows[0]['rank']}"} == {cm.ANALYST_LABEL}
    assert "(auto)" not in appendix


# --- f. Add from deck (George, 2026-10-22) ------------------------------------------------------------------------------------------
def test_a_claim_added_from_a_deck_line_is_not_approved_on_its_own_on_any_path(run_api):
    plain = {"claim_id": "a", "evidence_label": "Verified", "reason": "within ±5% of the claim", "definition_check": None,
             "deck_reading": cm.ADDED_FROM_DECK, "claimed_converted": None}
    assert run_audit.within_tolerance_ids([plain], ["a"]) == [], "the row test"
    assert run_audit.never_on_its_own({"origin": "deck_analyst"}), "the candidate test"
    prepared(run_api, claim("plain"), claim("picked", origin="deck_analyst"))
    stage(run_api, "claims")
    got = stored(run_api)
    assert got["plain"]["status"] == "approved" and got["picked"]["status"] == "pending" and not got["picked"].get("auto_accepted")


# --- g. a status the analyst sets clears the mark -------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", [("rejected", "approved"), ("rejected", "pending", "approved"), ("pending", "approved")])
def test_rejecting_or_unapproving_an_auto_approved_claim_clears_the_mark_so_a_later_approval_reads_analyst(run_api, path):
    prepared(run_api, claim("plain"))
    stage(run_api, "claims")
    for status in path:
        r = run_api.put(f"/api/audits/{AUDIT}/decks/candidates/plain", json={"status": status})
        assert r.status_code == 200, r.text
    assert stored(run_api)["plain"]["status"] == "approved" and not stored(run_api)["plain"].get("auto_accepted")
    listed = {c["id"]: c for c in run_api.get(f"/api/audits/{AUDIT}/decks").json()["candidates"]}
    assert not listed["plain"]["auto_approval"]
    assert review(run_api)["claims"]["auto_accepted"] == 0


# --- h. a claim that stops matching goes back to review ----------------------------------------------------------------------------------
NOTE = "No longer matches – was auto-approved"


def test_an_auto_approved_claim_that_stops_matching_after_an_as_of_change_goes_back_to_review_with_a_note(run_api):
    prepared(run_api, claim("auto"), claim("manual"))
    stage(run_api, "claims")
    for status in ("rejected", "approved"):             # the analyst's own approval of the second claim
        assert run_api.put(f"/api/audits/{AUDIT}/decks/candidates/manual", json={"status": status}).status_code == 200
    assert stored(run_api)["auto"]["auto_accepted"] is True
    r = run_api.put(f"/api/audits/{AUDIT}", json={"as_of_month": "2023-12"})       # Feb 2024 is now after the as-of month: a forecast
    assert r.status_code == 200, r.text
    assert stored(run_api)["auto"]["status"] == "approved", "the change marks the results stale; nothing re-checks until Run audit (2026-10-24)"
    stage(run_api, "engine")
    got = stored(run_api)
    assert got["auto"]["status"] == "pending" and not got["auto"].get("auto_accepted") and got["auto"]["auto_note"] == NOTE
    assert got["manual"]["status"] == "approved", "a manually approved claim is never changed"
    listed = {c["id"]: c for c in run_api.get(f"/api/audits/{AUDIT}/decks").json()["candidates"]}
    assert listed["auto"]["auto_note"] == NOTE and not listed["manual"].get("auto_note")
    assert review(run_api)["claims"]["auto_accepted"] == 0


def test_the_claims_stage_sends_back_an_auto_approved_claim_that_no_longer_matches_and_a_later_match_approves_it_again(run_api):
    prepared(run_api, claim("auto"))
    stage(run_api, "claims")
    stored(run_api)["auto"]["value"] = 300000            # the file now says otherwise (a new revenue file, a corrected claim base)
    stage(run_api, "claims")
    got = stored(run_api)["auto"]
    assert got["status"] == "pending" and got["auto_note"] == NOTE
    got["value"] = 200000
    stage(run_api, "claims")
    again = stored(run_api)["auto"]
    assert again["status"] == "approved" and again["auto_accepted"] is True and not again.get("auto_note")


def test_an_auto_approved_claim_that_still_matches_stays_approved_after_a_re_run(run_api):
    prepared(run_api, claim("auto"))
    stage(run_api, "claims")
    stage(run_api, "engine")
    stage(run_api, "claims")
    assert stored(run_api)["auto"]["status"] == "approved" and stored(run_api)["auto"]["auto_accepted"] is True


# --- i. one field for both counts --------------------------------------------------------------------------------------------------------
def test_the_review_count_and_the_deck_list_count_read_the_same_field(run_api):
    prepared(run_api, claim("auto"), claim("old", status="edited", auto_accepted=True, parsed={"value": 200000}))
    stage(run_api, "claims")
    listed = run_api.get(f"/api/audits/{AUDIT}/decks").json()["candidates"]
    on_list = sorted(c["id"] for c in listed if c["status"] == "approved" and c.get("auto_accepted"))
    assert review(run_api)["claims"]["auto_accepted_ids"] == on_list == ["auto"]
