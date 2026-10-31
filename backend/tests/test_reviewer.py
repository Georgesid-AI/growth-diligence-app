# ruff: noqa: F811, F401
"""The reviewer, its findings and the re-read (docs/design/read-check-review.md sections 3, 7, 9; PR 3 step b), on the synthetic monthly report of
the sheet reader flow tests. The provider is a router that answers a sheet reading and a review from scripts, so no test can reach a model."""
import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import test_llm_gateway as t  # noqa: E402
from app import cards, checks, deck_figures, readings, reviewer  # noqa: E402
from app.decks import CANDIDATES_COLLECTION, TEXT_COLLECTION  # noqa: E402
from app.llm import gateway  # noqa: E402
from app.structures import redact  # noqa: E402
from test_sheet_reader_flow import COMPANY, MODEL, MONTHLY, SHEET, Router, flow, good_map, monthly, upload  # noqa: E402

QUEUES_SHEET_READER = True      # tests/conftest.py: this module lets an upload queue the reader


def row(n, label, role, metric, **over):
    return {"row": n, "label_cell": f"A{n}", "role": role, "metric": metric, "basis": "monthly", "actual_plan": "mixed", "boundary_col": "G",
            "segment": None, "parent_row": None, "unit": "money", "currency": "EUR", "cells": f"B{n}:M{n}", "variance_of": None, "by_column": False,
            "evidence": f"{label} row, read by the reader", **over}


def map_with(bookings_role="revenue"):
    """The monthly report with row 10 (Bookings) read as `bookings_role`: "revenue" is the wrong-role reading the reviewer should catch."""
    fmap = good_map()
    fmap["sheets"][0]["rows"].append(row(10, "Bookings", bookings_role, "revenue" if bookings_role == "revenue" else "bookings"))
    return fmap


def finding(cell="B10:M10", sheet=SHEET, **over):
    return {"what": "Row 10 behaves like bookings, not recognised revenue.", "refs": [{"file": 1, "sheet": sheet, "cell": cell, "page": None}],
            "reading": "Row 10 is bookings.", "confidence": "high", **over}


class ReviewRouter(Router):
    """Answers a sheet reading, a re-read and a review from scripts; counts each."""

    def __init__(self, first, again=None, review=None):
        super().__init__(first, again)
        self.review, self.review_calls, self.review_payloads, self.sheet_systems = review, 0, [], []

    def complete(self, **kw):
        sent = json.loads(kw["user_payload"])
        if sent["type"] != "reviewer":
            self.sheet_systems.append(kw["system"])
            return super().complete(**kw)
        self.review_calls += 1
        self.review_payloads.append(sent)
        reply = self.review[min(self.review_calls - 1, len(self.review) - 1)] if isinstance(self.review, list) else self.review
        return (reply if isinstance(reply, str) else json.dumps(reply)), 2000, 300


def start(flow, first, again=None, review=None):
    flow.state["adapter"] = ReviewRouter(first, again, review if review is not None else {"findings": []})
    upload(flow, MONTHLY, monthly())
    return flow.state["adapter"]


def audit_of(flow):
    return flow.db["audits"].docs[0]


def review(flow, force=False):
    return asyncio.run(reviewer.review_audit(flow.db, audit_of(flow), force=force))


def cards_of(flow):
    return flow.db[readings.CARDS].docs


