"""A ruled PDF table whose value cell holds all of a row's amounts (finding A of 20 Oct, after issue #136). Built from the shape of the
artefact (table 1, row 2, col 2: the label in col 1, four amounts separated by spaces and currency signs in col 2; the header row's col 2
holds "Q1 2021 Q2 2021 Q3 2021 Q4 2021"), drawn as a synthetic PDF and read by the real PDF reader (CLAUDE.md rules 13 and 15): the
tests of issue #136 start from hand-made cells, these start from the file.

Task 1: the reader returns exactly that shape, with as many period tokens in the header cell as amounts in the value cell, and each
amount takes the period of its own position · Task 2: with N periods and N amounts they pair in order, one claim per amount; with
different counts every amount has no period and reads "Period unclear – confirm"."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from claim_matching_support import engine_results  # noqa: E402,F401
from pdf_support import pdf_page, ruled_table  # noqa: E402
from test_claim_matching import RUNS, results_for  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app.decks import claims  # noqa: E402
from app.decks.parser import parse_deck  # noqa: E402

TITLE = "2021 COMPARISON SALES vs RECOGNISED REVENUE"
QUARTERS = ("Q1 2021", "Q2 2021", "Q3 2021", "Q4 2021")
ACV = ("€ 120,000.00", "€ 156,000.00", "€ 130,000.00", "€ 140,000.00")
REV = ("€ 100,000.00", "€ 125,000.00", "€ 127,000.00", "€ 148,000.00")


def deck(periods, acv=ACV, rev=REV):
    texts, rects = ruled_table([("", " ".join(periods)), ("Sales (Annual Contracted Value)", " ".join(acv)),
                                ("Recognised Revenue", " ".join(rev))])
    return parse_deck(pdf_page([(50, 560, 20, TITLE), *texts], rects), "deck.pdf")


def row_series(parsed, value):
    found = claims.detect_candidates(parsed["blocks"], "deck.pdf")
    c = next(c for c in found if any(i["value"] == value for i in c.get("by_period") or ()))
    return c, [(i["value"], i["period_text"], i["period_start"], i["period_end"]) for i in c["by_period"]]


def test_1_the_reader_returns_the_two_column_shape_with_as_many_periods_as_amounts():
    cells = {(b["row"], b["col"]): b["text"] for b in deck(QUARTERS)["blocks"] if b["kind"] == "table"}
    assert set(cells) == {(1, 2), (2, 1), (2, 2), (3, 1), (3, 2)}          # no col 1 in the header row, no split cell
    assert cells[(2, 1)] == "Sales (Annual Contracted Value)"
    header, value = cells[(1, 2)], cells[(2, 2)]
    assert len(claims.find_dates(header, table=True)) == len(claims.find_numbers(value, claims.find_dates(value))) == 4
    assert value.count("€") == 4


def test_1_each_amount_of_the_cell_takes_the_period_of_its_position_and_none_takes_the_first():
    _, series = row_series(deck(QUARTERS), 156000)
    assert series == [(120000, "Q1 2021", "2021-01-01", "2021-03-31"), (156000, "Q2 2021", "2021-04-01", "2021-06-30"),
                      (130000, "Q3 2021", "2021-07-01", "2021-09-30"), (140000, "Q4 2021", "2021-10-01", "2021-12-31")]
    assert [p for _, p, _, _ in row_series(deck(QUARTERS), 148000)[1]] == list(QUARTERS)


@pytest.mark.parametrize("periods", [QUARTERS[:3], QUARTERS + ("Q1 2022",)])
def test_2_with_different_counts_no_amount_has_a_period_and_each_reads_period_unclear(periods):
    c, series = row_series(deck(periods), 125000)
    assert series == [(v, None, None, None) for v in (100000, 125000, 127000, 148000)]
    assert all(i["period_unclear"] for i in c["by_period"])
    rows = cm.build_register([{**c, "id": "c1", "status": "approved"}], results_for(RUNS["A"]),
                             {"fiscal_year_end": 12, "reporting_currency": "EUR", "fx": {"EUR": 1.0}})
    assert len(rows) == 4
    assert {(r["evidence_label"], r["reason"], r["period"]) for r in rows} == {("Unverified", cm.PERIOD_UNCLEAR, None)}
    assert cm.PERIOD_UNCLEAR == "Period unclear – confirm"


def test_2_with_matching_counts_the_register_has_one_claim_per_amount_with_its_own_period():
    c, _ = row_series(deck(QUARTERS), 125000)
    rows = cm.build_register([{**c, "id": "c1", "status": "approved"}], results_for(RUNS["A"]),
                             {"fiscal_year_end": 12, "reporting_currency": "EUR", "fx": {"EUR": 1.0}})
    assert [r["period"] for r in rows] == list(QUARTERS)
    assert [r["claimed_value"] for r in rows] == [100000, 125000, 127000, 148000]
    assert all(r["reason"] != cm.PERIOD_UNCLEAR for r in rows)
