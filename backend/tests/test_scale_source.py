"""A scale from another cell applies only when that cell is a scale mark, never a sentence; a number printed in full with seven or more digits
takes no outside scale; an applied outside scale is recorded ("scale from <cell>"). Layout from a live audit: row header "64 towns with population
over 2 million" | "SOLUTIONS" | "650 000 000 devices" read as 650,000,000 x 10^6."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.structures import checker, page_check, verify  # noqa: E402
from test_page_check import claim, grid, line  # noqa: E402


def row_grid(left, middle, right):
    return grid([line(1, left, 1, col=1, next_to=["r1c2"]), line(1, middle, 1, col=2, next_to=["r1c1", "r1c3"]),
                 line(1, right, 1, col=3, next_to=["r1c2"])])


def read(g, value, metric="other", unit="count"):
    return page_check.check(g, [claim("r1c3", value, metric=metric, unit=unit)])["items"][0]


def test_a_prose_cell_with_a_scale_word_is_no_scale_source():
    item = read(row_grid("64 towns with population over 2 million", "SOLUTIONS", "650 000 000 devices"), 650000000)
    assert item["status"] == page_check.MATCHED and item["value"] == 650000000
    assert "scale_from" not in item


@pytest.mark.parametrize("text", ["in €k", "€M", "'000", "in millions", "(in thousands)", "£m", "(£000)", "€ Mio", "USD thousands", "Revenue £m", "Revenue (£'000)", "2026 (€'000)"])
def test_a_short_cell_that_is_a_scale_expression_alone_is_a_scale(text):
    assert verify.scale_source(text) is not None


@pytest.mark.parametrize("text", ["64 towns with population over 2 million", "Revenue in millions of euros", "SOLUTIONS", "m2 area",
                                  "Population over 2 million in the largest towns", "", "2 million", "Sales in the 2 million club"])
def test_prose_is_never_a_scale_source(text):
    assert verify.scale_source(text) is None


def test_a_scale_mark_beside_a_short_figure_applies_and_is_recorded():
    item = read(row_grid("€k", "Revenue", "1 250"), 1250000, "revenue", "EUR")
    assert item["status"] == page_check.MATCHED and item["value"] == 1250000 and item["scale_from"] == "r1c1"
    flags = checker.check(row_grid("€k", "Revenue", "1 250"), [claim("r1c3", 1250000, metric="revenue", unit="EUR")])["items"][0]["flags"]
    assert "scale from r1c1" in flags and checker.is_informational("scale from r1c1")


def test_no_outside_scale_applies_to_a_number_printed_in_full_with_seven_or_more_digits():
    for text, value in (("1,250,000", 1250000), ("1 250 000", 1250000), ("1250000", 1250000), ("650 000 000 devices", 650000000)):
        item = read(row_grid("in millions", "Revenue", text), value, "revenue", "EUR")
        assert item["value"] == value and "scale_from" not in item, text
    short = read(row_grid("in millions", "Revenue", "999 999"), 999999000000, "revenue", "EUR")
    assert short["scale_from"] == "r1c1", "six digits are not printed in full: the scale still applies"


def test_the_flag_is_in_the_checker_output_only_when_a_scale_was_applied():
    out = checker.check(row_grid("64 towns with population over 2 million", "SOLUTIONS", "650 000 000 devices"),
                        [claim("r1c3", 650000000, metric="other", unit="count")])["items"][0]
    assert not [f for f in out["flags"] if f.startswith("scale from")]
