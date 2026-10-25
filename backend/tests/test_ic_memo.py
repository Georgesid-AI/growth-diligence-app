"""The IC memo (docs/specs/verdict-and-memo.md section 7, docs/design/simplified-flow.md): what it refuses, what it carries, and that
every number in sections 1-6 has a footnote resolved in Appendix D. It exports with no rating, judgment, gate edit or confirmation. The memo module is pure; the endpoint tests run on the in-memory Mongo stub. No network.
"""
import copy
import logging
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from claim_matching_support import answer_definition  # noqa: E402
from test_claim_matching import RUNS, candidates_for, results_for, settings  # noqa: E402
from test_claim_register_api import AUDIT, _put  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import formatting as fmt  # noqa: E402
from app import ic_memo as im  # noqa: E402
from app import verdict as vd  # noqa: E402

THESIS = {"plan": "Reach the target ARR with the current segment mix.", "evidence": "ARR is 202,125 EUR at the as-of month.",
          "condition": "The contradicted claims are re-based before closing."}
FILES = [{"dtype": "revenue", "file": "revenue.csv", "sheet": "CSV"}, {"dtype": "crm", "file": "crm.csv", "sheet": "CSV"},
         {"dtype": "pnl", "file": "pnl.csv", "sheet": "CSV"}]
DECKS = [{"file": "testco_board.pptx"}]
GATE_DECISION = "the Series B hiring plan"


def narrative(headline="The growth engine is steady.", flagging=("Win rate is below the claim.",), status="ok"):
    return {"step": "growth_engine", "narrative_status": status, "model": "claude-sonnet-5-5", "generated_at": "2026-10-08T10:00:00+00:00",
            "narrative": {"headline": headline, "what_this_means": "x", "table_rows": [], "worth_flagging": list(flagging),
                          "next_actions": [], "source_keys": []}}


def inputs(run="A", decision=None, thesis=None, narratives=(), files=None, decks_=None, blockers=(), tables=(), stored=None,
           answers=None, note=None, saved=False, open_questions=0, **extra):
    """Everything build_memo reads, for one fixture run, as the server hands it over: the five the app selects, the gates written from the
    claims (`saved`: the analyst edited the gate of each of the five, with `decision` as the budget decision), no rating, judgment or
    confirmation. `answers`: the analyst's Definition check answers by claim id (claim-matching.md section 4.1)."""
    r = RUNS[run]
    results = stored if stored is not None else results_for(r)

    def answered(cands):
        asked = cm.build_register(cands, results, settings(r))
        for cid, answer in (answers or {}).items():
            answer_definition(cands, asked, cid, answer)
        return cands
    first = cm.build_register(answered(candidates_for(r)), results, settings(r))
    top = vd.proposal(first)
    cands = answered(candidates_for(r))
    if saved:
        for c in cands:
            for cid in top:
                if cid.split("#")[0] == c["id"]:
                    gate = {"gate_threshold": 150000.0, "gate_date": "2024-06-30", **({"gate_budget_decision": decision} if decision else {})}
                    c.setdefault("claim_inputs", {}).setdefault(cid, {}).update(gate)
    rows = vd.mark_key_gates(cm.build_register(cands, results, settings(r)), top)
    ver = vd.verdict(rows, results, None, open_questions)
    ic = {"thesis": dict(thesis or {}), "first_quarterly_review": "2024-09-30", "open_questions": open_questions,
          **({"note": note} if note else {})}
    return dict(audit={"company_name": "TestCo", "target_arr": 1_000_000, "target_date": "2026-12-31", "as_of_month": "2024-02"},
                results=results, rows=rows, ver=ver, key=vd.key_gates(rows, top), ic=ic, today="2026-10-08",
                gaps=vd.data_gaps(results, rows, top), blockers=list(blockers), narratives=list(narratives),
                files=files if files is not None else FILES,
                decks=decks_ if decks_ is not None else DECKS, tables=list(tables), **extra)


def memo(**kw):
    return im.build_memo(**inputs(**kw))


def refusal(**kw):
    with pytest.raises(im.MemoRefused) as exc:
        memo(**kw)
    return exc.value


def head_of(text):
    return text.split("## Appendix A")[0]


# --- the refusals (section 7.1) ----------------------------------------------------------------------------------------------

