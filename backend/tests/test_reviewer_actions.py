# ruff: noqa: F811, F401
"""What a reviewer card offers (board-pack layout fix, item 7). A doubt that implies a correction offers it as the action ("Set currency GBP",
"Relabel as bookings") beside "Keep as read"; a doubt that implies none is a note with no button. "Use the reader" alone is never the only option.
The correction is a structured `fix` on the finding that code checks against closed lists and against the item it cites; a decision writes a dated
override record and never edits the reading."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app import cards, readings  # noqa: E402
from app.llm import schemas  # noqa: E402
from upload_support import AUDIT  # noqa: E402
from test_reviewer import ReviewRouter, cards_of, finding, map_with, review, start  # noqa: E402
from test_sheet_reader_flow import SHEET, flow  # noqa: E402

QUEUES_SHEET_READER = True      # tests/conftest.py: this module lets an upload queue the reader


def card_for(flow, fix, **over):
    start(flow, map_with("revenue"), again=map_with("revenue"), review={"findings": [finding(fix=fix, **over)]})
    review(flow)
    (card,) = cards_of(flow)
    return card


def test_the_finding_schema_takes_an_optional_fix_and_nothing_else_in_it():
    base = finding()
    assert schemas.ReviewFinding.model_validate(base).fix is None
    assert schemas.ReviewFinding.model_validate({**base, "fix": {"field": "currency", "value": "GBP"}}).fix.value == "GBP"
    with pytest.raises(Exception):
        schemas.ReviewFinding.model_validate({**base, "fix": {"field": "value", "value": "1"}})
    with pytest.raises(Exception):
        schemas.ReviewFinding.model_validate({**base, "fix": {"field": "currency", "value": "GBP", "why": "x"}})


def test_a_currency_doubt_offers_set_currency_beside_keep_as_read(flow):
    card = card_for(flow, {"field": "currency", "value": "GBP"})
    assert card["actions"] == ["apply_fix", "use_reader"]
    assert card["fix"]["label"] == "Set currency GBP" and card["fix"]["old"] == "EUR" and card["fix"]["value"] == "GBP"


def test_a_role_doubt_offers_relabel_as(flow):
    card = card_for(flow, {"field": "role", "value": "bookings"})
    assert card["actions"] == ["apply_fix", "use_reader"] and card["fix"]["label"] == "Relabel as bookings"


def test_applying_the_correction_writes_one_override_and_never_edits_the_reading(flow):
    card = card_for(flow, {"field": "currency", "value": "GBP"})
    stored = flow.db[readings.READINGS].docs[0]["file_map"]["sheets"][0]["rows"][1]["currency"]
    done = flow.post(f"/api/audits/{AUDIT}/cards/{card['id']}", json={"action": "apply_fix"})
    assert done.status_code == 200 and done.json()["decision"]["action"] == "apply_fix"
    (override,) = flow.db[readings.OVERRIDES].docs
    assert (override["path"], override["old"], override["new"], override["who"]) == ("sheets.0.rows.1.currency", "EUR", "GBP", "analyst")
    assert flow.db[readings.READINGS].docs[0]["file_map"]["sheets"][0]["rows"][1]["currency"] == stored == "EUR"
    effective = readings.effective(flow.db[readings.READINGS].docs[0]["file_map"], flow.db[readings.OVERRIDES].docs)
    assert effective["sheets"][0]["rows"][1]["currency"] == "GBP"


def test_keeping_the_reading_overrides_nothing(flow):
    card = card_for(flow, {"field": "currency", "value": "GBP"})
    assert flow.post(f"/api/audits/{AUDIT}/cards/{card['id']}", json={"action": "use_reader"}).status_code == 200
    assert not flow.db[readings.OVERRIDES].docs


@pytest.mark.parametrize("fix", [
    None,
    {"field": "currency", "value": "ZZZ"},                 # not a currency of the list
    {"field": "role", "value": "not_a_role"},              # not a role of the list
    {"field": "currency", "value": "EUR"},                 # what the reading already says is no correction
    {"field": "metric", "value": "nonsense"},
])
def test_a_doubt_with_no_valid_correction_is_a_note_with_no_button(flow, fix):
    card = card_for(flow, fix)
    assert card["actions"] == [] and card.get("fix") is None
    assert flow.post(f"/api/audits/{AUDIT}/cards/{card['id']}", json={"action": "use_reader"}).status_code == 400
    assert flow.post(f"/api/audits/{AUDIT}/cards/{card['id']}", json={"action": "apply_fix"}).status_code == 400


def test_a_correction_on_a_finding_that_cites_two_rows_is_a_note(flow):
    card = card_for(flow, {"field": "currency", "value": "GBP"}, refs=[{"file": 1, "sheet": SHEET, "cell": "B10:M10", "page": None},
                                                                      {"file": 1, "sheet": SHEET, "cell": "B4:M4", "page": None}])
    assert card["actions"] == [], "a fix names one item; two cited items leave it ambiguous"
