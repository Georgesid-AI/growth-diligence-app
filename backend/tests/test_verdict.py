"""Gates, data gaps, the analyst's top 5 and the verdict (docs/specs/verdict-and-memo.md sections 3, 4, 6 and 10).

Pure rows for the rule; the register endpoints (in-memory Mongo stub, no network) for the analyst's inputs. Each test was shown
failing on a deliberate violation (CLAUDE.md rule 11): the violations are listed in the session log.
"""
import copy

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import server  # noqa: E402
from claim_matching_support import engine_results  # noqa: E402
from test_claim_matching import RUNS, register, results_for, row_of  # noqa: E402
from test_claim_register_api import AUDIT, _get, _put, api  # noqa: E402,F401  (the fixture)

from app import claim_matching as cm  # noqa: E402
from app import decks  # noqa: E402
from app import verdict as vd  # noqa: E402


def row(rank, label, gate=False, **extra):
    """A register row with what the verdict reads."""
    base = dict.fromkeys(cm.FIELDS)
    base.update(claim_id=f"r{rank}", rank=rank, evidence_label=label, reason=f"reason {rank}", claim_type="revenue", metric="ARR",
                segment=cm.WHOLE, period="Feb 2024", unit=None, currency="EUR", claimed_value=100.0, observed_value=None,
                gloss=None, gate_saved=gate, gate_needed=label != "Verified" and not gate, key_gate=False, overlaps_with=[])
    base.update(extra)
    return base


def gated(rows):
    """The register with every gate saved: the rule's outcome is read once nothing blocks (section 6.3)."""
    return [{**r, "gate_saved": True, "gate_needed": False} for r in rows]


def verdict_of(labels, gates=(), stored="all"):
    rows = [row(i + 1, label, gate=(i + 1) in gates) for i, label in enumerate(labels)]
    ids = [r["claim_id"] for r in rows[:5]]
    return vd.verdict(rows, {"reporting_currency": "EUR"}, {"claim_ids": ids} if stored == "all" else stored), rows


# --- section 6.2: the rule, in order ---------------------------------------------------------------------------------------

def test_underwrite_when_every_top_5_claim_is_verified():
    v, _ = verdict_of(["Verified"] * 5 + ["Contradicted"])
    assert (v["status"], v["outcome"], v["rule"]) == ("ok", "Underwrite", "All top-5 claims are Verified.")


def test_underwrite_with_gates_when_nothing_is_contradicted_and_at_most_two_are_unsupported():
    v, _ = verdict_of(["Verified", "Unverified", "Unsupported", "Unsupported", "Verified"], gates={2, 3, 4})
    assert (v["outcome"], v["rule"]) == ("Underwrite with gates", "No top-5 claim is Contradicted; 3 are Unverified or Unsupported.")


@pytest.mark.parametrize("kind", ["miss", "beat"])
def test_replan_when_a_top_5_claim_is_contradicted_a_miss_or_a_beat(kind):
    rows = register(RUNS["A"])
    miss, beat = row_of(rows, "c06"), row_of(rows, "c08")
    assert (miss["gap_kind"], beat["gap_kind"]) == ("miss", "beat") and beat["evidence_label"] == "Contradicted"
    verified = [r for r in rows if r["evidence_label"] == "Verified"][:4]
    five = [miss if kind == "miss" else beat, *verified]
    v = vd.verdict(gated(rows), results_for(RUNS["A"]), {"claim_ids": [r["claim_id"] for r in five]})
    assert (v["status"], v["outcome"], v["rule"]) == ("ok", "Re-plan", "1 top-5 claim Contradicted.")


def test_replan_when_three_top_5_claims_are_unsupported():
    v, _ = verdict_of(["Unsupported"] * 3 + ["Verified", "Verified"], gates={1, 2, 3})
    assert (v["outcome"], v["rule"]) == ("Re-plan", "3 top-5 claims Unsupported (3 or more).")


