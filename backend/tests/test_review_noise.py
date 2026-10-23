"""Review tab noise (George, 2026-10-23; docs/specs/chat-upload.md section 28): synthetic pages only.

1/2 informational flags (the year label hint included) keep a claim in the main list · 3 "not a plan line" never fires for market,
pricing or use_of_funds · 4 a space is a thousands separator and a trailing rate suffix is ignored · 5 "use-of-funds share" does not
fire on a page with a raise cue · 6 a date claim is matched when its period is in the cited period cell."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("pdfplumber")

from test_checker import TITLE, bars, cell_of, claim, deck, one  # noqa: E402

from app.decks import claims  # noqa: E402
from app.structures import checker  # noqa: E402


def lines(*texts):
    return deck([TITLE, *[(50, 500 - 20 * n, 12, text) for n, text in enumerate(texts)]])


# 1 / 2 ----------------------------------------------------------------------------------------------------------------------
def test_the_year_label_hint_is_informational_and_a_claim_with_it_stays_in_the_main_list():
    flag = checker.year_label_flag("2022")
    assert claims.review_flags([flag]) == [] and checker.flagged({"flags": [flag]}) is False
    assert claims.review_flags([flag, checker.SIGN_NOT_ON_PAGE]) == [checker.SIGN_NOT_ON_PAGE]
    assert claims.review_flags(["year label below: Q3 2022"]) == ["year label below: Q3 2022"], "only the closed four-digit form"
    parsed = bars()
    first = cell_of(parsed, "€1.48MM")
    got = one(parsed, claim(f"p1{first}", 1_480_000, unit="EUR"))
    assert got["flags"] == [flag] and checker.flagged(got) is False


# 3 --------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("metric", ["market", "pricing", "use_of_funds"])
def test_not_a_plan_line_never_fires_for_market_pricing_or_use_of_funds(metric):
    parsed = lines("$2 billion global market opportunity")
    got = one(parsed, claim("p1r2c1", 2_000_000_000, metric=metric))
    assert checker.NOT_PLAN_LINE not in got["flags"]


def test_not_a_plan_line_still_fires_for_other_metrics():
    parsed = lines("$2 billion global market opportunity")
    assert checker.NOT_PLAN_LINE in one(parsed, claim("p1r2c1", 2_000_000_000, metric="revenue"))["flags"]


# 4 --------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, value, unit", [
    ("30 000 paying users", 30_000, None), ("7 753 000 annual revenue", 7_753_000, "EUR"), ("€ 2 000 000 annual revenue", 2_000_000, "EUR"),
    ("$30/year", 30, "USD"), ("$30/yr", 30, "USD"), ("$30/mo", 30, "USD"), ("$30/month", 30, "USD"), ("$3/video-hour", 3, "USD"),
    ("$30 per seat", 30, "USD"), ("€ 12 000/year", 12_000, "EUR")])
def test_a_space_is_a_thousands_separator_and_a_rate_suffix_is_ignored(text, value, unit):
    parsed = lines(text)
    got = one(parsed, claim("p1r2c1", value, unit=unit, metric="pricing" if "/" in text or "per" in text else "revenue"))
    assert got["status"] == "matched" and checker.VALUE_NOT_ON_PAGE not in got["flags"] and got["value"] == value


def test_a_space_between_a_year_and_a_number_is_no_thousands_separator():
    parsed = lines("2024 500 customers")
    got = one(parsed, claim("p1r2c1", 2_024_500, metric="customers", unit="count"))
    assert checker.VALUE_NOT_ON_PAGE in got["flags"]


# 5 --------------------------------------------------------------------------------------------------------------------------
def funds_page(extra=None):
    """A "Capital raise" slide (a funds cue of the rules read that is no raise cue of the list) with three shares."""
    texts = [(50, 560, 20, "Capital raise"), (50, 500, 12, "Marketing 40%"), (50, 480, 12, "Product development 35%"), (50, 460, 12, "Operations 25%")]
    return deck(texts + ([(50, 520, 12, extra)] if extra else []))


def cell_id(parsed, text):
    return "p1" + cell_of(parsed, text)


def test_use_of_funds_share_fires_as_a_review_flag_on_a_funds_page_with_no_raise_cue():
    parsed = funds_page()
    got = one(parsed, claim(cell_id(parsed, "Marketing 40%"), 40, metric="revenue_growth", unit="%"))
    assert checker.USE_OF_FUNDS in got["flags"] and checker.flagged(got) is True


@pytest.mark.parametrize("cue", ["use of funds", "Use of proceeds", "Funding ask", "Investment opportunity", "Equity investment",
                                 "Round size", "Our ask"])
def test_use_of_funds_share_does_not_fire_when_the_page_holds_a_raise_cue_in_any_cell(cue):
    parsed = funds_page(f"{cue}: EUR 2M")
    got = one(parsed, claim(cell_id(parsed, "Marketing 40%"), 40, metric="revenue_growth", unit="%"))
    assert checker.USE_OF_FUNDS not in got["flags"]


# 6 --------------------------------------------------------------------------------------------------------------------------
def test_a_date_claim_is_matched_to_page_when_its_period_is_in_the_cited_period_cell():
    parsed = deck([TITLE, (50, 500, 12, "Launch of the mobile app"), (50, 480, 12, "Q3 2026")])
    app, when = cell_id(parsed, "Launch of the mobile app"), cell_id(parsed, "Q3 2026")
    date = {**claim(app, None, metric="product", unit=None, period="2026-Q3", period_cell=when), "value": None}
    got = one(parsed, date)
    assert got["status"] == "matched" and checker.VALUE_NOT_ON_PAGE not in got["flags"]
    other = {**date, "period": "2027-Q1"}
    assert one(parsed, other)["status"] == "unmatched", "a period the cited cell does not state is not matched"
    no_period_cell = {**date, "period_cell": None}
    assert one(parsed, no_period_cell)["status"] == "unmatched"
