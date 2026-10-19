"""Usage on the owner page and the per-tester AI allowance (docs/specs/usage-and-allowance.md). In-memory Mongo stub and the fake
adapter: nothing reaches a provider."""
import asyncio
import copy
from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import test_llm_gateway as t  # noqa: E402
from app import allowance, access  # noqa: E402
from app.llm import gateway, guards  # noqa: E402
from test_chat_upload import by_column, mapping_reply, upload  # noqa: E402
import test_owner_page_api as owner_page  # noqa: E402
from test_owner_page_api import bearer, token_of  # noqa: E402

owner = owner_page.owner            # the owner fixture: the real access guard on the in-memory stub

TESTER = "tester-1"
FILE = "blank_vs_zero.csv"


def a_tester(**extra):
    return {"id": TESTER, "label": "Tester One", "hash": "x", "created_at": "2026-10-01T00:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00", "revoked_at": None, **extra}


def spent(cost, month=None):
    month = month or allowance.month_key()
    return {"ledger": {"all": {"cost_usd": cost}, month: {"cost_usd": cost}}}


def own(db, **extra):
    db[access.COLLECTION].docs.append(a_tester(**extra))
    for a in db["audits"].docs:
        a["owner"] = TESTER
    return db


def ledger(db):
    return db[access.COLLECTION].docs[0].get("ledger", {})


def narrative(db, adapter):
    return asyncio.run(gateway.generate_narrative(db, t.RUN_ID, "growth_engine", adapter=adapter, sleep=t._noop_sleep))


# --- the ledger ---------------------------------------------------------------------------------------------------
def test_a_billed_call_is_counted_on_the_tester_this_month_and_all_time_and_a_cache_hit_or_refusal_adds_nothing():
    db = own(t.make_db())
    adapter = t.FakeAdapter()
    assert narrative(db, adapter).narrative_status == "ok"
    month = allowance.month_key()
    row = {"calls": 1, "tokens": 1500, "cost_usd": pytest.approx(gateway.estimate_cost_usd(gateway.run_model(), 1200, 300))}
    assert ledger(db)["all"] == row and ledger(db)[month] == row
    assert narrative(db, adapter).narrative_status == "ok" and adapter.calls == 1, "the second read is the cache"
    assert ledger(db)["all"]["calls"] == 1
    db[access.COLLECTION].docs[0].update(spent(allowance.DEFAULT_ALLOWANCE_USD))
    before = copy.deepcopy(ledger(db))
    narrative(db, t.FakeAdapter())
    assert ledger(db) == before, "a refusal logs 0 tokens and adds nothing"


def test_deleting_an_audit_leaves_the_tester_ledger_and_an_audit_without_a_tester_counts_nowhere():
    db = own(t.make_db())
    narrative(db, t.FakeAdapter())
    asyncio.run(gateway.purge_run(db, t.RUN_ID))
    assert not db["llm_calls"].docs and ledger(db)["all"]["calls"] == 1
    loose = t.make_db()
    narrative(loose, t.FakeAdapter())
    assert "access_tokens" not in loose._cols or not loose[access.COLLECTION].docs


# --- the states ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("used,allowed,state,percent", [
    (0, 10, "ok", 0), (7.99, 10, "ok", 79), (8, 10, "warn", 80), (9.999, 10, "warn", 99), (10, 10, "blocked", 100),
    (12, 10, "blocked", 100), (0, 0, "blocked", 100), (1.5, 5, "ok", 30)])
def test_the_state_follows_80_and_100_percent_and_the_percent_is_rounded_down(used, allowed, state, percent):
    got = allowance.status(a_tester(allowance_usd=allowed, **spent(used)))
    assert (got["state"], got["percent"]) == (state, percent) and set(got) == {"allowance_usd", "used_usd", "percent", "state"}


def test_a_new_month_starts_at_zero_and_a_tester_without_a_set_allowance_has_ten_dollars():
    doc = a_tester(**spent(10, "2026-09"))
    assert allowance.status(doc, datetime(2026, 10, 1, tzinfo=timezone.utc)) == {
        "allowance_usd": 10.0, "used_usd": 0.0, "percent": 0, "state": "ok"}
    assert allowance.status(doc, datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc))["state"] == "blocked"


# --- at 100%: no new AI call, nothing else blocked ------------------------------------------------------------------
def test_at_100_percent_no_provider_call_is_made_for_a_narrative_or_a_deck_structure():
    db = own(t.make_db(), **spent(10))
    db["audits"].docs[0]["structure_reading_consent"] = True
    adapter = t.FakeAdapter()
    assert narrative(db, adapter).narrative_status == "unavailable" and adapter.calls == 0
    read = asyncio.run(gateway.read_structure(db, t.RUN_ID, "r1c1: A\nr2c1: 1", "table", adapter=adapter, sleep=t._noop_sleep))
    assert read.status == "not_read"
    assert adapter.calls == 0
    assert {c["status"] for c in db["llm_calls"].docs} == {"monthly_allowance_reached"}


