"""The top 5 the app selects, the always-computed verdict, the key gates and the data gaps (docs/design/simplified-flow.md, verdict-and-memo.md).

Pure rows for the rule; the register endpoints (in-memory Mongo stub, no network) for the analyst's inputs. Each test was shown
failing on a deliberate violation (CLAUDE.md rule 11): the violations are listed in the session log.
"""
import copy

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import server  # noqa: E402
from claim_matching_support import answer_definition, engine_results  # noqa: E402
from test_claim_matching import RUNS, register, results_for, row_of  # noqa: E402
from test_claim_register_api import AUDIT, _get, _put  # noqa: E402

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


def verdict_of(labels, gates=(), stored="all", **extra):
    rows = [row(i + 1, label, gate=(i + 1) in gates, **extra) for i, label in enumerate(labels)]
    ids = [r["claim_id"] for r in rows[:5]]
    return vd.verdict(rows, {"reporting_currency": "EUR"}, {"claim_ids": ids} if stored == "all" else stored), rows


# --- section 6.2: the rule, in order ---------------------------------------------------------------------------------------

# claim-review-conclusion.md section 2 (replaces the Underwrite / Re-plan rule): Contradicted, then Insufficient evidence, then
# Supported, then Partly supported. Untested = Unverified, Inconclusive or Unsupported.

def test_supported_when_every_selected_claim_is_verified():
    v, _ = verdict_of(["Verified"] * 5 + ["Contradicted"])
    assert (v["status"], v["outcome"], v["outcome_code"], v["rule"]) == (
        "ok", "Selected claims supported", "supported", "All 5 selected claims are Verified.")


def test_insufficient_evidence_when_nothing_is_contradicted_and_three_are_untested():
    v, _ = verdict_of(["Verified", "Unverified", "Unsupported", "Unsupported", "Verified"], gates={2, 3, 4})
    assert (v["outcome"], v["outcome_code"], v["rule"]) == (
        "Insufficient evidence", "insufficient", "No selected claim is Contradicted; 3 of 5 are untested (Unverified, Inconclusive or Unsupported).")


def test_inconclusive_counts_as_untested():
    v, _ = verdict_of(["Verified", "Inconclusive", "Inconclusive", "Unverified", "Verified"], gates={2, 3, 4})
    assert v["outcome_code"] == "insufficient"
    v, _ = verdict_of(["Verified", "Inconclusive", "Verified", "Verified", "Verified"], gates={2})
    assert (v["outcome_code"], v["rule"]) == ("partly_supported", "No selected claim is Contradicted; 4 of 5 are Verified, 1 untested.")


def test_not_supported_when_a_selected_claim_is_contradicted_a_miss():
    rows = register(RUNS["A"])
    miss = row_of(rows, "c28")              # Revenue Q4 2023 (c06, undated, waits for its period since claim-types-and-correction.md)
    assert (miss["gap_kind"], miss["evidence_label"]) == ("miss", "Contradicted")
    verified = [r for r in rows if r["evidence_label"] == "Verified"][:4]
    five = [miss, *verified]
    v = vd.verdict(gated(rows), results_for(RUNS["A"]), {"claim_ids": [r["claim_id"] for r in five]})
    assert (v["status"], v["outcome"], v["outcome_code"], v["rule"]) == (
        "ok", "Selected claims not supported", "not_supported", "1 selected claim is Contradicted.")


def test_a_selected_beat_beyond_tolerance_is_verified_so_it_is_supported_and_never_blocks():
    """Amended 2026-10-13 (George): a beat outside tolerance is Verified, marked (beat); it needs no gate."""
    rows = register(RUNS["A"])
    beat = row_of(rows, "c08")
    assert (beat["gap_kind"], beat["evidence_label"], beat["gate_needed"]) == ("beat", "Verified", False)
    verified = [r for r in rows if r["evidence_label"] == "Verified" and r is not beat][:4]
    five = [beat, *verified]
    v = vd.verdict(rows, results_for(RUNS["A"]), {"claim_ids": [r["claim_id"] for r in five]})
    assert (v["status"], v["outcome"], v["rule"]) == ("ok", "Selected claims supported", "All 5 selected claims are Verified.")


def test_contradicted_comes_before_insufficient_evidence():
    v, _ = verdict_of(["Contradicted", "Unsupported", "Unsupported", "Unverified", "Verified"], gates={1, 2, 3, 4})
    assert (v["outcome_code"], v["rule"]) == ("not_supported", "1 selected claim is Contradicted.")


def test_two_untested_and_three_verified_is_partly_supported():
    v, _ = verdict_of(["Unsupported", "Unverified", "Verified", "Verified", "Verified"], gates={1, 2})
    assert (v["outcome"], v["outcome_code"]) == ("Selected claims partly supported", "partly_supported")


def test_with_fewer_than_five_rows_the_top_5_is_every_row_and_the_rule_says_so():
    v, rows = verdict_of(["Verified", "Verified", "Verified"])
    assert len(v["five"]) == 3 and v["outcome"] == "Selected claims supported"
    assert v["rule"] == "All 3 selected claims are Verified. Top 3 (the register has 3 claims)."
    v, rows = verdict_of(["Unverified", "Unverified", "Unsupported"], gates={1, 2, 3})
    assert v["outcome_code"] == "insufficient", "3 or more stays 3"