def test_three_unsupported_and_one_unverified_is_replan_not_underwrite_with_gates():
    """The request's rules match both outcomes; Re-plan is checked first (section 6.2)."""
    v, _ = verdict_of(["Unsupported", "Unsupported", "Unsupported", "Unverified", "Verified"], gates={1, 2, 3, 4})
    assert v["outcome"] == "Re-plan"


def test_two_unsupported_and_two_unverified_is_not_replan():
    v, _ = verdict_of(["Unsupported", "Unsupported", "Unverified", "Unverified", "Verified"], gates={1, 2, 3, 4})
    assert v["outcome"] == "Underwrite with gates"


def test_with_fewer_than_five_rows_the_top_5_is_every_row_and_the_rule_says_so():
    v, rows = verdict_of(["Verified", "Verified", "Verified"])
    assert len(v["five"]) == 3 and v["outcome"] == "Underwrite"
    assert v["rule"] == "All top-5 claims are Verified. Top 3 (the register has 3 claims)."


def test_no_rows_and_no_results_give_no_verdict():
    assert vd.verdict([], {"reporting_currency": "EUR"}, None)["message"] == "No verdict: the register has no claims."
    assert vd.verdict([row(1, "Verified")], None, None)["message"] == "No verdict: compute the audit first."
    assert vd.verdict([], {"reporting_currency": "EUR"}, None)["status"] == "no_verdict"


def test_the_three_reasons_are_the_claims_that_made_the_rule_fire_each_citing_its_evidence():
    rows = gated(register(RUNS["A"]))
    v = vd.verdict(rows, results_for(RUNS["A"]), {"claim_ids": vd.proposal(rows)})
    assert v["outcome"] == "Re-plan" and len(v["reasons"]) == 3
    assert v["reasons"][0].startswith("#1 Median sales cycle: Contradicted, 58.5 days against 45.0 days (13.5 days longer, two working weeks (miss)).")
    assert "Evidence: Sales cycle · sales_cycle.median_days (crm.csv · CSV · rows 2–121" in v["reasons"][0]
    unsupported = [row(1, "Unsupported", gate=True), *[row(i, "Verified") for i in range(2, 6)]]
    again = vd.verdict(unsupported, {"reporting_currency": "EUR"}, {"claim_ids": [r["claim_id"] for r in unsupported]})
    assert again["reasons"][0] == "#1 ARR, Feb 2024: Unsupported, reason 1. No figure in the supplied files."


@pytest.mark.parametrize("run, expected", [("A", ("ok", "Re-plan")), ("C", ("ok", "Re-plan")), ("D", ("ok", "Re-plan"))])
def test_the_fixture_runs_measure_as_the_spec_says_with_the_proposed_top_5_confirmed(run, expected):
    rows = register(RUNS[run])
    ids = {"claim_ids": vd.proposal(rows)}
    assert vd.verdict(rows, results_for(RUNS[run]), ids)["status"] == "blocked", "no gate saved yet"
    v = vd.verdict(gated(rows), results_for(RUNS[run]), ids)
    assert (v["status"], v["outcome"]) == expected


def test_run_b_is_one_unverified_claim_blocked_until_its_gate_is_saved():
    rows = register(RUNS["B"])
    assert [(r["evidence_label"]) for r in rows if r["rank"] == 1] == ["Unverified"]
    single = [r for r in rows if r["rank"] == 1]
    state = {"claim_ids": vd.proposal(rows)}
    blocked = vd.verdict(rows, results_for(RUNS["B"]), state)
    assert blocked["status"] == "blocked" and blocked["outcome"] is None
    gated = [{**r, "gate_saved": True, "gate_needed": False} if r["rank"] == 1 else r for r in rows]
    assert vd.verdict(gated, results_for(RUNS["B"]), state)["outcome"] == "Underwrite with gates"
    assert single


# --- section 6.1: the top 5 --------------------------------------------------------------------------------------------------

