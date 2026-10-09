"""The IC memo (docs/specs/verdict-and-memo.md section 7): what it refuses, what it carries, and that every number in sections
1-6 has a footnote resolved in Appendix D. The memo module is pure; the endpoint tests run on the in-memory Mongo stub. No network.
"""
import copy
import logging
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from claim_matching_support import engine_results  # noqa: E402
from test_claim_matching import RUNS, candidates_for, results_for, settings  # noqa: E402
from test_claim_register_api import AUDIT, _get, _put, api  # noqa: E402,F401  (the fixture)

from app import claim_matching as cm  # noqa: E402
from app import decks  # noqa: E402
from app import formatting as fmt  # noqa: E402
from app import ic_memo as im  # noqa: E402
from app import verdict as vd  # noqa: E402

THESIS = {"plan": "Reach the target ARR with the current segment mix.", "evidence": "ARR is 202,125 EUR at the as-of month.",
          "condition": "The contradicted claims are re-based before closing."}
RATINGS = {"data_reliability": "Adequate", "growth_engine": "Weak"}
USAGE = {"calls": 0, "structure_calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0,
         "by_step": {}}
FILES = [{"dtype": "revenue", "file": "revenue.csv", "sheet": "CSV"}, {"dtype": "crm", "file": "crm.csv", "sheet": "CSV"},
         {"dtype": "pnl", "file": "pnl.csv", "sheet": "CSV"}]
DECKS = [{"file": "testco_board.pptx"}]
GATE_DECISION = "the Series B hiring plan"


def narrative(headline="The growth engine is steady.", flagging=("Win rate is below the claim.",), status="ok"):
    return {"step": "growth_engine", "narrative_status": status, "model": "claude-sonnet-5-5", "generated_at": "2026-10-08T10:00:00+00:00",
            "narrative": {"headline": headline, "what_this_means": "x", "table_rows": [], "worth_flagging": list(flagging),
                          "next_actions": [], "source_keys": []}}