def test_no_rows_and_no_results_give_no_verdict():
    assert vd.verdict([], {"reporting_currency": "EUR"}, None)["message"] == "No testable claims found. Upload a deck or plan with revenue targets."
    assert vd.verdict([row(1, "Verified")], None, None)["message"] == "No conclusion: compute the audit first."
    assert vd.verdict([], {"reporting_currency": "EUR"}, None)["status"] == "no_verdict"


def test_the_three_reasons_are_the_claims_that_made_the_rule_fire_each_citing_its_evidence():
    rows = register(RUNS["A"])
    v = vd.verdict(rows, results_for(RUNS["A"]), None)
    assert v["outcome"] == "Selected claims not supported" and len(v["reasons"]) == 3
    assert v["reasons"][0] == ("#1 Revenue, Q4 2023: Contradicted, €49,047 against €60,000 (€10,953 lower (miss)). "
                               "Evidence: Revenue by month (revenue_series.data.total, CSV, rows 2–71 (70 rows), Oct–Dec 2023).")
    unsupported = [row(1, "Unsupported", gate=True), *[row(i, "Verified") for i in range(2, 6)]]
    again = vd.verdict(unsupported, {"reporting_currency": "EUR"}, {"claim_ids": [r["claim_id"] for r in unsupported]})
    assert again["reasons"][0] == "#1 ARR, Feb 2024: Unsupported, reason 1.", "an implied claim with no stated value: the files are not what is missing"
    missing = [row(1, "Unverified", gate=True, reason="Missing: CRM export"), *[row(i, "Verified") for i in range(2, 6)]]
    assert vd.verdict(missing, {"reporting_currency": "EUR"}, {"claim_ids": [r["claim_id"] for r in missing]})["reasons"][0] == \
        "#1 ARR, Feb 2024: Unverified, Missing: CRM export. No figure in the supplied files."


@pytest.mark.parametrize("run, expected", [("A", ("ok", "Selected claims not supported")), ("B", ("ok", "Selected claims partly supported")),
                                           ("C", ("ok", "Selected claims not supported")), ("D", ("ok", "Selected claims not supported"))])
def test_the_fixture_runs_give_their_outcome_at_once_with_no_confirmation_and_no_gate(run, expected):
    """simplified-flow.md: the verdict is always computed from the five the app selects; nothing is confirmed, nothing blocks."""
    rows = register(RUNS[run])
    v = vd.verdict(rows, results_for(RUNS[run]), None)
    assert (v["status"], v["outcome"]) == expected
    assert [f["claim_id"] for f in v["five"]] == vd.proposal(rows) and v["top5"]["changed"] is False


def _run_d(answer=None):
    """Run D's register with the analyst's answer to c37's Definition check (New MRR €5,000 claimed, 0 observed: a 100% miss)."""
    from test_claim_matching import candidates_for, settings
    run = RUNS["D"]
    cands = candidates_for(run)
    if answer:
        answer_definition(cands, cm.build_register(cands, results_for(run), settings(run)), "c37", answer)
    return cm.build_register(cands, results_for(run), settings(run))


def test_an_open_definition_check_counts_as_untested_and_is_a_count_on_the_rule_line_never_a_block():
    """claim-matching.md section 4.1 as amended: a gap beyond 50% has no label until the analyst answers; the row counts as untested and
    the explanation line adds "1 question open."; the outcome is never blocked (simplified-flow.md decision 4)."""
    rows = _run_d()
    c37 = row_of(rows, "c37")
    assert (c37["evidence_label"], c37["definition_check"], c37["rank"], c37["gate_needed"]) == (None, "ask", 1, False)
    assert c37["definition_question"] == "Observed €0, claimed €5,000. Same metric and period?"
    ids = {"claim_ids": ["c37", *[i for i in vd.proposal(rows) if i != "c37"][:4]]}
    v = vd.verdict(rows, results_for(RUNS["D"]), ids, open_questions=1)
    assert v["status"] == "ok" and v["outcome"] == "Selected claims not supported"
    assert v["rule"] == "1 selected claim is Contradicted. 1 question open."
    assert next(f for f in v["five"] if f["claim_id"] == "c37")["definition_check"] == "ask"
    assert sum(cm.label_counts(rows).values()) == len(rows) - 1, "the open check is in no count by label"
    only = [row(1, None, definition_check="ask"), *[row(i, "Verified") for i in range(2, 6)]]
    held = vd.verdict(only, {"reporting_currency": "EUR"}, None, open_questions=2)
    assert (held["outcome"], held["rule"]) == ("Selected claims partly supported",
                                               "No selected claim is Contradicted; 4 of 5 are Verified, 1 untested. 2 questions open.")
    assert "Definition check open" in held["reasons"][0], "a row with no label reads as its status, never as None"
    quiet = vd.verdict(only, {"reporting_currency": "EUR"}, None)
    assert "question" not in quiet["rule"], "the count is added only when a question is open"
    yes = _run_d("yes")
    assert (row_of(yes, "c37")["evidence_label"], row_of(yes, "c37")["definition_check"]) == ("Contradicted", "yes")
    no = _run_d("no")
    assert (row_of(no, "c37")["evidence_label"], row_of(no, "c37")["reason"], row_of(no, "c37")["gate_needed"]) == \
        ("Unverified", "definition mismatch", False)
    assert row_of(no, "c37")["gate_status"] == "proposed", "a No needs a gate as any Unverified claim, written from the claim"