# ---------------------------------------------------------------------------
# Findings and what follows
# ---------------------------------------------------------------------------
def test_a_finding_on_a_wrong_role_row_is_read_again_and_corrected_on_review(flow):
    router = start(flow, map_with("revenue"), again=map_with("bookings"), review={"findings": [finding()]})
    assert flow.db[readings.CHECKS].docs[0]["counts"]["rejected"] == 0, "the cell check cannot see a wrong role"
    done = review(flow)
    assert router.review_calls == 1 and router.sheet_calls == 2, "one review, one re-read"
    assert "Row 10 behaves like bookings" in router.sheet_payloads[1]["recheck"][0]["reason"], "the finding goes with the re-read"
    assert router.sheet_payloads[1]["recheck"][0]["item"] == f"row:{SHEET}:10"
    assert done["findings"][0]["items"][0]["result"] == "agrees" and not cards_of(flow)
    stored = flow.db[readings.READINGS].docs[0]["file_map"]["sheets"][0]["rows"][1]
    assert stored["role"] == "revenue", "the reading itself is never edited"
    overrides = flow.db[readings.OVERRIDES].docs
    assert {o["path"] for o in overrides} >= {"sheets.0.rows.1.role", "sheets.0.rows.1.metric"}
    assert all(o["who"] == "reviewer" and o["why"].startswith("corrected on review") for o in overrides)
    effective = readings.effective(flow.db[readings.READINGS].docs[0]["file_map"], overrides)
    assert effective["sheets"][0]["rows"][1]["role"] == "bookings" and effective["sheets"][0]["rows"][1]["metric"] == "bookings"
    assert flow.db[readings.CHECKS].docs[0]["corrections"][0]["item"] == f"row:{SHEET}:10"


def test_a_finding_the_reader_rejects_becomes_a_card_with_both_readings(flow):
    router = start(flow, map_with("revenue"), again=map_with("revenue"), review={"findings": [finding()]})
    done = review(flow)
    assert router.sheet_calls == 2 and done["findings"][0]["items"][0]["result"] == "repeats the first reading"
    assert not flow.db[readings.OVERRIDES].docs, "no override when the reader disagrees"
    (card,) = cards_of(flow)
    assert card["kind"] == cards.DISAGREEMENT and card["status"] == "open"
    assert card["reader"]["label"] == "Reader, twice" and card["reader"]["role"] == "revenue"
    assert card["other"]["label"] == "Reviewer" and "bookings" in card["other"]["evidence"]
    assert card["source"]["cell"] == "B10:M10" and card["source"]["sheet"] == SHEET


def test_a_re_read_that_never_ran_opens_no_card_and_the_next_review_tries_it_again(flow, caplog):
    import logging
    router = start(flow, map_with("revenue"), again=None, review={"findings": [finding()]})        # the reader fails on the re-read
    caplog.set_level(logging.INFO)
    done = review(flow)
    assert "bookings" not in done["reason"] and COMPANY not in done["reason"], "the reason is a closed word, never the finding or the file"
    assert "bookings" not in "\n".join(r.getMessage() for r in caplog.records)
    assert done["status"] == "incomplete" and done["reason"] and done["reason"]
    assert done["findings"][0]["items"][0]["result"] == "not read"
    assert not cards_of(flow) and not flow.db[readings.OVERRIDES].docs, "a re-read that never ran is no disagreement"
    stored = flow.db[readings.REVIEWS].docs[0]
    assert stored["status"] == "incomplete"
    router.again = map_with("bookings")                                                           # the next Run audit
    router.review_calls = 0
    done = review(flow)
    assert router.review_calls == 1 and done["status"] == "read", "an incomplete review is not kept for its input"
    assert done["findings"][0]["items"][0]["result"] == "agrees" and not cards_of(flow)


def test_the_register_says_review_not_completed_with_the_reason(flow):
    start(flow, map_with("revenue"), again=None, review={"findings": [finding()]})
    review(flow)
    from app import register
    summary = asyncio.run(register.build(flow.db, audit_of(flow)["id"]))["review"]
    assert summary["not_completed"].startswith("review not completed: ") and len(summary["not_completed"]) > len("review not completed: ")