def test_the_memo_is_built_from_the_run_a_fixture_in_the_order_of_w15_with_the_four_appendices():
    text = memo(narratives=[narrative()])
    headings = re.findall(r"^## (.+)$", text, re.M)
    assert headings == ["Summary", "Deal thesis", "Scorecard", "Key gates and deal terms", "Worth flagging",
                        "Data gaps and requests", "Appendix A – Claim register and gates",
                        "Appendix B – Data gaps and data request list", "Appendix C – Detailed analysis tables",
                        "Appendix D – Source key list and value-at-risk de-duplication"]
    assert text.startswith("# Investment committee memo: TestCo\nDate: 2026-10-08\n")
    summary = head_of(text).split("## Summary\n")[1]
    assert summary.startswith("Claim-review conclusion — assessment of the five selected claims\n"
                              "Verdict: Selected claims not supported – 4 selected claims are Contradicted.")
    assert "This assesses the five claims the analyst selected. It is not an investment recommendation." in summary
    assert "Conclusion:" not in text and "Evidence supports the plan" not in text
    assert text.count("Selected by the app by value at stake; the analyst may change the selection.") == 1
    assert "Top 5 set by the analyst pending" not in text, "W24 is gone: the app picks the five"
    assert head_of(text).index("Selected by the app by value at stake") < head_of(text).index("## Deal thesis")


def test_the_run_a_memo_fits_1500_words_and_every_number_in_sections_1_to_6_has_a_footnote_resolved_in_appendix_d():
    text = memo(narratives=[narrative()])
    head = head_of(text)
    assert im.count_words(head) <= 1500 and im.word_count_of(text) == im.count_words(head)
    defined = set(re.findall(r"^\[\^(\d+)\]: ", text, re.M))
    assert {m for m in re.findall(r"\[\^(\d+)\]", head)} <= defined, "every marker is resolved in Appendix D"
    fixed = {str(n) for n in im.FIXED_NUMERALS}
    for line in head.split("\n"):
        if line.startswith("Date: ") or line.startswith("# "):
            continue
        numbers = [t for t in im._tokens(line) if t not in fixed]
        if numbers:
            assert re.search(r"\[\^\d+\]", line), f"a number without a footnote: {line!r}"
    assert "[^1]: claim register, #1, #2, #3, #5, #6" in text
    assert re.search(r"\[\^\d+\]: Monthly MRR by Segment · arr.value · revenue.csv · CSV · rows 2–71", memo())


def test_the_date_line_is_the_only_line_the_number_check_skips():
    text = memo()
    assert "Date: 2026-10-08" in text
    ok = inputs()
    ok["today"] = "2031-07-19"
    assert "Date: 2031-07-19" in im.build_memo(**ok)


def test_the_memo_exports_with_no_confirmation_no_gate_edit_no_rating_no_judgment_and_no_thesis():
    """simplified-flow.md: the refusals for an unconfirmed top 5, a blocked verdict, 3 to 5 key gates, a missing rating, judgment or thesis are gone."""
    kw = inputs()
    assert kw["ic"].get("thesis") == {} and "ratings" not in kw["ic"] and "judgment" not in kw["ic"] and not kw["ic"].get("note")
    text = im.build_memo(**kw)
    assert "Verdict: Selected claims not supported" in text and "Analyst note:" not in text
    kw = inputs(run="D", open_questions=1)
    assert any(r["definition_check"] == "ask" for r in kw["rows"]), "an open Definition check no longer blocks"
    assert "1 question open." in im.build_memo(**kw), "it is a count on the rule line"
    assert "question open" not in text


def test_a_never_tested_row_is_in_the_data_gaps_table_with_the_reason_it_cannot_be_measured():
    kw = inputs()
    last = kw["rows"][-1]
    kw["rows"][-1] = {**last, "claim_type": "pricing", "reason": cm.PRICING_NOTE, "gate_sentence": None, "gate_status": None}
    assert cm.is_untested(kw["rows"][-1])
    text = im.build_memo(**kw)
    section = text.split("## Data gaps and requests")[1].split("## Appendix A")[0]
    assert "1 claim is never tested against data; the reason for each is in Appendix B" in section
    table = text.split("## Appendix B")[1].split("Requests")[0]
    assert f"#{last['rank']} " in table and f"Cannot be measured: {cm.PRICING_NOTE}." in table
    assert "never tested against data" not in memo(), "a register of tested claims adds neither the line nor the rows"
    assert "Cannot be measured" not in memo()


def test_the_key_gates_are_those_of_the_non_verified_top_5_rows_never_padded():
    text = memo()
    section = head_of(text).split("## Key gates and deal terms")[1].split("## Worth flagging")[0]
    assert section.count("\n- ") == 4 and section.count("(proposed)") == 4, "the fifth of the five is Verified: no gate"
    verified_five = inputs()
    top = vd.proposal(verified_five["rows"])
    fewer = [{**r, "gate_sentence": None, "gate_status": None} if r["rank"] > 2 else r for r in verified_five["rows"]]
    verified_five.update(rows=fewer, key=vd.key_gates(fewer, top))
    text = im.build_memo(**verified_five)
    assert "2 gates set; all are key gates." in text


