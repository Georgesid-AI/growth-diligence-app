"""Issue #148, from the artefact (a bar chart "Revenue forecast 2022 -2024" with three bars over the axis labels 2022, 2023, 2024: the rules
read gave the 2024 bar FY2022 from the heading's first year, the panel read dated one bar and not its neighbour, and a claim with no
date showed "Verified" in the deck list). One failing test per point, synthetic page only (CLAUDE.md rules 13 and 15):

a a heading with a year range gives no single year to a figure under it · b a row of figures over a row of year labels takes its years
by position in the rules read · c the same in the panel read, assigned by code after the model's labels · d the middle bar is a claim ·
e a claim with no readable period is Unverified "Period not read – set it in the claim row" in the register. (Why the deck list still says
Verified for it, and what changing that would move, is in the PR: the badge is the AI reading's, not the register's.)"""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from claim_matching_support import engine_results  # noqa: E402,F401
from pdf_support import pdf_page  # noqa: E402
from test_claim_matching import RUNS, results_for, settings  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app.decks import claims  # noqa: E402
from app.decks.parser import parse_deck  # noqa: E402
from app.structures import candidate_from_item, items, verify  # noqa: E402

BARS = ("€1.48MM", "€3.39MM", "€5.3MM")
YEARS = ("2022", "2023", "2024")
VALUES = (1480000, 3390000, 5300000)
OFFSET = (100, 255, 410)          # the bars sit beside their year labels, not over them: no label shares their width
LABELS = (150, 300, 450)


def deck(title="Revenue forecast", bars=BARS, years=YEARS, at=OFFSET, label_at=LABELS):
    texts = [(50, 560, 20, title)]
    texts += [(x, 380 + 20 * i, 12, bar) for i, (bar, x) in enumerate(zip(bars, at))]
    texts += [(x, 340, 12, year) for year, x in zip(years, label_at)]
    return parse_deck(pdf_page(texts, []), "deck.pdf")


def found(title="Revenue forecast", **kw):
    return claims.detect_candidates(deck(title, **kw)["blocks"], "deck.pdf")


def dated(candidates):
    return {c["value"]: c["target_date"] for c in candidates if c["value"] is not None}


def register_of(candidates):
    for n, c in enumerate(candidates, 1):
        c.update(id=f"c{n}", status="approved", file="deck.pdf", order=n)
        claims.resolve_period(c, 12)
    run = RUNS["A"]
    return cm.build_register(candidates, results_for(run), settings(run))


# ---------------------------------------------------------------------------
# a. A heading with a year range gives no single year
# ---------------------------------------------------------------------------
RANGES = ("Revenue forecast 2022–2024", "Revenue forecast 2022 -2024", "Revenue forecast FY22–24", "Revenue forecast 2022 to 2024")


@pytest.mark.parametrize("title", RANGES)
def test_a_a_heading_with_a_year_range_gives_no_single_year_to_a_figure_under_it(title):
    got = found(title, years=(), label_at=())
    assert dated(got) == dict.fromkeys(VALUES), dated(got)


@pytest.mark.parametrize("title", RANGES)
def test_a_the_range_is_no_figure_of_its_own(title):
    assert sorted(c["value"] for c in found(title, years=(), label_at=())) == sorted(VALUES)


@pytest.mark.parametrize("title", RANGES)
def test_a_a_figure_under_such_a_heading_takes_its_own_year_only(title):
    own = parse_deck(pdf_page([(50, 560, 20, title), (50, 500, 12, "Revenue in 2023 of €3.39MM")], []), "deck.pdf")["blocks"]
    assert dated(claims.detect_candidates(own, "deck.pdf")) == {3390000: "2023"}


@pytest.mark.parametrize("title", ("Revenue forecast 2023", "Revenue forecast FY2023"))
def test_a_a_heading_with_one_year_still_dates_the_figure(title):
    got = found(title, years=(), label_at=(), bars=BARS[:1], at=OFFSET[:1])
    assert set(dated(got).values()) <= {"2023"} and None not in dated(got).values(), dated(got)


@pytest.mark.parametrize("text", ("2022–2024", "2022 -2024", "FY22–24", "2022 to 2024", "FY2022-2024"))
def test_a_a_year_range_is_a_date_with_no_period(text):
    assert claims.find_dates(text) == [] and claims.find_dates(text, table=True) == [], text
    assert claims.period_cell(text) is None
    assert claims.find_numbers(text, claims.find_dates(text)) == []


@pytest.mark.parametrize("text, date", (("2025-03", "2025-03"), ("FY2024/25", "2025"), ("2023", "2023"), ("FY24", "2024")))
def test_a_what_is_one_period_stays_one(text, date):
    assert [d["date"] for d in claims.find_dates(text, table=True)] == [date]