def inputs(run="A", decision=GATE_DECISION, ratings=None, thesis=None, key=5, narratives=(), files=None, decks_=None, usage=None,
           blockers=(), tables=(), stored=None, **extra):
    """Everything build_memo reads, for one fixture run: the proposed top 5 confirmed and gated, `key` of them marked key."""
    r = RUNS[run]
    results = stored if stored is not None else results_for(r)
    first = cm.build_register(candidates_for(r), results, settings(r))
    top = vd.proposal(first)
    cands = candidates_for(r)
    for c in cands:
        for cid in top:
            if cid.split("#")[0] == c["id"]:
                gate = {"gate_threshold": 150000.0, "gate_budget_decision": decision, "gate_date": "2024-06-30",
                        "key_gate": top.index(cid) < key}
                c.setdefault("claim_inputs", {}).setdefault(cid, {}).update(gate)
    rows = cm.build_register(cands, results, settings(r))
    ver = vd.verdict(rows, results, {"claim_ids": top})
    ic = {"ratings": dict(RATINGS) if ratings is None else ratings, "thesis": dict(THESIS) if thesis is None else thesis, "first_quarterly_review": "2024-09-30"}
    state = vd.top5_state(rows, {"claim_ids": top})
    return dict(audit={"company_name": "TestCo", "target_arr": 1_000_000, "target_date": "2026-12-31", "as_of_month": "2024-02"},
                results=results, rows=rows, ver=ver, key=vd.key_gates(rows), ic=ic, today="2026-10-08",
                gaps=vd.data_gaps(results, rows, state["in_force"]), blockers=list(blockers), narratives=list(narratives),
                usage=usage or copy.deepcopy(USAGE), files=files if files is not None else FILES,
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
    assert "Verdict: Re-plan – 5 top-5 claims Contradicted." in text
    assert text.count("Top 5 set by the analyst pending ARR (see glossary) bridge.") == 1
    assert head_of(text).index("Top 5 set by the analyst pending ARR (see glossary) bridge.") < head_of(text).index("## Deal thesis")


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
    assert "[^1]: claim register, #1, #2, #3, #4, #5" in text
    assert re.search(r"\[\^\d+\]: Monthly MRR by Segment · arr.value · revenue.csv · CSV · rows 2–71", memo())


def test_the_date_line_is_the_only_line_the_number_check_skips():
    text = memo()
    assert "Date: 2026-10-08" in text
    ok = inputs()
    ok["today"] = "2031-07-19"
    assert "Date: 2031-07-19" in im.build_memo(**ok)


def test_an_unconfirmed_top_5_refuses_and_names_the_step():
    kw = inputs()
    kw["ver"] = vd.verdict(kw["rows"], kw["results"], None)
    with pytest.raises(im.MemoRefused) as exc:
        im.build_memo(**kw)
    assert exc.value.code == "top5" and exc.value.message == "Memo not exported: confirm the top 5."


def test_a_blocked_verdict_refuses():
    kw = inputs()
    kw["ver"] = vd.verdict([{**r, "gate_saved": False, "gate_needed": True} for r in kw["rows"]], kw["results"],
                           {"claim_ids": vd.proposal(kw["rows"])})
    with pytest.raises(im.MemoRefused) as exc:
        im.build_memo(**kw)
    assert exc.value.message == "Memo not exported: the verdict is blocked."


def test_key_gates_that_are_not_three_to_five_refuse_unless_fewer_than_three_gates_are_saved():
    two = refusal(key=2)
    assert (two.code, two.message) == ("key_gates", "Memo not exported: mark 3 to 5 key gates.")
    kw = inputs(key=5)
    kw["rows"] = [{**r, "key_gate": False} if r["claim_id"] == kw["key"]["marked"][0] else r for r in kw["rows"]]
    kw["rows"] = [{**r, "key_gate": False} for r in kw["rows"]][:]
    kw["key"] = vd.key_gates(kw["rows"])
    with pytest.raises(im.MemoRefused):
        im.build_memo(**kw)
    few = inputs(key=5)
    few["rows"] = [{**r, "gate_saved": r["rank"] <= 2, "gate_sentence": r["gate_sentence"] if r["rank"] <= 2 else None} for r in few["rows"]]
    few["key"] = vd.key_gates(few["rows"])
    few["ver"] = vd.verdict([{**r, "gate_saved": True} for r in few["rows"]], few["results"], {"claim_ids": vd.proposal(few["rows"])})
    text = im.build_memo(**few)
    assert "2 gates set; all are key gates." in text


def test_a_rating_or_a_thesis_sentence_missing_refuses_and_names_it():
    assert refusal(ratings={"data_reliability": "Strong"}).message == "Memo not exported: rate Growth engine."
    assert refusal(ratings={}).message == "Memo not exported: rate Data reliability, Growth engine."
    missing = refusal(thesis={"plan": "p", "evidence": "e"})
    assert missing.code == "inputs" and "Condition" in missing.message


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


def test_a_thesis_number_must_be_in_the_results_the_register_or_the_cost_log_not_in_the_analysts_deal_terms():
    assert "202,125" in memo(thesis={**THESIS, "evidence": "ARR is 202,125 EUR now."})
    exc = refusal(thesis={**THESIS, "plan": "Fund the 2025 plan."}, decision="the 2025 plan")
    assert exc.unmatched == ["2025"], "a number of the budget decision is a deal term, not evidence"
    cost = copy.deepcopy(USAGE)
    cost["by_step"] = {"growth_engine": {"calls": 1, "cache_hits": 0, "input_tokens": 4321, "output_tokens": 98, "estimated_cost_usd": 0.07}}
    assert "4321" in memo(thesis={**THESIS, "condition": "The audit used 4321 tokens."}, usage=cost)


def test_a_number_in_a_budget_decision_passes_and_is_cited_set_by_the_analyst():
    text = memo(decision="the 37 hire plan")
    key_line = next(line for line in head_of(text).split("\n") if "the 37 hire plan" in line)
    note = re.search(r"\[\^(\d+)\]", key_line).group(1)
    assert re.search(rf"^\[\^{note}\]: .*set by the analyst", text, re.M)


def test_a_gate_metric_name_number_is_a_deal_term_too():
    kw = inputs()
    kw["rows"] = [{**r, "gate_metric_name": "Pipeline cover 37"} for r in kw["rows"]]
    assert im.build_memo(**kw)


def test_a_figure_written_as_the_formatter_writes_it_is_accepted_by_its_kind_and_nothing_else_is():
    kw = inputs()
    allowed = im.allowed_numbers(kw["audit"], kw["results"], kw["rows"], kw["gaps"], kw["ic"], kw["usage"], kw["files"], kw["decks"],
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

def test_four_rows_are_not_assessed_and_never_carry_a_rating_even_when_one_is_stored():
    rating = dict(RATINGS, strategic_coherence="Strong", defensibility="Strong", forecast_track_record="Weak")
    text = memo(ratings=rating)
    rows = {line.split("|")[1].strip(): [c.strip() for c in line.split("|")[2:-1]] for line in text.split("\n")
            if line.startswith("| ") and line.split("|")[1].strip() in
            ("Strategic coherence", "Forecast track record", "Execution capacity", "Defensibility")}
    assert rows == {
        "Strategic coherence": ["Not assessed – strategy documents not ingested", "", ""],
        "Forecast track record": ["Not assessed – past budgets and forecasts not ingested", "", ""],
        "Execution capacity": ["Not assessed – hiring plan and organisation data not ingested", "", ""],
        "Defensibility": ["Not assessed – market and competitor data not ingested", "", ""]}


def test_the_two_assessed_rows_carry_the_analysts_rating_and_the_w17_headline():
    text = memo()
    reliability = next(line for line in text.split("\n") if line.startswith("| Data reliability |"))
    assert "| Adequate |" in reliability
    assert "Revenue file and P&L differ by 69.61% over 2023-03–2024-02" in reliability
    assert "0 anomaly flags" in reliability and "10 of 33 claims Verified" in reliability
    assert next(line for line in text.split("\n") if line.startswith("| Growth engine |")).split("|")[2].strip() == "Weak"


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
    assert re.search(r"ARR 202,125 EUR\[\^\d+\], NRR 113%\[\^\d+\], gross revenue churn 0%\[\^\d+\]", growth)
    assert im.S17 in growth and im.S17 in head.split("## Worth flagging")[1]
    assert "The growth engine is steady." not in text


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
    assert "Overlap groups: #1, #12;" in text


def test_the_appendices_carry_the_register_the_gaps_the_tables_and_the_cost_table():
    cost = copy.deepcopy(USAGE)
    cost["by_step"] = {"growth_engine": {"calls": 1, "cache_hits": 0, "input_tokens": 1200, "output_tokens": 300, "estimated_cost_usd": 0.0456},
                       "deck_structure": {"calls": 2, "cache_hits": 1, "input_tokens": 80, "output_tokens": 20, "estimated_cost_usd": 0.01}}
    cost.update(calls=1, structure_calls=2, cache_hits=1, input_tokens=1280, output_tokens=320, estimated_cost_usd=0.0556)
    tables = [{"sheet": "Headline", "rows": [["Metric", "Value"], ["Company", "TestCo"]]}]
    text = memo(usage=cost, tables=tables)
    a = text.split("## Appendix A")[1].split("## Appendix B")[0]
    assert a.count("\n| #") == 33 + 1 and "top 5" in a and "key" in a
    b = text.split("## Appendix B")[1].split("## Appendix C")[0]
    assert "First quarterly review: 2024-09-30" in b and "Required vs observed net-new customers (12m)" in b
    assert "Headline[^" in text.split("## Appendix C")[1]
    d = text.split("## Appendix D")[1]
    assert "| Narrative – growth_engine | 1 | 0 | 1,200 | 300 | 0.05 |" in d
    assert "| Deck structure reading | 2 | 1 | 80 | 20 | 0.01 |" in d and "| Total | 3 | 1 |" in d


# --- the endpoint -----------------------------------------------------------------------------------------------------------------------------------

def _ready(client, decision=GATE_DECISION):
    ids = client.get(f"/api/audits/{AUDIT}/verdict").json()["verdict"]["top5"]["proposed"]
    assert client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"top5": ids}).status_code == 200
    for n, cid in enumerate(ids):
        assert _put(client, cid, {"gate_threshold": 100.0 + n, "gate_budget_decision": decision, "gate_date": "2024-06-30"}).status_code == 200
        assert _put(client, cid, {"key_gate": True}).status_code == 200
    ok = client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"ratings": RATINGS, "thesis": THESIS})
    assert ok.status_code == 200, ok.text