def test_results_that_fail_the_contract_refuse_and_name_the_fields_not_the_value():
    kw = inputs()
    bad = copy.deepcopy(kw["results"])
    bad["nrr"]["overall_pct"] = 106.41
    kw["results"] = bad
    with pytest.raises(im.MemoRefused) as exc:
        im.build_memo(**kw)
    assert exc.value.code == "contract" and "nrr.overall_pct" in exc.value.message and "106" not in exc.value.message
    assert exc.value.message.startswith("Memo not exported: the stored results fail the contract: ")


# --- the number check (section 7.4) ---------------------------------------------------------------------------------------------

def test_a_number_absent_from_the_stored_results_in_a_narrative_paragraph_refuses_and_is_listed():
    bad = narrative(flagging=("Churn will fall to 37% next year.",))
    exc = refusal(narratives=[bad])
    assert exc.code == "numbers" and exc.unmatched == ["37"]
    assert exc.message == "Memo not exported: 1 numbers are not in the stored results: 37."


def test_a_thesis_sentence_carrying_a_number_absent_from_the_stored_results_refuses_and_is_listed():
    exc = refusal(thesis={**THESIS, "plan": "Grow 37% a year to the target."})
    assert exc.code == "numbers" and exc.unmatched == ["37"]


def test_a_thesis_number_must_be_in_the_results_or_the_register_not_in_the_analysts_deal_terms_and_not_in_the_cost_log():
    assert "202,125" in memo(thesis={**THESIS, "evidence": "ARR is 202,125 EUR now."})
    exc = refusal(thesis={**THESIS, "plan": "Fund the 2025 plan."}, decision="the 2025 plan", saved=True)
    assert exc.unmatched == ["2025"], "a number of the budget decision is a deal term, not evidence"
    assert refusal(thesis={**THESIS, "condition": "The audit used 4321 tokens."}).unmatched == ["4321"], "the cost log is not evidence"


def test_a_number_in_a_budget_decision_passes_and_is_cited_set_by_the_analyst():
    text = memo(decision="the 37 hire plan", saved=True)
    section = head_of(text).split("## Key gates and deal terms")[1].split("## Worth flagging")[0]
    key_line = next(line for line in section.split("\n") if "the 37 hire plan" in line)
    note = re.search(r"\[\^(\d+)\]", key_line).group(1)
    assert re.search(rf"^\[\^{note}\]: .*set by the analyst", text, re.M)


def test_a_gate_metric_name_number_is_a_deal_term_too():
    kw = inputs()
    kw["rows"] = [{**r, "gate_metric_name": "Pipeline cover 37"} for r in kw["rows"]]
    assert im.build_memo(**kw)


def test_a_figure_written_as_the_formatter_writes_it_is_accepted_by_its_kind_and_nothing_else_is():
    kw = inputs()
    allowed = im.allowed_numbers(kw["audit"], kw["results"], kw["rows"], kw["gaps"], kw["ic"], kw["files"], kw["decks"],
                                 thesis=False)
    assert im.unmatched("ARR 202,125 EUR, NRR 113%, gross margin 78%, 59 days (58.5 days stored)", allowed) == []
    assert im.unmatched("37% and 4,100 EUR and 113.2%", allowed) == ["37", "4,100", "113.2"]
    assert im.unmatched("rows 2–71", allowed) == [], "a citation's own text is stored data"


def test_dates_months_quarters_and_footnote_markers_are_not_numbers():
    assert im._tokens("Q4 2023-Q4 2024-02 2024-03-31 [^12] [^3]: top-5 L1 p12 slide 4") == ["5", "4"]


# --- the word count (section 7.5) -------------------------------------------------------------------------------------------------

def test_words_are_tokens_with_a_letter_or_a_digit_pipes_and_heading_marks_are_not():
    assert im.count_words("## Summary\n| a | b |\n|---|---|\n- one[^1] two [^2] ***") == 6


def _padded(words):
    return narrative(headline=" ".join(["word"] * words))


def test_the_memo_passes_at_1500_words_and_refuses_at_1501_showing_the_count():
    base = im.word_count_of(memo(narratives=[_padded(1)]))
    ok = memo(narratives=[_padded(1500 - base + 1)])
    assert im.word_count_of(ok) == 1500
    exc = refusal(narratives=[_padded(1500 - base + 2)])
    assert exc.code == "words" and exc.words == 1501
    assert exc.message == "Memo not exported: 1,501 words; the limit is 1,500."


def test_the_appendices_are_not_counted():
    base = im.word_count_of(memo(narratives=[_padded(1)]))
    many_files = [{"dtype": "revenue", "file": f"file{i}.csv", "sheet": "CSV"} for i in range(40)]
    text = memo(narratives=[_padded(1500 - base + 1)], files=many_files)
    assert im.word_count_of(text) == 1500 + 0 or im.word_count_of(text) <= 1500
    assert len(text.split()) > 1500, "the appendices make the file longer than the limit"


# --- the scorecard (section 7.2) ------------------------------------------------------------------------------------------------------

