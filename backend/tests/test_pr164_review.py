"""Review of PR #164 and George's decisions of 2026-10-23: one failing test per High and Medium finding, written before the fix.

H1 Python enters no flagged claim on its own: it waits for the analyst
H2 basis and scenario go through the register, the CSV, the memo's Appendix A and contract 6; only scenario realistic / none are plan
   targets; best / worst are stored and listed under Scenarios, never matched, never top 5, no value at stake, left out of the deck
   inconsistency pairs; they enter the register on their own (simplified-flow.md section 2)
M1 the scenario label must stand on the same line or block as the figure
M2 basis never changes an evidence label: a projection with a past period stays matched and is flagged "basis conflicts with period"
M3/M4 are frontend tests (DeckPanel.test.jsx, Review.test.jsx)
M5 the page read never deletes an analyst-added claim; the model's duplicate is flagged "matches analyst claim"
M6 a missing deck_reading prompt reads "AI reading not run – deck_reading prompt missing in prompt store"; the deck is read again on the
   next Run audit once the prompt exists, with no new upload
"""
import asyncio
import copy
import csv
import io
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")
pytest.importorskip("pdfplumber")

import test_checker as tc  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from claim_matching_support import engine_results, fixture  # noqa: E402
from test_ic_memo import inputs  # noqa: E402
from test_claims_enter_on_their_own import AUDIT, claim, prepared, register, stage, stored  # noqa: E402
from test_structure_reading import AUDIT as PAGE_AUDIT  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import decks, structures  # noqa: E402
from app import ic_memo as im  # noqa: E402
from app import run_audit  # noqa: E402
from app import verdict as vd  # noqa: E402
from app.decks import claims as deck_claims  # noqa: E402
from app.llm import gateway  # noqa: E402
from app.llm.schemas import PAGE_CLAIMS  # noqa: E402
from app.structures import checker, page_check  # noqa: E402
from schemas import metrics  # noqa: E402

CASE = {"basis": "scenario", "scenario": "best"}
RUN_A = fixture()["runs"]["A"]


# ---------------------------------------------------------------------------
# H1 Run audit never approves a flagged claim
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("flag", ["axis tick", "not a plan line", "scenario label not on page", "use-of-funds share", "matches analyst claim"])
def test_h1_python_leaves_a_flagged_claim_to_the_analyst(run_api, flag):
    prepared(run_api, claim("plain"), claim("flagged", flags=[flag]))
    res = stage(run_api, "claims")
    got = stored(run_api)
    assert (got["plain"]["status"], got["plain"].get("auto_accepted")) == ("approved", True)
    assert (got["flagged"]["status"], got["flagged"].get("auto_accepted")) == ("pending", None)
    assert res["entered"] == 1 and res["open"] == 1


def test_h1_a_best_or_worst_case_enters_like_any_claim_and_is_listed_unverified(run_api):
    assert not run_audit.needs_a_word({"scenario": "worst"}) and not run_audit.needs_a_word({"scenario": "best"})
    prepared(run_api, claim("plain"), claim("best", **CASE), claim("worst", basis="scenario", scenario="worst"),
             claim("realistic", basis="scenario", scenario="realistic"))
    stage(run_api, "claims")
    got = stored(run_api)
    assert [got[c]["status"] for c in ("plain", "best", "worst", "realistic")] == ["approved"] * 4


# ---------------------------------------------------------------------------
# H2 basis and scenario through the register, the CSV, the memo and the contract
# ---------------------------------------------------------------------------
def test_h2_the_register_row_carries_basis_and_scenario():
    assert "basis" in cm.FIELDS and "scenario" in cm.FIELDS
    row = register([{**claim("a", basis="projection", scenario="realistic"), "status": "approved"}])[0]
    assert (row["basis"], row["scenario"]) == ("projection", "realistic")
    assert register([{**claim("a"), "status": "approved"}])[0]["scenario"] == "none", "a claim with no scenario reads none"


