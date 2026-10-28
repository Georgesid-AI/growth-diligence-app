"""Issue #146, from the artefact (a live run with a deck and a monthly revenue file: type Monthly revenue report, revenue row confirmed,
last actual month set, currency EUR, status "Ready – press Run audit", and the deck's AI reading stayed "waiting for revenue file"
after a reload; a page with the heading "2020 REVENUE" above the figure "151K"; a claim edited by the analyst that was rescored).
One failing test per item, synthetic data only (CLAUDE.md rules 13 and 15). Item 1 (the drop zone) is a frontend test.

2 any confirmed revenue file that gives the engine a revenue series is the revenue file for AI reading, a report with no customer column
  included · 3 a candidate with no figure is dropped when a figure on its page already uses it as its label; no other valueless
  candidate is dropped · 4 an edited claim shows the confidence "Analyst-edited" in the deck list, the register and the CSV, and a
  parsed claim is scored as before."""
import asyncio
import copy
import csv
import io

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from claim_matching_support import engine_results  # noqa: E402,F401
from pdf_support import pdf_page  # noqa: E402
from test_claim_matching import run_claim  # noqa: E402
from test_structure_reading import AUDIT, RecordedAdapter, _db, t  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import structures  # noqa: E402
from app.decks import TEXT_COLLECTION, claims  # noqa: E402
from app.decks.parser import parse_deck  # noqa: E402


@pytest.fixture(autouse=True)
def _rules_path(monkeypatch):
    """This module tests the former path (the rules read and the structure read; docs/specs/deck-parser.md, llm-structure-reading.md),
    kept under DECK_PIPELINE=rules for scripts/compare_pipelines.py. The default since 2026-10-22 is "ai" (docs/design/
    ai-reads-rules-check.md; tests/test_page_pipeline.py, test_checker.py)."""
    monkeypatch.setenv("DECK_PIPELINE", "rules")

# ---------------------------------------------------------------------------
# 2. The revenue file for AI reading
# ---------------------------------------------------------------------------
CELLS = [{"row": 1, "col": 1, "text": "Revenue"}, {"row": 1, "col": 2, "text": "FY2025"},
         {"row": 2, "col": 1, "text": "Recurring"}, {"row": 2, "col": 2, "text": "1,200,000"}]
REPORT = {"audit_id": AUDIT, "dtype": "revenue", "mapping": {}, "recognition_only": True, "mapping_dropped": True,
          "mapped_at": "2026-10-21T10:00:00", "recognition_decisions": {"file_type": "monthly_revenue_report", "currency": "EUR"}}


def read_deck(dataset):
    """The status and the model calls of a deck uploaded with consent ticked, against a stored revenue file."""
    db = _db()
    db["datasets"].docs.append(copy.deepcopy(dataset))
    db[TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "d1", "file": "plan.pptx", "page_unit": "slide",
                                     "structures": [{"type": "table", "slide": 1, "header_rows": 1, "cells": CELLS}]})
    adapter = RecordedAdapter()
    return asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep)), adapter.calls


def test_2_a_monthly_revenue_report_with_no_customer_column_is_the_revenue_file():
    assert read_deck(REPORT) == (structures.READ, 1)


@pytest.mark.parametrize("kind", ["revenue_summary", "financial_statements", "arr_mrr_snapshot"])
def test_2_every_file_type_read_by_recognition_only_is_the_revenue_file(kind):
    assert read_deck({**REPORT, "recognition_decisions": {"file_type": kind}}) == (structures.READ, 1)


def test_2_a_report_still_waiting_for_a_click_is_not_yet_the_revenue_file():
    assert read_deck({**REPORT, "mapped_at": None}) == (structures.WAITING, 0)


def test_2_a_column_mapping_with_no_customer_is_still_waiting():
    unmapped = {"audit_id": AUDIT, "dtype": "revenue", "mapping": {"date": "Month", "amount": "Revenue"}, "mapped_at": "2026-10-21T10:00:00"}
    assert read_deck(unmapped) == (structures.WAITING, 0)


# PR 147 review M1: the gate asks the check the rest of the app uses (`_is_mapped`), not `mapped_at` alone.
def report_api(api, name, as_of="2025-06-30"):
    """A monthly report uploaded through the API, a deck stored for the audit, consent ticked. Returns (the model calls so far)."""
    from test_recognition_recheck import RECOGNITION_ONLY, upload
    from test_revenue_recognition import rules_only
    rules_only(api, as_of)
    assert upload(api, "file.csv", RECOGNITION_ONLY[name][0].encode()).json()["recognition_only"] is True
    api.db["audits"].docs[0]["structure_reading_consent"] = True
    api.db[TEXT_COLLECTION].docs.append({"audit_id": api_audit(), "deck_id": "d1", "file": "plan.pptx", "page_unit": "slide",
                                         "structures": [{"type": "table", "slide": 1, "header_rows": 1, "cells": CELLS}]})