# --- the top 5 the app selects -----------------------------------------------------------------------------------------------

def test_the_five_are_in_force_without_a_confirmation_and_follow_the_selection_rule():
    rows = register(RUNS["A"])
    v = vd.verdict(rows, results_for(RUNS["A"]), None)
    assert v["status"] == "ok" and v["top5"]["proposed"] == vd.proposal(rows) == v["top5"]["in_force"]
    assert v["top5"]["changed"] is False and "confirmed" not in v["top5"]
    assert v["top5"]["proposed"] == ["c28", "c05", "c32", "c24", "c23"], "plan claims first, by normalised shortfall: no Target ARR on the fixture"


def _sel(rank, label, vas=None, shortfall=None, claim_type="revenue", value=100.0):
    return row(rank, label, value_at_stake_arr=vas, shortfall=shortfall, claim_type=claim_type, claimed_value=value)


def test_the_selection_ranks_by_value_at_stake_then_shortfall_whatever_the_label():
    """simplified-flow.md decision 11 (reversed): VaS first, then the normalised shortfall; the label is no key."""
    rows = [_sel(1, "Unverified", vas=900), _sel(2, "Verified", vas=800), _sel(3, "Contradicted", vas=100, shortfall=0.2),
            _sel(4, "Unverified", vas=700), _sel(5, "Unverified", vas=600), _sel(6, "Contradicted", vas=50, shortfall=0.1),
            _sel(7, "Unverified", vas=500)]
    assert vd.proposal(rows) == ["r1", "r2", "r4", "r5", "r7"], "pure VaS: a Contradicted row of small VaS (r3, r6) is not in the five"
    ties = [_sel(1, "Unverified", vas=100, shortfall=None), _sel(2, "Contradicted", vas=100, shortfall=0.1),
            _sel(3, "Contradicted", vas=100, shortfall=0.3), _sel(4, "Unverified", vas=None), _sel(5, "Unverified", vas=100),
            _sel(6, "Unverified", vas=100)]
    assert vd.proposal(ties) == ["r3", "r2", "r1", "r5", "r6"], "same VaS: the larger shortfall first; a row with no VaS after those with one"
    assert vd.proposal([_sel(1, "Unverified", vas=5), _sel(2, "Unverified", vas=None, claim_type="cac_payback"),
                        _sel(3, "Unverified", vas=9, claim_type="cac_payback")]) == ["r1", "r3", "r2"], "a plan claim before any other"


def test_a_stored_set_the_analyst_changed_stays_in_force_and_one_equal_to_the_selection_is_the_selection():
    rows = register(RUNS["A"])
    selection = vd.proposal(rows)
    verified = next(r for r in rows if r["evidence_label"] == "Verified" and r["claim_id"] not in selection)
    swapped = [verified["claim_id"], *selection[1:]]
    state = vd.top5_state(rows, {"claim_ids": swapped, "set_at": "2026-10-25"})
    assert (state["changed"], state["set_at"]) == (True, "2026-10-25")
    assert set(state["in_force"]) == set(swapped) and state["proposed"] == selection
    same = vd.top5_state(rows, {"claim_ids": list(reversed(selection))})
    assert (same["changed"], same["in_force"]) == (False, selection)
    v = vd.verdict(rows, results_for(RUNS["A"]), {"claim_ids": swapped})
    assert v["rule"] == "3 selected claims are Contradicted." and swapped[0] in [f["claim_id"] for f in v["five"]]


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


def test_a_changed_claim_leaving_the_register_drops_the_change_and_the_selection_is_in_force_again():
    rows = register(RUNS["A"])
    verified = next(r for r in rows if r["evidence_label"] == "Verified")
    stored = {"claim_ids": [verified["claim_id"], *vd.proposal(rows)[1:]]}
    assert vd.top5_state(rows, stored)["changed"]
    left = [r for r in rows if r["claim_id"] != verified["claim_id"]]
    state = vd.top5_state(left, stored)
    assert (state["changed"], state["in_force"]) == (False, vd.proposal(left))
    v = vd.verdict(left, results_for(RUNS["A"]), stored)
    assert v["status"] == "ok" and v["top5"]["changed"] is False, "no void state exists"
    shuffled = sorted(({**r, "rank": len(rows) + 1 - r["rank"]} for r in rows), key=lambda r: r["rank"])
    assert vd.top5_state(shuffled, stored)["changed"], "a new rank order alone does not drop the change"


def test_the_banner_reads_the_five_in_force_the_apps_selection_or_the_set_the_analyst_changed():
    rows = register(RUNS["A"])
    assert vd.banner_ids(rows) == vd.proposal(rows) and vd.banner_ids(rows, {"claim_ids": vd.proposal(rows)}) == vd.proposal(rows)
    selection = vd.proposal(rows)
    other = next(r["claim_id"] for r in vd.sortable(rows) if r["claim_id"] not in selection)
    changed = [other, *selection[1:]]
    assert set(vd.banner_ids(rows, {"claim_ids": changed})) == set(changed) != set(selection)


# --- the verdict is never blocked -----------------------------------------------------------------------------------------------

def test_a_non_verified_top_5_claim_without_an_analyst_gate_does_not_block():
    v, _ = verdict_of(["Verified", "Unverified", "Verified", "Verified", "Verified"])
    assert v["status"] == "ok" and v["outcome"] == "Selected claims partly supported" and "blocked" not in v