def test_four_rows_are_not_assessed_and_never_carry_a_rating():
    text = memo()
    rows = {line.split("|")[1].strip(): [c.strip() for c in line.split("|")[2:-1]] for line in text.split("\n")
            if line.startswith("| ") and line.split("|")[1].strip() in
            ("Strategic coherence", "Forecast track record", "Execution capacity", "Defensibility")}
    assert rows == {
        "Strategic coherence": ["Not assessed – strategy documents not ingested", "", ""],
        "Forecast track record": ["Not assessed – past budgets and forecasts not ingested", "", ""],
        "Execution capacity": ["Not assessed – hiring plan and organisation data not ingested", "", ""],
        "Defensibility": ["Not assessed – market and competitor data not ingested", "", ""]}


def test_the_two_assessed_rows_carry_the_computed_rating_its_rule_line_and_the_w17_headline():
    text = memo()
    reliability = next(line for line in text.split("\n") if line.startswith("| Data reliability |"))
    assert reliability.split("|")[2].strip() == "Weak", "Material concerns is Weak"
    assert "Weak: at least one check Red, 5 of 5 completed." in reliability
    assert "Revenue file and P&L differ by 69.61% over 2023-03–2024-02" in reliability
    assert "0 anomaly flags" in reliability and "9 of 33 claims Verified" in reliability
    growth = next(line for line in text.split("\n") if line.startswith("| Growth engine |"))
    assert growth.split("|")[2].strip() == "Adequate"
    assert "Adequate: NRR 113%, gross churn 0%, CAC payback not computed (benchmark, not company data)." in growth


def test_a_rating_with_a_missing_input_reads_not_rated_and_names_it():
    kw = inputs()
    bare = copy.deepcopy(kw["results"])
    bare["nrr"] = None
    bare["gross_churn"] = None
    kw["results"] = bare
    growth = next(line for line in im.build_memo(**kw).split("\n") if line.startswith("| Growth engine |"))
    assert growth.split("|")[2].strip() == "not rated – data missing"
    assert "not rated – data missing: NRR, gross revenue churn not computed (benchmark, not company data)." in growth


def test_data_reliability_says_no_pnl_to_reconcile_when_there_is_none():
    kw = inputs()
    results = copy.deepcopy(kw["results"])
    results["revenue_reconciliation"] = {"available": False, "reason": "no P&L", "by_month": []}
    kw["results"] = results
    text = im.build_memo(**kw)
    assert "no P&L to reconcile" in text


def test_the_growth_engine_headline_is_the_narratives_when_it_is_current_and_ok():
    text = memo(narratives=[narrative(headline="Growth is steady and the engine holds.")])
    assert "Growth is steady and the engine holds." in head_of(text)
    assert im.S17 not in head_of(text)
    assert "Win rate is below the claim." in head_of(text), "its worth_flagging items are in section 5"


@pytest.mark.parametrize("narratives", [[], [narrative(status="flagged")], [narrative(status="unavailable")]],
                         ids=["none", "flagged", "unavailable"])
def test_without_a_narrative_the_memo_carries_every_figure_with_its_footnote_and_the_s17_note(narratives):
    text = memo(narratives=narratives)
    head = head_of(text)
    growth = next(line for line in head.split("\n") if line.startswith("| Growth engine |"))
    assert re.search(r"ARR 202,125 EUR \(2024-02\)\[\^\d+\], NRR 113% \(2024-02\)\[\^\d+\], gross revenue churn 0% \(2024-02\)\[\^\d+\]", growth)
    assert im.S17 in growth and im.S17 in head.split("## Worth flagging")[1]
    assert "The growth engine is steady." not in text


def test_the_summary_counts_the_definition_checks_answered_and_worth_flagging_lists_a_yes_once():
    """claim-matching.md section 4.1: run D's c37 (New MRR €5,000 claimed, 0 observed) asks its Definition check; the memo is
    refused while it is open, and once answered the summary counts the answers and Worth flagging names a Yes with its gloss."""
    open_text = memo(run="D", open_questions=1)
    assert "1 question open." in head_of(open_text), "an open Definition check no longer blocks: the rule line counts it"
    text = memo(run="D", answers={"c37": "yes"})
    summary = head_of(text).split("## Deal thesis")[0]
    assert re.search(r"^Definition checks: 1 answered Yes, 0 answered No\.\[\^\d+\]$", summary, re.M), summary
    section = head_of(text).split("## Worth flagging")[1].split("## Data gaps")[0]
    line = "- #1 New MRR (see glossary), Q4 2023: Contradicted, €5,000 lower (miss). Same metric and period confirmed by the analyst."
    assert sum(1 for item in section.splitlines() if item.startswith(line)) == 1, section
    banner = {"kind": "claim_contradicted", "claim_id": "c37", "text": "Top-5 claim contradicted: revenue 5,000 EUR vs 0 EUR observed."}
    shown = head_of(memo(run="D", answers={"c37": "yes"}, blockers=[banner])).split("## Worth flagging")[1].split("## Data gaps")[0]
    assert banner["text"] in shown and line not in shown, "a Yes the banner already lists is not repeated"
    no = head_of(memo(run="D", answers={"c37": "no"}))
    assert "Definition checks: 0 answered Yes, 1 answered No." in no and "Same metric and period confirmed" not in no
    assert "Definition checks" not in head_of(memo()), "run A asks none: the line is left out"