def api_audit():
    from test_chat_upload import AUDIT as chat_audit
    return chat_audit


def deck_gate(api):
    adapter = RecordedAdapter()
    return asyncio.run(structures.process_deck(api.db, api_audit(), "d1", adapter=adapter, sleep=t._noop_sleep)), adapter.calls


def revenue_doc(api):
    return next(d for d in api.db["datasets"].docs if d["dtype"] == "revenue")


def test_2_a_report_whose_clicks_are_done_opens_the_gate_through_the_api(api):
    report_api(api, "monthly report found")
    assert revenue_doc(api)["mapped_at"] and deck_gate(api) == (structures.READ, 1)


def test_2_an_as_of_month_moved_before_the_last_actual_column_moves_the_column_and_keeps_the_gate_open(api):
    import server
    report_api(api, "monthly report found")
    assert revenue_doc(api)["mapped_at"]
    assert api.put(f"/api/audits/{api_audit()}", json={"as_of_month": "2025-03-31"}).status_code == 200
    audit = api.db["audits"].docs[0]
    assert revenue_doc(api)["mapped_at"], "mapped_at is only rewritten by upload and by a recognition decision"
    assert asyncio.run(server._is_mapped(api_audit(), audit, revenue_doc(api))) is True, "the boundary follows the as-of month: nothing waits"
    assert deck_gate(api) == (structures.READ, 1)


def test_2_an_empty_decisions_call_on_a_report_waiting_for_its_currency_does_not_open_the_gate(api):
    report_api(api, "monthly report none")
    assert api.post(f"/api/audits/{api_audit()}/datasets/revenue/decisions", json=[]).status_code == 200
    assert deck_gate(api) == (structures.WAITING, 0)


def test_2_an_empty_mapping_put_on_a_report_waiting_for_its_currency_does_not_open_the_gate(api):
    report_api(api, "monthly report none")
    api.put(f"/api/audits/{api_audit()}/datasets/revenue/mapping", json={"mapping": {}})
    assert deck_gate(api) == (structures.WAITING, 0)


# ---------------------------------------------------------------------------
# 3. Heading-only candidates
# ---------------------------------------------------------------------------
def detect(texts):
    return claims.detect_candidates(parse_deck(pdf_page(texts, []), "deck.pdf")["blocks"], "deck.pdf")


def lines_of(found):
    return sorted(c["snippet"] for c in found)


def test_3_a_heading_a_figure_uses_as_its_label_is_not_a_claim_of_its_own():
    found = detect([(50, 560, 22, "Growth plan"), (80, 500, 14, "2020 REVENUE"), (80, 470, 14, "€151K")])
    assert lines_of(found) == ["€151K"] and found[0]["label_from"] == "2020 REVENUE"


def test_3_a_heading_with_no_figure_under_it_stays():
    found = detect([(50, 560, 22, "Growth plan"), (80, 500, 14, "2020 REVENUE"), (300, 500, 14, "2021 REVENUE"), (300, 470, 14, "€190K")])
    assert lines_of(found) == ["2020 REVENUE", "€190K"]


def test_3_the_same_heading_on_another_page_is_not_dropped_by_a_figure_of_this_page():
    one = {"page": 1, "kind": "text", "bbox": [0.1, 0.1, 0.4, 0.14], "box": 1, "text": "2020 REVENUE"}
    two = {**one, "page": 2}
    figure = {"page": 1, "kind": "text", "bbox": [0.1, 0.2, 0.3, 0.24], "box": 2, "text": "€151K"}
    found = claims.detect_candidates([one, figure, two], "deck.pdf")
    assert lines_of(found) == ["2020 REVENUE", "€151K"]
    assert [s.get("page") for c in found if c["value"] is None for s in c["sources"]] == [2]


def test_3_a_direction_with_no_figure_is_not_dropped():
    found = detect([(50, 560, 22, "Growth plan"), (80, 500, 14, "Positive EBITDA 2024"), (80, 470, 14, "€5M")])
    assert [c["claim_direction"] for c in found if c["value"] is None] == ["positive"]
    assert [c["label_from"] for c in found if c["value"] is not None] == ["Positive EBITDA 2024"], "the figure uses the line as its label"


def test_3_a_heading_no_figure_uses_is_medium_no_figure_like_a_direction():
    found = detect([(50, 560, 22, "Growth plan"), (80, 500, 14, "2020 REVENUE"), (300, 500, 14, "2021 REVENUE"), (300, 470, 14, "€190K")])
    heading, = [c for c in found if c["value"] is None]
    conf = claims.confidence(heading, found)
    assert (conf["level"], conf["failed"]) == ("Medium", ["no figure"]) and heading["claim_type"] == "revenue"


