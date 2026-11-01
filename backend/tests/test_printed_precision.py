"""The precision a deck figure is printed at (PR 4e, item 3): read from the page's text, from the digits and the K/M suffix. Synthetic pages only."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import deck_figures, role_engine  # noqa: E402


def page(*lines):
    return {"page_unit": "page", "blocks": [{"page": 3, "kind": "text", "text": t} for t in lines], "structures": []}


@pytest.mark.parametrize("text,value,expected", [
    ("Revenue $1.2M in 2025", 1_200_000, 100_000),
    ("Revenue $850K in 2025", 850_000, 1_000),
    ("Revenue $2M in 2025", 2_000_000, 1_000_000),
    ("ARR of 2.35 million", 2_350_000, 10_000),
    ("Revenue $1,234,567", 1_234_567, 0),
    ("Revenue 1 500 000 EUR", 1_500_000, 0),
])
def test_precision_comes_from_the_digits_and_the_suffix(text, value, expected):
    assert deck_figures.printed_precision(page(text), 3, value) == expected


def test_a_figure_not_found_on_the_page_has_no_assumed_rounding():
    assert deck_figures.printed_precision(page("Customers 120"), 3, 1_200_000) == 0
    assert deck_figures.printed_precision(page("Revenue $1.2M"), 3, None) == 0


def test_the_precision_has_a_unit_name():
    assert [role_engine.precision_unit(p) for p in (1_000, 100_000, 1_000_000)] == ["thousand", "hundred thousand", "million"]
