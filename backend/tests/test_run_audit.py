"""Run audit: the three stages in order, the claims and columns accepted without a click, the review screen's inputs, the
narratives that run only from their button, the memo, and the click count from upload to memo (CLAUDE.md rule 12: the task of
2026-10-11). Every test runs on the in-memory Mongo stub and a fake provider: nothing reaches a model."""
import copy
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from test_claim_matching import RUNS, candidates_for, results_for, settings  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import column_rules as cr  # noqa: E402
from app import decks, run_audit, usage as usage_mod  # noqa: E402
from app.llm import gateway  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
SAMPLE = BACKEND.parent / "sample_data"
AUDIT = "audit-run"
AUDIT_DOC = {"id": AUDIT, "company_name": "TestCo", "structure_reading_consent": True,
             "fiscal_year_end": 12, "reporting_currency": "EUR", "target_arr": 1000000, "target_date": "2026-12-31",
             "as_of_month": None, "results": None, "status": "draft", "usage": usage_mod.empty(),
             "created_at": "2026-10-11T08:00:00+00:00", "ic_inputs": {"first_quarterly_review": "2027-01-09"}}      # as create_audit stores it
RATINGS = {"data_reliability": "Adequate", "growth_engine": "Weak"}
THESIS = {"plan": "Grow through the mid-market.", "evidence": "Retention holds in the base.", "condition": "Gates met on time."}
JUDGMENT = {"reasons": "The five claims hold against the files.", "unresolved_questions": "None beyond the data requests."}
RUN = RUNS["A"]


class Clicks:
    """What the analyst does, counted. One for a click, one for a choice in a list, one for a field typed into, one for the file
    picker (however many files it takes). The API calls behind an action are the ones the screen makes."""

    def __init__(self):
        self.log = []

    def __call__(self, what):
        self.log.append(what)

    @property
    def n(self):
        return len(self.log)


class EchoAdapter(t.FakeAdapter):
    """A provider that answers every narrative step from its own payload, with no figure of its own."""

    def complete(self, *, model, system, user_payload, **kw):
        self.calls += 1
        self.payloads.append(user_payload)
        sent = json.loads(user_payload)
        if "valid_source_keys" not in sent:            # a column-mapping call: the model proposes the S&M column of the P&L
            item = {"metric": "sm_expense", "period": None, "value": None, "unit": None, "actual_or_forecast": "unknown",
                    "value_cell": "r1c2", "unit_other": None, "period_cells": [], "proposed_flags": []}
            return json.dumps({"type": "column_mapping", "items": [item]}), 100, 20
        keys = sent["valid_source_keys"]
        key = "S1" if "S1" in keys else keys[0]
        base = {"headline": "The data supports a first reading.", "what_this_means": "Read the figures with their sources.",
                "table_rows": [{"label": "Source", "value": "see source", "source_key": key}],
                "worth_flagging": [], "next_actions": ["Ask management to explain the open items."], "source_keys": [key]}
        if "data-inventory" in system or "data_inventory" in system:
            base["table_rows"][0]["decision_informed"] = "Which analyses to rely on"
        elif "data-integrity" in system:
            checks = {c["check"]: c for c in sent["metrics"]["integrity"]}
            rec = checks["Revenue file against P&L"]
            base["table_rows"][0]["decision_informed"] = "Whether revenue can be relied on"
            base["verdict"] = "Material concerns" if rec.get("window_over_tolerance") else "Needs clarification"
            base["headline"] = f"{base['verdict']}: the checks that could be run are listed below."
        return json.dumps(base), 1200, 300


def upload_files(client, kinds=("revenue", "crm", "pnl")):
    out = {}
    for kind in kinds:
        name = f"{kind}.csv"
        r = client.post(f"/api/audits/{AUDIT}/datasets/upload", files={"file": (name, (SAMPLE / name).read_bytes())})
        assert r.status_code == 200, r.text
        out[kind] = r.json()
    return out