def test_a_re_read_after_the_prompt_changed_uses_the_stored_readings_prompt_and_makes_no_new_reading(flow):
    router = start(flow, map_with("revenue"), again=map_with("bookings"), review={"findings": [finding()]})
    old = next(d for d in flow.db["prompts"].docs if d["name"] == "sheet_reading")
    flow.db["prompts"].docs.append({**old, "version": "v2", "text": old["text"] + "\nTEST ONLY changed"})
    router.sheet_systems.clear()
    calls_before = router.sheet_calls
    done = review(flow)
    assert router.sheet_calls == calls_before + 1, "one re-read, never a full reading under the new prompt"
    assert router.sheet_systems == [old["text"]], "the re-read carries the text the reading was made with"
    assert len(flow.db[readings.READINGS].docs) == 1
    assert done["findings"][0]["items"][0]["result"] == "agrees"
    assert all(o["reading"] == flow.db[readings.READINGS].docs[0]["key"] for o in flow.db[readings.OVERRIDES].docs)


def test_a_re_read_whose_stored_prompt_version_is_gone_is_not_read_and_makes_no_call(flow):
    router = start(flow, map_with("revenue"), again=map_with("bookings"), review={"findings": [finding()]})
    flow.db[readings.READINGS].docs[0]["prompt_version"] = "v99"
    calls_before = router.sheet_calls
    done = review(flow)
    assert router.sheet_calls == calls_before and done["status"] == "incomplete" and "prompt" in done["reason"]
    assert not cards_of(flow)


def test_a_second_reading_the_checks_reject_is_a_card_not_a_correction(flow):
    bad = map_with("bookings")
    bad["sheets"][0]["rows"][1]["cells"] = "B10:Z10"      # past the last column of the sheet
    start(flow, map_with("revenue"), again=bad, review={"findings": [finding()]})
    done = review(flow)
    assert done["findings"][0]["items"][0]["result"] == "gives a third value"
    assert len(cards_of(flow)) == 1 and not flow.db[readings.OVERRIDES].docs


@pytest.mark.parametrize("ref", [dict(cell="Z99"), dict(cell="B900:M900"), dict(sheet="No such sheet"), dict(file=7)])
def test_a_finding_citing_a_cell_sheet_or_file_that_does_not_exist_is_dropped_and_logged(flow, caplog, ref):
    bad = finding(**{k: v for k, v in ref.items() if k != "file"})
    if "file" in ref:
        bad["refs"][0]["file"] = ref["file"]
    router = start(flow, map_with("revenue"), again=map_with("bookings"), review={"findings": [bad]})
    import logging
    caplog.set_level(logging.WARNING)
    done = review(flow)
    assert done["dropped"] == 1 and done["findings"][0]["state"] == "dropped" and done["findings"][0]["drop_reason"]
    assert router.sheet_calls == 1, "a dropped finding triggers no re-read"
    assert not cards_of(flow) and not flow.db[readings.OVERRIDES].docs
    assert "finding dropped: run_id=audit-chat finding=f1 reason=" in "\n".join(r.getMessage() for r in caplog.records)
    assert "behaves like bookings" not in "\n".join(r.getMessage() for r in caplog.records), "a log line holds a closed word, never the finding"


def test_nothing_flagged_means_no_card_no_re_read_and_no_override(flow):
    router = start(flow, map_with("bookings"), review={"findings": []})
    done = review(flow)
    assert done["status"] == "read" and done["findings"] == []
    assert router.sheet_calls == 1 and not cards_of(flow) and not flow.db[readings.OVERRIDES].docs


def test_a_valid_finding_on_a_cell_no_mapped_row_holds_is_a_card_without_a_re_read(flow):
    router = start(flow, map_with("bookings"), review={"findings": [finding(cell="B7:M7")]})        # Customers: not mapped in this reading
    done = review(flow)
    assert router.sheet_calls == 1 and done["findings"][0]["items"][0]["result"] == "no item"
    assert len(cards_of(flow)) == 1