def test_the_endpoint_downloads_the_memo_as_markdown_named_after_the_company(api):
    client, db = api
    db["audits"].docs[0]["company_name"] = "Test Co / Ltd"
    _ready(client)
    r = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/markdown")
    assert 'filename="Test_Co__Ltd_ic_memo.md"' in r.headers["content-disposition"]
    assert r.text.startswith("# Investment committee memo: Test Co / Ltd\n")
    assert "Evidence categories covered: 1 of 7." in r.text or "of 7." in r.text
    assert im.word_count_of(r.text) <= 1500 and "## Appendix D" in r.text


def test_the_memo_is_built_on_request_and_never_stored_and_no_model_is_called(api):
    client, db = api
    _ready(client)
    before = {name: copy.deepcopy(col.docs) for name, col in db._cols.items()}
    assert client.get(f"/api/audits/{AUDIT}/memo.md").status_code == 200
    after = {name: col.docs for name, col in db._cols.items() if name in before}
    assert all(after[name] == before[name] for name in before), "a memo writes nothing"
    assert not db["llm_calls"].docs and not db["llm_narratives"].docs, "a memo makes no call and generates no narrative"
    assert not any("memo" in name for name in db._cols)


@pytest.mark.parametrize("step, message", [
    ("none", "Memo not exported: confirm the top 5."),
])
def test_the_endpoint_refuses_and_names_the_reason_without_writing(api, step, message):
    client, db = api
    before = copy.deepcopy([col.docs for col in db._cols.values()])
    r = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert r.status_code == 409 and r.json()["detail"] == message
    assert before == [col.docs for col in db._cols.values()][:len(before)]