def add_deck(client, only_verified=False):
    """The deck the way the parser leaves it: a read deck and its pending candidates (the TestCo claims)."""
    client.db[decks.TEXT_COLLECTION].docs.append({"audit_id": AUDIT, "deck_id": "d1", "file": "testco_board.pptx", "ai_status": "read"})
    keep = None
    if only_verified:
        rows = cm.build_register(candidates_for(RUN), results_for(RUN), settings(RUN))
        keep = set(run_audit.within_tolerance_ids(rows, [c["id"] for c in candidates_for(RUN)]))
    for n, c in enumerate(candidates_for(RUN)):
        if keep is not None and c["id"] not in keep:
            continue
        client.db[decks.CANDIDATES_COLLECTION].docs.append({**c, "audit_id": AUDIT, "deck_id": "d1", "order": n, "status": "pending"})


def confirm_open_columns(client):
    """The analyst's Confirm on every column that waits (what the review screen's mapping rows do). Returns how many."""
    n = 0
    for ds in client.get(f"/api/audits/{AUDIT}/datasets").json()["datasets"]:
        pending = [c for c in ds["columns"] if c["pending"]]
        if pending:
            r = client.post(f"/api/audits/{AUDIT}/datasets/{ds['dtype']}/decisions",
                            json=[{"column": c["column"], "action": "confirm", "field": c["field"]} for c in pending])
            assert r.status_code == 200, r.text
            n += len(pending)
    return n


def stage(client, name):
    r = client.post(f"/api/audits/{AUDIT}/run/{name}")
    assert r.status_code == 200, r.text
    return r.json()


def run_audit_button(client):
    """Run audit: the stages in order, stopping where the screen stops."""
    results = []
    for name in run_audit.STAGES:
        res = stage(client, name)
        results.append(res)
        if res["status"] != run_audit.DONE:
            break
    return results


def review(client):
    r = client.get(f"/api/audits/{AUDIT}/review")
    assert r.status_code == 200, r.text
    return r.json()


def candidates(client):
    return [c for c in client.db[decks.CANDIDATES_COLLECTION].docs if c["audit_id"] == AUDIT]


# --- the stages -------------------------------------------------------------------------------------------------------------

def test_the_stages_run_in_the_order_mapping_engine_claims_and_each_reports_done(run_api):
    upload_files(run_api)
    confirm_open_columns(run_api)
    add_deck(run_api)
    assert run_audit.STAGES == ("mapping", "engine", "claims")
    results = run_audit_button(run_api)
    assert [(r["stage"], r["status"]) for r in results] == [("mapping", "done"), ("engine", "done"), ("claims", "done")]
    assert run_api.db["audits"].docs[0]["results"] and run_api.db["audits"].docs[0]["status"] == "computed"


def test_a_stage_asked_out_of_order_waits_and_does_nothing(run_api):
    upload_files(run_api)
    confirm_open_columns(run_api)
    add_deck(run_api)
    assert stage(run_api, "claims")["status"] == "waiting" and not run_api.db["audits"].docs[0]["results"]
    assert all(c["status"] == "pending" for c in candidates(run_api)), "no claim is accepted before the calculations"
    assert stage(run_api, "engine")["status"] == "done"
    assert stage(run_api, "claims")["status"] == "done"


def test_an_unknown_stage_is_a_404_and_an_unknown_audit_too(run_api):
    assert run_api.post(f"/api/audits/{AUDIT}/run/launch").status_code == 404
    assert run_api.post("/api/audits/nope/run/mapping").status_code == 404
    assert run_api.get("/api/audits/nope/review").status_code == 404


def test_with_no_file_the_mapping_stage_says_so_in_plain_english(run_api):
    res = stage(run_api, "mapping")
    assert (res["status"], res["message"]) == ("failed", run_audit.NO_FILES)
    upload_files(run_api, ("crm",))
    assert stage(run_api, "mapping")["message"] == run_audit.NO_REVENUE


def test_a_column_that_waits_stops_the_run_at_the_mapping_stage_and_the_engine_waits(run_api):
    upload_files(run_api)
    confirm_open_columns(run_api)
    doc = next(d for d in run_api.db["datasets"].docs if d["dtype"] == "revenue")
    doc["columns_state"][0] = {**doc["columns_state"][0], "state": "unsure"}
    results = run_audit_button(run_api)
    assert [(r["stage"], r["status"]) for r in results] == [("mapping", "needs_review")] and results[0]["open"] == 1
    assert stage(run_api, "engine")["status"] == "waiting" and not run_api.db["audits"].docs[0]["results"]
    doc["columns_state"][0] = {**doc["columns_state"][0], "state": "confirmed"}
    assert [r["status"] for r in run_audit_button(run_api)] == ["done", "done", "done"], "Run audit again carries on"