def test_below_100_percent_the_daily_cap_still_refuses_on_top(monkeypatch):
    monkeypatch.setenv("LLM_DAILY_SPEND_CAP_USD", "0.01")
    db = own(t.make_db(), **spent(1))
    db["llm_calls"].docs.append({"run_id": "elsewhere", "cache_hit": False, "estimated_cost_usd": 1.0,
                                 "timestamp": datetime.now(timezone.utc).isoformat()})
    adapter = t.FakeAdapter()
    assert narrative(db, adapter).narrative_status == "unavailable" and adapter.calls == 0
    assert "daily_spend_cap_exceeded" in db["llm_calls"].docs[-1]["status"]


def test_at_100_percent_an_upload_still_works_the_rules_map_alone_and_open_columns_wait_for_a_click(api):
    own(api.db, **spent(10))
    api.state["adapter"] = t.FakeAdapter(replies=[mapping_reply(("revenue_type", 6))])
    body = upload(api, FILE).json()
    assert api.state["adapter"].calls == 0, "no model call"
    assert body["ai_reading"]["status"] == "not_read"
    assert by_column(body)["Adj"]["pending"] and not by_column(body)["Adj"]["field"], "the model's proposal never arrives"
    assert all(c["source"] != "ai" for c in body["columns"] if c.get("source"))
    assert api.db[access.COLLECTION].docs[0]["ledger"]["all"]["files"] == 1, "the file is counted"
    assert upload(api, "mystery.csv", b"Alpha,Beta\n1,2\n").json()["status"] == "unknown_type", "the analyst picks the type"
    assert api.state["adapter"].calls == 0 and api.db["llm_calls"].docs[-1]["status"] == "monthly_allowance_reached"


def test_an_upload_below_100_percent_counts_the_file_the_mapping_call_and_the_recognition_call(api):
    own(api.db)
    api.state["adapter"] = t.FakeAdapter(replies=[mapping_reply(("revenue_type", 6))])
    upload(api, FILE)
    total = ledger(api.db)["all"]
    assert total["files"] == 1 and total["calls"] == 2 and total["cost_usd"] > 0, "the mapping call and the recognition call count toward the allowance"


# --- the routes -------------------------------------------------------------------------------------------------------
def make_tester(owner_client, label="Tester One"):
    body = owner_client.post("/api/admin/testers", json={"label": label}, headers=owner_client.headers_owner).json()
    return body["id"], bearer(token_of(body))


def test_the_owner_usage_lists_totals_and_one_row_per_label_with_counts_and_usd_only(owner):
    a_id, a = make_tester(owner, "Alpha")
    b_id, _ = make_tester(owner, "Beta")
    asyncio.run(allowance.record(owner.db, a_id, files=2, calls=3, tokens=1000, cost_usd=1.25))
    asyncio.run(allowance.record(owner.db, b_id, files=1, calls=1, tokens=500, cost_usd=0.5))
    last_month = owner.db[access.COLLECTION].docs[1]
    last_month.setdefault("ledger", {}).setdefault("all", {})["cost_usd"] = last_month["ledger"]["all"]["cost_usd"] + 4
    body = owner.get("/api/admin/usage", headers=owner.headers_owner).json()
    assert set(body) == {"month", "totals", "testers"}
    assert body["totals"]["this_month"] == {"files": 3, "calls": 4, "tokens": 1500, "cost_usd": 1.75}
    assert body["totals"]["all_time"]["cost_usd"] == 5.75
    rows = {r["label"]: r for r in body["testers"]}
    assert set(rows) == {"Alpha", "Beta"} and all(
        set(r) == {"id", "label", "status", "allowance_usd", "this_month", "all_time"} for r in rows.values())
    assert rows["Alpha"]["this_month"] == {"files": 2, "calls": 3, "tokens": 1000, "cost_usd": 1.25} and rows["Alpha"]["allowance_usd"] == 10


def test_the_usage_never_carries_a_company_file_or_audit_name(owner):
    a_id, a = make_tester(owner)
    created = owner.post("/api/audits", json={"company_name": "Zorblax Holdings"}, headers=a).json()
    owner.db["llm_calls"].docs.append({"run_id": created["id"], "step": "growth_engine", "cache_hit": False, "input_tokens": 1,
                                       "output_tokens": 1, "estimated_cost_usd": 0.1, "status": "ok", "file": "secret_deck.pptx"})
    asyncio.run(allowance.record(owner.db, a_id, files=1, calls=1, tokens=2, cost_usd=0.1))
    text = owner.get("/api/admin/usage", headers=owner.headers_owner).text
    for needle in ("Zorblax", "Quuxfund", "secret_deck", created["id"]):
        assert needle not in text