def test_no_verdict_before_the_top_5_is_confirmed_and_the_proposal_is_rows_1_to_5():
    rows = register(RUNS["A"])
    v = vd.verdict(rows, results_for(RUNS["A"]), None)
    assert (v["status"], v["outcome"], v["message"]) == ("unconfirmed", None, "No verdict until the top 5 is confirmed.")
    assert v["top5"]["proposed"] == [r["claim_id"] for r in rows[:5]] and not v["top5"]["confirmed"]


def test_a_replaced_row_counts_and_the_replaced_one_does_not():
    rows = gated(register(RUNS["A"]))
    ids = vd.proposal(rows)
    verified = next(r for r in rows if r["evidence_label"] == "Verified")
    replaced = [verified["claim_id"], *ids[1:]]
    v = vd.verdict(rows, results_for(RUNS["A"]), {"claim_ids": replaced})
    assert [f["claim_id"] for f in v["five"]] == sorted(replaced, key=lambda i: row_of(rows, i)["rank"])
    assert ids[0] not in [f["claim_id"] for f in v["five"]] and verified["claim_id"] in [f["claim_id"] for f in v["five"]]
    assert v["rule"] == "4 top-5 claims Contradicted.", "the replaced Contradicted row no longer counts"


@pytest.mark.parametrize("size", [0, 4, 6])
def test_a_set_of_the_wrong_size_or_with_a_claim_twice_or_unknown_is_refused(size):
    rows = register(RUNS["A"])
    with pytest.raises(ValueError):
        vd.check_top5(rows, [r["claim_id"] for r in rows[:size]])
    with pytest.raises(ValueError):
        vd.check_top5(rows, [rows[0]["claim_id"]] * 5)
    with pytest.raises(ValueError):
        vd.check_top5(rows, [*[r["claim_id"] for r in rows[:4]], "nope"])
    vd.check_top5(rows, [r["claim_id"] for r in rows[:5]])
    vd.check_top5(rows[:3], [r["claim_id"] for r in rows[:3]])


def test_a_confirmed_claim_leaving_the_register_voids_the_set_and_a_new_rank_order_does_not():
    rows = register(RUNS["A"])
    stored = {"claim_ids": vd.proposal(rows)}
    assert vd.top5_state(rows, stored)["confirmed"]
    left = [r for r in rows if r["claim_id"] != stored["claim_ids"][2]]
    state = vd.top5_state(left, stored)
    assert (state["confirmed"], state["void"]) == (False, True)
    v = vd.verdict(left, results_for(RUNS["A"]), stored)
    assert (v["status"], v["message"]) == ("void", "A claim of the confirmed top 5 left the register – confirm the top 5 again.")
    shuffled = sorted(({**r, "rank": len(rows) + 1 - r["rank"]} for r in rows), key=lambda r: r["rank"])
    assert [r["claim_id"] for r in shuffled[:5]] != stored["claim_ids"], "fixture: the five are no longer rows 1 to 5"
    assert vd.top5_state(shuffled, stored)["confirmed"], "a new rank order alone does not void the set"


def test_the_banner_keeps_rows_1_to_5_of_the_pre_sort_after_the_analyst_replaces_a_row():
    rows = register(RUNS["A"])
    assert vd.banner_ids(rows) == [r["claim_id"] for r in rows[:5]]


# --- section 6.3: blocked --------------------------------------------------------------------------------------------------------

def test_a_non_verified_top_5_claim_without_a_gate_blocks_and_saving_its_gate_unblocks():
    v, rows = verdict_of(["Verified", "Unverified", "Verified", "Verified", "Verified"])
    assert v["status"] == "blocked" and v["outcome"] is None and v["blocked"] == ["r2"]
    assert v["message"] == "Verdict blocked: set a gate on #2 (top-5 claims that are not Verified)."
    again, _ = verdict_of(["Verified", "Unverified", "Verified", "Verified", "Verified"], gates={2})
    assert again["status"] == "ok" and again["outcome"] == "Underwrite with gates"