def test_a_stage_that_fails_says_what_to_do_without_the_exception_text_and_retry_runs_it_again(run_api, monkeypatch, caplog):
    import logging
    upload_files(run_api)
    confirm_open_columns(run_api)
    original = server._run_compute

    async def broken(audit_id):
        raise ValueError("Zeta Holdings 4242 secret")
    monkeypatch.setattr(server, "_run_compute", broken)
    with caplog.at_level(logging.DEBUG):
        res = stage(run_api, "engine")
    assert (res["status"], res["message"]) == ("failed", run_audit.ENGINE_FAILED)
    assert "Zeta" not in json.dumps(res) and "4242" not in json.dumps(res)
    assert "Zeta" not in caplog.text and "4242" not in caplog.text and "ValueError" in caplog.text, "the log has the type"
    monkeypatch.setattr(server, "_run_compute", original)
    assert stage(run_api, "engine")["status"] == "done", "Retry stage"


def test_the_claims_stage_waits_while_the_decks_are_read(run_api):
    upload_files(run_api)
    confirm_open_columns(run_api)
    add_deck(run_api)
    run_api.db[decks.TEXT_COLLECTION].docs[0]["ai_status"] = "reading"
    stage(run_api, "engine")
    assert stage(run_api, "claims")["status"] == "running"
    run_api.db[decks.TEXT_COLLECTION].docs[0]["ai_status"] = "read"
    assert stage(run_api, "claims")["status"] == "done"


def test_an_audit_with_no_deck_has_no_claims_to_read(run_api):
    upload_files(run_api)
    confirm_open_columns(run_api)
    stage(run_api, "engine")
    res = stage(run_api, "claims")
    assert (res["status"], res["accepted"], res["open"], res["message"]) == ("done", 0, 0, run_audit.NO_DECKS)


# --- accepted without a click -------------------------------------------------------------------------------------------------

def test_no_threshold_or_tolerance_changed():
    assert cr.MAPPING_THRESHOLD == 80
    assert (cm.RATE_TOLERANCE_PP, cm.AMOUNT_TOLERANCE) == (1.0, 0.05)


def test_columns_the_rules_accepted_are_counted_and_the_ones_that_wait_are_listed_once(run_api):
    uploads = upload_files(run_api)
    waiting = sum(1 for body in uploads.values() for c in body["columns"] if c["pending"])
    auto = sum(1 for body in uploads.values() for c in body["columns"] if c["state"] == "auto")
    res = stage(run_api, "mapping")
    assert auto > 0 and (res["status"], res["open"], res["auto"]) == ("needs_review" if waiting else "done", waiting, auto)
    assert confirm_open_columns(run_api) == waiting
    assert review(run_api)["mappings"]["open"] == 0 and review(run_api)["mappings"]["auto"] == auto, "a Confirm does not change the count of auto columns"
    assert stage(run_api, "mapping")["status"] == "done"


def test_claims_within_tolerance_are_accepted_and_the_others_stay_for_the_review_screen(run_api):
    upload_files(run_api)
    confirm_open_columns(run_api)
    add_deck(run_api)
    stage(run_api, "engine")
    res = stage(run_api, "claims")
    rows = cm.build_register(candidates_for(RUN), results_for(RUN), settings(RUN))
    verified = {r["claim_id"].split("#")[0] for r in rows if r["evidence_label"] == "Verified"}
    beats = {r["claim_id"].split("#")[0] for r in rows if cm.is_beat(r)}
    accepted = {c["id"] for c in candidates(run_api) if c.get("auto_accepted")}
    assert beats, "fixture: a Verified beat"
    assert res["accepted"] == len(accepted) and 0 < len(accepted) <= len(verified - beats)
    assert accepted <= verified - beats, "only what the register labels Verified within tolerance: a beat waits for the analyst"
    assert not accepted & beats and all(c["status"] == "pending" for c in candidates(run_api) if c["id"] in beats)
    left = [c for c in candidates(run_api) if c["status"] == "pending"]
    assert res["open"] == len(left) and left, "claims outside tolerance wait for the analyst"
    assert all(c["status"] in ("approved", "edited") for c in candidates(run_api) if c.get("auto_accepted"))
    summary = review(run_api)["claims"]
    assert summary["auto_accepted"] == len(accepted) and set(summary["auto_accepted_ids"]) == accepted and summary["open"] == len(left)
    again = stage(run_api, "claims")
    assert again["accepted"] == 0, "running the stage again accepts nothing twice"


