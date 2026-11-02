"""A space, no-break space, thin space, "." or "'" between digit groups of exactly three digits is a thousands separator, never a scale; only a suffix
attached to the number (K, M, MM, Bn, B) multiplies (deck_reading rule 10). A grouping that is not three digits ("1 25 000") is no separator
pattern: it is never merged into one number."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.decks import claims  # noqa: E402
from app.structures import page_check, verify  # noqa: E402
from test_page_check import claim, grid, line  # noqa: E402

SEPARATED = ["650 000 000", "650 000 000", "650 000 000", "650 000 000", "650.000.000", "650'000'000", "650’000’000"]


@pytest.mark.parametrize("text", SEPARATED)
def test_a_figure_with_three_digit_groups_is_one_number_in_full_units(text):
    found = verify.figures(f"{text} devices")
    assert [f["readings"][0][0] for f in found] == [650_000_000], text
    assert [n["value"] for n in claims.find_numbers(f"{text} devices", [])] == [650_000_000], text


@pytest.mark.parametrize("text", SEPARATED)
def test_the_checker_matches_the_value_with_no_scale(text):
    g = grid([line(1, "Reach", 1, next_to=["r2c1"]), line(2, f"{text} devices", 1, next_to=["r1c1"])])
    out = page_check.check(g, [claim("r2c1", 650_000_000, metric="other", unit="count")])["items"][0]
    assert out["status"] == page_check.MATCHED and out["value"] == 650_000_000, text


def test_only_a_suffix_attached_to_the_number_multiplies():
    assert [f["readings"][0][0] for f in verify.figures("650 000M")] == [650_000 * 10 ** 6]
    assert [n["value"] for n in claims.find_numbers("650 000M", [])] == [650_000 * 10 ** 6]
    assert [f["readings"][0][0] for f in verify.figures("1 250 000")] == [1_250_000]


def test_a_grouping_that_is_not_three_digits_is_not_a_separator_pattern():
    values = [f["readings"][0][0] for f in verify.figures("1 25 000")]
    assert 125_000 not in values and 1_025_000 not in values, "never merged into one number"
    assert values == [1, 25_000], "left as read, group by group"
    assert 12_345_678 not in [f["readings"][0][0] for f in verify.figures("1.23.456")]


def test_one_dot_before_three_digits_stays_ambiguous():
    f, = verify.figures("2.500")
    assert [r[0] for r in f["readings"]] == [2.5, 2500]