def test_a_verified_top_5_claim_without_a_gate_does_not_block():
    v, _ = verdict_of(["Verified"] * 5)
    assert v["status"] == "ok"


# --- section 3: gates ------------------------------------------------------------------------------------------------------------

BASE = {"claim_type": "revenue", "snippet": "ARR", "value": 200000, "target_date": "2024-02", "period_text": "Feb 2024"}


def run_row(claim, inputs=None, **extra):
    from test_claim_matching import run_claim
    return run_claim({**BASE, **claim, "claim_inputs": {"x1": inputs or {}}}, **extra)


GATE = {"gate_threshold": 150000.0, "gate_budget_decision": "the Series B hiring plan", "gate_date": "2024-06-30"}


def test_the_gate_date_starts_empty_and_the_gate_is_not_saved_without_it():
    assert run_row({})["gate_date"] is None
    r = run_row({}, {k: v for k, v in GATE.items() if k != "gate_date"})
    assert (r["gate_saved"], r["gate_sentence"]) == (False, None)
    assert run_row({}, GATE)["gate_saved"] is True


def test_every_row_that_is_not_verified_needs_a_gate_until_it_is_saved():
    contradicted = run_row({"value": 240000})
    assert (contradicted["evidence_label"], contradicted["gate_needed"]) == ("Contradicted", True)
    assert run_row({"value": 240000}, GATE)["gate_needed"] is False
    verified = run_row({})
    assert (verified["evidence_label"], verified["gate_needed"]) == ("Verified", False)
    assert run_row({}, GATE)["gate_saved"] is True, "a Verified row may carry a gate"
    unsupported = run_row({"claim_type": "market", "snippet": "TAM"})
    assert (unsupported["evidence_label"], unsupported["gate_needed"]) == ("Unsupported", True)


def test_a_row_with_no_observed_figure_gets_the_sentence_of_w6():
    r = run_row({"claim_type": "market", "snippet": "TAM", "value": 2_000_000_000}, {
        **GATE, "gate_threshold": 5, "gate_metric_name": "Pipeline coverage", "gate_direction": "at least"})
    assert r["reason"] == "no metric" and r["gate_saved"] is True
    assert r["gate_sentence"] == ("Before the Series B hiring plan, Pipeline coverage must be at least €5 by 2024-06-30. "
                                  "Not yet observed: no metric; claimed €2,000,000,000 (Feb 2024).")


def test_a_no_metric_row_needs_the_metric_name_and_the_direction():
    market = {"claim_type": "market", "snippet": "TAM"}
    assert run_row(market, GATE)["gate_saved"] is False, "no name, no direction"
    assert run_row(market, {**GATE, "gate_metric_name": "Pipeline coverage"})["gate_saved"] is False, "no direction"
    assert run_row(market, {**GATE, "gate_direction": "at most"})["gate_saved"] is False, "no name"
    full = run_row(market, {**GATE, "gate_metric_name": "Pipeline coverage", "gate_direction": "at most"})
    assert full["gate_saved"] is True and "must be at most" in full["gate_sentence"]
    assert run_row({}, {**GATE})["gate_saved"] is True, "an app metric needs neither"


def test_an_untested_row_with_an_app_metric_gets_w6_with_the_apps_metric_and_direction():
    r = run_row({"currency": "USD", "value": 210000}, GATE)
    assert r["evidence_label"] == "Unverified" and r["reason"] == "FX rate needed: USD→EUR"
    assert r["gate_sentence"] == ("Before the Series B hiring plan, ARR must be at least €150,000 by 2024-06-30. "
                                  "Not yet observed: FX rate needed: USD→EUR; claimed $210,000 (Feb 2024).")


def test_with_fewer_than_three_saved_gates_every_saved_gate_is_key_and_the_note_says_so():
    rows = [row(i, "Verified", gate=i <= 2) for i in range(1, 5)]
    key = vd.key_gates(rows)
    assert (key["all_key"], key["ok"], len(key["gates"]), key["note"]) == (True, True, 2, "2 gates set; all are key gates.")
    none = vd.key_gates([row(1, "Verified")])
    assert (none["ok"], none["note"]) == (True, "No key gates marked.")