def test_only_a_row_within_tolerance_is_accepted_not_a_beat_nor_a_definition_check_however_it_was_answered():
    """claim-matching.md section 4.1 (George, 2026-10-14): a beat of 5% to 50% and a bigger beat answered Yes are Verified (beat), not
    within tolerance; the analyst reviews them. A table row counts only when every value is within tolerance."""
    plain = {"claim_id": "a", "evidence_label": "Verified", "reason": "within ±5% of the claim", "definition_check": None}
    beat = {"claim_id": "b", "evidence_label": "Verified", "reason": cm.BEAT_PREFIX + "€5 higher (beat)", "definition_check": None}
    big_yes = {**beat, "claim_id": "c", "definition_check": "yes"}
    open_ = {"claim_id": "d", "evidence_label": None, "reason": "definition check", "definition_check": "ask"}
    table = [{**plain, "claim_id": "e#1"}, {**beat, "claim_id": "e#2"}]
    assert run_audit.within_tolerance_ids([plain, beat, big_yes, open_, *table], list("abcde")) == ["a"]
    assert run_audit.within_tolerance_ids([{**plain, "claim_id": "e#1"}, {**plain, "claim_id": "e#2"}], ["e"]) == ["e"]


def test_an_accepted_claim_can_still_be_rejected_or_edited_by_the_analyst(run_api):
    upload_files(run_api)
    confirm_open_columns(run_api)
    add_deck(run_api)
    stage(run_api, "engine")
    stage(run_api, "claims")
    cid = next(c["id"] for c in candidates(run_api) if c.get("auto_accepted"))
    r = run_api.put(f"/api/audits/{AUDIT}/decks/candidates/{cid}", json={"status": "rejected"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert review(run_api)["claims"]["auto_accepted"] == len(
        [c for c in candidates(run_api) if c.get("auto_accepted") and c["status"] != "rejected"])


def test_a_claim_with_an_open_revenue_or_volume_question_is_never_accepted(run_api):
    upload_files(run_api)
    confirm_open_columns(run_api)
    add_deck(run_api)
    # A turnover claim the deck makes in the TestCo wording, whose figure the revenue file would otherwise confirm.
    base = next(c for c in candidates(run_api) if c["claim_type"] == "revenue")
    run_api.db[decks.CANDIDATES_COLLECTION].docs.append(
        {**copy.deepcopy(base), "id": "turnover1", "snippet": "Gross turnover (GMV) of the platform", "label_from": "GMV",
         "status": "pending"})
    stage(run_api, "engine")
    audit = run_api.db["audits"].docs[0]
    views = server.claim_matching.turnover_views(
        candidates(run_api), audit["results"], server._register_settings(audit, {"EUR": 1.0}, None))
    open_ids = {cid for cid, vs in views.items() if any(v["turnover_set_by"] != "analyst" for v in vs)}
    assert open_ids, "fixture: a claim with an open Revenue / Volume question"
    stage(run_api, "claims")
    assert not [c for c in candidates(run_api) if c["id"] in open_ids and c.get("auto_accepted")]
    summary = review(run_api)["claims"]
    assert 0 < summary["turnover_open"] <= summary["open"]


# --- the review screen's inputs persist ---------------------------------------------------------------------------------------

def ready_for_review(client, only_verified=False):
    upload_files(client)
    confirm_open_columns(client)
    add_deck(client, only_verified)
    assert [r["status"] for r in run_audit_button(client)] == ["done", "done", "done"]


def test_the_review_inputs_persist_and_come_back_on_the_next_read(run_api):
    ready_for_review(run_api)
    ids = run_api.get(f"/api/audits/{AUDIT}/verdict").json()["verdict"]["top5"]["proposed"]
    assert run_api.put(f"/api/audits/{AUDIT}/ic-inputs", json={"top5": ids}).status_code == 200
    assert run_api.put(f"/api/audits/{AUDIT}/ic-inputs", json={"thesis": THESIS, "ratings": RATINGS}).status_code == 200
    body = run_api.get(f"/api/audits/{AUDIT}/verdict").json()
    assert body["verdict"]["top5"]["confirmed"] and body["verdict"]["top5"]["claim_ids"] == ids
    assert body["ic_inputs"]["thesis"] == THESIS and body["ic_inputs"]["ratings"] == RATINGS
    assert run_api.db["audits"].docs[0]["ic_inputs"]["ratings"] == RATINGS, "stored on the audit, not in the browser"


def test_a_gate_set_on_the_review_screen_is_the_registers_gate(run_api):
    ready_for_review(run_api)
    open_claim = next(c for c in candidates(run_api) if c["status"] == "pending")
    assert run_api.put(f"/api/audits/{AUDIT}/decks/candidates/{open_claim['id']}", json={"status": "approved"}).status_code == 200
    row = next(r for r in run_api.get(f"/api/audits/{AUDIT}/claims").json()["register"] if r["evidence_label"] != "Verified")
    body = {"gate_threshold": 100.0, "gate_budget_decision": "the Series B hiring plan", "gate_date": "2024-06-30"}
    cid = row["claim_id"].replace("#", "%23")
    assert run_api.put(f"/api/audits/{AUDIT}/claims/{cid}", json=body).status_code == 200
    saved = next(r for r in run_api.get(f"/api/audits/{AUDIT}/claims").json()["register"] if r["claim_id"] == row["claim_id"])
    assert saved["gate_saved"] and saved["gate_threshold"] == 100.0


# --- narratives run only from their button -----------------------------------------------------------------------------------

def test_opening_the_review_screen_runs_no_narrative_and_the_estimate_makes_no_call(run_api):
    ready_for_review(run_api)
    for path in (f"/api/audits/{AUDIT}/review", f"/api/audits/{AUDIT}/verdict", f"/api/audits/{AUDIT}/claims",
                 f"/api/runs/{AUDIT}/narratives/estimate", f"/api/runs/{AUDIT}/narrative/growth_engine",
                 f"/api/runs/{AUDIT}/narrative/data_inventory", f"/api/runs/{AUDIT}/narrative/data_integrity"):
        assert run_api.get(path).status_code == 200, path
    narrative_calls = [p for p in run_api.adapter.payloads if "valid_source_keys" in p]
    assert narrative_calls == [] and run_api.db["llm_narratives"].docs == []


def write_all(client):
    """Write all narratives: the steps the estimate lists, one request each, as the button does."""
    est = client.get(f"/api/runs/{AUDIT}/narratives/estimate").json()
    out = {}
    for step in (s["step"] for s in est["steps"] if s["available"]):
        r = client.post(f"/api/runs/{AUDIT}/narrative/{step}")
        assert r.status_code == 200, r.text
        out[step] = r.json()["narrative_status"]
    return est, out


def test_write_all_narratives_runs_every_enabled_step_through_the_gateway_and_a_second_press_costs_nothing(run_api):
    ready_for_review(run_api)
    est = run_api.get(f"/api/runs/{AUDIT}/narratives/estimate").json()
    enabled = [s for s, c in gateway.STEP_CONFIG.items() if c.get("enabled")]
    assert [s["step"] for s in est["steps"]] == enabled and set(enabled) == {"growth_engine", "data_inventory", "data_integrity"}
    assert est["total_usd"] == round(sum(s["estimate_usd"] for s in est["steps"]), 4) > 0
    assert all(s["cached"] is False and s["estimate_usd"] > 0 for s in est["steps"])
    _, done = write_all(run_api)
    assert done == {step: "ok" for step in enabled}, done
    assert len([p for p in run_api.adapter.payloads if "valid_source_keys" in p]) == len(enabled)
    calls = len(run_api.adapter.payloads)
    est2, again = write_all(run_api)
    assert len(run_api.adapter.payloads) == calls, "the cache serves the second press"
    assert est2["total_usd"] == 0 and all(s["cached"] for s in est2["steps"])
    assert {c["status"] for c in run_api.db["llm_calls"].docs} <= {"ok", "flagged"}


def test_write_all_narratives_keeps_the_spend_cap_and_a_refusal_degrades_to_the_metrics(run_api, monkeypatch):
    from app.llm import guards

    async def refuse(db):
        raise guards.GuardRefusal("daily_spend_cap_exceeded", "daily spend cap reached")
    ready_for_review(run_api)
    monkeypatch.setattr(guards, "check_spend_cap", refuse)
    _, done = write_all(run_api)
    assert set(done.values()) == {"unavailable"} and not [p for p in run_api.adapter.payloads if "valid_source_keys" in p]
    assert run_api.get(f"/api/audits/{AUDIT}/results").status_code == 200, "every computed metric still renders"


def est_steps(est):
    return {s["step"] for s in est["steps"]}


def test_the_estimate_is_an_upper_bound_not_a_cost_and_is_not_logged_as_a_call(run_api):
    ready_for_review(run_api)
    est = run_api.get(f"/api/runs/{AUDIT}/narratives/estimate").json()
    before = len(run_api.db["llm_calls"].docs)
    assert "upper bound" in est["basis"] and len(run_api.db["llm_calls"].docs) == before, "an estimate is not a call"
    write_all(run_api)
    spent = sum(c["estimated_cost_usd"] for c in run_api.db["llm_calls"].docs if c["step"] in est_steps(est))
    assert 0 < spent <= est["total_usd"], (spent, est["total_usd"])


# --- the memo ----------------------------------------------------------------------------------------------------------------

def memo(client):
    return client.get(f"/api/audits/{AUDIT}/memo.md")


def test_the_memo_is_refused_until_ratings_are_entered_and_then_built(run_api):
    ready_for_review(run_api, only_verified=True)
    ids = run_api.get(f"/api/audits/{AUDIT}/verdict").json()["verdict"]["top5"]["proposed"]
    run_api.put(f"/api/audits/{AUDIT}/ic-inputs", json={"top5": ids, "thesis": THESIS, "judgment": JUDGMENT})
    r = memo(run_api)
    assert r.status_code == 409 and "rate Data reliability, Growth engine" in r.json()["detail"]
    run_api.put(f"/api/audits/{AUDIT}/ic-inputs", json={"ratings": RATINGS})
    r = memo(run_api)
    assert r.status_code == 200, r.text


def test_the_reconciliation_blocker_is_on_the_review_summary_and_in_the_memo_not_hidden(run_api):
    ready_for_review(run_api, only_verified=True)
    kinds = [b["kind"] for b in review(run_api)["blockers"]]
    assert "revenue_reconciliation" in kinds, "the sample files differ from the sample P&L by more than 2%"
    ids = run_api.get(f"/api/audits/{AUDIT}/verdict").json()["verdict"]["top5"]["proposed"]
    run_api.put(f"/api/audits/{AUDIT}/ic-inputs", json={"top5": ids, "thesis": THESIS, "ratings": RATINGS, "judgment": JUDGMENT})
    r = memo(run_api)
    assert r.status_code == 200 and "Revenue file and P&L differ by" in r.text.split("## Key gates")[1].split("## Data gaps")[0]


# --- the click count: from upload to the memo download -------------------------------------------------------------------------
MAX_CLICKS = 15
# 21 set by George (2026-10-11), plus the two analyst judgment fields the plan of 15 Oct 2026 requires before export
# (claim-review-conclusion.md section 3). 23 accepted by George, 15 Oct 2026.
MAX_CLICKS_FULL = 23


def analyst_flow(client, only_verified):
    """The TestCo audit, from the file picker to the memo, the way the screens take it. Each line that counts an action is one
    thing the analyst does; the API calls beside it are the ones that action makes. What the app does by itself (the stages, the
    claims within tolerance, the stages again once the last column is confirmed) is not counted."""
    clicks = Clicks()
    clicks("pick the files in one picker: three data files and the deck")
    upload_files(client)
    add_deck(client, only_verified)
    clicks("Run audit")
    results = run_audit_button(client)
    waiting = confirm_open_columns(client)
    for _ in range(waiting):
        clicks("Confirm a mapping row")
    if waiting:
        results = run_audit_button(client)            # the review screen runs the stages again when the last row is decided
    assert [r["status"] for r in results] == ["done", "done", "done"], results

    # Open claims: one click on "Approve all" for each category that still holds claims to review.
    groups = sorted({server.deck_claims.type_group(c.get("claim_type")) for c in candidates(client) if c["status"] == "pending"})
    for group in groups:
        clicks(f"Approve all, category {group}")
        r = client.post(f"/api/audits/{AUDIT}/decks/candidates/approve-all", json={"group": group})
        assert r.status_code == 200, r.text

    clicks("Confirm the top 5")
    ids = client.get(f"/api/audits/{AUDIT}/verdict").json()["verdict"]["top5"]["proposed"]
    assert client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"top5": ids}).status_code == 200

    # The gates of the claims that are not Verified, prefilled from stored data. The analyst picks the budget decision on each (the
    # first one is typed, the next ones are picked from the audit's list), fills what the prefill leaves blank, and presses Save all.
    reg = client.get(f"/api/audits/{AUDIT}/claims").json()
    register = {r["claim_id"]: r for r in reg["register"]}
    gated = [cid for cid in ids if register[cid]["evidence_label"] != "Verified"]
    batch = []
    for n, cid in enumerate(gated):
        fill = {**reg["gate_prefill"][cid]}
        clicks("gate budget decision: typed after Other" if n == 0 else "gate budget decision: picked from the list")
        for blank in ("gate_threshold", "gate_date"):
            if blank not in fill:
                clicks(f"gate {blank} (not prefilled)")
                fill[blank] = 100.0 if blank == "gate_threshold" else "2024-06-30"
        if register[cid]["reason"] in server.claim_matching.NO_APP_METRIC:
            clicks("gate direction: at least / at most")
            fill["gate_direction"] = "at least"
        batch.append({"claim_id": cid, **fill, "gate_budget_decision": "the Series B hiring plan"})
    if gated:
        clicks("Save all gates")
        assert client.put(f"/api/audits/{AUDIT}/claim-gates", json={"gates": batch}).status_code == 200
    marked = [e["claim_id"] for e in batch if e.get("key_gate")]
    if len(gated) >= 3:
        for cid in gated[:3]:
            if cid not in marked:
                clicks("mark a key gate")
                assert client.put(f"/api/audits/{AUDIT}/claims/{cid}", json={"key_gate": True}).status_code == 200

    for part in ("plan", "evidence", "condition"):
        clicks(f"deal thesis: {part}")
    clicks("rating: Data reliability")
    clicks("rating: Growth engine")
    for part in ("reasons", "unresolved questions"):      # claim-review-conclusion.md section 3: the analyst judgment
        clicks(f"analyst judgment: {part}")
    assert client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"thesis": THESIS, "ratings": RATINGS, "judgment": JUDGMENT}).status_code == 200

    clicks("Write all narratives")
    _, done = write_all(client)
    assert set(done.values()) == {"ok"}, done

    clicks("Generate IC memo")
    r = memo(client)
    assert r.status_code == 200, r.text
    return clicks, gated


