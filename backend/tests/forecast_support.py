"""Shared set-up of the forecast and annual payback tests (docs/specs/forecast-and-payback.md): the TestCo results with a 36-month series, a
claim and its register row. Synthetic figures; nothing here touches a network or a database."""
import copy

from claim_matching_support import engine_results

from app import claim_matching as cm
from app.decks import claims as deck_claims

NOTE = "Forecast calculations describe assumptions; future outcomes are unverified."
YEAR = {2022: 80_000, 2023: 100_000, 2024: 120_000}          # revenue, MRR and so ARR (x12) per month
CUSTOMERS = {2022: 50, 2023: 80, 2024: 120}


def long_results(last="2024-12"):
    """The TestCo results with a 36-month revenue, MRR and customer series (to `last`); everything else as the engine computed it."""
    r = copy.deepcopy(engine_results())
    rows, customers = [], []
    for year in (2022, 2023, 2024):
        for month in range(1, 13):
            key = f"{year}-{month:02d}"
            if key > last:
                continue
            rows.append({"month": key, "total": float(YEAR[year]), "Enterprise": float(YEAR[year]) * 0.6, "Mid-Market": float(YEAR[year]) * 0.3,
                         "SMB": float(YEAR[year]) * 0.1})
            customers.append({"month": key, "total": CUSTOMERS[year], "Enterprise": CUSTOMERS[year] // 2, "Mid-Market": CUSTOMERS[year] // 4,
                              "SMB": CUSTOMERS[year] // 4})
    for key, data in (("revenue_series", rows), ("mrr_series", rows)):
        r[key] = {**r[key], "months": [d["month"] for d in data], "data": data}
    r["customers_series"] = {**r["customers_series"], "months": [d["month"] for d in customers], "data": customers}
    r["as_of_month"] = last
    r["source_period"] = {"month": last, "status": "Complete", "complete_by": "analyst", "evidence_to": last}
    r.pop("metric_periods", None)
    return r


def settings(last="2024-12", **extra):
    return {"fiscal_year_end": 12, "as_of_month": last, "reporting_currency": "EUR", "fx": {"EUR": 1.0}, **extra}


def claim(snippet, value, period_text, target_date, claim_type="revenue", **over):
    c = {"id": "x1", "status": "approved", "claim_type": claim_type, "value": value, "value_high": None, "unit": None, "currency": "EUR",
         "target_date": target_date, "period_text": period_text, "snippet": snippet, "label_from": None, "file": "deck.pptx", "order": 0,
         "sources": [{"file": "deck.pptx", "slide": 3}], **over}
    deck_claims.resolve_period(c, 12)
    return c


def row_of(candidate, last="2024-12", results=None, **extra):
    return cm.build_register([candidate], results or long_results(last), settings(last, **extra))[0]


def forecast(value=2_073_600, **over):
    return claim("Revenue €2.1M in FY2026", value, "FY2026", "2026", basis="projection", **over)


# --- a yearly-basis P&L (annual payback) ------------------------------------------------------------------------------------------

def yearly_input(sm_scope="sales and marketing", sm=(250_000, 300_000, 336_000), revenue=(1_000_000, 1_200_000, 1_440_000),
                 cost=(300_000, 360_000, 432_000), file="pnl.xlsx"):
    """The engine's yearly input (sheet.yearly_input) for FY2022 to FY2024: gross margin 70%, revenue growth 200,000 then 240,000."""
    actual = []
    for k, year in enumerate((2022, 2023, 2024)):
        fields = {"revenue": {"value": revenue[k], "cells": [f"{'CDE'[k]}3"]}, "cost_of_revenue": {"value": cost[k], "cells": [f"{'CDE'[k]}4"]}}
        if sm[k] is not None:
            fields["sm_expense"] = {"value": sm[k], "cells": [f"{'CDE'[k]}5"], "scope": sm_scope}
        actual.append({"period": f"FY{year}", "year": year, "start": f"{year}-01", "end": f"{year}-12", "fields": fields})
    return {"file": file, "sheet": "P&L", "rows": [3, 4, 5], "actual": actual, "planned": [], "reported": []}


def arr_series(dec=(70_000, 90_000, 120_000)):
    """An MRR series, flat within each year: the December MRR of 2022, 2023 and 2024 (ARR = 12 x)."""
    data = [{"month": f"{year}-{month:02d}", "total": float(dec[year - 2022])} for year in (2022, 2023, 2024) for month in range(1, 13)]
    return {"months": [d["month"] for d in data], "segments": [], "data": data, "source": {"file": "revenue.csv", "sheet": "CSV", "rows": "rows 2-9"}}


def payback_results(yearly=None, mrr=None, last="2024-12"):
    """Long results with the yearly-basis block of the engine, for a P&L read as a statement (no monthly P&L, so no CAC payback block)."""
    import growth_engine as ge
    r = long_results(last)
    r["mrr_series"] = mrr if mrr is not None else {**long_results(last)["mrr_series"], **arr_series()}
    r["cac_payback"] = None
    r["missing_data"] = [{"metric": "CAC payback", "reason": "P&L is yearly; CAC payback needs monthly S&M, revenue and cost of revenue",
                          "unlocked_by": "Upload P&L with month, S&M expense, revenue, cost of revenue", "file": "pnl.xlsx", "status": "Missing"}]
    r["yearly_basis"] = ge.compute_yearly_basis(yearly or yearly_input(), r, r["revenue_series"])
    return r


def payback_claim(text, value, year=2024, **over):
    return claim(text, value, f"FY{year}", str(year), claim_type="cac_payback", unit="months", currency=None, **over)