def test_worth_flagging_lists_every_verified_beat_with_its_gloss_after_the_blockers():
    """Amended 2026-10-13 (George): a beat outside tolerance is Verified, so Worth flagging lists it to keep a large beat visible.
    A beat within tolerance is plain Verified and is not listed."""
    blocker = {"kind": "revenue_file_missing", "text": "Revenue file missing: upload and map it to compute metrics."}
    text = memo(narratives=[narrative()], blockers=[blocker])
    section = head_of(text).split("## Worth flagging")[1].split("## Data gaps")[0]
    items = [line for line in section.split("\n") if line.startswith("- ")]
    assert items[0] == f"- {blocker['text']}"
    assert re.fullmatch(r"- #10 Customer count, Feb 2024: Verified, 1 customer more \(beat\)\.\[\^\d+\]", items[1])
    assert items[2].startswith("- Win rate is below the claim."), "the narrative's items follow"
    assert len(items) == 3, "c01, a beat within tolerance, is not listed"
    marker = re.search(r"\[\^(\d+)\]$", items[1]).group(1)
    assert f"[^{marker}]: claim register, #10" in text


def test_the_memo_never_generates_a_narrative_or_reads_the_model():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(im))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
        {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not [m for m in imported if "llm" in m or "anthropic" in m or "server" in m]


# --- evidence categories (section 7.2) ---------------------------------------------------------------------------------------------------

def test_revenue_crm_pnl_and_a_deck_cover_4_of_7_and_revenue_only_covers_1():
    full = memo()
    assert "Evidence categories covered: 4 of 7." in full
    only = memo(files=FILES[:1], decks_=[])
    assert "Evidence categories covered: 1 of 7." in only and "Files reviewed: 1 data file and 0 decks." in only
    table = only.split("Files reviewed\n")[1].split("\n\n")[0]
    assert "| Monthly revenue by customer | yes | revenue.csv (CSV) |  |" in table
    assert "| P&L and budget vs actuals | no |" in table
    assert "| Board decks, last 6–8 quarters | no |" in table


def test_partial_coverage_is_noted_in_appendix_d_not_counted_as_half():
    table = memo().split("Files reviewed\n")[1].split("\n\n")[0]
    assert "budget vs actuals is not ingested" in table
    assert "the app does not check which quarters the decks cover" in table
    assert table.count("| no |") == 3 and table.count("not ingested by the app") == 3


# --- value at risk, the appendices ------------------------------------------------------------------------------------------------------------

def test_value_at_risk_reads_not_yet_computed_in_the_summary_and_appendix_d_with_the_method():
    text = memo()
    line = ("Value at risk: ARR (see glossary) not yet computed (ARR bridge not run); cash not yet computed (no cash analysis). "
            "Overlapping claims are counted once, at the largest value in their group.")
    assert head_of(text).count(line) == 1 and text.count(line) == 2
    assert "Overlap groups: #1, #7;" in text


def test_the_appendices_carry_the_register_the_gaps_and_the_tables_and_no_cost_table():
    tables = [{"sheet": "Headline", "rows": [["Metric", "Value"], ["Company", "TestCo"]]}]
    text = memo(tables=tables)
    a = text.split("## Appendix A")[1].split("## Appendix B")[0]
    assert a.count("\n| #") == 33 + 1 and "top 5" in a and "key" in a
    b = text.split("## Appendix B")[1].split("## Appendix C")[0]
    assert "First quarterly review: 2024-09-30" in b and "Required vs observed net-new customers (12m)" in b
    assert "Headline[^" in text.split("## Appendix C")[1]
    d = text.split("## Appendix D")[1]
    assert not re.search(r"(?i)AI usage|Cost \(USD\)|Input tokens|Output tokens|\btokens\b", text), "cost is hidden from testers (usage-and-allowance.md section 9)"
    assert "Deck structure reading" not in d and "Column mapping" not in d


# --- the endpoint -----------------------------------------------------------------------------------------------------------------------------------

def _ready(client, decision=None, edit_gates=False):
    """Nothing is required before the download. `edit_gates`: the analyst also edits each gate of the five in force."""
    if edit_gates:
        ids = client.get(f"/api/audits/{AUDIT}/verdict").json()["verdict"]["top5"]["in_force"]
        for n, cid in enumerate(ids):
            body = {"gate_threshold": 100.0 + n, "gate_date": "2024-06-30", **({"gate_budget_decision": decision} if decision else {})}
            assert _put(client, cid, body).status_code == 200


def test_the_endpoint_downloads_the_memo_as_markdown_named_after_the_company(register_api):
    client, db = register_api
    db["audits"].docs[0]["company_name"] = "Test Co / Ltd"
    _ready(client)
    r = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/markdown")
    assert 'filename="Test_Co__Ltd_ic_memo.md"' in r.headers["content-disposition"]
    assert r.text.startswith("# Investment committee memo: Test Co / Ltd\n")
    assert "Evidence categories covered: 1 of 7." in r.text or "of 7." in r.text
    assert im.word_count_of(r.text) <= 1500 and "## Appendix D" in r.text


def test_the_memo_is_built_on_request_and_never_stored_and_no_model_is_called(register_api):
    client, db = register_api
    _ready(client)
    before = {name: copy.deepcopy(col.docs) for name, col in db._cols.items()}
    assert client.get(f"/api/audits/{AUDIT}/memo.md").status_code == 200
    after = {name: col.docs for name, col in db._cols.items() if name in before}
    assert all(after[name] == before[name] for name in before), "a memo writes nothing"
    assert not db["llm_calls"].docs and not db["llm_narratives"].docs, "a memo makes no call and generates no narrative"
    assert not any("memo" in name for name in db._cols)


def test_the_endpoint_downloads_a_fresh_audit_with_nothing_confirmed_filled_or_rated(register_api):
    client, db = register_api
    before = copy.deepcopy([col.docs for col in db._cols.values()])
    r = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert r.status_code == 200, r.text
    assert "Verdict: Selected claims" in r.text and "(proposed)" in r.text and "Analyst note:" not in r.text
    assert before == [col.docs for col in db._cols.values()][:len(before)], "a download writes nothing, not even the auto-entered claims"


def test_the_analyst_note_is_one_line_in_the_memo_and_nothing_else_changes(register_api):
    client, _ = register_api
    plain = client.get(f"/api/audits/{AUDIT}/memo.md").text
    assert client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"note": "Call with the CFO booked for 3 Nov."}).status_code == 200
    noted = client.get(f"/api/audits/{AUDIT}/memo.md").text
    line = next(x for x in noted.split("\n") if x.startswith("Analyst note: "))
    assert line.startswith("Analyst note: Call with the CFO booked for 3 Nov.[^")
    strip = lambda text: [re.sub(r"\[\^\d+\]", "", x) for x in text.split("\n") if not x.startswith(("Analyst note: ", "[^"))]      # noqa: E731
    assert strip(noted) == strip(plain), "one added line"
    assert client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"note": "Raise 37% more."}).status_code == 200
    assert client.get(f"/api/audits/{AUDIT}/memo.md").status_code == 200, "the analyst's own numbers are the analyst's (section 7.4 d)"