def test_a_clean_testco_audit_goes_from_upload_to_the_memo_in_no_more_than_15_clicks(run_api):
    clicks, gated = analyst_flow(run_api, only_verified=True)
    print(f"\nCLICKS clean TestCo: {clicks.n} -> {clicks.log}")
    assert gated == [], "fixture: a clean audit has no top-5 claim outside tolerance, so no gate to set"
    assert clicks.n <= MAX_CLICKS, f"{clicks.n} clicks: {clicks.log}"


def test_the_click_count_fails_above_15():
    """The limit is enforced: a flow with one more action than the limit is refused by the same comparison."""
    spent = Clicks()
    for i in range(MAX_CLICKS + 1):
        spent(f"click {i}")
    with pytest.raises(AssertionError):
        assert spent.n <= MAX_CLICKS


def test_the_full_testco_audit_with_contradicted_top_5_claims_needs_more_clicks_than_a_clean_one(run_api):
    clicks, gated = analyst_flow(run_api, only_verified=False)
    print(f"\nCLICKS full TestCo (33 claims, top 5 outside tolerance): {clicks.n}")
    assert len(gated) == 5 and clicks.n > MAX_CLICKS, "the budget decision of each gate is the analyst's: more than the clean audit"


def test_the_full_testco_audit_goes_from_upload_to_the_memo_in_no_more_than_23_clicks(run_api):
    clicks, _ = analyst_flow(run_api, only_verified=False)
    assert clicks.n <= MAX_CLICKS_FULL, f"{clicks.n} clicks: {clicks.log}"