def test_one_review_per_audit_and_input_and_force_reviews_again(flow):
    router = start(flow, map_with("bookings"), review={"findings": []})
    review(flow)
    review(flow)
    assert router.review_calls == 1
    review(flow, force=True)
    assert router.review_calls == 2 and len(flow.db[readings.REVIEWS].docs) == 1


def test_a_reply_that_is_not_the_findings_format_is_asked_again_once_then_not_read(flow):
    router = start(flow, map_with("bookings"), review="this is not json")
    done = review(flow)
    assert router.review_calls == 2 and done["status"] == "not_read" and done["findings"] == []
    assert not cards_of(flow)
    router2 = start_again(flow, ["not json", {"findings": []}])
    assert router2 is not None


def start_again(flow, replies):
    flow.state["adapter"].review = replies
    flow.state["adapter"].review_calls = 0
    done = review(flow, force=True)
    assert flow.state["adapter"].review_calls == 2 and done["status"] == "read", "the retry carries the errors and the second reply stands"
    return flow.state["adapter"]


def test_the_review_input_is_masked_holds_no_evidence_line_no_file_name_and_the_cannot_check_list(flow):
    router = start(flow, map_with("revenue"), review={"findings": []})
    review(flow)
    sent = router.review_payloads[0]
    text = json.dumps(sent)
    assert COMPANY not in text and MONTHLY not in text, "no company name, no file name"
    assert "read by the reader" not in text and "Recognised revenue row" not in text, "the readers' evidence lines are left out"
    (file1,) = sent["input"]["files"]
    assert file1["kind"] == "sheet" and file1["map"]["sheets"][0]["rows"][1]["series"]["refs"][0] == "B10", "maps go with their series"
    assert "cannot_check" in sent["input"] and "computed" in sent["input"]
    assert redact.personal_items(text) == []


@pytest.mark.parametrize("setup", ["no_model", "no_consent", "no_prompt"])
def test_the_reviewer_makes_no_call_without_an_allowed_model_consent_or_prompt(flow, monkeypatch, setup):
    router = start(flow, map_with("bookings"), review={"findings": [finding()]})
    if setup == "no_model":
        monkeypatch.setenv("SHEET_READER_MODEL", "latest")
    elif setup == "no_consent":
        audit_of(flow)["structure_reading_consent"] = False
    else:
        flow.db["prompts"].docs[:] = [d for d in flow.db["prompts"].docs if d["name"] != "reviewer"]
    done = review(flow)
    assert router.review_calls == 0 and done["status"] != "read" and not cards_of(flow)


def test_the_reviewer_uses_the_readers_model_allow_list_and_the_prompt_reviewer(flow):
    router = start(flow, map_with("bookings"), review={"findings": []})
    review(flow)
    stored = flow.db["llm_calls"].docs
    assert any(c.get("structure_type") == "reviewer" and c["model"] == MODEL for c in stored)
    assert gateway.REVIEWER_PROMPT == "reviewer" and router.review_calls == 1


# ---------------------------------------------------------------------------
# Deck figures join the same path
# ---------------------------------------------------------------------------
def deck(blocks, pages=3):
    return {"audit_id": "a1", "deck_id": "d1", "file": "deck.pdf", "pages": pages, "page_unit": "page", "blocks": blocks, "structures": []}


def candidate(value, page=2, **over):
    return {"id": "c1", "audit_id": "a1", "deck_id": "d1", "origin": "ai", "status": "pending", "claim_type": "arr", "value": value, "unit": None,
            "currency": "EUR", "target_date": "2024-12-31", "period_text": "Dec 2024", "basis": "actual", "flags": [],
            "sources": [{"file": "deck.pdf", "page": page, "kind": "page", "cell": "r2c1"}], **over}


def check_deck(blocks, cand, pages=3):
    d = deck(blocks, pages)
    fig = deck_figures.figure_of(cand, d)
    return deck_figures.check_figure(fig, cand, d)


