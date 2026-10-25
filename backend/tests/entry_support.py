"""The database of the `entry_api` fixture (tests/conftest.py): run A's audit and revenue file and a claim of each kind the register meets
(docs/design/simplified-flow.md section 2): clean claims Python enters on its own, a flagged one that waits for an answer, a rejected one,
an Other figure, use of funds and acquisition channels, an edited claim. Shared by the definition-check, the entry and the scenario tests."""
import copy

import test_llm_gateway as t
from claim_matching_support import engine_results, fixture

from app import decks
from app.decks import claims as deck_claims

AUDIT = "audit-all"
RUN = fixture()["runs"]["A"]
REVENUE, CUSTOMERS, CHANNELS, FUNDS, OTHER = (deck_claims.type_group(x) for x in
                                              ("revenue", "customers", "acquisition_channels", "use_of_funds", "other"))


def claim(cid, claim_type="revenue", **over):
    # FY2023 revenue is 187,701.05 in run A: the figures stay within 50% of it, so no claim asks a Definition check unless a test says so
    c = {"audit_id": AUDIT, "id": cid, "deck_id": "d1", "status": "pending", "claim_type": claim_type, "value": 190000, "value_high": None,
         "unit": None, "currency": "EUR", "snippet": f"Revenue EUR 190,000 ({cid})", "label_from": None, "file": "deck.pptx", "order": 0,
         "sources": [{"file": "deck.pptx", "slide": 3}], "target_date": "2023", "period_text": "FY2023", **over}
    deck_claims.resolve_period(c, RUN["fiscal_year_end"])
    return c


def starting_db():
    db = t.FakeDB()
    db["audits"].docs.append({"id": AUDIT, "reporting_currency": "EUR", "fiscal_year_end": 12, "as_of_month": None,
                              "results": copy.deepcopy(engine_results(tuple(RUN["files"]), RUN["as_of_month"]))})
    db["datasets"].docs.append({"audit_id": AUDIT, "dtype": "revenue", "fx": {}})
    docs = db[decks.CANDIDATES_COLLECTION].docs
    docs += [claim("r1"), claim("r2", value=200000), claim("r3", status="rejected"), claim("r4", status="approved"),
             claim("c1", "customers", value=4, currency=None, unit="count", snippet="4 customers"),
             claim("a1", "acquisition_channels", value=30000, currency=None, unit="count", snippet="Telegram(30K)", channel="Telegram",
                   target_date=None, period_text=None),
             claim("a2", "acquisition_channels", value=3000, currency=None, unit="count", snippet="Twitter(3K)", channel="Twitter",
                   target_date=None, period_text=None, deck_id="d2"),
             claim("f1", "use_of_funds", value=40, currency=None, unit="%", snippet="Hiring (40%)", target_date=None, period_text=None),
             claim("o1", "other", value=7, currency=None, snippet="7 things", target_date=None, period_text=None),
             claim("e1", "revenue", value=180000, status="pending", parsed={"claim_type": "revenue", "value": 18000})]
    return db


def status(db, cid):
    return next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == cid)["status"]