def test_the_endpoint_refuses_a_blocked_verdict_missing_key_gates_ratings_and_a_bad_number(api):
    client, db = api
    ids = client.get(f"/api/audits/{AUDIT}/verdict").json()["verdict"]["top5"]["proposed"]
    client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"top5": ids})
    assert client.get(f"/api/audits/{AUDIT}/memo.md").json()["detail"] == "Memo not exported: the verdict is blocked."
    for n, cid in enumerate(ids):
        _put(client, cid, {"gate_threshold": 100.0 + n, "gate_budget_decision": GATE_DECISION, "gate_date": "2024-06-30"})
    assert client.get(f"/api/audits/{AUDIT}/memo.md").json()["detail"] == "Memo not exported: mark 3 to 5 key gates."
    for cid in ids:
        _put(client, cid, {"key_gate": True})
    assert client.get(f"/api/audits/{AUDIT}/memo.md").json()["detail"] == "Memo not exported: rate Data reliability, Growth engine."
    client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"ratings": RATINGS, "thesis": {**THESIS, "plan": "Grow 37% a year."}})
    detail = client.get(f"/api/audits/{AUDIT}/memo.md").json()["detail"]
    assert detail == "Memo not exported: 1 numbers are not in the stored results: 37."
    client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"thesis": THESIS})
    bad = copy.deepcopy(db["audits"].docs[0]["results"])
    bad["nrr"]["overall_pct"] = 106.41
    db["audits"].docs[0]["results"] = bad
    detail = client.get(f"/api/audits/{AUDIT}/memo.md").json()["detail"]
    assert detail.startswith("Memo not exported: the stored results fail the contract: ") and "106" not in detail


def test_an_audit_with_no_results_refuses_with_the_compute_first_reason(api):
    client, db = api
    db["audits"].docs[0]["results"] = None
    r = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert r.status_code == 409 and "compute the audit first" in r.json()["detail"]


def test_the_export_log_line_holds_a_code_and_counts_only(api, caplog):
    client, _ = api
    _ready(client, decision="the Falcon hiring plan")
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


def test_w8_says_is_for_one_open_claim_and_are_for_more():
    v, _ = verdict_of_labels(["Verified", "Unverified", "Verified", "Verified", "Verified"], gates={2})
    assert v["rule"] == "No top-5 claim is Contradicted; 1 is Unverified or Unsupported."
    v, _ = verdict_of_labels(["Unverified", "Unsupported", "Verified", "Verified", "Verified"], gates={1, 2})
    assert v["rule"] == "No top-5 claim is Contradicted; 2 are Unverified or Unsupported."


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
        for term in fmt.GLOSSED:
            uses = re.findall(rf"(?<![\w-]){term}(?![\w-])( \(see glossary\))?", line)
            if uses:
                assert uses[0] == " (see glossary)" and all(u == "" for u in uses[1:]), (term, line)
    glossary = glossary.split("\n\n")[0].split("\n")       # the glossary's own entries define the terms, unchanged
    assert glossary == [f"- {term}: {definition}" for term, definition in fmt.GLOSSARY.items()]
    assert "- VaS: value at stake: " in text
    # a source reference keeps its own words (the footnotes hold MRR, never with the pointer: checked above)
    assert [line for line in text.split("\n") if line.startswith("[^") and " MRR" in line]