def test_a_page_figure_found_in_the_page_text_within_tolerance_is_confirmed():
    got = check_deck([{"page": 2, "text": "ARR reached EUR 447,223 at year end", "kind": "text"}], candidate(447223.43))
    assert got["outcome"] == "confirmed" and got["reason"] is None


def test_a_page_figure_absent_from_the_page_text_is_rejected():
    got = check_deck([{"page": 2, "text": "ARR reached EUR 398,736 at year end", "kind": "text"}], candidate(447223))
    assert got["outcome"] == "rejected" and got["reason"] == "Reading says 447223; page 2 holds no such figure."


def test_a_figure_read_from_the_image_only_cannot_be_checked_page_has_no_text_layer():
    no_text = check_deck([{"page": 3, "text": "Growth chart", "kind": "text"}], candidate(447223, page=2))
    assert no_text["outcome"] == "cannot_check" and no_text["reason"] == "Page 2 has no text layer; figure read from the image."
    unread = check_deck([{"page": 2, "text": "Customers 120", "kind": "text"}], candidate(447223, flags=["extraction incomplete"]))
    assert unread["outcome"] == "cannot_check"


def test_a_count_on_a_page_is_compared_exactly_money_within_half_a_percent_and_other_cannot_be_checked():
    page = [{"page": 2, "text": "Customers 1,004 at year end", "kind": "text"}]
    assert check_deck(page, candidate(1000, unit="count", currency=None))["outcome"] == "rejected", "1,000 customers are not confirmed by 1,004"
    assert check_deck(page, candidate(1004, unit="count", currency=None))["outcome"] == "confirmed"
    assert check_deck(page, candidate(1004, unit=None, currency=None))["outcome"] == "confirmed", "no unit given: compared exactly against the page text"
    assert check_deck(page, candidate(1000, unit=None, currency=None))["outcome"] == "rejected", "exact, not within a tolerance"
    assert check_deck([{"page": 2, "text": "ARR EUR 1,004", "kind": "text"}], candidate(1000))["outcome"] == "confirmed", "money: within 0.5 %"
    other = check_deck(page, candidate(1004, unit="other", currency=None))
    assert other["outcome"] == "confirmed" and other["reason"] is None, '"other" is no unit either: exact'
    assert checks.C_NO_UNIT not in {check_deck(page, candidate(v, unit=None, currency=None))["reason"] for v in (1004, 7)}, "never a cannot-check reason for a page"


def test_the_page_does_not_choose_the_scale_a_reading_of_2_5_is_not_confirmed_by_2_5m():
    page = [{"page": 2, "text": "ARR EUR 2.5m at year end", "kind": "text"}]
    assert check_deck(page, candidate(2_500_000))["outcome"] == "confirmed"
    got = check_deck(page, candidate(2.5))
    assert got["outcome"] == "cannot_check" and got["reason"] == "Page 2 states 2.5; reading says 2.5. Unit or scale differs; not compared."
    assert check_deck(page, candidate(7))["outcome"] == "rejected"


def test_a_deck_rate_is_held_as_a_fraction_and_compared_within_one_point_of_the_page():
    page = [{"page": 2, "text": "Churn 5.4 % a month", "kind": "text"}]
    figure = deck_figures.figure_of(candidate(4.5, unit="%", currency=None), deck(page))
    assert figure["unit"] == "rate" and abs(figure["value"] - 0.045) < 1e-12, "the screen writes it with the one formatter: 4.5%"
    assert check_deck(page, candidate(4.5, unit="%", currency=None))["outcome"] == "confirmed"      # 0.9 points apart
    assert check_deck(page, candidate(3.0, unit="%", currency=None))["outcome"] == "rejected"      # 2.4 points apart


def test_actual_or_plan_is_the_readers_own_word_a_scenario_is_not_turned_into_a_plan():
    d = deck([{"page": 2, "text": "ARR 447,223", "kind": "text"}])
    assert deck_figures.figure_of(candidate(447223, basis="projection"), d)["actual_plan"] == "plan"
    assert deck_figures.figure_of(candidate(447223, basis="actual"), d)["actual_plan"] == "actual"
    assert deck_figures.figure_of(candidate(447223, basis="scenario"), d)["actual_plan"] is None


