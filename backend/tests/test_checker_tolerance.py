"""Checker tolerance and two guards (synthetic pages only; claim-matching.md, amended 2026-10-23, and chat-upload.md section 28).

1. Cell tolerance: a value that is not in the cited cell but is in another cell of the same page is "Matched to page", flagged
   "cell corrected", value_cell set to the cell found (the nearest when several hold it; page furniture never counts).
2. Sign guard: a negative value whose value cell shows no minus sign and no loss / decline / decrease word is flagged "sign not on page".
3. Null guard: a claim with no value that is not a date claim (metric product with a period) is dropped at validation.
4. A "cell corrected" claim counts as matched in the panel's label.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("pdfplumber")

from test_checker import AUDIT, LINES, TITLE, _page_db, claim, deck, one  # noqa: E402
from test_structure_reading import t  # noqa: E402

from app import structures  # noqa: E402
from app.decks import CANDIDATES_COLLECTION  # noqa: E402
from app.llm import gateway  # noqa: E402
from app.llm.schemas import PAGE_CLAIMS  # noqa: E402
from app.structures import checker, page_check  # noqa: E402

CORRECTED = "cell corrected"
SIGN = "sign not on page"


# ---------------------------------------------------------------------------
# 1. Cell tolerance
# ---------------------------------------------------------------------------
def test_a_value_in_another_cell_of_the_page_is_matched_there_and_flagged_cell_corrected():
    parsed = deck([TITLE, *LINES])
    found = one(parsed, claim("p1r4c1", 150_000))                       # cited r4c1 ("97% margins"); the value stands in r3c1
    assert found["status"] == "matched" and found["flags"] == [CORRECTED]
    assert found["value_cell"] == "r3c1" and found["value"] == 150_000 and found["checks"]["value"] is True
    assert page_check.label(found["status"]) == "Matched to page"
    right = one(parsed, claim("p1r3c1", 150_000))
    assert right["status"] == "matched" and right["flags"] == [] and right["value_cell"] == "r3c1", "a hit in the cited cell is not corrected"
    assert one(parsed, claim("p1r3c1", 999_000))["flags"] == [checker.VALUE_NOT_ON_PAGE], "a value on no cell stays unmatched and flagged"
    assert one(parsed, claim("p1r3c1", 999_000))["status"] == "unmatched"


@pytest.mark.parametrize("value, unit, metric", [(27_000, "EUR", "revenue"), (3, "%", "market_share"), (27, "%", "market_share"),
                                                 (2_300, "EUR", "revenue")])
def test_a_cell_holding_several_figures_matches_any_one_of_them(value, unit, metric):
    parsed = deck([TITLE, (50, 500, 12, "€27K 3% 27% €2.3K"), (50, 460, 12, "Founded by two engineers")])
    item = one(parsed, claim("p1r3c1", value, unit=unit, metric=metric))
    assert item["status"] == "matched" and item["flags"] == [CORRECTED] and item["value_cell"] == "r2c1"
    same = one(parsed, claim("p1r2c1", value, unit=unit, metric=metric))
    assert same["status"] == "matched" and same["flags"] == [] and same["value_cell"] == "r2c1"


def test_k_m_mm_and_bn_are_expanded_and_separators_and_symbols_ignored_when_looking_in_other_cells():
    parsed = deck([TITLE, (50, 500, 12, "Revenue of 1.5MM"), (50, 480, 12, "Sales of $2Bn"), (50, 460, 12, "ARR 12,500"),
                   (50, 440, 12, "Nothing here")])
    for value, unit in ((1_500_000, None), (2_000_000_000, "USD"), (12_500, None)):
        item = one(parsed, claim("p1r5c1", value, unit=unit))
        assert item["status"] == "matched" and item["flags"] == [CORRECTED], value
        assert item["value_cell"] in {"r2c1", "r3c1", "r4c1"}


def test_with_several_cells_holding_the_value_the_one_nearest_the_cited_cell_is_taken():
    texts = [TITLE, (50, 500, 12, "$150,000 revenue"), (50, 480, 12, "Filler one"), (50, 460, 12, "Filler two"), (50, 440, 12, "$150,000 revenue")]
    parsed = deck(texts)
    assert one(parsed, claim("p1r4c1", 150_000))["value_cell"] == "r5c1", "r5 is one row away, r2 two"
    assert one(parsed, claim("p1r3c1", 150_000))["value_cell"] == "r2c1", "r2 is one row away, r5 two"
    assert one(parsed, claim("p1r4c1", 150_000))["flags"] == [CORRECTED]


def test_page_furniture_never_counts_as_the_cell_holding_the_value():
    footer = deck([TITLE, (50, 500, 12, "800 Paying Users"), (50, 15, 10, "Confidential $150,000")])      # footer band: the bottom 7%
    header = deck([(50, 600, 10, "Confidential $150,000"), TITLE, (50, 500, 12, "800 Paying Users")])      # header band: the top 5%
    number = deck([TITLE, (50, 500, 12, "800 Paying Users"), (400, 300, 12, "1")])                         # the page's own number
    for parsed, value in ((footer, 150_000), (header, 150_000), (number, 1)):
        item = one(parsed, claim("p1r2c1", value, unit="count" if value == 1 else "USD"))
        assert item["status"] == "unmatched" and checker.VALUE_NOT_ON_PAGE in item["flags"] and CORRECTED not in item["flags"]
        assert item["value_cell"] == "r2c1", "the claim stays on the cell the model cited"


def test_a_corrected_claim_is_checked_on_the_cell_found():
    """The unit is read from the cell the value was found in, not from the one the model cited (a currency assumed would flag it)."""
    parsed = deck([TITLE, (50, 500, 12, "Revenue of \u20ac150,000"), (50, 460, 12, "Margin 40%")])
    item = one(parsed, claim("p1r3c1", 150_000, unit="EUR"))
    assert item["status"] == "matched" and item["value_cell"] == "r2c1" and item["flags"] == [CORRECTED] and item["checks"]["unit"] is True


# ---------------------------------------------------------------------------
# 2. Sign guard
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text, flagged", [
    ("EBITDA (1,200)", True),                    # brackets read either way; the model chose negative; no minus, no word
    ("EBITDA -1,200", False),
    ("EBITDA \u20131,200", False),                # an en dash is a minus sign too
    ("Net loss (1,200)", False),
    ("EBITDA decline (1,200)", False),
    ("Decrease in EBITDA (1,200)", False),
])
def test_a_negative_value_needs_a_minus_sign_or_a_loss_word_in_its_cell(text, flagged):
    parsed = deck([TITLE, (50, 500, 12, text)])
    item = one(parsed, claim("p1r2c1", -1_200, metric="net_profit", unit=None))
    assert item["status"] == "matched", "the claim is kept"
    assert (SIGN in item["flags"]) is flagged
    assert flagged is False or item["flags"] == [SIGN]


def test_a_positive_value_is_never_sign_flagged():
    parsed = deck([TITLE, (50, 500, 12, "Profit 1,200")])
    assert one(parsed, claim("p1r2c1", 1_200, metric="net_profit", unit=None))["flags"] == []


# ---------------------------------------------------------------------------
# 3. Null guard (the gateway's validation)
# ---------------------------------------------------------------------------
def _reply(*claims_):
    return json.dumps({"type": PAGE_CLAIMS, "claims": list(claims_)})


def test_a_claim_with_no_value_is_dropped_at_validation_unless_it_is_a_date_claim(caplog):
    text = "p5r1c1: Traction\np5r2c1: Launch\np5r3c1: Paying users"
    base = claim("p5r2c1", None, metric="customers", unit=None)
    date_claim = claim("p5r2c1", None, metric="product", unit=None, period="2026-Q3")
    product_without_period = claim("p5r2c1", None, metric="product", unit=None)
    valued = claim("p5r3c1", 800, metric="customers", unit="count")
    with caplog.at_level(logging.INFO):
        out = gateway.parse_page_reply(_reply(base, date_claim, product_without_period, valued), text)
    assert [(c.metric, c.value, c.period) for c in out.claims] == [("product", None, "2026-Q3"), ("customers", 800, None)]
    lines = [r.getMessage() for r in caplog.records if "claim rejected" in r.getMessage()]
    assert lines == ["page 5: claim rejected (no value)"] * 2
    assert "Launch" not in caplog.text and "Paying users" not in caplog.text


def test_a_dropped_claim_never_reaches_the_panel(monkeypatch, caplog):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    parsed = deck([TITLE, *LINES])
    db = _page_db(parsed)
    reply = _reply(claim("p1r2c1", 800, metric="customers", unit="count"), claim("p1r3c1", None, metric="revenue"))
    adapter = t.FakeAdapter(replies=[reply])
    with caplog.at_level(logging.INFO):
        status = asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert status == "read"
    assert [r["claim_type"] for r in db[CANDIDATES_COLLECTION].docs] == ["customers"]
    assert "page 1: claim rejected (no value)" in caplog.text


# ---------------------------------------------------------------------------
# 4. The panel's label
# ---------------------------------------------------------------------------
def test_a_cell_corrected_claim_counts_as_matched_in_the_row_the_panel_shows(monkeypatch):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    parsed = deck([TITLE, *LINES])
    db = _page_db(parsed)
    reply = _reply(claim("p1r4c1", 150_000, basis="projection"))
    adapter = t.FakeAdapter(replies=[reply])
    asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    row, = db[CANDIDATES_COLLECTION].docs
    assert row["ai_status"] == "matched" and row["ai_label"] == "Matched to page" and row["flags"] == [CORRECTED]
    assert row["cell"] == "r3c1" and row["value"] == 150_000
    stored, = db[gateway.STRUCTURES_COLLECTION].docs
    assert stored["items"]["claims"][0]["status"] == "matched" and stored["items"]["claims"][0]["value_cell"] == "r3c1"
    assert stored["items"]["claims"][0]["model_cell"] == "r4c1"
    assert "margins" not in json.dumps(stored) and "Paying Users" not in json.dumps(stored), "cell ids only, no deck text (rules 14, 17)"
