"""Claim types, required fields and the correction path (docs/specs/claim-types-and-correction.md; plan of 15 Oct 2026,
section 4 and 7.1).

Every type has the fields it must know before matching; the editor corrects any of them with a logged reason; Other figures
are never tasks; a sentence the parser missed is added from the stored deck page with its page as source. Python only, no
network, no model.
"""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from test_claim_matching import run_claim  # noqa: E402
from test_claim_register_api import AUDIT, _get, api  # noqa: E402,F401  (the fixture)

from app import decks  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402

DECK_ID = "deck-1"
MISSED = "Signed twelve enterprise pilots last quarter"     # a figure in words: the parser finds no claim in it


def _add(db, **fields):
    c = {"audit_id": AUDIT, "status": "approved", "value_high": None, "unit": None, "currency": "EUR", "label_from": None,
         "file": "testco_board.pptx", "deck_id": DECK_ID, "order": 90, "sources": [{"file": "testco_board.pptx", "slide": 9}], **fields}
    deck_claims.resolve_period(c, 12)
    db[decks.CANDIDATES_COLLECTION].docs.append(c)
    return c


def _deck(db):
    db[decks.TEXT_COLLECTION].docs.append({
        "audit_id": AUDIT, "deck_id": DECK_ID, "file": "testco_board.pptx", "format": "pptx", "page_unit": "slide", "pages": 12,
        "blocks": [{"slide": 3, "kind": "text", "text": "Our customers love us", "box": 1},
                   {"slide": 4, "kind": "text", "text": MISSED, "box": 2},
                   {"slide": 4, "kind": "table", "table": 1, "row": 1, "col": 2, "text": "Q1 2024"}],
        "structures": [], "ai_status": "python_only", "uploaded_at": "2026-10-15T09:00:00+00:00"})


def _row(client, claim_id):
    return next((r for r in _get(client)["register"] if r["claim_id"] == claim_id), None)


# --- plan section 4, acceptance test 1 -------------------------------------------------------------------------------------------

def test_plan_4_1_a_claim_extracted_as_target_but_actually_actual_is_corrected_in_the_editor_and_re_matched(api):  # noqa: F811
    client, db = api
    _add(db, id="t1", claim_type="revenue", value=200000, target_date="2024-02", period_text="Feb 2024",
         snippet="Target ARR of €200,000 in Feb 2024")
    row = _row(client, "t1")
    assert row["figure_type"] == "target", "the line holds a target cue"
    assert row["evidence_label"] == "Unverified"
    assert row["reason"] == "target figure: the deck states a plan for this period, not a result"
    r = client.put(f"/api/audits/{AUDIT}/decks/candidates/t1", json={"figure_type": "actual", "reason": "parser_misread"})
    assert r.status_code == 200, r.text
    edited = r.json()
    assert edited["status"] == "edited" and edited["figure_type"] == "actual"
    log = edited["edit_log"][-1]
    assert {k: log[k] for k in ("field", "previous", "value", "by", "reason")} == \
        {"field": "figure_type", "previous": "target", "value": "actual", "by": "analyst", "reason": "parser_misread"}
    assert log["at"], "when it changed"
    assert edited["sources"] == [{"file": "testco_board.pptx", "slide": 9}] and edited["snippet"] == "Target ARR of €200,000 in Feb 2024", \
        "the provenance is unchanged"
    row = _row(client, "t1")
    assert (row["figure_type"], row["evidence_label"], row["observed_value"]) == ("actual", "Verified", 202125.48), "re-matched"


# --- plan section 4, acceptance test 2, and 7.1 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("claim_type", ["other", "unknown"])
def test_plan_4_2_fifteen_months_typed_other_creates_no_task_and_is_not_in_the_review_list(api, claim_type):  # noqa: F811
    client, db = api
    _add(db, id="o1", claim_type=claim_type, status="pending", value=15, unit="months", currency=None, target_date=None,
         period_text=None, snippet="15 months")
    review = client.get(f"/api/audits/{AUDIT}/review").json()
    assert review["claims"]["open"] == 1, "only the fixture's own pending revenue claim is a task"
    group = deck_claims.type_group(claim_type)
    done = client.post(f"/api/audits/{AUDIT}/decks/candidates/approve-all", json={"group": group}).json()
    assert (done["approved"], done["skipped"]) == (0, 0), "Approve all neither approves nor counts an Other figure"
    assert client.put(f"/api/audits/{AUDIT}/decks/candidates/o1", json={"status": "approved"}).status_code == 400
    assert _row(client, "o1") is None, "never in the register"
    listed = next(c for c in client.get(f"/api/audits/{AUDIT}/decks").json()["candidates"] if c["id"] == "o1")
    assert listed["group"] == deck_claims.OTHER_GROUP


def test_retyping_out_of_other_puts_the_claim_back_into_matching(api):  # noqa: F811
    client, db = api
    _add(db, id="o2", claim_type="other", status="pending", value=200000, target_date="2024-02", period_text="Feb 2024",
         snippet="ARR €200,000 in Feb 2024")
    r = client.put(f"/api/audits/{AUDIT}/decks/candidates/o2", json={"claim_type": "revenue", "reason": "parser_misread"})
    assert r.status_code == 200 and r.json()["status"] == "edited"
    log = r.json()["edit_log"][-1]
    assert (log["field"], log["previous"], log["value"]) == ("claim_type", "other", "revenue")
    assert _row(client, "o2")["evidence_label"] == "Verified"


# --- plan section 4, acceptance test 3 -------------------------------------------------------------------------------------------