def test_with_three_or_more_saved_gates_the_memo_needs_three_to_five_marked():
    rows = [row(i, "Verified", gate=True, key_gate=i <= 2) for i in range(1, 6)]
    key = vd.key_gates(rows)
    assert (key["all_key"], key["ok"]) == (False, False) and len(key["gates"]) == 2
    rows = [row(i, "Verified", gate=True, key_gate=i <= 3) for i in range(1, 6)]
    assert vd.key_gates(rows)["ok"] is True
    assert vd.key_gates([row(i, "Verified", gate=True) for i in range(1, 6)])["note"] == "No key gates marked."


def _gate_all(client, ids):
    for claim_id in ids:
        assert _put(client, claim_id, {**{k: v for k, v in GATE.items()}}).status_code == 200


def test_a_sixth_key_gate_is_refused_and_so_is_a_key_gate_on_an_unsaved_gate(api):
    client, db = api
    rows = _get(client)["register"]
    ids = [r["claim_id"] for r in rows[:6]]
    _gate_all(client, ids)
    for claim_id in ids[:5]:
        assert _put(client, claim_id, {"key_gate": True}).status_code == 200
    sixth = _put(client, ids[5], {"key_gate": True})
    assert sixth.status_code == 400 and sixth.json()["detail"] == "At most 5 key gates."
    stored = next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == ids[5].split("#")[0])
    assert not (stored.get("claim_inputs") or {}).get(ids[5], {}).get("key_gate"), "nothing was written"
    unsaved = _put(client, rows[8]["claim_id"], {"key_gate": True})
    assert unsaved.status_code == 400
    assert _put(client, ids[0], {"key_gate": False}).status_code == 200
    assert _put(client, ids[5], {"key_gate": True}).status_code == 200, "a mark freed is a mark available"


def test_a_key_mark_counts_only_while_its_gate_is_saved(api):
    client, _ = api
    rows = _get(client)["register"]
    _gate_all(client, [rows[0]["claim_id"]])
    _put(client, rows[0]["claim_id"], {"key_gate": True})
    cleared = _put(client, rows[0]["claim_id"], {"gate_threshold": None}).json()["register"]
    assert next(r for r in cleared if r["claim_id"] == rows[0]["claim_id"])["key_gate"] is False


# --- the analyst's top 5 through the API -----------------------------------------------------------------------------------------

def _verdict(client):
    r = client.get(f"/api/audits/{AUDIT}/verdict")
    assert r.status_code == 200, r.text
    return r.json()


def _inputs(client, body):
    return client.put(f"/api/audits/{AUDIT}/ic-inputs", json=body)


def test_the_verdict_endpoint_proposes_rows_1_to_5_and_gives_no_outcome_until_confirmed(api):
    client, _ = api
    body = _verdict(client)
    register = _get(client)["register"]
    assert body["verdict"]["status"] == "unconfirmed" and body["verdict"]["outcome"] is None
    assert body["verdict"]["top5"]["proposed"] == [r["claim_id"] for r in register[:5]]
    assert len(body["candidates"]) == len(register)


def test_confirming_a_set_stores_it_as_an_analyst_decision_and_a_wrong_size_is_refused(api):
    client, db = api
    ids = _verdict(client)["verdict"]["top5"]["proposed"]
    assert _inputs(client, {"top5": ids[:4]}).status_code == 400
    assert _inputs(client, {"top5": [ids[0]] * 5}).status_code == 400
    assert db["audits"].docs[0].get("ic_inputs") is None
    r = _inputs(client, {"top5": ids})
    assert r.status_code == 200
    stored = db["audits"].docs[0]["ic_inputs"]["top5"]
    assert stored["claim_ids"] == ids and stored["set_at"]
    assert r.json()["verdict"]["status"] == "blocked", "the proposed five are Contradicted and have no gate yet"


