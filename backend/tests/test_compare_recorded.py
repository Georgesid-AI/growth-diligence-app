"""scripts/compare_pipelines.py --recorded <run> (docs/design/ai-reads-rules-check.md section 7, PR B): the page read replayed from the
model's own recorded replies, one B row set per pass, agreement across the passes, and the unmatched and dropped rows grouped by the
check that failed, with page and cell ids. No network, no MongoDB."""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

pytest.importorskip("pdfplumber")
pytest.importorskip("pptx")

RUN = "pages_2026-10-22"
DECKS = ["03-buffer.pptx", "09-genesisai-2024.pdf"]


def _script():
    spec = importlib.util.spec_from_file_location("compare_pipelines", BACKEND.parent / "scripts" / "compare_pipelines.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


def _recorded_claims(deck, n):
    folder = BACKEND / "tests" / "fixtures" / "page_replies" / "recorded" / RUN / f"pass-{n}"
    return [c for f in folder.glob("*.json") for d in [json.loads(f.read_text(encoding="utf-8"))] if d["file"] == deck for c in d["claims"]]


def test_the_recorded_run_is_replayed_pass_by_pass_and_every_claim_is_matched_unmatched_or_dropped(capsys):
    script = _script()
    report = script.main(["--recorded", RUN, "--deck", DECKS[0], "--deck", DECKS[1]])
    assert report["recorded"] == RUN and report["passes"] == [1, 2, 3]
    for deck in DECKS:
        rows = report["decks"][deck]
        assert set(rows["passes"]) == {1, 2, 3} and rows["rows_a"] > 0
        for n, row in rows["passes"].items():
            claims = _recorded_claims(deck, n)
            assert row["claims"] == len(claims) > 0, "every recorded claim of the pass went through the gateway and page_check"
            assert row["matched"] + row["unmatched"] + row["dropped"] == row["claims"]
            assert row["rows_b"] == row["matched"] + row["unmatched"]
            assert 0 <= row["recall"] <= 1 and 0 <= row["precision"] <= 1
    buffer = report["decks"][DECKS[0]]
    assert buffer["agreement"]["union"] >= buffer["agreement"]["agreed"] > 0 and 0 < buffer["agreement"]["pct"] <= 100
    assert set(buffer["agreement"]["disagree"]) == {"metric", "period", "presence"}
    assert set(report["causes"]) > {"matched"} and "other" not in report["causes"] and sum(report["causes"].values()) == sum(
        row["claims"] for d in report["decks"].values() for row in d["passes"].values())
    assert all(set(r) == {"deck", "page", "cell", "cause", "metric", "value", "passes"} for r in report["unmatched_rows"])
    # Since 2026-10-23 (George) a figure the model labelled other is matched like any other: the cause "other" is gone from the report.
    assert all(r["cause"] != "other" for r in report["unmatched_rows"])
    out = capsys.readouterr().out
    assert out.count(DECKS[0]) >= 4 and "agreement" in out, "one line per pass, the agreement line, the causes"
    assert "by cause" in out and re.search(r" p\d+ r\d+c\d+ ", out), "cell ids are printed with their page"


def test_one_pass_can_be_chosen_and_the_tables_can_be_written_as_markdown(tmp_path):
    script = _script()
    md = tmp_path / "compare.md"
    report = script.main(["--recorded", RUN, "--pass", "2", "--deck", DECKS[0], "--md", str(md)])
    assert report["passes"] == [2] and set(report["decks"][DECKS[0]]["passes"]) == {2}
    assert report["decks"][DECKS[0]]["agreement"] is None, "agreement needs more than one pass"
    text = md.read_text(encoding="utf-8")
    assert text.startswith("# ") and "| Deck |" in text and "03-buffer.pptx" in text and "| matched |" in text
    assert "Paying Users" not in text and "Traction" not in text, "no line of a deck"


def test_without_recorded_the_hand_written_replies_are_replayed_as_before():
    script = _script()
    report = script.main(["--deck", DECKS[0]])
    assert "recorded" not in report and set(report["decks"][DECKS[0]]) >= {"rows_a", "rows_b", "b_matched", "b_unmatched", "a", "b"}


def test_an_unknown_run_is_refused():
    script = _script()
    with pytest.raises(SystemExit, match="no recorded run"):
        script.main(["--recorded", "pages_1999-01-01", "--deck", DECKS[0]])