def test_a_verified_top_5_claim_does_not_block():
    v, _ = verdict_of(["Verified"] * 5)
    assert v["status"] == "ok"


# --- section 3: gates ------------------------------------------------------------------------------------------------------------

BASE = {"claim_type": "revenue", "snippet": "ARR", "value": 200000, "target_date": "2024-02", "period_text": "Feb 2024"}


def run_row(claim, inputs=None, **extra):
    from test_claim_matching import run_claim
    return run_claim({**BASE, **claim, "claim_inputs": {"x1": inputs or {}}}, **extra)


GATE = {"gate_threshold": 150000.0, "gate_budget_decision": "the Series B hiring plan", "gate_date": "2024-06-30"}


def test_the_gate_is_written_from_the_claim_and_the_analysts_edit_needs_threshold_and_date():
    proposed = run_row({"value": 240000})
    assert (proposed["gate_date"], proposed["gate_threshold"], proposed["gate_status"], proposed["gate_saved"]) == \
        ("2024-02-29", 240000, "proposed", False)
    r = run_row({"value": 240000}, {k: v for k, v in GATE.items() if k != "gate_date"})
    assert (r["gate_saved"], r["gate_status"], r["gate_date"]) == (False, "proposed", "2024-02-29"), "half an edit is the proposal"
    edited = run_row({"value": 240000}, GATE)
    assert (edited["gate_saved"], edited["gate_status"], edited["gate_date"]) == (True, "set by the analyst", "2024-06-30")
    assert vd.gate_text(proposed).endswith("(proposed)") and vd.gate_text(edited).endswith("(set by the analyst)")


def test_every_row_that_is_not_verified_has_a_gate_and_none_is_ever_needed_or_blocking():
    contradicted = run_row({"value": 240000})
    assert (contradicted["evidence_label"], contradicted["gate_needed"], contradicted["gate_status"]) == ("Contradicted", False, "proposed")
    assert run_row({"value": 240000}, GATE)["gate_needed"] is False
    verified = run_row({})
    assert (verified["evidence_label"], verified["gate_needed"], verified["gate_sentence"]) == ("Verified", False, None)
    unverified = run_row({"claim_type": "market", "snippet": "TAM"})
    assert (unverified["evidence_label"], unverified["gate_needed"], unverified["gate_status"]) == ("Unverified", False, "proposed")
    assert unverified["gate_metric_name"], "a row with no app metric is named by its claim"


def test_a_row_with_no_observed_figure_gets_the_sentence_of_w6():
    r = run_row({"claim_type": "market", "snippet": "TAM", "value": 2_000_000_000}, {
        **GATE, "gate_threshold": 5, "gate_metric_name": "Pipeline coverage", "gate_direction": "at least"})
    assert r["reason"] == "no metric" and r["gate_saved"] is True
    assert r["gate_sentence"] == ("Before the Series B hiring plan, Pipeline coverage must be at least €5 by 2024-06-30. "
                                  "Not yet observed: no metric; claimed €2,000,000,000 (Feb 2024).")


def test_a_no_metric_row_edit_needs_the_metric_name_and_the_direction():
    market = {"claim_type": "market", "snippet": "TAM"}
    assert run_row(market, GATE)["gate_saved"] is False, "no name, no direction"
    assert run_row(market, {**GATE, "gate_metric_name": "Pipeline coverage"})["gate_saved"] is False, "no direction"
    assert run_row(market, {**GATE, "gate_direction": "at most"})["gate_saved"] is False, "no name"
    full = run_row(market, {**GATE, "gate_metric_name": "Pipeline coverage", "gate_direction": "at most"})
    assert full["gate_saved"] is True and "must be at most" in full["gate_sentence"]
    assert run_row({"value": 240000}, {**GATE})["gate_saved"] is True, "an app metric needs neither"


def test_an_untested_row_with_an_app_metric_gets_w6_with_the_apps_metric_and_direction():
    r = run_row({"currency": "USD", "value": 210000}, GATE)
    assert r["evidence_label"] == "Unverified" and r["reason"] == "FX rate needed: USD→EUR"
    assert r["gate_sentence"] == ("Before the Series B hiring plan, ARR must be at least €150,000 by 2024-06-30. "
                                  "Not yet observed: FX rate needed: USD→EUR; claimed $210,000 (Feb 2024).")


def _gated(rank, label, text=None):
    return row(rank, label, gate_sentence=text if text is not None else f"gate {rank}" if label != "Verified" else None,
               gate_status="proposed" if label != "Verified" else None)


def test_key_gates_are_the_gates_of_the_non_verified_top_5_rows_and_never_padded():
    rows = [_gated(1, "Contradicted"), _gated(2, "Verified"), _gated(3, "Unverified"), _gated(4, "Verified"), _gated(5, "Verified"),
            _gated(6, "Unverified"), _gated(7, "Unverified")]
    key = vd.key_gates(rows, [f"r{i}" for i in range(1, 6)])
    assert [g["rank"] for g in key["gates"]] == [1, 3], "a Verified row has none; a gate outside the five is not promoted"
    assert (key["saved"], key["ok"], key["note"]) == (2, True, "2 gates set; all are key gates.")
    assert vd.key_gates([_gated(i, "Verified") for i in range(1, 6)], [f"r{i}" for i in range(1, 6)])["note"] == \
        "No key gates: every selected claim is Verified."
    five = vd.key_gates([_gated(i, "Unverified") for i in range(1, 8)], [f"r{i}" for i in range(1, 6)])
    assert (len(five["gates"]), five["note"], five["all_key"]) == (5, None, False), "five gates at most, the five's own"
    assert [r["key_gate"] for r in vd.mark_key_gates(rows, [f"r{i}" for i in range(1, 6)])] == [True, False, True, False, False, False, False]