def test_h2_a_best_or_worst_case_is_listed_never_matched_never_top_five_with_no_value_at_stake():
    plan = {**claim("plan", scenario="realistic", basis="scenario"), "status": "approved"}
    best = {**claim("best", **CASE), "status": "approved"}
    worst = {**claim("worst", basis="scenario", scenario="worst", value=100000), "status": "approved"}
    rows = register([best, plan, worst])
    by = {r["claim_id"]: r for r in rows}
    assert by["plan"]["evidence_label"] == "Verified", "a realistic case is a plan target like any other"
    for cid in ("best", "worst"):
        r = by[cid]
        assert r["evidence_label"] == "Unverified" and r["reason"] == cm.SCENARIO_NOTE.format(case=r["scenario"])
        assert cm.is_untested(r) and r["value_at_stake_arr"] is None and r["gate_needed"] is False and r["overlaps_with"] in (None, [])
        assert r["observed_value"] is None and r["gap"] is None
    assert [r["claim_id"] for r in rows][-2:] == ["best", "worst"] or {r["claim_id"] for r in rows[-2:]} == {"best", "worst"}, \
        "ranked after every tested claim"
    assert vd.proposal(rows) == ["plan"], "never in the top 5"


def test_h2_a_best_case_and_a_realistic_case_of_one_metric_are_no_deck_inconsistency():
    def fig(cid, value, scenario):
        return {**claim(cid, value=value, basis="scenario", scenario=scenario), "label_from": "Revenue", "currency": "EUR"}
    assert deck_claims.cross_deck_inconsistencies([fig("a", 10_000_000, "realistic"), fig("b", 15_000_000, "best")]) == []
    assert deck_claims.cross_deck_inconsistencies([fig("a", 10_000_000, "worst"), fig("b", 15_000_000, "best")]) == []
    two = deck_claims.cross_deck_inconsistencies([fig("a", 10_000_000, "realistic"), fig("b", 15_000_000, "realistic")])
    assert len(two) == 2, "two plan targets that differ stay a deck inconsistency"


def test_h2_the_baseline_csv_carries_basis_and_scenario(run_api):
    prepared(run_api, claim("plain", basis="projection", scenario="realistic"), claim("best", **CASE))
    for c in run_api.db[decks.CANDIDATES_COLLECTION].docs:
        c["status"] = "approved"
    table = list(csv.reader(io.StringIO(run_api.get(f"/api/audits/{AUDIT}/claims.csv").text)))
    head = table[0]
    assert "basis" in head and "scenario" in head
    got = {r[head.index("claim_id")]: (r[head.index("basis")], r[head.index("scenario")]) for r in table[1:] if r[0] == "claim"}
    assert got == {"plain": ("projection", "realistic"), "best": ("scenario", "best")}


def test_h2_the_memo_appendix_a_names_the_case_of_a_scenario_row():
    rows = copy.deepcopy(inputs()["rows"])
    rows[0].update(basis="scenario", scenario="best")
    memo = im.build_memo(**{**inputs(), "rows": rows})
    appendix = memo.split("## Appendix A")[1].split("## Appendix B")[0]
    table = [[c.strip() for c in line.strip("|").split("|")] for line in appendix.splitlines() if line.startswith("| ")]
    header, body = table[0], table[1:]
    assert "Case" in header
    case = {r[0]: r[header.index("Case")] for r in body}
    assert case[f"#{rows[0]['rank']}"] == "best case"
    assert {v for k, v in case.items() if k != f"#{rows[0]['rank']}"} <= {"—", ""}


def test_h2_the_deck_list_groups_a_best_or_worst_case_under_scenarios_and_the_contract_names_the_fields(run_api):
    assert metrics.CONTRACT_VERSION == 9
    assert metrics.DECK_CLAIM_FIELDS == ("basis", "scenario", "flags")
    prepared(run_api, claim("best", **CASE), claim("plain", basis="projection", scenario="realistic"))
    listed = {c["id"]: c for c in run_api.get(f"/api/audits/{AUDIT}/decks").json()["candidates"]}
    assert listed["best"]["group"] == deck_claims.SCENARIO_GROUP != listed["plain"]["group"] == deck_claims.type_group("revenue")
    for c in listed.values():
        assert set(metrics.DECK_CLAIM_FIELDS) <= set(c), "every listed claim names its basis, scenario and flags"