def test_the_endpoint_refuses_only_for_a_bad_number_the_contract_or_no_results(register_api):
    client, db = register_api
    _ready(client, edit_gates=True)
    assert client.get(f"/api/audits/{AUDIT}/memo.md").status_code == 200
    client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"thesis": {**THESIS, "plan": "Grow 37% a year."}})
    detail = client.get(f"/api/audits/{AUDIT}/memo.md").json()["detail"]
    assert detail == "Memo not exported: 1 numbers are not in the stored results: 37."
    client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"thesis": THESIS})
    bad = copy.deepcopy(db["audits"].docs[0]["results"])
    bad["nrr"]["overall_pct"] = 106.41
    db["audits"].docs[0]["results"] = bad
    detail = client.get(f"/api/audits/{AUDIT}/memo.md").json()["detail"]
    assert detail.startswith("Memo not exported: the stored results fail the contract: ") and "106" not in detail


def test_an_audit_with_no_results_refuses_with_the_compute_first_reason(register_api):
    client, db = register_api
    db["audits"].docs[0]["results"] = None
    r = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert r.status_code == 409 and "compute the audit first" in r.json()["detail"]


def test_the_export_log_line_holds_a_code_and_counts_only(register_api, caplog):
    client, _ = register_api
    _ready(client, decision="the Falcon hiring plan", edit_gates=True)
    with caplog.at_level(logging.DEBUG):
        client.get(f"/api/audits/{AUDIT}/memo.md")
        client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"thesis": {**THESIS, "plan": "Grow 37% a year."}})
        client.get(f"/api/audits/{AUDIT}/memo.md")
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("memo export")]
    assert lines == [f"memo export: run_id={AUDIT} status=ok reason=none words={int(lines[0].split('words=')[1].split()[0])} unmatched=0",
                     f"memo export: run_id={AUDIT} status=refused reason=numbers words=0 unmatched=1"]
    for needle in ("Falcon", "37", "Grow", "Reach the target", "TestCo", "testco_board", "Before "):
        assert needle not in " ".join(lines), needle