def test_a_gate_the_analyst_edited_keeps_its_place_and_reads_set_by_the_analyst():
    edited = row(1, "Unverified", gate_sentence="Before the plan, ARR must be at least 5.", gate_status="set by the analyst")
    key = vd.key_gates([edited], ["r1"])
    assert vd.gate_text(key["gates"][0]) == "Before the plan, ARR must be at least 5. (set by the analyst)"


# --- the analyst's top 5 through the API -----------------------------------------------------------------------------------------

def _verdict(client):
    r = client.get(f"/api/audits/{AUDIT}/verdict")
    assert r.status_code == 200, r.text
    return r.json()


def _inputs(client, body):
    return client.put(f"/api/audits/{AUDIT}/ic-inputs", json=body)


def test_the_verdict_endpoint_gives_the_outcome_at_once_from_the_five_the_app_selects(register_api):
    client, _ = register_api
    body = _verdict(client)
    register = _get(client)["register"]
    assert body["verdict"]["status"] == "ok" and body["verdict"]["outcome"] is not None
    assert body["verdict"]["top5"]["proposed"] == vd.proposal(register) == body["verdict"]["top5"]["in_force"]
    assert body["verdict"]["top5"]["changed"] is False
    assert len(body["candidates"]) == len(register)
    assert body["selection_sentence"] == "Selected by the app by value at stake; the analyst may change the selection"
    assert body["ratings"]["data_reliability"]["line"] and "judgment" not in body["ic_inputs"]
    assert {g["claim_id"] for g in body["key_gates"]["sentences"]} <= set(body["verdict"]["top5"]["in_force"])


def test_changing_the_set_stores_it_as_the_analysts_and_a_wrong_size_is_refused(register_api):
    client, db = register_api
    ids = _verdict(client)["verdict"]["top5"]["proposed"]
    assert _inputs(client, {"top5": ids[:4]}).status_code == 400
    assert _inputs(client, {"top5": [ids[0]] * 5}).status_code == 400
    assert db["audits"].docs[0].get("ic_inputs") is None
    same = _inputs(client, {"top5": ids})
    assert same.status_code == 200 and same.json()["verdict"]["top5"]["changed"] is False, "a set equal to the selection is the selection"
    register = _get(client)["register"]
    other = next(r["claim_id"] for r in register if r["claim_id"] not in ids and r["claim_type"] not in vd.PROPOSAL_EXCLUDED)
    changed = _inputs(client, {"top5": [other, *ids[1:]]})
    assert changed.status_code == 200
    top5 = changed.json()["verdict"]["top5"]
    assert top5["changed"] is True and set(top5["in_force"]) == {other, *ids[1:]} and top5["set_at"]
    assert changed.json()["verdict"]["status"] == "ok", "never blocked"
    reset = _inputs(client, {"top5": None})
    assert reset.json()["verdict"]["top5"]["changed"] is False


def test_a_changed_claim_that_is_rejected_leaves_the_register_and_the_selection_is_in_force_again(register_api):
    client, db = register_api
    ids = _verdict(client)["verdict"]["top5"]["proposed"]
    other = next(r["claim_id"] for r in _get(client)["register"] if r["claim_id"] not in ids and r["claim_type"] not in vd.PROPOSAL_EXCLUDED)
    _inputs(client, {"top5": [other, *ids[1:]]})
    gone = next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == other.split("#")[0])
    gone["status"] = "rejected"
    v = _verdict(client)["verdict"]
    assert v["status"] == "ok" and v["top5"]["changed"] is False and v["top5"]["in_force"] == v["top5"]["proposed"]


def test_the_banner_reads_the_set_in_force_after_the_analyst_changes_the_set(register_api):
    client, _ = register_api
    register = _get(client)["register"]
    selection = vd.proposal(register)
    verified = next(r for r in register if r["evidence_label"] == "Verified" and r["claim_id"] not in selection)["claim_id"]
    swapped = [verified, *selection[1:]]
    in_force = lambda ids: {r["claim_id"] for r in register if r["claim_id"] in ids and r["evidence_label"] == "Contradicted"}   # noqa: E731
    banner = lambda: {b["claim_id"] for b in client.get(f"/api/audits/{AUDIT}/blockers").json()["blockers"] if b["kind"] == "claim_contradicted"}  # noqa: E731
    assert banner() == in_force(selection)
    _inputs(client, {"top5": swapped})
    assert banner() == in_force(swapped) != in_force(selection), "the claim that left the five leaves the banner (it stays in Other contradictions)"