def test_a_confirmed_claim_that_is_rejected_leaves_the_register_and_voids_the_set(api):
    client, db = api
    ids = _verdict(client)["verdict"]["top5"]["proposed"]
    _inputs(client, {"top5": ids})
    gone = next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == ids[0].split("#")[0])
    gone["status"] = "rejected"
    v = _verdict(client)["verdict"]
    assert v["status"] == "void" and v["message"].startswith("A claim of the confirmed top 5 left the register")


def test_the_banner_still_uses_rows_1_to_5_of_the_pre_sort_after_a_replacement(api):
    client, _ = api
    before = client.get(f"/api/audits/{AUDIT}/blockers").json()["blockers"]
    register = _get(client)["register"]
    verified = next(r for r in register if r["evidence_label"] == "Verified")["claim_id"]
    _inputs(client, {"top5": [verified, *[r["claim_id"] for r in register[1:5]]]})
    after = client.get(f"/api/audits/{AUDIT}/blockers").json()["blockers"]
    assert after == before and {b["claim_id"] for b in after if b["kind"] == "claim_contradicted"} == \
        {r["claim_id"] for r in register[:5] if r["evidence_label"] == "Contradicted"}


def test_the_verdict_reads_no_figure_of_results_that_fail_the_contract(api):
    client, db = api
    bad = copy.deepcopy(db["audits"].docs[0]["results"])
    bad["nrr"]["overall_pct"] = 106.41
    db["audits"].docs[0]["results"] = bad
    v = _verdict(client)["verdict"]
    assert v["status"] == "no_verdict" and v["message"].startswith("No verdict: the stored results fail the contract: ")
    assert "nrr.overall_pct" in v["message"] and "106" not in v["message"]


# --- section 4: data gaps -------------------------------------------------------------------------------------------------------------

def _gaps(run="A", top=()):
    rows = register(RUNS[run])
    return rows, vd.data_gaps(results_for(RUNS[run]), rows, list(top))


def test_the_gap_list_holds_the_missing_items_that_name_an_analysis_and_nothing_else():
    results = copy.deepcopy(engine_results())
    results["missing_data"] = [
        {"metric": "NRR (12-month)", "reason": "Needs 12+ months", "unlocked_by": "Provide 13 months", "status": "Missing"},
        {"metric": "Revenue rows with blank amount", "reason": "r", "unlocked_by": "u", "status": "Missing"},
        {"metric": "As-of month", "reason": "r", "unlocked_by": "u", "status": "Missing"},
        {"metric": "CAC payback (calculation error)", "reason": "r", "unlocked_by": "u", "status": "Missing"},
        {"metric": "CAC payback (quarters without P&L)", "reason": "No P&L rows", "unlocked_by": "Upload P&L", "status": "Missing"},
        {"metric": "Sales cycle", "reason": "r", "unlocked_by": "u", "status": "Computed – explanation requested"},
        {"metric": "Observed net-new customers (24 months)", "reason": "Needs 25+", "unlocked_by": "Provide", "status": "Missing"}]
    gaps = vd.data_gaps(results, [], [])
    assert [g["item"] for g in gaps] == ["NRR (12-month)", "CAC payback (quarters without P&L)",
                                         "Observed net-new customers (24 months)"]
    assert [g["analysis"] for g in gaps] == ["NRR", "CAC Payback by Quarter", "Path to Plan"]
    assert {i["item"] for i in vd.other_requests(results)} >= {"Revenue rows with blank amount", "As-of month",
                                                                "CAC payback (calculation error)"}


def test_the_fixture_gaps_are_the_three_path_to_plan_items_and_say_what_they_block():
    rows, gaps = _gaps("A")
    assert [g["item"] for g in gaps] == ["Required vs observed net-new customers (12m)", "Required vs observed net-new customers (24m)",
                                         "Observed net-new customers (24 months)"]
    assert gaps[0]["why"] == "Blocks Path to Plan. customer base shrinking or flat; ratio not meaningful."
    assert gaps[2]["requested"] == "Provide at least 25 months of revenue lines"


