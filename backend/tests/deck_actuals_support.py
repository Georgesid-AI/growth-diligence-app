"""Shared set-up of the deck-actuals tests (docs/design/deck-actuals.md): page 3 of a deck as the page reader stores it, and a yearly P&L
that is mapped. Synthetic company, figures of the addendum's test case only; nothing here touches a network or a database (rule 15)."""
import copy

from forecast_support import long_results

from app import claim_matching as cm
from app.decks import claims as deck_claims

FYE = 12
DECK = "testco_deck.pdf"
AS_OF = "2021-12"
FY = {2019: 170_044.11, 2020: 151_056.65, 2021: 501_378.04}


def yearly_pnl(revenue=FY, sheet="P&L"):
    """The engine's yearly input for FY2019 to FY2021 (sheet.yearly_input): revenue in row 3, columns C, D and E."""
    actual = []
    for k, year in enumerate(sorted(revenue)):
        actual.append({"period": f"FY{year}", "year": year, "start": f"{year}-01", "end": f"{year}-12",
                       "fields": {"revenue": {"value": revenue[year], "cells": [f"{'CDE'[k]}3"]}}})
    return {"file": "pnl.xlsx", "sheet": sheet, "rows": [3], "actual": actual, "planned": [], "reported": []}


def results(revenue=FY, as_of=AS_OF):
    """Long results with no monthly series (a yearly P&L only) and its yearly-basis block, as of December 2021."""
    import growth_engine as ge
    r = long_results(as_of)
    for key in ("revenue_series", "mrr_series", "customers_series"):
        r[key] = {**r[key], "months": [], "data": [], "segments": []}
    r["cac_payback"] = None
    r["yearly_basis"] = ge.compute_yearly_basis(yearly_pnl(revenue), r, r["revenue_series"])
    return r


def settings(as_of=AS_OF, **extra):
    return {"fiscal_year_end": FYE, "as_of_month": as_of, "reporting_currency": "EUR", "fx": {"EUR": 1.0}, **extra}


def reading(cid, value, label, period, page=3, claim_type="revenue", unit=None, currency="EUR", cell=None, order=None, **over):
    """One stored page reading: an AI row as the page reader and the checker leave it, matched to its cell, with no flag."""
    n = int(cid[1:]) if order is None else order
    c = {"id": cid, "status": "approved", "origin": "ai", "ai_status": "matched", "ai_label": "Verified", "claim_type": claim_type, "value": value,
         "value_high": None, "unit": unit, "currency": currency if unit is None else None, "target_date": period, "period_text": period,
         "snippet": f"{value:,}", "label_from": label, "file": DECK, "deck_id": "d1", "order": n, "cell": cell or f"p{page}r{n}c1",
         "structure_key": f"page-{page}", "basis": "actual", "scenario": "none", "flags": [], "heading_metric": "revenue",
         "sources": [{"file": DECK, "page": page, "kind": "page", "cell": cell or f"p{page}r{n}c1"}], **over}
    return deck_claims.resolve_period(c, FYE)


def page3():
    """Page 3: heading "2021 REVENUE"; a stacked bar of two segments over a total; a table of three years; two growth multiples; and the
    table again on page 12. Eleven stored readings, eight of them on page 3."""
    return [
        reading("c1", 501_378, "2021 REVENUE", "FY2021"),                                   # the bar's total, read under the heading
        reading("c2", 482_475, "New business", None),                                       # a segment of the bar: no period read
        reading("c3", 18_903, "Committed from 2020", "FY2020"),                             # a segment whose period disagrees
        reading("c4", 170_044.11, "Recognised Revenue", "FY2019", cell="p3t1r1c2"),
        reading("c5", 151_056.65, "Recognised Revenue", "FY2020", cell="p3t1r1c3"),
        reading("c6", 501_378.04, "Recognised Revenue", "FY2021", cell="p3t1r1c4"),
        reading("c7", 0.9, "2019 → 2020", "FY2020", claim_type="revenue_growth", unit="x", snippet="0.9 x"),
        reading("c8", 3.3, "2020 → 2021", "FY2021", claim_type="revenue_growth", unit="x", snippet="3.3 x"),
        reading("c9", 170_044.11, "Recognised Revenue", "FY2019", page=12, cell="p12t1r1c2", structure_key="page-12"),
        reading("c10", 151_056.65, "Recognised Revenue", "FY2020", page=12, cell="p12t1r1c3", structure_key="page-12"),
        reading("c11", 501_378.04, "Recognised Revenue", "FY2021", page=12, cell="p12t1r1c4", structure_key="page-12"),
    ]


def register(candidates, res=None, **extra):
    """The register of folded candidates, as the server reads them."""
    return cm.build_register(deck_claims.fold_twins(copy.deepcopy(candidates)), res or results(), settings(**extra))


def by_id(rows):
    return {r["claim_id"]: r for r in rows}
