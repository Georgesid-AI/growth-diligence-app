"""How a deck figure is referred to on the mapping page (board-pack layout fix, item 6). A figure on a text-style page (prose, bullets, no table) is
shown with the line of text it sits in, up to 120 characters, beside the page number: "p1: ARR: 1 774 628 EUR - 93% of the plan!". The rNcM anchor stays
internal. A figure in a table keeps its cell reference and gets its row label. The line is for the screen only: it is in no result and in no log."""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app import deck_figures, register  # noqa: E402

LINE = "ARR: 1 774 628 EUR - 93% of the plan!"


def candidate(text=LINE, table=None, **over):
    source = {"page": 1, "kind": "page", "cell": "r2c1", **({"table": table, "row": 3, "col": 2} if table is not None else {})}
    return {"id": "c1", "deck_id": "d1", "claim_type": "arr", "value": 1774628.0, "unit": None, "currency": "EUR", "period_text": None, "target_date": None,
            "label_from": over.pop("label_from", None), "flags": [], "basis": "actual", "page_segment": None, "cell": "r2c1", "snippet": text, "sources": [source], **over}


def test_a_figure_on_a_text_page_carries_the_line_it_sits_in():
    figure = deck_figures.figure_of(candidate(), {})
    assert figure["line"] == LINE and figure["source"]["page"] == 1
    assert figure["cell"] == "r2c1", "the anchor is kept internally"


def test_a_long_line_is_cut_at_120_characters_and_whitespace_is_one_space():
    figure = deck_figures.figure_of(candidate("ARR  grew\n" + "x" * 300), {})
    assert len(figure["line"]) == 120 and figure["line"].startswith("ARR grew x") and figure["line"].endswith("…")


def test_a_figure_in_a_table_has_no_line_and_keeps_its_cell_and_row_label():
    figure = deck_figures.figure_of(candidate("1,774,628", table=0, label_from="ARR"), {})
    assert figure["line"] is None and figure["cell"] == "r2c1" and figure["label"] == "ARR"


def test_the_register_row_and_the_deck_figure_list_carry_the_line():
    deck = {"deck_id": "d1", "file": "deck.pdf", "figures": [{**deck_figures.figure_of(candidate(), {}), "key": "deck:d1:c1", "outcome": "confirmed", "reason": None}]}
    row = register.deck_rows(deck)["confirmed"][0]
    assert row["source"] == {"file": "deck.pdf", "deck_id": "d1", "page": 1, "line": LINE}