# --- Appendix C: derived cells are sums and differences of stored cells only ----------------------------------------------------------

def _table(*row):
    return [{"sheet": "Headline", "rows": [["Metric", "A", "B", "C"], list(row)]}]


def test_a_table_cell_that_is_the_sum_or_difference_of_two_stored_cells_of_its_row_passes():
    assert im.build_memo(**inputs(tables=_table("Total", "202,125", "81,431", "283,556")))
    assert im.build_memo(**inputs(tables=_table("Change", "283,556", "202,125", "81,431")))


@pytest.mark.parametrize("cells", [("Ratio", "283,556", "202,125", "1.4"), ("Product", "202,125", "81,431", "16,459,000,000"),
                                   ("Share", "81,431", "202,125", "40.29"), ("Alone", "81,431", "", "")])
def test_a_ratio_or_any_other_derived_figure_in_a_table_refuses(cells):
    exc = refusal(tables=_table(*cells))
    assert exc.code == "numbers" and exc.unmatched


def test_the_rule_text_says_is_for_one_contradicted_claim_and_are_for_more():
    """claim-review-conclusion.md section 2 (replaces W8)."""
    v, _ = verdict_of_labels(["Contradicted", "Verified", "Verified", "Verified", "Verified"], gates={1})
    assert v["rule"] == "1 selected claim is Contradicted."
    v, _ = verdict_of_labels(["Contradicted", "Contradicted", "Verified", "Verified", "Verified"], gates={1, 2})
    assert v["rule"] == "2 selected claims are Contradicted."
    v, _ = verdict_of_labels(["Unverified", "Unsupported", "Verified", "Verified", "Verified"], gates={1, 2})
    assert v["rule"] == "No selected claim is Contradicted; 3 of 5 are Verified, 2 untested."


def verdict_of_labels(labels, gates):
    from test_verdict import verdict_of
    return verdict_of(labels, gates=gates)


# --- abbreviations (George, 2026-10-09): Value at stake reads VaS; the first use in a text block points to the glossary ----------

def test_value_at_stake_reads_vas_and_each_abbreviation_points_to_the_glossary_once_per_text_block():
    text = memo(narratives=[narrative()])
    assert "| VaS |" in text and "Value at stake" not in text
    body, glossary = text.split("\nGlossary\n")
    for line in body.split("\n"):
        if line.startswith("|") or line.startswith("#") or line.startswith("[^"):
            assert "(see glossary)" not in line, f"a table, a heading or a footnote is not a text block: {line!r}"
            continue
        if line.startswith(("Reasons: ", "Unresolved questions: ")):      # the analyst's judgment is printed verbatim
            assert "(see glossary)" not in line, line
            continue
        for term in fmt.GLOSSED:
            uses = re.findall(rf"(?<![\w-]){term}(?![\w-])( \(see glossary\))?", line)
            if uses:
                assert uses[0] == " (see glossary)" and all(u == "" for u in uses[1:]), (term, line)
    glossary = glossary.split("\n\n")[0].split("\n")       # the glossary's own entries define the terms, unchanged
    assert glossary == [f"- {term}: {definition}" for term, definition in fmt.GLOSSARY.items()]
    assert "- VaS: value at stake: " in text
    # a source reference keeps its own words (the footnotes hold MRR, never with the pointer: checked above)
    assert [line for line in text.split("\n") if line.startswith("[^") and " MRR" in line]


# --- the data inventory (A1) and data integrity (A2) narratives ---------------------------------------------------------------

def data_step(step, headline="Material concerns: the revenue file and the P&L differ by 69.61%.", verdict="Material concerns",
              actions=(), status="ok"):
    n = narrative(headline=headline, status=status)
    n["step"] = step
    n["narrative"].update(next_actions=list(actions), verdict=verdict if step == "data_integrity" else None)
    return n


def reliability_row(text):
    return next(line for line in text.split("\n") if line.startswith("| Data reliability |"))


def appendix_b(text):
    return text.split("## Appendix B")[1].split("## Appendix C")[0]


def test_the_data_reliability_row_reads_the_integrity_conclusion_never_the_a2_verdict_and_the_rating_is_computed_from_it():
    """integrity-coverage.md section 4 (replaces the A2-verdict headline of 2026-10-08): the conclusion and the coverage head the row."""
    text = memo(narratives=[data_step("data_integrity")])
    row = reliability_row(text).split("|")
    assert row[2].strip() == "Weak", "computed from the integrity conclusion: Material concerns is Weak"
    assert row[3].strip().startswith("Material concerns. Completed 5 of 5 applicable checks.")
    assert "not a finding about the company" not in row[3], "the sentence belongs to Insufficient assessment coverage only"
    assert "Revenue file and P&L differ by 69.61% over 2023-03–2024-02" in row[3], "the computed line follows"
    assert row[4].strip() == "Data integrity conclusion: Material concerns; revenue_reconciliation, anomalies, claim register"
    assert "Material concerns: the revenue file and the P&L differ by 69.61%." not in text and "Data integrity verdict" not in text