def test_h2_a_best_or_worst_case_is_entered_on_its_own_and_listed_under_scenarios(entry_api):
    client, db = entry_api
    import entry_support as es
    docs = db[decks.CANDIDATES_COLLECTION].docs
    docs.append(es.claim("s1", basis="scenario", scenario="best"))
    docs.append(es.claim("s2", basis="scenario", scenario="worst"))
    docs.append(es.claim("s3", basis="scenario", scenario="realistic"))
    rows = {r["claim_id"]: r for r in client.get(f"/api/audits/{es.AUDIT}/claims").json()["register"]}
    assert {"s1", "s2", "s3"} <= set(rows) and rows["s1"]["evidence_label"] == rows["s2"]["evidence_label"] == "Unverified"
    assert (rows["s1"]["reason"], rows["s2"]["reason"]) == (cm.SCENARIO_NOTE.format(case="best"), cm.SCENARIO_NOTE.format(case="worst"))
    assert cm.is_untested(rows["s1"]) and cm.is_untested(rows["s2"])
    assert not cm.is_untested(rows["s3"]) and "scenario" not in rows["s3"]["reason"], "a realistic case is a plan target, tested as any claim"


def test_h2_the_flag_words_stay_closed():
    assert checker.BASIS_CONFLICT == "basis conflicts with period" and checker.MATCHES_ANALYST == "matches analyst claim"
    assert checker.BASIS_SCENARIO_DISAGREE == "basis and scenario disagree"
    assert {checker.BASIS_CONFLICT, checker.MATCHES_ANALYST, checker.BASIS_SCENARIO_DISAGREE} <= set(checker.FLAGS)


# ---------------------------------------------------------------------------
# M1 the scenario label stands on the same line or block as the figure
# ---------------------------------------------------------------------------
def test_m1_swapping_the_case_of_a_uber_claim_is_flagged_and_the_recorded_assignment_is_not():
    parsed, grid, reply = tc.uber_page_20()
    blocks = checker.page_blocks(parsed["blocks"], grid)

    def flags(claims_):
        out = checker.check(grid, page_check.by_page(claims_)[20], 12, blocks, "06-uber.pdf")
        return [i["flags"] for i in out["items"]]
    recorded = copy.deepcopy(reply["claims"])
    assert checker.SCENARIO_NOT_ON_PAGE not in sum(flags(recorded), []), "the recorded cases stand beside their figures"
    swapped = copy.deepcopy(recorded)
    swapped[0]["scenario"] = "worst"        # the $1B revenue is the best case
    assert checker.SCENARIO_NOT_ON_PAGE in flags(swapped)[0]
    swapped = copy.deepcopy(recorded)
    swapped[3]["scenario"] = "best"         # 100 clients is the worst case
    assert checker.SCENARIO_NOT_ON_PAGE in flags(swapped)[3]


# ---------------------------------------------------------------------------
# M2 basis never changes an evidence label
# ---------------------------------------------------------------------------
PAST = [tc.TITLE, (50, 500, 12, "Feb 2024"), (50, 480, 12, "€300,000 ARR")]


def _past_claim_rows(monkeypatch, basis):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    parsed = tc.deck(PAST)
    db = tc._page_db(parsed)
    reply = {"type": PAGE_CLAIMS, "claims": [tc.claim("p1r3c1", 300000, unit="EUR", period="2024-02", period_cell="p1r2c1", basis=basis)]}
    adapter = t.FakeAdapter(replies=[json.dumps(reply)])
    assert asyncio.run(structures.process_deck(db, PAGE_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep)) == "read"
    return db[decks.CANDIDATES_COLLECTION].docs