def test_the_owner_sets_an_allowance_within_range_and_nobody_else_can(owner):
    tid, tester = make_tester(owner)
    url = f"/api/admin/testers/{tid}/allowance"
    saved = owner.post(url, json={"allowance_usd": 25.5}, headers=owner.headers_owner)
    assert saved.status_code == 200 and saved.json()["allowance_usd"] == 25.5
    assert owner.db[access.COLLECTION].docs[0]["allowance_usd"] == 25.5 and "allowance_usd" not in owner.get("/api/allowance", headers=tester).json()
    for bad in (-1, 1000.01, 1.234, "ten", None):
        assert owner.post(url, json={"allowance_usd": bad}, headers=owner.headers_owner).status_code == 422, bad
    assert owner.post(url, json={"allowance_usd": 1, "x": 1}, headers=owner.headers_owner).status_code == 422
    assert owner.post("/api/admin/testers/nobody/allowance", json={"allowance_usd": 5}, headers=owner.headers_owner).status_code == 404
    assert owner.post(url, json={"allowance_usd": 5}).status_code == 401
    assert owner.post(url, json={"allowance_usd": 5}, headers=tester).status_code == 404
    owner.post(url, json={"allowance_usd": 0}, headers=owner.headers_owner)
    assert owner.get("/api/allowance", headers=tester).json()["state"] == "blocked"


def test_the_owner_audit_costs_list_one_row_per_audit_with_label_time_calls_tokens_and_cost_and_no_name(owner):
    a_id, a = make_tester(owner, "Alpha")
    _, b = make_tester(owner, "Beta")
    first = owner.post("/api/audits", json={"company_name": "Zorblax Holdings"}, headers=a).json()
    second = owner.post("/api/audits", json={"company_name": "Quuxfund"}, headers=b).json()
    calls = owner.db["llm_calls"].docs
    calls += [{"run_id": first["id"], "step": "growth_engine", "cache_hit": False, "input_tokens": 1000, "output_tokens": 200,
               "estimated_cost_usd": 0.25, "status": "ok", "file": "secret_deck.pptx"},
              {"run_id": first["id"], "step": "data_inventory", "cache_hit": False, "input_tokens": 300, "output_tokens": 100,
               "estimated_cost_usd": 0.5, "status": "ok"},
              {"run_id": first["id"], "step": "growth_engine", "cache_hit": True, "input_tokens": 0, "output_tokens": 0,
               "estimated_cost_usd": 0.0, "status": "ok"},
              {"run_id": first["id"], "step": "growth_engine", "cache_hit": False, "input_tokens": 0, "output_tokens": 0,
               "estimated_cost_usd": 0.0, "status": "monthly_allowance_reached"}]
    res = owner.get("/api/admin/audit-costs", headers=owner.headers_owner)
    assert res.status_code == 200 and set(res.json()) == {"audits"}
    rows = {r["tester"]: r for r in res.json()["audits"]}
    assert set(rows) == {"Alpha", "Beta"} and all(set(r) == {"tester", "created_at", "calls", "tokens", "cost_usd"} for r in rows.values())
    assert (rows["Alpha"]["calls"], rows["Alpha"]["tokens"], rows["Alpha"]["cost_usd"]) == (2, 1600, 0.75), "billed calls only"
    assert (rows["Beta"]["calls"], rows["Beta"]["tokens"], rows["Beta"]["cost_usd"]) == (0, 0, 0.0)
    assert rows["Alpha"]["created_at"] == owner.db["audits"].docs[0]["created_at"]
    for needle in ("Zorblax", "Quuxfund", "secret_deck", first["id"], second["id"]):
        assert needle not in res.text
    assert owner.get("/api/admin/audit-costs").status_code == 401 and owner.get("/api/admin/audit-costs", headers=a).status_code == 404


def test_a_reissued_or_revoked_link_keeps_the_ledger_and_the_allowance(owner):
    tid, _ = make_tester(owner)
    owner.post(f"/api/admin/testers/{tid}/allowance", json={"allowance_usd": 7}, headers=owner.headers_owner)
    asyncio.run(allowance.record(owner.db, tid, calls=1, tokens=1, cost_usd=1))
    owner.post(f"/api/admin/testers/{tid}/reissue", headers=owner.headers_owner)
    owner.post(f"/api/admin/testers/{tid}/revoke", headers=owner.headers_owner)
    row = owner.get("/api/admin/usage", headers=owner.headers_owner).json()["testers"][0]
    assert (row["allowance_usd"], row["all_time"]["cost_usd"], row["status"]) == (7, 1, "revoked")
    assert all("ledger" not in r for r in owner.get("/api/admin/testers", headers=owner.headers_owner).json())


def test_my_allowance_is_401_without_a_token_and_404_for_the_owner_token(owner):
    _, tester = make_tester(owner)
    assert owner.get("/api/allowance").status_code == 401
    assert owner.get("/api/allowance", headers=owner.headers_owner).status_code == 404
    assert owner.get("/api/allowance", headers=tester).json() == {"percent": 0, "state": "ok"}, "a percentage and a state, no amount"


def test_a_tester_cannot_read_another_testers_usage_and_the_guard_codes_are_closed_words():
    assert guards.GuardRefusal("monthly_allowance_reached").reason == "monthly_allowance_reached"
    assert gateway.CAP_REASONS["monthly_allowance_reached"] == "allowance"