@pytest.mark.parametrize("claim_type, snippet, level", [("product", "Launch the API", "High"), ("unknown", "Milestone Q2", "Medium"),
                                                      ("ebitda", "Profitable by Q2", "High"), ("ebitda", "Break-even 2024", "High"),
                                                      ("ebitda", "2024 EBITDA", "Medium")])
def test_3_a_line_with_no_figure_is_scored_by_its_cue_and_not_its_type(claim_type, snippet, level):
    line = {"claim_type": claim_type, "snippet": snippet, "value": None, "value_high": None, "target_date": "2024-Q2", "type_from": "line",
            "sources": [{"slide": 1}]}
    assert claims.confidence(line, [line])["level"] == level


# PR 147 review M2: a milestone line is told from a heading by the figure or a milestone cue, never by the claim type (both are ebitda).
def test_3_profitable_by_2024_above_a_figure_stays_a_milestone_line():
    found = detect([(50, 560, 22, "Growth plan"), (80, 500, 14, "Profitable by 2024"), (80, 470, 14, "€0.4M")])
    assert "Profitable by 2024" in lines_of(found), "decision 2: a milestone line is kept even when a figure uses its line as its label"
    line, = [c for c in found if c["snippet"] == "Profitable by 2024"]
    assert claims.confidence(line, found)["level"] == "High", "and it is scored as a milestone line, as before"


def test_3_an_ebitda_heading_no_figure_uses_is_medium_no_figure():
    found = detect([(50, 560, 22, "Growth plan"), (80, 500, 14, "2023 EBITDA"), (300, 500, 14, "2024 EBITDA"), (300, 470, 14, "€1.2M")])
    heading, = [c for c in found if c["snippet"] == "2023 EBITDA"]
    assert heading["claim_type"] == "ebitda" and heading["value"] is None
    conf = claims.confidence(heading, found)
    assert (conf["level"], conf["failed"]) == ("Medium", ["no figure"])


def test_3_a_break_even_line_with_no_figure_under_it_is_still_a_milestone():
    found = detect([(50, 560, 22, "Growth plan"), (80, 500, 14, "Break-even in Q3 2025")])
    line, = [c for c in found if c["value"] is None]
    assert claims.confidence(line, found)["level"] == "High"


# L1: the figure uses the heading's whole line, not a longer line that holds it.
def test_3_a_longer_label_that_holds_the_heading_does_not_drop_it():
    found = detect([(50, 560, 22, "Growth plan"), (80, 500, 14, "Revenue 2020"), (300, 500, 14, "Revenue 2020 per customer"),
                    (300, 470, 14, "€40K")])
    assert "Revenue 2020" in lines_of(found)
    heading, = [c for c in found if c["snippet"] == "Revenue 2020"]
    assert claims.confidence(heading, found)["failed"] == ["no figure"]


# ---------------------------------------------------------------------------
# 4. Analyst-edited
# ---------------------------------------------------------------------------
def parsed_claim(**extra):
    return {"id": "c1", "deck_id": "d1", "file": "deck.pptx", "claim_type": "revenue", "value": 1000, "value_high": None, "unit": None,
            "currency": None, "target_date": "2023", "period_text": "2023", "snippet": "Revenue 1000", "label_from": None,
            "type_from": "line", "sources": [{"file": "deck.pptx", "slide": 3}], **extra}


def test_4_an_edited_claim_reads_analyst_edited_and_is_not_rescored():
    edited = parsed_claim(status="edited", parsed={"unit": None, "currency": None}, currency="EUR")
    assert claims.confidence(edited, [edited]) == {"level": None, "failed": [], "text": "Analyst-edited"}


def test_4_a_parsed_claim_is_scored_as_before():
    plain = parsed_claim(status="pending")
    assert claims.confidence(plain, [plain])["text"] == "Low – no unit, not corroborated"


def test_4_a_claim_the_analyst_added_stays_analyst_entered_after_an_edit():
    added = parsed_claim(origin="analyst", status="edited", parsed={})
    assert claims.confidence(added, [added])["text"] == "Analyst-entered"


def test_4_the_register_and_the_csv_use_the_same_label():
    row = run_claim({"status": "edited", "parsed": {"currency": None}})
    assert row["extraction_confidence"] == "Analyst-edited"
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(cm.FIELDS))
    writer.writeheader()
    writer.writerow({k: row.get(k) for k in cm.FIELDS})
    assert next(csv.DictReader(io.StringIO(out.getvalue())))["extraction_confidence"] == "Analyst-edited"