def test_a_page_outside_the_deck_is_rejected_and_a_rate_is_compared_in_points():
    assert check_deck([], candidate(5, page=9))["outcome"] == "rejected"
    rate = check_deck([{"page": 2, "text": "Churn 4.5 % a month", "kind": "text"}], candidate(4.5, unit="%", currency=None))
    assert rate["outcome"] == "confirmed"


def test_deck_figures_reach_the_reviewer_and_a_finding_on_a_page_is_a_card(flow):
    router = start(flow, map_with("bookings"), review={"findings": [
        {"what": "The page figure is a plan value read as actual.", "refs": [{"file": 2, "sheet": None, "cell": None, "page": 2}],
         "reading": "plan", "confidence": "low"}]})
    flow.db[TEXT_COLLECTION].docs.append({**deck([{"page": 2, "text": "ARR 447,223", "kind": "text"}]), "audit_id": audit_of(flow)["id"]})
    flow.db[CANDIDATES_COLLECTION].docs.append({**candidate(447223), "audit_id": audit_of(flow)["id"]})
    done = review(flow)
    deck_file = router.review_payloads[0]["input"]["files"][1]
    assert deck_file["kind"] == "deck" and deck_file["figures"][0]["value"] == 447223 and deck_file["figures"][0]["page"] == 2
    assert "ARR 447,223" not in json.dumps(router.review_payloads[0]), "no page text goes to the reviewer"
    assert done["findings"][0]["items"][0]["result"] == "no item" and router.sheet_calls == 1, "a deck figure has no re-read"
    (card,) = cards_of(flow)
    assert card["source"]["page"] == 2 and card["reader"]["value"] == 447223


def test_a_finding_citing_a_page_that_does_not_exist_is_dropped(flow):
    start(flow, map_with("bookings"), review={"findings": [
        {"what": "x", "refs": [{"file": 2, "sheet": None, "cell": None, "page": 40}], "reading": "y", "confidence": "low"}]})
    flow.db[TEXT_COLLECTION].docs.append({**deck([{"page": 2, "text": "ARR 447,223", "kind": "text"}]), "audit_id": audit_of(flow)["id"]})
    done = review(flow)
    assert done["dropped"] == 1 and done["findings"][0]["drop_reason"] == "no_such_page" and not cards_of(flow)


# ---------------------------------------------------------------------------
# Masking order (section 8): a company is tokenised before the personal-name rule
# ---------------------------------------------------------------------------
def test_a_company_name_with_a_first_name_is_tokenised_in_a_sheet_payload_and_comes_back_on_display():
    text = redact.reading_text([{"name": "Sales", "cells": [
        {"row": 1, "col": 1, "text": "Customer"}, {"row": 2, "col": 1, "text": "Anna Group"}, {"row": 2, "col": 2, "text": "1200"},
        {"row": 3, "col": 1, "text": "Jane Doe"}, {"row": 4, "col": 1, "text": "Peter Holdings Ltd"}]}])
    mapping = {}
    learned = redact.reading_company_names(text, "Acme", mapping)
    assert learned == ["Anna Group", "Peter Holdings Ltd"], "a person's name under the same header is not a company"
    mapping = {n: f"Client-0{i + 1}" for i, n in enumerate(learned)}
    masked, counts = redact.mask_reading(text, "Acme", mapping)
    assert "A3: [person]" in masked and "A2: Client-01" in masked and "A4: Client-02" in masked and "Anna" not in masked
    from app.llm import redaction
    assert redaction.restore("Client-01", mapping) == "Anna Group", "display un-masks on the server"