def test_plan_4_3_a_sentence_missed_by_the_parser_is_added_from_the_deck_page_with_its_page_as_source(api):  # noqa: F811
    client, db = api
    _deck(db)
    assert deck_claims.detect_candidates([{"slide": 4, "kind": "text", "text": MISSED, "box": 2}], "testco_board.pptx") == [], \
        "the premise: the parser finds no claim in the sentence"
    page = client.get(f"/api/audits/{AUDIT}/decks/{DECK_ID}/pages/4")
    assert page.status_code == 200, page.text
    lines = page.json()["lines"]
    assert {"ref": "b1", "kind": "text", "text": MISSED} in lines and all(line["ref"] != "b0" for line in lines), "page 4 only"
    r = client.post(f"/api/audits/{AUDIT}/decks/{DECK_ID}/add-from-deck", json={"page": 4, "ref": "b1"})
    assert r.status_code == 200, r.text
    added = r.json()
    assert added["snippet"] == MISSED, "the selected text, verbatim"
    assert added["origin"] == "deck_analyst" and added["status"] == "pending"
    assert added["sources"][0]["file"] == "testco_board.pptx" and added["sources"][0]["slide"] == 4
    listed = next(c for c in client.get(f"/api/audits/{AUDIT}/decks").json()["candidates"] if c["id"] == added["id"])
    assert listed["sources"][0]["slide"] == 4


def test_add_from_deck_takes_a_stored_line_only(api):  # noqa: F811
    client, db = api
    _deck(db)
    assert client.post(f"/api/audits/{AUDIT}/decks/{DECK_ID}/add-from-deck", json={"page": 4, "ref": "b0"}).status_code == 400, \
        "b0 is on slide 3"
    assert client.post(f"/api/audits/{AUDIT}/decks/{DECK_ID}/add-from-deck",
                       json={"page": 4, "ref": "b1", "text": "ARR €9M"}).status_code == 422, "no free claim text"
    assert client.get(f"/api/audits/{AUDIT}/decks/other-deck/pages/4").status_code == 404


# --- section 2: required fields ------------------------------------------------------------------------------------------------

def test_a_claim_with_no_period_is_not_matched_until_its_period_is_set():
    row = run_claim({"claim_type": "sales", "value": 45, "unit": "days", "currency": None, "snippet": "Sales cycle 45 days"})
    assert row["evidence_label"] == "Unverified" and "period" in row["required_unknown"]
    assert row["reason"] == "required field unknown: period; set it with Edit in the claims list"
    assert row["observed_value"] is None


def test_users_with_no_qualifier_need_their_population_and_registered_users_are_inconclusive():
    base = {"claim_type": "users", "value": 10000, "unit": "users", "currency": None, "target_date": "2024-02",
            "period_text": "Feb 2024", "snippet": "10,000 users in Feb 2024"}
    unknown = run_claim(base)
    assert unknown["evidence_label"] == "Unverified" and unknown["required_unknown"] == ["population"]
    registered = run_claim({**base, "population": "registered"})
    assert registered["evidence_label"] == "Inconclusive"
    assert registered["reason"] == "population differs: the claim counts registered users; the figure shown counts paying customers"
    paying = run_claim({**base, "value": 5, "population": "paying"})
    assert (paying["metric"], paying["evidence_label"]) == ("Customer count", "Verified")


def test_add_from_deck_reads_the_fields_of_the_line_or_makes_an_other_figure_and_refuses_a_long_passage(api):  # noqa: F811
    client, db = api
    _deck(db)
    deck = db[decks.TEXT_COLLECTION].docs[-1]
    deck["blocks"] += [{"slide": 5, "kind": "text", "text": "ARR of €2.4M in Dec 2023", "box": 3},
                       {"slide": 5, "kind": "text", "text": "x" * 301, "box": 4}]
    url = f"/api/audits/{AUDIT}/decks/{DECK_ID}/add-from-deck"
    parsed = client.post(url, json={"page": 5, "ref": "b3"}).json()
    assert (parsed["claim_type"], parsed["value"], parsed["currency"], parsed["target_date"]) == ("revenue", 2400000, "EUR", "2023-12")
    missed = client.post(url, json={"page": 4, "ref": "b1"}).json()
    assert (missed["claim_type"], missed["value"]) == ("unknown", None), "no figure: Other, typed by the analyst"
    long = client.post(url, json={"page": 5, "ref": "b4"})
    assert long.status_code == 400 and "Select a shorter passage (300 characters at most)" in long.text
    reading = client.get(f"/api/audits/{AUDIT}/claims").json()
    assert all(r["claim_id"] != missed["id"] for r in reading["register"]), "an Other figure is not in the register"


def test_a_growth_basis_set_in_the_editor_replaces_the_one_set_on_the_register_row(api):  # noqa: F811
    client, db = api
    _add(db, id="g1", claim_type="revenue_growth", value=10, unit="%", currency=None, target_date="2024-02", period_text="Feb 2024",
         snippet="Revenue up 10% in Feb 2024")
    assert client.put(f"/api/audits/{AUDIT}/claims/g1", json={"growth_basis": "yoy"}).status_code == 200
    assert _row(client, "g1")["growth_basis"] == "yoy"
    r = client.put(f"/api/audits/{AUDIT}/decks/candidates/g1", json={"growth_basis": "mom", "reason": "deck_context"})
    assert r.status_code == 200, r.text
    log = r.json()["edit_log"][-1]
    assert (log["field"], log["previous"], log["value"], log["reason"]) == ("growth_basis", "yoy", "mom", "deck_context"), "as shown"
    assert _row(client, "g1")["growth_basis"] == "mom"