def test_the_verdict_reads_no_figure_of_results_that_fail_the_contract(register_api):
    client, db = register_api
    bad = copy.deepcopy(db["audits"].docs[0]["results"])
    bad["nrr"]["overall_pct"] = 106.41
    db["audits"].docs[0]["results"] = bad
    v = _verdict(client)["verdict"]
    assert v["status"] == "no_verdict" and v["message"].startswith("No conclusion: the stored results fail the contract: ")
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
    run = copy.deepcopy(RUNS["B"])
    for entry in run["claims"]:                 # the win rate claim, dated at the as-of month: a claim with no period is not matched
        if entry["claim_id"] == "c11":
            entry["candidate"].update(target_date="2024-02", period_text="Feb 2024")
    rows = register(run)
    gaps = vd.data_gaps(results_for(run), rows, [r["claim_id"] for r in rows[:5]])
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

def test_a_gap_date_needs_the_review_first_and_may_not_be_after_it_and_the_review_may_not_move_before_a_gap(register_api):
    client, db = register_api
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


@pytest.mark.parametrize("body", [{"ratings": {"data_reliability": "Strong"}}, {"judgment": {"reasons": "x"}}, {"note": "n" * 1001},
                                  {"thesis": {"plan": "x" * 301}}, {"thesis": {"vision": "x"}}, {"first_quarterly_review": "soon"},
                                  {}, {"unknown": 1}])
def test_inputs_that_are_not_valid_are_refused_and_write_nothing(register_api, body):
    client, db = register_api
    assert _inputs(client, body).status_code in (400, 422)
    assert db["audits"].docs[0].get("ic_inputs") is None


def test_the_thesis_and_the_analyst_note_are_stored_on_the_audit_and_the_note_clears_with_null(register_api):
    client, db = register_api
    r = _inputs(client, {"note": "  Management call booked for 3 Nov.  ", "thesis": {"plan": "p" * 300, "evidence": "e", "condition": "c"}})
    assert r.status_code == 200
    ic = db["audits"].docs[0]["ic_inputs"]
    assert ic["note"] == "Management call booked for 3 Nov." and len(ic["thesis"]["plan"]) == 300
    assert r.json()["ic_inputs"]["note"] == ic["note"] and r.json()["note_max"] == 1000
    assert _inputs(client, {"note": "n" * 1000}).status_code == 200
    assert _inputs(client, {"note": None}).status_code == 200
    assert "note" not in db["audits"].docs[0]["ic_inputs"]
    assert db["audits"].docs[0]["ic_inputs"]["thesis"]["plan"] == "p" * 300, "a key not sent stays"


def test_the_ratings_and_judgment_a_stored_audit_holds_stay_stored_and_are_not_read(register_api):
    client, db = register_api
    db["audits"].docs[0]["ic_inputs"] = {"ratings": {"data_reliability": "Strong", "growth_engine": "Strong"},
                                         "judgment": {"reasons": "old reasons", "unresolved_questions": "old questions"}}
    body = _verdict(client)
    reliability = body["ratings"]["data_reliability"]
    assert (reliability["rating"], reliability["line"]) == ("Weak", "Weak (Material concerns; 4 of 5 checks)"), "from the integrity conclusion"
    assert reliability["rule"] == "Weak: at least one check Red, 4 of 5 completed"
    assert "old reasons" not in str(body), "the computed rating and lists show"
    assert _inputs(client, {"note": "kept"}).status_code == 200
    assert db["audits"].docs[0]["ic_inputs"]["judgment"]["reasons"] == "old reasons", "stored fields are untouched"


# --- rule 22: delete audit removes the new inputs with their documents ----------------------------------------------------------------

def test_delete_audit_removes_the_ic_inputs_and_every_claim_input_with_their_documents(register_api):
    client, db = register_api
    ids = _verdict(client)["verdict"]["top5"]["proposed"]
    _inputs(client, {"top5": ids, "note": "Plumb note", "thesis": {"plan": "Quartz thesis"}})
    assert _put(client, ids[0], {**GATE, "gate_metric_name": "Zephyr cover", "gate_direction": "at most"}).status_code == 200
    blob = str([db["audits"].docs, db[decks.CANDIDATES_COLLECTION].docs])
    assert "Quartz thesis" in blob and "Zephyr cover" in blob and "Plumb note" in blob, "fixture: the inputs are stored"
    r = client.request("DELETE", f"/api/audits/{AUDIT}", json={"confirm": "TestCo"})
    assert r.status_code == 400, "the company name is required"
    db["audits"].docs[0]["company_name"] = "TestCo"
    r = client.request("DELETE", f"/api/audits/{AUDIT}", json={"confirm": "TestCo"})
    assert r.status_code == 200, r.text
    left = {name: str(col.docs) for name, col in db._cols.items() if col.docs}
    assert not any("Quartz thesis" in b or "Zephyr cover" in b or "Plumb note" in b for b in left.values()), left.keys()
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


# --- Use of funds is not one of the top 5 ----------------------------------------------------------------------------------------

def test_a_use_of_funds_row_is_never_in_the_proposal_the_top_5_or_the_verdict():
    funds = row(1, "Unverified", claim_type="use_of_funds", metric=None)
    rows = [funds, *[row(i + 2, "Verified") for i in range(5)]]
    assert vd.proposal(rows) == [f"r{i}" for i in range(2, 7)] and vd.banner_ids(rows) == vd.proposal(rows)
    v = vd.verdict(rows, {"reporting_currency": "EUR"}, {"claim_ids": vd.proposal(rows)})
    assert (v["status"], v["outcome"]) == ("ok", "Selected claims supported") and "r1" not in [f["claim_id"] for f in v["five"]]
    with pytest.raises(ValueError):
        vd.check_top5(rows, ["r1", *vd.proposal(rows)[:4]])
    only = [funds]
    assert vd.proposal(only) == [] and vd.top5_state(only, None)["in_force"] == []
    assert vd.verdict(only, {"reporting_currency": "EUR"}, None)["message"] == vd.W10_NO_CLAIMS


