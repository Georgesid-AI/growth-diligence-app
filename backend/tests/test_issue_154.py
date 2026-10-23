"""Issue #154, from the artefact (a live run, test deck page 11: a bar chart "Revenue forecast 2022 -2024" with €5.3MM on the 2024 bar only. The rules
read gave it FY2022 from the nearby sentence "IN 2022 WE FOCUS ON GROWTH OF ARPA AND KEY ACCOUNTS"; the panel read gave it FY2024 from cell r1c2;
both rows stayed in the deck list). One failing test per point, synthetic page only (CLAUDE.md rules 13 and 15):

a a sentence is never a date source; a year comes from the figure's own text, its label, a heading or an axis label · b a rules-read figure with the
same value on the same page as a panel-read row merges into that row and takes its period · c a bar takes its axis year in the rules read when the
page holds fewer figures than year labels (the live page had one: #149 placed bars by position only when the counts were equal)."""
import asyncio
import copy
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from claim_matching_support import engine_results  # noqa: E402,F401
from pdf_support import pdf_page  # noqa: E402
from test_structure_reading import AUDIT, REVENUE_MAPPING, _db, _label, t  # noqa: E402

from app import structures  # noqa: E402
from app.decks import CANDIDATES_COLLECTION, TEXT_COLLECTION, claims  # noqa: E402
from app.decks.parser import parse_deck  # noqa: E402
from app.structures import items  # noqa: E402


@pytest.fixture(autouse=True)
def _rules_path(monkeypatch):
    """This module tests the former path (the rules read and the structure read; docs/specs/deck-parser.md, llm-structure-reading.md),
    kept under DECK_PIPELINE=rules for scripts/compare_pipelines.py. The default since 2026-10-22 is "ai" (docs/design/
    ai-reads-rules-check.md; tests/test_page_pipeline.py, test_checker.py)."""
    monkeypatch.setenv("DECK_PIPELINE", "rules")

SENTENCE = "IN 2022 WE FOCUS ON GROWTH OF ARPA AND KEY ACCOUNTS"
TITLE = "Revenue forecast 2022 -2024"
AXIS = [(150, 340, 12, "2022"), (300, 340, 12, "2023"), (450, 340, 12, "2024")]
BAR = (410, 380, 12, "€5.3MM")             # beside its label "2024", not over it: the bar and the label share no width


def parsed(texts):
    return parse_deck(pdf_page(texts, []), "deck.pdf")


def found(texts):
    return claims.detect_candidates(parsed(texts)["blocks"], "deck.pdf")


def dated(candidates):
    return {c["value"]: (c["target_date"], c["period_text"]) for c in candidates if c["value"] is not None}


# ---------------------------------------------------------------------------
# a. A sentence is never a date source
# ---------------------------------------------------------------------------
SENTENCES = (
    SENTENCE,                                                                          # a verb, in capitals
    "In 2022 we focus on growth of ARPA and key accounts",                               # the same in lower case
    "Revenue will double in 2023",                                                       # an auxiliary
    "We closed the year at a strong run rate across 2021, led by the largest key accounts",   # longer than a heading
    "Growth came from key accounts in 2022.",                                            # ends on a full stop
)


@pytest.mark.parametrize("sentence", SENTENCES)
def test_a_a_sentence_near_a_figure_gives_it_no_year(sentence):
    got = found([(50, 560, 20, TITLE), (50, 520, 12, sentence), BAR])
    assert dated(got) == {5300000: (None, None)}, dated(got)


@pytest.mark.parametrize("sentence", SENTENCES[:2])
def test_a_a_sentence_near_a_figure_gives_it_no_year_even_with_no_range_heading(sentence):
    got = found([(50, 560, 20, "Revenue forecast"), (50, 520, 12, sentence), BAR])
    assert dated(got) == {5300000: (None, None)}, dated(got)


@pytest.mark.parametrize("heading, year, stated", (("Revenue forecast 2023", "2023", "2023"), ("FY2024 revenue", "2024", "FY2024"),
                                                  ("2021 Revenue", "2021", "2021")))
def test_a_a_heading_still_dates_the_figure_under_it(heading, year, stated):
    assert dated(found([(50, 560, 20, "Plan"), (50, 520, 12, heading), (50, 480, 12, "€5.3MM")])) == {5300000: (year, stated)}


def test_a_the_figures_own_text_and_an_axis_label_still_date_it():
    assert dated(found([(50, 560, 20, "Revenue forecast"), (50, 500, 12, "Revenue in 2023 of €3.39MM")])) == {3390000: ("2023", "2023")}
    assert dated(found([(50, 560, 20, "Revenue forecast"), (450, 380, 12, "€5.3MM")] + AXIS)) == {5300000: ("2024", "2024")}


# ---------------------------------------------------------------------------
# b. One figure, one row: the rules-read copy merges into the panel-read row
# ---------------------------------------------------------------------------
BARS = ((100, 380, 12, "€1.48MM"), (255, 400, 12, "€3.39MM"), (410, 420, 12, "€5.3MM"))


def rules_rows(wrong_year="2022"):
    """The rules read of the three bars with the 5.3MM bar dated from a sentence: what the live run stored."""
    deck = parsed([(50, 560, 20, TITLE)] + list(BARS) + AXIS)
    rows = claims.detect_candidates(deck["blocks"], "deck.pdf")
    for n, c in enumerate(rows, 1):
        c.update(id=f"rules-{n}", audit_id=AUDIT, deck_id="d1", file="deck.pdf", order=n, status="pending")
        if c["value"] == 5300000:
            c.update(target_date=wrong_year, period_text=wrong_year, date_from=SENTENCE)
            claims.resolve_period(c, 12)
    return deck, rows