def test_m2_the_model_basis_sets_no_figure_type_and_a_projection_in_the_past_stays_contradicted(monkeypatch):
    row, = _past_claim_rows(monkeypatch, "projection")
    assert row["figure_type_set_by"] is None and row.get("figure_type") in (None, "unknown"), "Python reads the figure type from the period"
    got = cm.build_register([{**row, "status": "edited"}], engine_results(tuple(RUN_A["files"]), RUN_A["as_of_month"]),
                            {"fiscal_year_end": 12, "as_of_month": RUN_A["as_of_month"], "reporting_currency": "EUR", "fx": {"EUR": 1.0}})[0]
    same_as_actual = cm.build_register([{**_past_claim_rows_actual(monkeypatch), "status": "edited"}],
                                       engine_results(tuple(RUN_A["files"]), RUN_A["as_of_month"]),
                                       {"fiscal_year_end": 12, "as_of_month": RUN_A["as_of_month"], "reporting_currency": "EUR",
                                        "fx": {"EUR": 1.0}})[0]
    # (an edited claim: an unedited AI suggestion is never above Unverified, decision D3, whatever its figure type)
    assert got["evidence_label"] == same_as_actual["evidence_label"] == "Contradicted", "basis changes no evidence label (rules 18, 19.1)"
    assert got["figure_type"] == "actual"


def _past_claim_rows_actual(monkeypatch):
    return _past_claim_rows(monkeypatch, "actual")[0]


def test_m2_a_projection_with_a_past_period_is_flagged_in_the_deck_list_and_left_to_the_analyst(run_api):
    prepared(run_api, claim("plain"), claim("proj", basis="projection", scenario="none"), claim("fut", basis="projection", target_date="2030",
                                                                                          period_text="2030"))
    res = stage(run_api, "claims")
    listed = {c["id"]: c for c in run_api.get(f"/api/audits/{AUDIT}/decks").json()["candidates"]}
    assert listed["proj"]["flags"] == [checker.BASIS_CONFLICT], "Feb 2024 is on or before the as-of month"
    assert listed["plain"]["flags"] == [] and checker.BASIS_CONFLICT not in listed["fut"]["flags"], "a plan for a future period is no conflict"
    got = stored(run_api)
    assert got["proj"]["status"] == "pending", "a flagged claim is not approved on its own"
    assert res["entered"] >= 1 and got["plain"]["status"] == "approved"


# ---------------------------------------------------------------------------
# M5 the page read never deletes an analyst-added claim
# ---------------------------------------------------------------------------
def _analyst_row(origin="deck_analyst", period="2025"):
    return {"audit_id": PAGE_AUDIT, "id": "mine", "deck_id": "d1", "file": "deck.pdf", "origin": origin, "status": "pending", "order": 1,
            "claim_type": "revenue", "value": 150000, "value_high": None, "unit": None, "currency": "USD", "target_date": period,
            "period_text": period, "snippet": "$150,000 annual revenue run rate", "label_from": None,
            "sources": [{"file": "deck.pdf", "page": 1, "kind": "page", "cell": None}]}