# --- Use of funds through the API (deck-parser.md section 2, review of PR 86) -----------------------------------------------

def _add_funds(db):
    db[decks.CANDIDATES_COLLECTION].docs.append(
        {"audit_id": AUDIT, "id": "funds1", "status": "approved", "claim_type": "use_of_funds", "value": 40, "unit": "%",
         "file": "testco_board.pptx", "order": 99, "sources": [{"file": "testco_board.pptx", "slide": 22, "kind": "text"}]})


def test_the_top_5_replace_list_holds_no_use_of_funds_row(register_api):
    client, db = register_api
    before = len(_verdict(client)["candidates"])
    _add_funds(db)
    body = _verdict(client)
    assert len(body["candidates"]) == before, "the replace dropdown offers no Use of funds row"
    ranked = [r["claim_id"] for r in _get(client)["register"] if r["claim_type"] == "use_of_funds"]
    assert ranked and not {c["claim_id"] for c in body["candidates"]} & set(ranked)
    assert not set(ranked) & set(body["verdict"]["top5"]["proposed"])
    assert _inputs(client, {"top5": [*body["verdict"]["top5"]["proposed"][:4], ranked[0]]}).status_code == 400


def test_correcting_a_use_of_funds_figure_keeps_its_type_and_the_row_stays_out_of_the_top_5(register_api):
    client, db = register_api
    _add_funds(db)
    r = client.put(f"/api/audits/{AUDIT}/decks/candidates/funds1", json={"claim_type": "use_of_funds", "value": 42})
    assert r.status_code == 200, r.text
    assert (r.json()["claim_type"], r.json()["value"], r.json()["status"]) == ("use_of_funds", 42, "edited")
    body = _verdict(client)
    assert not [c for c in body["candidates"] if "funds" in str(c.get("claim", "")).lower()]
    assert "use_of_funds" not in {c["claim_type"] for c in _get(client)["register"] if c["claim_id"] in body["verdict"]["top5"]["proposed"]}
    # a bad type name is still refused
    assert client.put(f"/api/audits/{AUDIT}/decks/candidates/funds1", json={"claim_type": "nonsense"}).status_code == 422


def test_an_acquisition_channels_row_is_never_in_the_proposal_the_top_5_or_the_verdict():
    channel = row(1, "Unverified", claim_type="acquisition_channels", metric=None)
    rows = [channel, *[row(i + 2, "Verified") for i in range(5)]]
    assert vd.proposal(rows) == [f"r{i}" for i in range(2, 7)] and vd.banner_ids(rows) == vd.proposal(rows)
    v = vd.verdict(rows, {"reporting_currency": "EUR"}, {"claim_ids": vd.proposal(rows)})
    assert (v["status"], v["outcome"]) == ("ok", "Selected claims supported") and "r1" not in [f["claim_id"] for f in v["five"]]
    with pytest.raises(ValueError):
        vd.check_top5(rows, ["r1", *vd.proposal(rows)[:4]])
    assert vd.proposal([channel]) == [] and vd.top5_state([channel], None)["in_force"] == []


def test_the_top_5_replace_list_holds_no_acquisition_channels_row(register_api):
    client, db = register_api
    before = len(_verdict(client)["candidates"])
    db[decks.CANDIDATES_COLLECTION].docs.append(
        {"audit_id": AUDIT, "id": "chan1", "status": "approved", "claim_type": "acquisition_channels", "value": 30000, "unit": "count",
         "channel": "Telegram", "file": "testco_board.pptx", "order": 99,
         "sources": [{"file": "testco_board.pptx", "slide": 17, "kind": "text"}]})
    body = _verdict(client)
    ranked = [r["claim_id"] for r in _get(client)["register"] if r["claim_type"] == "acquisition_channels"]
    assert ranked and len(body["candidates"]) == before
    assert not set(ranked) & ({c["claim_id"] for c in body["candidates"]} | set(body["verdict"]["top5"]["proposed"]))
    assert _inputs(client, {"top5": [*body["verdict"]["top5"]["proposed"][:4], ranked[0]]}).status_code == 400
    kept = client.put(f"/api/audits/{AUDIT}/decks/candidates/chan1", json={"claim_type": "acquisition_channels", "value": 31000})
    assert (kept.status_code, kept.json()["claim_type"], kept.json()["status"]) == (200, "acquisition_channels", "edited")


# --- the ratings, computed (simplified-flow.md section 3) ------------------------------------------------------------------------------

def _growth(nrr=1.04, churn=0.05, months=10.0, quarters=True):
    results = {"nrr": {"overall_pct": nrr} if nrr is not None else None, "gross_churn": {"overall_pct": churn} if churn is not None else None}
    if quarters:
        results["cac_payback"] = {"default_l": 1, "headline_quarter": "2026-Q1" if months is not None else None,
                                  "quarters": {"2026-Q1": {"partial": False, "L1": {"months": months}}}}
    return results


def _rate(results):
    from app import formatting as fmt
    return vd.rate_growth(results, fmt.fmt_pct, fmt.fmt_months)