# ---------------------------------------------------------------------------
# b. Bars take the year of their position in the rules read
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("title", ("Revenue forecast", "Revenue forecast 2022 -2024", "Revenue forecast 2022–2024"))
def test_b_three_bars_over_a_row_of_year_labels_take_2022_2023_2024_by_position(title):
    assert dated(found(title)) == dict(zip(VALUES, YEARS))


def test_b_the_bars_are_ordered_by_their_place_not_by_their_height_or_their_order_in_the_file():
    got = found(bars=BARS[::-1], at=OFFSET[::-1])
    assert dated(got) == dict(zip(VALUES, YEARS))


def test_b_a_bar_over_its_own_label_keeps_it():
    assert dated(found(at=LABELS)) == dict(zip(VALUES, YEARS))


def test_b_the_year_is_the_labels_not_the_headings():
    got = found("Revenue forecast 2019 -2021")
    assert dated(got) == dict(zip(VALUES, YEARS))
    assert [c["period_text"] for c in got] == list(YEARS)


def test_b_when_the_counts_differ_no_bar_takes_a_year_by_position():
    got = found("Revenue forecast 2022 -2024", years=YEARS + ("2025",), label_at=LABELS + (600,))
    assert dated(got) == dict.fromkeys(VALUES), dated(got)


# ---------------------------------------------------------------------------
# c. The panel read: code assigns the years by position after the model's labels
# ---------------------------------------------------------------------------
def panel(**kw):
    structure, = [s for s in deck(**kw)["structures"] if s["type"] == "kpi_panel"]
    return structure


def read(structure, periods):
    """verify.verify over the model's labels: every figure revenue, with the periods the model gave (a list in the order of the items)."""
    listed = items.list_items(structure)
    labels = [{"item": item["id"], "metric": "revenue", "period": period, "unit": "EUR", "unit_other": None,
               "actual_or_forecast": "forecast"} for item, period in zip(listed["items"], periods)]
    return verify.verify(structure, listed, labels, (), 12, "suggest")["items"]


def by_value(checked):
    return {round(i["value"]): i for i in checked}


@pytest.mark.parametrize("given", ([None] * 3, ["2024", "2023", "2022"], ["2022", None, "2024"]), ids=("none", "reversed", "one-missing"))
def test_c_the_panel_items_take_the_year_of_their_position_whatever_the_model_gave(given):
    checked = by_value(read(panel(), given))
    assert {v: checked[v]["period"] for v in VALUES} == dict(zip(VALUES, YEARS)), checked
    assert {checked[v]["status"] for v in VALUES} == {verify.VERIFIED}


def test_c_a_year_the_model_gave_against_its_position_is_a_correction():
    checked = by_value(read(panel(), ["2022", "2022", "2022"]))
    assert [checked[v]["period"] for v in VALUES] == list(YEARS)
    assert [checked[v]["checks"]["period_corrected"] for v in VALUES] == [False, True, True]


def test_c_the_approval_rows_carry_the_year_and_every_bar_is_a_row():
    structure = panel(title="Revenue forecast 2022 -2024")
    rows = [candidate_from_item(i, structure, {"file": "deck.pdf", "blocks": []}, "kpi_panel", 12) for i in read(structure, [None] * 3)]
    assert {r["value"]: r["target_date"] for r in rows} == dict(zip(VALUES, YEARS))
    assert {r["ai_label"] for r in rows} == {"Verified"}


def test_c_when_the_counts_differ_the_panel_dates_no_bar_by_position():
    checked = by_value(read(panel(years=YEARS + ("2025",), label_at=LABELS + (600,)), [None] * 3))
    assert {v: checked[v]["period"] for v in VALUES} == dict.fromkeys(VALUES)


# ---------------------------------------------------------------------------
# d. The middle bar is a claim
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("middle", ("€3.39MM", "€3.4MM", "€3.0MM"))
def test_d_the_middle_bar_is_a_claim_in_the_rules_read(middle):
    got = found(bars=(BARS[0], middle, BARS[2]))
    assert len([c for c in got if c["claim_type"] == "revenue"]) == 3, [(c["claim_type"], c["value"]) for c in got]


@pytest.mark.parametrize("middle", ("€3.39MM", "€3.4MM"))
def test_d_the_middle_bar_is_an_item_of_the_panel(middle):
    assert len(items.list_items(panel(bars=(BARS[0], middle, BARS[2])))["items"]) == 3


# ---------------------------------------------------------------------------
# e. A claim with no readable period is Unverified
# ---------------------------------------------------------------------------
def test_e_a_bar_with_no_readable_period_is_unverified_period_not_read_in_the_register():
    candidates = found(years=(), label_at=())
    assert dated(candidates) == dict.fromkeys(VALUES)
    rows = [r for r in register_of(candidates) if r["claim_type"] == "revenue"]
    assert len(rows) == 3
    assert {(r["evidence_label"], r["reason"]) for r in rows} == {("Unverified", cm.PERIOD_NOT_READ)}