def test_a_company_name_with_a_first_name_is_tokenised_in_a_page_payload():
    cells = [{"row": 1, "col": 1, "text": "Customers", "box": 1}, {"row": 2, "col": 1, "text": "Anna Group", "box": 1},
             {"row": 3, "col": 1, "text": "ARR 120k", "box": 2}, {"row": 4, "col": 1, "text": "Jane Doe", "box": 3}]
    text = redact.page_text([(3, cells)])
    mapping = {}
    learned = redact.page_company_names(text, "Acme", mapping)
    assert learned == ["Anna Group"]
    masked, counts = redact.mask_pages(text, "Acme", {"Anna Group": "Client-01"})
    assert "p3r2c1: Client-01" in masked and "Anna" not in masked and "p3r4c1: [person]" in masked


@pytest.mark.parametrize("with_prompt", [True, False])
def test_run_audit_goes_on_without_the_reviewer_stage_when_the_reviewer_prompt_is_missing(flow, with_prompt):
    router = start(flow, map_with("bookings"), review={"findings": []})
    if not with_prompt:
        flow.db["prompts"].docs[:] = [d for d in flow.db["prompts"].docs if d["name"] != "reviewer"]
    done = flow.post(f"/api/audits/{audit_of(flow)['id']}/run/engine")
    assert done.status_code == 200 and done.json()["status"] in ("done", "needs_review", "waiting"), done.text
    assert done.json()["status"] != "failed"
    assert router.review_calls == (1 if with_prompt else 0), "the review stage runs only with its prompt; the audit goes on either way"
    assert bool(flow.db[readings.REVIEWS].docs) == with_prompt, "no reviewer stage, so no review record and no 'review not completed' line"


@pytest.mark.parametrize("printed, reading, unit", [
    ("ARR $22.9B at year end", 22_900_000_000, None), ("ARR $22.9 Bn at year end", 22_900_000_000, None),
    ("Bookings 12MM in the year", 12_000_000, None), ("Bookings 3.5Mn in the year", 3_500_000, None),
    ("Pipeline EUR 450K open", 450_000, None), ("Pipeline EUR 2.5M open", 2_500_000, None),
    ("Net loss -1.2m for the year", -1_200_000, None), ("Net loss -1.2m for the year", 1_200_000, None),
    ("Cost of sales (3,400) in the year", -3400, None), ("Cost of sales (3,400) in the year", 3400, None),
    ("Cost of sales $(1.2)M in the year", -1_200_000, None),
    ("Churn 4.5% a month", 4.5, "%"), ("Margin (8%) this year", -8, "%"),
])
def test_page_figure_suffixes_signs_brackets_and_percent_are_read_the_way_the_prompt_describes(printed, reading, unit):
    got = check_deck([{"page": 2, "text": printed, "kind": "text"}], candidate(reading, unit=unit, currency=None if unit == "%" else "USD"))
    assert got["outcome"] == "confirmed", printed


def test_a_suffix_multiplies_the_printed_number_and_a_wrong_scale_is_still_not_a_match():
    page = [{"page": 2, "text": "ARR $22.9B at year end", "kind": "text"}]
    assert check_deck(page, candidate(22.9, currency="USD"))["outcome"] == "cannot_check", "22.9 against 22.9B: the scale differs"
    assert check_deck(page, candidate(23_900_000_000, currency="USD"))["outcome"] == "rejected"


def test_a_date_only_claim_cannot_be_checked_because_it_has_no_value_not_because_it_has_no_cell():
    got = check_deck([{"page": 2, "text": "Launch planned for Q3 2025", "kind": "text"}], candidate(None, claim_type="product"))
    assert got["outcome"] == "cannot_check" and got["reason"] == "No value to compare; date only."
    nothing = check_deck([{"page": 2, "text": "Launch", "kind": "text"}], candidate(None, period_text=None, target_date=None))
    assert nothing["reason"] == checks.C_NO_REF, "no value and no period keeps the old reason"
