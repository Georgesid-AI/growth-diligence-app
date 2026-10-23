"""The live path (structures.process_deck under DECK_PIPELINE=ai) writes every AI row after the cell match and the checker ran:
a cell holding several figures matches each one cited, and a sign the page does not show is flagged on the stored row. Synthetic
pages only (rule 15)."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("pdfplumber")

from test_checker import AUDIT, TITLE, _page_db, claim, deck  # noqa: E402
from test_structure_reading import t  # noqa: E402

from app import structures  # noqa: E402
from app.decks import CANDIDATES_COLLECTION  # noqa: E402
from app.llm.schemas import PAGE_CLAIMS  # noqa: E402

CELL_TEXT = "€27K 3% 27% €2.3K €15.6K"


def _run(monkeypatch, texts, claims_):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    db = _page_db(deck([TITLE, *texts]))
    adapter = t.FakeAdapter(replies=[json.dumps({"type": PAGE_CLAIMS, "claims": claims_})])
    status = asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert status == "read"
    return db[CANDIDATES_COLLECTION].docs


def test_three_figures_of_one_cell_are_each_stored_matched(monkeypatch):
    rows = _run(monkeypatch, [(50, 500, 12, CELL_TEXT)], [
        claim("p1r2c1", 2_300, metric="cac", unit="EUR"), claim("p1r2c1", 27_000, metric="mrr", unit="EUR"),
        claim("p1r2c1", 3, metric="churn", unit="%")])
    assert sorted((r["claim_type"], r["value"], r["ai_status"]) for r in rows) == [
        ("cac", 2_300, "matched"), ("churn", 3, "matched"), ("mrr", 27_000, "matched")]
    assert all(r["flags"] == [] and r["cell"] == "r2c1" for r in rows)


def test_a_bracketed_figure_cited_negative_is_stored_positive_with_the_sign_flag(monkeypatch):
    rows = _run(monkeypatch, [(50, 500, 12, "(71%) annually")], [claim("p1r2c1", -71, metric="other", unit="%")])
    row, = rows
    assert row["value"] == 71 and "sign not on page" in row["flags"]


def test_a_row_stored_by_an_earlier_run_is_checked_again_when_the_page_is_read_again(monkeypatch):
    """Live bug (2026-10-23): rows stored before the checks existed stayed "unmatched" with no flags, because a re-read skipped any
    figure its cell already listed. The untouched AI rows of the reply are replaced; an approved row stays."""
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    db = _page_db(deck([TITLE, (50, 500, 12, CELL_TEXT)]))
    claims_ = [claim("p1r2c1", 2_300, metric="cac", unit="EUR"), claim("p1r2c1", 27_000, metric="mrr", unit="EUR"),
               claim("p1r2c1", 3, metric="churn", unit="%")]

    def read():
        adapter = t.FakeAdapter(replies=[json.dumps({"type": PAGE_CLAIMS, "claims": claims_})])
        asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    read()
    rows = db[CANDIDATES_COLLECTION].docs
    orders = sorted(r["order"] for r in rows)
    for r in rows:
        r.update(ai_status="unmatched", flags=[], position=None)
    rows[0]["status"] = "approved"
    kept = dict(rows[0])
    read()
    rows = db[CANDIDATES_COLLECTION].docs
    assert len(rows) == 3 and sorted(r["order"] for r in rows) == orders
    approved, = [r for r in rows if r["status"] == "approved"]
    assert approved["id"] == kept["id"] and approved["ai_status"] == "unmatched", "an approved row is never replaced"
    assert all(r["ai_status"] == "matched" for r in rows if r["status"] == "pending")