@pytest.mark.parametrize("narratives", [[], [data_step("data_integrity", status="flagged")], [data_step("data_integrity", status="unavailable")],
                                        [data_step("data_integrity", verdict=None)], [data_step("data_inventory")]],
                         ids=["none", "flagged", "unavailable", "no verdict", "other step"])
def test_whatever_the_a2_narrative_the_row_keeps_the_computed_line(narratives):
    row = reliability_row(memo(narratives=narratives))
    assert "Revenue file and P&L differ by 69.61% over 2023-03–2024-02" in row and "Data integrity verdict" not in row


def test_appendix_b_takes_the_a1_data_request_list_in_its_order_and_the_other_appendices_do_not():
    actions = ["Ask management for the missing P&L months.", "Ask management for the CRM export."]
    text = memo(narratives=[data_step("data_inventory", actions=actions)])
    b = appendix_b(text)
    assert b.index(actions[0]) < b.index(actions[1])
    assert "Data request list from the data inventory, most important first" in b
    assert actions[0] not in head_of(text) and actions[0] not in text.split("## Appendix C")[1]


@pytest.mark.parametrize("narratives", [[], [data_step("data_inventory", actions=["Ask for X."], status="flagged")],
                                        [data_step("data_integrity", actions=["Ask for X."])]],
                         ids=["none", "flagged", "other step"])
def test_without_a_current_a1_narrative_appendix_b_has_no_request_list(narratives):
    assert "Data request list from the data inventory" not in appendix_b(memo(narratives=narratives))


def test_the_a2_headline_is_not_printed_so_a_number_in_it_never_reaches_the_memo():
    """integrity-coverage.md section 4: the A2 narrative's headline left the scorecard, so its figures are never checked or shown."""
    text = memo(narratives=[data_step("data_integrity", headline="Material concerns: the files differ by 77.31%.")])
    assert "77.31" not in text


@pytest.mark.parametrize("when", ["2026-10-08T14:43:00+00:00", "2026-10-08T09:57:12+00:00", "2026-10-08T23:59:00+00:00"])
def test_the_time_in_the_ai_disclosure_is_not_a_number_the_memo_must_find_in_the_results(when):
    """A narrative written at 14:43 UTC puts "14:43" in the disclosure block; its minutes are not a figure."""
    n = narrative()
    n["generated_at"] = when
    text = memo(narratives=[n])
    assert when[11:16] in text, "fixture: the time is in the memo"


# --- value at stake in Appendix A (George, 2026-10-24, PR 176 item 2) -----------------------------------------------------------

def _vas_cells(text):
    header = next(line for line in text.split("\n") if line.startswith("| #") and "| VaS |" in line)
    col = [c.strip() for c in header.strip("|").split("|")].index("VaS")
    return {line.split("|")[1].strip(): line.strip("|").split("|")[col].strip() for line in text.split("\n") if re.match(r"\| #\d+ ", line)}


def _memo_with_vas(amounts, **kw):
    ins = inputs(**kw)
    for r in ins["rows"]:
        r["value_at_stake_arr"] = amounts.get(r["rank"])
    return ins, im.build_memo(**ins)


def test_the_vas_column_prints_the_registers_amount_once_per_overlap_group_and_the_stored_reason_where_there_is_none():
    ins, text = _memo_with_vas({1: 1_200_000.0, 5: 300_000.0, 6: 450_000.0})
    cells = _vas_cells(text)
    by_rank = {r["rank"]: r for r in ins["rows"]}
    assert cells["#1"].startswith("€1,200,000") or cells["#1"].startswith("EUR 1,200,000")
    assert "450,000" in cells["#6"] and "counted in" not in cells["#6"], "the largest of its group carries the amount"
    assert "300,000" in cells["#5"] and "counted in #6" in cells["#5"], "a smaller overlapping claim is counted once, in the largest"
    assert by_rank[3]["vas_reason"] in cells["#3"], "no amount: the stored reason, as the register holds it"
    assert "not yet computed" not in cells["#1"]


def test_a_vas_amount_the_register_does_not_hold_refuses_the_memo():
    ins, _ = _memo_with_vas({1: 1_200_000.0})
    allowed = im.allowed_numbers(ins["audit"], ins["results"], ins["rows"], ins["gaps"], ins["ic"], ins["files"], ins["decks"], thesis=False)
    assert im.unmatched("| #1 | EUR 1,200,000 |", allowed) == []
    assert im.unmatched("| #1 | EUR 1,200,001 |", allowed) == ["1,200,001"]