def read_panel(rows, deck, status="pending"):
    structure, = [s for s in deck["structures"] if s["type"] == "kpi_panel"]
    listed = items.list_items(structure)
    labels = [_label(i["id"], "revenue", unit="EUR") for i in listed["items"]]
    db = _db()
    db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "mapping": REVENUE_MAPPING, "mapped_at": "2026-10-05T00:00:00"})
    db[TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "d1", "file": "deck.pdf", "page_unit": "page",
                                     "blocks": deck["blocks"], "structures": [structure]})
    db[CANDIDATES_COLLECTION].docs.extend(copy.deepcopy(r) | {"status": status} for r in rows)
    adapter = t.FakeAdapter(replies=[json.dumps({"type": "kpi_panel", "labels": labels, "pairs": []})])
    asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    return db[CANDIDATES_COLLECTION].docs


def test_b_a_rules_read_figure_with_the_value_of_a_panel_read_row_on_its_page_is_one_row_with_the_panel_period():
    deck, rows = rules_rows()
    got = read_panel(rows, deck)
    five = [c for c in got if c["value"] == 5300000]
    assert len(five) == 1, [(c["id"], c["target_date"]) for c in five]
    assert five[0]["target_date"] == "2024"
    assert {s["kind"] for s in five[0]["sources"]} == {"text", "structure"}, "both sources are cited on the one row"
    assert len(got) == 3


def test_b_a_figure_with_another_value_or_on_another_page_is_not_merged():
    deck, rows = rules_rows()
    rows[2]["sources"] = [{**rows[2]["sources"][0], "page": 9}]           # the 5.3MM figure of the parser sits on page 9
    five = [c for c in read_panel(rows, deck) if c["value"] == 5300000]
    assert sorted(c["target_date"] for c in five) == ["2022", "2024"]
    deck, rows = rules_rows()
    rows[2]["value"] = 5300001
    assert len(read_panel(rows, deck)) == 4


def test_b_a_row_the_analyst_already_decided_is_left_alone():
    deck, rows = rules_rows()
    five = [c for c in read_panel(rows, deck, status="approved") if c["value"] == 5300000]
    assert any(c["id"] == "rules-3" and c["target_date"] == "2022" for c in five)


# ---------------------------------------------------------------------------
# c. A bar takes its axis year when the page holds fewer figures than year labels
# ---------------------------------------------------------------------------
def test_c_one_figure_over_three_year_labels_takes_the_label_of_its_place():
    got = found([(50, 560, 20, TITLE), BAR] + AXIS)
    assert dated(got) == {5300000: ("2024", "2024")}, dated(got)


def test_c_the_first_and_middle_places_too():
    assert dated(found([(50, 560, 20, TITLE), (110, 380, 12, "€1.48MM")] + AXIS)) == {1480000: ("2022", "2022")}
    assert dated(found([(50, 560, 20, TITLE), (265, 380, 12, "€3.39MM")] + AXIS)) == {3390000: ("2023", "2023")}


def test_c_two_figures_over_three_labels_take_the_labels_of_their_places():
    got = found([(50, 560, 20, TITLE), (110, 380, 12, "€1.48MM"), BAR] + AXIS)
    assert dated(got) == {1480000: ("2022", "2022"), 5300000: ("2024", "2024")}, dated(got)


def test_c_a_figure_exactly_between_two_labels_takes_none():
    """"5.3M" and the labels are four characters wide, so they share a width and x=300 is the middle of 100 and 500."""
    axis = [(100, 340, 12, "2022"), (500, 340, 12, "2024")]
    assert dated(found([(50, 560, 20, "Revenue forecast"), (300, 380, 12, "5.3M")] + axis)) == {5300000: (None, None)}
    assert dated(found([(50, 560, 20, "Revenue forecast"), (320, 380, 12, "5.3M")] + axis)) == {5300000: ("2024", "2024")}


def test_c_a_figure_more_than_half_a_spacing_from_its_nearest_label_takes_none():
    """Left of the first label by a spacing's two thirds: inside the axis' reach, too far from 2022 to be its bar."""
    assert dated(found([(50, 560, 20, TITLE), (30, 380, 12, "€5.3MM")] + AXIS)) == {5300000: (None, None)}


def test_c_a_figure_far_outside_the_axis_takes_none():
    assert dated(found([(50, 560, 20, TITLE), (900, 380, 12, "€5.3MM")] + AXIS)) == {5300000: (None, None)}


def test_c_two_figures_nearest_the_same_label_take_none():
    got = found([(50, 560, 20, TITLE), (405, 380, 12, "€5.3MM"), (392, 400, 12, "€4.9MM")] + AXIS)
    assert set(dated(got).values()) == {(None, None)}, dated(got)


# ---------------------------------------------------------------------------
# The ten test decks: the four rows that took a year from a sentence now have none
# ---------------------------------------------------------------------------
def test_the_four_figures_of_02_moz_that_took_a_year_from_a_sentence_have_none():
    from test_deck_parser import DECKS
    from app.decks import parser
    got = claims.detect_candidates(parser.parse_deck((DECKS / "02-moz.pdf").read_bytes(), "02-moz.pdf")["blocks"], "02-moz.pdf")
    def page(c):
        return c["sources"][0].get("slide") or c["sources"][0].get("page")
    by = {(page(c), c["claim_type"], c["value"]): c["target_date"] for c in got}
    assert [by[k] for k in ((2, "sales", 500000), (3, "customers", 10000), (3, "unknown", 1200000), (3, "gross_margin", 83))] == [None] * 4