def test_strong_needs_all_three_inputs_present_and_green():
    assert _rate(_growth())["rating"] == "Strong"
    no_payback = _rate(_growth(months=None))
    assert no_payback["rating"] == "Adequate" and "CAC payback not computed" in no_payback["line"], "two green inputs are not enough for Strong"
    assert _rate(_growth(quarters=False))["rating"] == "Adequate"
    assert _rate(_growth(nrr=0.98))["rating"] == "Adequate", "NRR below 100% is not green"
    assert _rate(_growth(churn=0.10))["rating"] == "Adequate", "churn above 8% is not green"
    assert _rate(_growth(months=14.0))["rating"] == "Adequate"


@pytest.mark.parametrize("kw", [dict(churn=0.16), dict(months=19.0), dict(churn=0.16, months=19.0)])
def test_a_red_input_makes_the_growth_engine_weak(kw):
    assert _rate(_growth(**kw))["rating"] == "Weak"


def test_the_boundaries_are_the_dashboards_own_and_the_rating_carries_the_benchmark_label():
    assert _rate(_growth(nrr=1.0, churn=0.08, months=12.0))["rating"] == "Strong", "NRR 100%, churn 8% and 12 months are green"
    assert _rate(_growth(churn=0.15))["rating"] == "Adequate" and _rate(_growth(months=18.0))["rating"] == "Adequate", "red is above 15% and 18"
    r = _rate(_growth())
    assert r["benchmark"] is True and r["line"].startswith("Strong (NRR 104%, gross churn 5%, CAC payback 10")
    assert vd.BENCHMARK == "benchmark, not company data"


@pytest.mark.parametrize("kw, missing", [(dict(nrr=None), ["NRR"]), (dict(churn=None), ["gross revenue churn"]),
                                         (dict(nrr=None, churn=None), ["NRR", "gross revenue churn"])])
def test_nrr_or_churn_absent_is_not_rated_and_names_the_missing_input(kw, missing):
    r = _rate(_growth(**kw))
    assert (r["rating"], r["line"], r["missing"]) == (None, "not rated – data missing", missing)


def test_data_reliability_follows_the_integrity_conclusion():
    def rated(code, conclusion, x=5, y=5):
        return vd.rate_reliability({"code": code, "conclusion": conclusion, "completed": x, "applicable": y})
    assert rated("reliable", "Reliable")["line"] == "Strong (Reliable; 5 of 5 checks)"
    assert rated("reliable", "Reliable")["rule"] == "Strong: every completed check Green, 5 of 5 completed"
    assert rated("needs_clarification", "Needs clarification")["rating"] == "Adequate"
    assert rated("material_concerns", "Material concerns")["rating"] == "Weak"
    insufficient = rated("insufficient", "Insufficient assessment coverage (2 of 5)", 2, 5)
    assert (insufficient["rating"], insufficient["line"]) == (None, "not rated – data missing")
    assert vd.rate_reliability(None)["rating"] is None


def test_the_cac_headline_is_the_dashboards_pick():
    quarters = {"2025-Q4": {"partial": False, "L1": {"months": 9.0}}, "2026-Q1": {"partial": True, "L1": {"months": 30.0}}}
    assert vd.cac_headline_months({"cac_payback": {"default_l": 1, "quarters": quarters}}) == 9.0, "a partial quarter never headlines"
    assert vd.cac_headline_months({"cac_payback": {"default_l": 1, "headline_quarter": "2026-Q1", "quarters": quarters}}) == 30.0
    assert vd.cac_headline_months({"cac_payback": {"default_l": 1, "headline_quarter": None, "quarters": quarters}}) is None
    assert vd.cac_headline_months({}) is None


def test_the_unresolved_questions_are_one_list_in_a_fixed_order_and_the_thesis_is_drafted_from_computed_text():
    gaps = [{"item": f"gap{i}", "why": f"why{i}"} for i in range(5)]
    integrity = {"blocked": ["Deck consistency"]}
    results = {"questions_for_management": [{"question": "Why did churn fall?"}]}
    out = vd.unresolved_questions(gaps, 2, integrity, results)
    assert out == ["gap0: why0", "gap1: why1", "gap2: why2", "2 claim questions open on the Audit page.", "Deck consistency: not assessed",
                   "Why did churn fall?"]
    assert vd.unresolved_questions([], 1, None, None) == ["1 claim question open on the Audit page."]
    ver = {"outcome": "Selected claims partly supported", "rule": "No selected claim is Contradicted; 4 of 5 are Verified, 1 untested."}
    gate = {"gate_sentence": "ARR must be at least 5.", "gate_status": "proposed"}
    thesis = vd.default_thesis({"target_arr": 5_000_000, "target_date": "2027-12-31"}, ver, {"gates": [gate]}, lambda v: f"EUR {v:,.0f}")
    assert thesis == {"plan": "The plan targets ARR of EUR 5,000,000 by 2027-12-31.",
                      "evidence": "Selected claims partly supported: No selected claim is Contradicted; 4 of 5 are Verified, 1 untested.",
                      "condition": "ARR must be at least 5. (proposed)"}
    assert vd.default_thesis({}, {"outcome": None}, {"gates": []}, str) == {
        "plan": "Target ARR and Target date are not set.", "evidence": "No conclusion yet.",
        "condition": "No condition: every selected claim is Verified."}
