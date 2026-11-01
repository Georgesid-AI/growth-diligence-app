"""PR 4c step c: the downloaded report reads `role_metrics`. A memo built from a synthetic reading with OLD_CLAIMS off carries the role metrics with
their cells and none of the old claims phrases. Synthetic maps only; no network, no MongoDB, no company's figures."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from test_role_engine import monthly_report, row, run, yearly_pnl  # noqa: E402

from app import ic_memo as im  # noqa: E402
from app import integrity as integrity_mod  # noqa: E402
from app import verdict as vd  # noqa: E402

OLD_CLAIMS_PHRASES = ("claim questions open", "claim question open", "Deal thesis", "Draft from computed text", "Value at risk", "value at risk",
                      "Appendix A", "Claim register and gates", "Claims:", "claims Verified", "Overlap groups", "Not part of this report",
                      "Contradicted", "Key gate", "Top 5")


def reading_results():
    """A monthly report (ARR, customers, churn, revenue), a yearly P&L with costs and a plan row: the file map of one synthetic audit."""
    jan_jun = [f"2026-{m:02d}" for m in range(1, 7)]
    mixed = row(9, "forecast", [110] * 18, [f"2025-{m:02d}" for m in range(1, 13)] + jan_jun, actual_plan="plan", plan=True)
    files = monthly_report([mixed]) + yearly_pnl()
    deck = [{"metric": "revenue", "period": "2025", "value": 1_500.0, "currency": "EUR", "actual_plan": "actual", "file": "deck.pdf", "page": 4,
             "label": "Total revenue FY2025"},
            {"metric": "revenue", "period": "2025", "value": 400.0, "currency": "EUR", "actual_plan": "actual", "file": "deck.pdf", "page": 4,
             "label": "New customers"}]
    return run(files, deck=deck)


def build(results, **over):
    integrity = integrity_mod.assess(results, 1, [])
    args = dict(audit={"company_name": "SynthCo", "target_arr": 1_000_000, "target_date": "2026-12-31", "as_of_month": "2026-06"},
                results=results, rows=[], ver={"status": "ok", "outcome": None, "five": [], "top5": {"changed": False, "in_force": []}, "reasons": []},
                key={"gates": [], "note": None}, gaps=vd.data_gaps(results, [], []), ic={"open_questions": 3}, blockers=[], narratives=[],
                files=[], decks=[{"file": "deck.pdf"}], tables=[], today="2026-11-01", integrity=integrity, claims=False)
    args.update(over)
    return im.build_memo(**args)


@pytest.fixture(scope="module")
def text():
    return build(reading_results())


def test_with_old_claims_off_no_claims_text_appears_anywhere(text):
    for phrase in OLD_CLAIMS_PHRASES:
        assert phrase not in text, phrase
    assert "## Appendix B" in text and "## Appendix C" in text


def test_the_summary_opens_with_arr_customers_churn_and_growth_with_the_as_of_month_then_the_unresolved_questions(text):
    summary = text.split("## Summary")[1].split("## Scorecard")[0]
    assert summary.index("As of 2026-06") < summary.index("Ending ARR") < summary.index("Customers") < summary.index("Monthly churn") \
        < summary.index("Growth") < summary.index("Unresolved questions")
    assert "2,220 EUR" in summary and "67" in summary and "3%" in summary


def test_appendix_c_carries_the_role_metrics_with_their_cells(text):
    appendix = text.split("## Appendix C")[1].split("## Appendix D")[0]
    for title in ("Metrics read from the files", "Growth by year", "Yearly P&L", "Revenue reconciliation", "Plan to date"):
        assert title in appendix, title
    metrics_table = appendix.split("Growth by year")[0]
    for name in ("Customers", "Monthly churn", "Gross margin", "S&M share of revenue"):
        assert name in metrics_table, name
    assert "Report!S8" in metrics_table and "Report!S7" in metrics_table, "the cells of customers and churn"
    plan = appendix.split("Plan to date")[1].split("Yearly P&L")[0] if "Plan to date" in appendix.split("Yearly P&L")[0] else appendix
    assert "Report!" in plan
    recon = appendix.split("Revenue reconciliation")[1]
    assert "deck.pdf page 4" in recon and "Also read" in recon and "400 EUR" in recon, "the second FY figure of the page is listed, not compared"
    assert "P&L!" in appendix.split("Yearly P&L")[1] or "P&L" in appendix.split("Yearly P&L")[1]


def test_files_reviewed_marks_the_pnl_as_covered_when_a_pnl_is_read_and_counts_the_categories(text):
    table = text.split("Files reviewed")[2] if text.count("Files reviewed") > 2 else text.split("Files reviewed")[-1]
    assert "| P&L and budget vs actuals | yes |" in table
    assert "Evidence categories covered: 2 of 7" in text, "the P&L and the decks"
    none = reading_results()
    none = {**none, "yearly_basis": None}
    no_pnl = run(monthly_report())
    assert "Evidence categories covered: 1 of 7" in build(no_pnl)


def test_data_requests_are_one_line_per_file():
    results = run(monthly_report())
    text = build(results)
    requests = text.split("Requests")[1].split("## Appendix C")[0].split("\n\n")[0]
    file_lines = [line for line in requests.splitlines() if line.startswith("- A file with")]
    assert len(file_lines) == 1, requests
    assert "sales_marketing" in file_lines[0] and "cash" in file_lines[0]


def test_the_narrative_could_not_be_generated_line_is_a_footnote(text):
    head = text.split("## Appendix B")[0]
    assert "Narrative could not be generated" not in head
    assert "Narrative could not be generated" in text.split("Footnotes")[-1]


def test_with_old_claims_on_the_claim_sections_are_still_there():
    from test_ic_memo import inputs
    out = im.build_memo(**inputs())
    assert "## Deal thesis" in out and "## Appendix A" in out and "Value at risk" in out
