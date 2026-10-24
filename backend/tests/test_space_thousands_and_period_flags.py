"""Space thousands in the parser, a year range is no period, growth dated to its start year (George, 2026-10-24; docs/specs/chat-upload.md
section 30): synthetic pages only.

1 a space between groups of three digits is a thousands separator in the parser too, three groups or more, and a year followed by a
number is still two figures · 3 a period cited from a cell that holds a year range gets the review flag "period is a range" ·
4 a growth claim whose period is the year after "from" or "compared to" in its own cell gets the review flag "growth dated to start year"."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("pdfplumber")

from test_checker import TITLE, cell_of, claim, deck, one  # noqa: E402

from app.decks import claims  # noqa: E402
from app.structures import checker  # noqa: E402


def lines(*texts):
    return deck([TITLE, *[(50, 500 - 20 * n, 12, text) for n, text in enumerate(texts)]])


def cite(parsed, text):
    return "p1" + cell_of(parsed, text)


# 1 --------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, values", [
    ("770 000 000", [770_000_000]), ("EUR 770 000 000 revenue", [770_000_000]), ("1 234 567 890 users", [1_234_567_890]),
    ("7 753 000 annual revenue", [7_753_000]), ("30 000 paying users", [30_000]), ("5 000 and 12 000", [5_000, 12_000]),
    ("2022 770 000 000", [770_000_000]), ("2024 500 customers", [500]), ("Q3 2024 12 500 customers", [12_500]),
    ("1 2345", [1, 2345])])
def test_the_parser_reads_a_space_as_a_thousands_separator_in_any_number_of_groups(text, values):
    assert [f["value"] for f in claims.figures(text)] == values


@pytest.mark.parametrize("sep", [" ", " "])
def test_a_no_break_space_is_a_thousands_separator_too(sep):
    assert [f["value"] for f in claims.figures(f"770{sep}000{sep}000 EUR")] == [770_000_000]


def test_a_year_followed_by_a_number_is_still_two_figures_in_the_checker_and_the_parser():
    parsed = lines("2024 500 customers")
    assert [f["value"] for f in claims.figures("2024 500 customers")] == [500]
    got = one(parsed, claim("p1r2c1", 2_024_500, metric="customers", unit="count"))
    assert checker.VALUE_NOT_ON_PAGE in got["flags"]
    assert one(parsed, claim("p1r2c1", 500, metric="customers", unit="count"))["status"] == "matched"


def test_the_deck_parser_reads_a_spaced_figure_as_one_candidate():
    parsed = lines("Revenue target 770 000 000 EUR in 2027")
    found = [c for c in claims.detect_candidates(parsed["blocks"], "deck.pdf") if c.get("value") is not None]
    assert [c["value"] for c in found] == [770_000_000]


def test_the_checker_matches_a_spaced_figure_of_three_groups():
    parsed = lines("EUR 770 000 000 revenue")
    got = one(parsed, claim("p1r2c1", 770_000_000, unit="EUR"))
    assert got["status"] == "matched" and got["value"] == 770_000_000 and checker.VALUE_NOT_ON_PAGE not in got["flags"]


# 3 --------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("range_text", ["2022 - 2024", "2019–2021", "2022 to 2024"])
def test_a_period_cited_from_a_year_range_is_flagged_as_a_range(range_text):
    parsed = lines("€5M revenue", range_text)
    got = one(parsed, claim(cite(parsed, "€5M revenue"), 5_000_000, unit="EUR", period="2023", period_cell=cite(parsed, range_text)))
    assert checker.PERIOD_IS_RANGE in got["flags"] and checker.flagged(got) is True
    assert checker.PERIOD_NOT_ON_PAGE not in got["flags"], "one flag says it: the range"
    assert got["period_cells"] == [], "the range is no period source"


def test_a_period_cited_from_a_single_year_is_not_flagged_as_a_range():
    parsed = lines("€5M revenue", "2023")
    got = one(parsed, claim(cite(parsed, "€5M revenue"), 5_000_000, unit="EUR", period="2023", period_cell=cite(parsed, "2023")))
    assert checker.PERIOD_IS_RANGE not in got["flags"]


def test_a_year_range_the_claim_does_not_cite_is_no_flag():
    parsed = lines("€5M revenue", "2022 - 2024")
    got = one(parsed, claim(cite(parsed, "€5M revenue"), 5_000_000, unit="EUR"))
    assert checker.PERIOD_IS_RANGE not in got["flags"]


def test_a_two_digit_pair_that_is_no_year_range_is_no_period_range():
    parsed = lines("€5M revenue", "5-10")
    got = one(parsed, claim(cite(parsed, "€5M revenue"), 5_000_000, unit="EUR", period="2023", period_cell=cite(parsed, "5-10")))
    assert checker.PERIOD_IS_RANGE not in got["flags"]


# 4 --------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["Revenue growth of 40% from 2021", "Growth of 40% compared to 2021", "Growth 40%, from FY2021",
                                  "Growth of 40% Compared To 2021"])
def test_a_growth_claim_dated_to_the_year_after_from_or_compared_to_is_flagged(text):
    parsed = lines(text)
    got = one(parsed, claim("p1r2c1", 40, metric="revenue_growth", unit="%", period="2021", period_cell="p1r2c1"))
    assert checker.GROWTH_START_YEAR in got["flags"] and checker.flagged(got) is True


def test_a_growth_claim_dated_to_another_year_than_the_start_year_is_not_flagged():
    parsed = lines("Revenue growth of 40% from 2021 to 2023")
    got = one(parsed, claim("p1r2c1", 40, metric="revenue_growth", unit="%", period="2023", period_cell="p1r2c1"))
    assert checker.GROWTH_START_YEAR not in got["flags"]


@pytest.mark.parametrize("metric", ["revenue", "customers", "arr"])
def test_a_claim_that_is_no_growth_claim_is_not_flagged_for_its_start_year(metric):
    parsed = lines("Revenue of 40% from 2021")
    got = one(parsed, claim("p1r2c1", 40, metric=metric, unit="%", period="2021", period_cell="p1r2c1"))
    assert checker.GROWTH_START_YEAR not in got["flags"]


def test_a_growth_claim_with_no_period_is_not_flagged_for_its_start_year():
    parsed = lines("Revenue growth of 40% from 2021")
    assert checker.GROWTH_START_YEAR not in one(parsed, claim("p1r2c1", 40, metric="revenue_growth", unit="%"))["flags"]


def test_the_two_new_flags_are_review_flags_not_informational():
    for flag in (checker.PERIOD_IS_RANGE, checker.GROWTH_START_YEAR):
        assert flag in checker.FLAGS and flag in checker.REVIEW_FLAGS and not claims.is_informational(flag)
    assert (checker.PERIOD_IS_RANGE, checker.GROWTH_START_YEAR) == ("period is a range", "growth dated to start year")