@pytest.mark.parametrize("origin", ["deck_analyst", "analyst"])
def test_m5_an_analyst_claim_is_kept_and_the_model_duplicate_is_flagged(monkeypatch, origin):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    parsed = tc.deck([tc.TITLE, *tc.LINES])
    db = tc._page_db(parsed)
    db[decks.CANDIDATES_COLLECTION].docs.append(_analyst_row(origin))
    reply = {"type": PAGE_CLAIMS, "claims": [tc.claim("p1r3c1", 150000, period="2026")]}
    adapter = t.FakeAdapter(replies=[json.dumps(reply)])
    asyncio.run(structures.process_deck(db, PAGE_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    docs = db[decks.CANDIDATES_COLLECTION].docs
    mine = next(c for c in docs if c["id"] == "mine")
    assert mine["origin"] == origin and mine["status"] == "pending", "the analyst's claim is never deleted"
    theirs = [c for c in docs if c["id"] != "mine"]
    assert len(theirs) == 1 and checker.MATCHES_ANALYST in theirs[0]["flags"], "the model's duplicate is flagged, not merged away"


def test_m5_rules_copy_matches_parser_rows_only():
    parser_row = {**_analyst_row(), "id": "p", "origin": None}
    parser_row.pop("origin")
    cand = {**_analyst_row(), "id": "c", "origin": "ai", "target_date": "2026"}
    assert structures.rules_copy([_analyst_row("deck_analyst")], cand) is None
    assert structures.rules_copy([_analyst_row("analyst")], cand) is None
    assert structures.rules_copy([parser_row], cand) is parser_row, "a parser row (no origin) is still the copy the panel read replaces"


# ---------------------------------------------------------------------------
# M6 a missing deck_reading prompt
# ---------------------------------------------------------------------------
MISSING = "AI reading not run – deck_reading prompt missing in prompt store"


def test_m6_the_missing_prompt_is_named_on_the_deck_and_the_next_run_audit_reads_it_without_a_new_upload(monkeypatch, caplog):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    parsed = tc.deck([tc.TITLE, *tc.LINES])
    db = tc._page_db(parsed)
    stubs = list(db["prompts"].docs)
    db["prompts"].docs.clear()
    adapter = t.FakeAdapter(replies=[json.dumps({"type": PAGE_CLAIMS, "claims": [tc.claim("p1r2c1", 800, metric="customers", unit="count")]})])
    with caplog.at_level("WARNING"):
        status = asyncio.run(structures.process_deck(db, PAGE_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    deck_doc, = db[decks.TEXT_COLLECTION].docs
    assert f"deck_reading prompt missing: run_id={PAGE_AUDIT}" in caplog.text and "Traction" not in caplog.text, "codes only (rule 17)"
    assert status == structures.PROMPT_MISSING == deck_doc["ai_status"] and deck_doc["ai_message"] == MISSING == gateway.PROMPT_MISSING_TEXT
    assert adapter.calls == 0 and db[decks.CANDIDATES_COLLECTION].docs == []
    # The prompt is uploaded; no new upload: the deck is queued again, once, and only when the store holds the prompt.
    assert asyncio.run(structures.queue_prompt_missing(db, PAGE_AUDIT)) == [], "still no prompt: nothing is queued"
    db["prompts"].docs.extend(stubs)
    assert asyncio.run(structures.queue_prompt_missing(db, PAGE_AUDIT)) == ["d1"]
    assert db[decks.TEXT_COLLECTION].docs[0]["ai_status"] == "reading"
    assert asyncio.run(structures.queue_prompt_missing(db, PAGE_AUDIT)) == [], "a deck already being read is not queued twice"
    status = asyncio.run(structures.process_deck(db, PAGE_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert status == "read" and adapter.calls == 1 and len(db[decks.CANDIDATES_COLLECTION].docs) == 1


def test_m6_run_audit_names_the_missing_prompt_and_reads_the_deck_again_once_it_exists(run_api, monkeypatch):
    prepared(run_api)
    deck_doc, = run_api.db[decks.TEXT_COLLECTION].docs
    deck_doc.update(ai_status=structures.PROMPT_MISSING, ai_message=MISSING)
    stubs = list(run_api.db["prompts"].docs)
    run_api.db["prompts"].docs.clear()
    res = stage(run_api, "claims")
    assert res["status"] == run_audit.DONE and res["message"] == MISSING, "the stage says why there is no claim"
    assert deck_doc["ai_status"] == structures.PROMPT_MISSING
    run_api.db["prompts"].docs.extend(stubs)
    seen = []

    async def fake(db, audit_id, deck_id, *a, **k):
        seen.append(deck_id)
        return "read"
    monkeypatch.setattr(structures, "process_deck_safely", fake)
    res = stage(run_api, "claims")
    assert res["status"] == run_audit.RUNNING and res["message"] == run_audit.DECKS_READING and seen == ["d1"], res


# ---------------------------------------------------------------------------
# Lows fixed in the same round (each under an hour)
# ---------------------------------------------------------------------------
def test_l2_uber_page_20_lists_all_four_claims_under_claims_and_only_the_far_label_under_review():
    """The pipeline view of the recorded p20 reply: best and worst under Scenarios, the realistic market share and profit under their types;
    the profit claim keeps the informational flag "currency assumed" (matched since 2026-10-23, so no longer under Review). (The reply's basis and scenario are the author's, kept as the spec until the
    first live run is recorded again: George, 2026-10-23.)"""
    parsed, grid, reply = tc.uber_page_20()
    out = checker.check(grid, page_check.by_page(reply["claims"])[20], 12, checker.page_blocks(parsed["blocks"], grid), "06-uber.pdf")
    deck = {"file": "06-uber.pdf", "page_unit": "page", "blocks": parsed["blocks"]}
    rows = [structures.pages.row_from_claim(item, grid, deck, 12) for item in out["items"]]
    listing = [(r["claim_type"], deck_claims.claim_group(r), bool(r["flags"])) for r in rows]
    assert listing == [("revenue", deck_claims.SCENARIO_GROUP, False), ("market", deck_claims.type_group("market"), True),
                       ("net_profit", deck_claims.type_group("net_profit"), True), ("customers", deck_claims.SCENARIO_GROUP, False)]
    # Since 2026-10-23 (George) the profit claim is matched and its "currency assumed" flag is informational. The market share cites a label
    # far from the figure with only the page title as fallback: not corrected, flagged for a card (hotfix of PR 182).
    assert [r["flags"] for r in rows if r["flags"]] == [[checker.LABEL_MISMATCH], [checker.CURRENCY_ASSUMED]]
    assert [r["claim_type"] for r in rows if deck_claims.review_flags(r["flags"])] == ["market"]


def test_l3_a_flag_survives_the_merge_into_a_row_still_to_review(monkeypatch):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    parsed = tc.deck([tc.TITLE, *tc.LINES])
    db = tc._page_db(parsed)
    twin = {**_analyst_row("deck_analyst", "2027"), "origin": None, "id": "twin", "flags": []}
    twin.pop("origin")
    deck_claims.resolve_period(twin, 12)
    db[decks.CANDIDATES_COLLECTION].docs.append(twin)
    reply = {"type": PAGE_CLAIMS, "claims": [tc.claim("p1r3c1", 150000, period="2027")]}     # a period no cell of the page states
    asyncio.run(structures.process_deck(db, PAGE_AUDIT, "d1", adapter=t.FakeAdapter(replies=[json.dumps(reply)]), sleep=t._noop_sleep))
    docs = db[decks.CANDIDATES_COLLECTION].docs
    assert len(docs) == 1 and docs[0]["id"] == "twin" and docs[0]["flags"] == [checker.PERIOD_NOT_ON_PAGE]


def test_l5_the_consent_off_line_is_stored_by_the_page_pipeline_only(monkeypatch):
    for pipeline, message in (("ai", structures.CONSENT_OFF_LINE), ("rules", None)):
        monkeypatch.setenv("DECK_PIPELINE", pipeline)
        db = tc._page_db(tc.deck([tc.TITLE, *tc.LINES]))
        db["audits"].docs[0]["structure_reading_consent"] = False
        assert asyncio.run(structures.process_deck(db, PAGE_AUDIT, "d1", adapter=t.FakeAdapter(replies=[]), sleep=t._noop_sleep)) == "python_only"
        assert db[decks.TEXT_COLLECTION].docs[0]["ai_message"] == message
    assert structures.CONSENT_OFF_LINE == ("Deck not read. AI-assisted reading is off for this audit, so no claims were extracted. "
                                           "Tick consent on the Upload page to read it, or use Add claim.")


def test_l8_a_basis_and_scenario_that_contradict_each_other_are_flagged():
    parsed = tc.deck([tc.TITLE, *tc.LINES])
    assert tc.one(parsed, tc.claim("p1r3c1", 150000, basis="actual", scenario="best"))["flags"] == [
        checker.SCENARIO_NOT_ON_PAGE, checker.BASIS_SCENARIO_DISAGREE]
    assert tc.one(parsed, tc.claim("p1r3c1", 150000, basis="scenario", scenario="none"))["flags"] == [checker.BASIS_SCENARIO_DISAGREE]
    assert tc.one(parsed, tc.claim("p1r3c1", 150000, basis="projection", scenario="none"))["flags"] == []
    assert tc.one(parsed, tc.claim("p1r3c1", 150000, basis="actual", scenario="none"))["flags"] == []


def test_m6_a_prompt_stored_under_the_former_name_page_claims_is_not_read(monkeypatch):
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    db = tc._page_db(tc.deck([tc.TITLE, *tc.LINES]))
    for doc in db["prompts"].docs:
        doc["name"] = "page_claims"
    adapter = t.FakeAdapter(replies=[json.dumps({"type": PAGE_CLAIMS, "claims": []})])
    status = asyncio.run(structures.process_deck(db, PAGE_AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep))
    assert status == structures.PROMPT_MISSING and adapter.calls == 0