def test_a_gap_that_blocks_register_claims_names_their_ranks_and_sorts_first():
    rows, gaps = _gaps("B", top=[r["claim_id"] for r in register(RUNS["B"])[:5]])
    first = gaps[0]
    assert first["item"] == "Sales cycle & win rate" and first["blocks_top5"] == 1
    assert first["why"].startswith("Blocks Sales cycle and Win rate; claims #1. ")
    assert [g["blocks_top5"] for g in gaps] == sorted((g["blocks_top5"] for g in gaps), reverse=True)
    assert [g["item"] for g in vd.top_gaps(gaps)] == [g["item"] for g in gaps[:3]]


def test_an_item_computed_from_another_file_is_a_management_question_not_a_gap():
    results = copy.deepcopy(engine_results())
    results["missing_data"] = [{"metric": "Sales cycle & win rate", "reason": "CRM not provided", "unlocked_by": "Upload CRM",
                                "status": "Computed – explanation requested"}]
    results["questions_for_management"] = [{"metric": "Sales cycle", "status": "Computed – explanation requested",
                                            "question": "Sales cycle was computed from the revenue upload."}]
    assert vd.data_gaps(results, [], []) == []
    assert vd.management_questions(results) == ["Sales cycle was computed from the revenue upload."]


def test_the_items_the_engine_does_not_test_against_every_upload_each_need_a_field_only_one_upload_type_carries():
    """The V6 pass tests the six analyses of growth_engine.ANALYSIS_NEEDS against every upload. The other gap items must be
    answerable by one upload type only, or a stored file could answer a gap the list names."""
    import growth_engine as ge

    defs = {dtype: set(d["required"]) | set(d["optional"]) for dtype, d in server.FIELD_DEFS.items()}
    covered = {prefix for prefix, _ in vd.GAP_ANALYSES}
    assert set(ge.MISSING_ANALYSES) <= covered, "every item the V6 pass tests is a gap candidate"
    others = covered - set(ge.MISSING_ANALYSES)
    assert others == set(vd.SINGLE_TYPE_NEEDS), others ^ set(vd.SINGLE_TYPE_NEEDS)
    for prefix, (dtype, fields) in vd.SINGLE_TYPE_NEEDS.items():
        carrying = [t for t, names in defs.items() if set(fields) <= names]
        assert carrying == [dtype], f"{prefix}: {fields} are carried by {carrying}"


# --- the analyst's dates (W7) -----------------------------------------------------------------------------------------------------------

def test_a_gap_date_needs_the_review_first_and_may_not_be_after_it_and_the_review_may_not_move_before_a_gap(api):
    client, db = api
    item = _verdict(client)["data_gaps"][0]["item"]
    gap = {"gap_target_dates": {item: "2024-08-31"}}
    first = _inputs(client, gap)
    assert first.status_code == 400 and first.json()["detail"] == "Set the first quarterly review first."
    assert _inputs(client, {"first_quarterly_review": "2024-09-30"}).status_code == 200
    late = _inputs(client, {"gap_target_dates": {item: "2024-10-31"}})
    assert late.status_code == 400
    assert late.json()["detail"] == "The target date must be on or before the first quarterly review (2024-09-30)."
    assert _inputs(client, gap).status_code == 200
    early = _inputs(client, {"first_quarterly_review": "2024-07-31"})
    assert early.status_code == 400
    assert early.json()["detail"] == "The first quarterly review cannot be before a gap's target date (2024-08-31)."
    assert db["audits"].docs[0]["ic_inputs"]["first_quarterly_review"] == "2024-09-30", "a refusal writes nothing"
    assert _inputs(client, {"gap_target_dates": {"No such gap": "2024-01-01"}}).status_code == 400


@pytest.mark.parametrize("body", [{"ratings": {"data_reliability": "Excellent"}}, {"ratings": {"defensibility": "Strong"}},
                                  {"thesis": {"plan": "x" * 301}}, {"thesis": {"vision": "x"}}, {"first_quarterly_review": "soon"},
                                  {}, {"unknown": 1}])
def test_inputs_that_are_not_valid_are_refused_and_write_nothing(api, body):
    client, db = api
    assert _inputs(client, body).status_code in (400, 422)
    assert db["audits"].docs[0].get("ic_inputs") is None


def test_ratings_and_thesis_are_stored_on_the_audit_and_a_thesis_of_300_characters_is_kept(api):
    client, db = api
    r = _inputs(client, {"ratings": {"data_reliability": "Strong", "growth_engine": "Weak"},
                         "thesis": {"plan": "p" * 300, "evidence": "e", "condition": "c"}})
    assert r.status_code == 200
    ic = db["audits"].docs[0]["ic_inputs"]
    assert ic["ratings"] == {"data_reliability": "Strong", "growth_engine": "Weak"} and len(ic["thesis"]["plan"]) == 300
    assert _inputs(client, {"ratings": {"growth_engine": None}}).status_code == 200
    assert db["audits"].docs[0]["ic_inputs"]["ratings"] == {"data_reliability": "Strong"}


# --- rule 22: delete audit removes the new inputs with their documents ----------------------------------------------------------------

def test_delete_audit_removes_the_ic_inputs_and_every_claim_input_with_their_documents(api):
    client, db = api
    ids = _verdict(client)["verdict"]["top5"]["proposed"]
    _inputs(client, {"top5": ids, "ratings": {"data_reliability": "Strong"}, "thesis": {"plan": "Quartz thesis"}})
    assert _put(client, ids[0], {**GATE, "gate_metric_name": "Zephyr cover", "gate_direction": "at most"}).status_code == 200
    assert _put(client, ids[0], {"key_gate": True}).status_code == 200
    blob = str([db["audits"].docs, db[decks.CANDIDATES_COLLECTION].docs])
    assert "Quartz thesis" in blob and "Zephyr cover" in blob, "fixture: the inputs are stored"
    r = client.request("DELETE", f"/api/audits/{AUDIT}", json={"confirm": "TestCo"})
    assert r.status_code == 400, "the company name is required"
    db["audits"].docs[0]["company_name"] = "TestCo"
    r = client.request("DELETE", f"/api/audits/{AUDIT}", json={"confirm": "TestCo"})
    assert r.status_code == 200, r.text
    left = {name: str(col.docs) for name, col in db._cols.items() if col.docs}
    assert not any("Quartz thesis" in b or "Zephyr cover" in b for b in left.values()), left.keys()
    assert not [d for d in db[decks.CANDIDATES_COLLECTION].docs if d.get("audit_id") == AUDIT] and not db["audits"].docs


# --- 2026-10-08: the memo and the verdict word a claim in another currency, and a direction, as the register does -------------

def test_a_claim_in_another_currency_is_worded_with_both_figures_in_the_verdict_and_the_memo_register():
    row = {"claim_id": "c1", "rank": 1, "evidence_label": "Contradicted", "claim_type": "revenue", "metric": "ARR",
           "claimed_value": 150000.0, "claimed_high": None, "unit": None, "currency": "GBP", "claimed_converted": 171000.0,
           "claimed_converted_high": None, "fx_rate": 1.14, "fx_date": "2026-06-30", "claim_direction": None}
    assert vd.claimed_text(row, "EUR") == "£150,000 (€171,000 at 1.14, 30 Jun 2026)"
    assert vd.claimed_text({**row, "currency": "EUR", "claimed_converted": None, "fx_rate": None, "fx_date": None}, "EUR") == "€150,000"
    assert vd.claimed_text({**row, "claimed_value": None, "currency": None, "claimed_converted": None, "claim_direction": "positive"},
                           "EUR") == "positive (no figure)"
