"""Forecast tables read as claims (docs/specs/chat-upload.md section 20, issue #114): one plan line × one year, read by rules from the
stored file, rolled up from months or quarters, capped at 60, stored only when the analyst confirms, and kept Unverified in the register
with no value at stake, no overlaps and no gate. Fixtures in tests/fixtures/forecast/ hold invented figures only (CLAUDE.md rule 15).
Every API test runs on the in-memory Mongo stub and the fake adapter: nothing reaches a provider."""
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import server  # noqa: E402
import claim_matching_support as support  # noqa: E402
from test_chat_upload import AUDIT, adapter_of, api, upload, view  # noqa: E402,F401

from app import claim_matching as cm  # noqa: E402
from app import column_rules as cr  # noqa: E402
from app import decks, forecast_claims as fc  # noqa: E402
from app import ic_memo as im  # noqa: E402
from app import verdict as vd  # noqa: E402

FORECAST = Path(__file__).resolve().parent / "fixtures" / "forecast"
ANNUAL, MONTHLY, EIGHTY = "annual_forecast.csv", "monthly_model.csv", "eighty_lines.csv"
PLAN_ROWS = [5, 7, 8, 12, 15, 16, 17, 18]          # the annual fixture's plan lines, by sheet row
SETTINGS = {"fiscal_year_end": 12, "reporting_currency": "EUR", "fx": {"EUR": 1.0}, "as_of_month": None}


def stored(name: str, fiscal_year_end: int = 12) -> dict:
    """A fixture as the server stores it: the first sheet's rows and the fields the reader reads."""
    sheet = cr.read_workbook((FORECAST / name).read_bytes(), name)[0]
    return {"columns": sheet.columns, "rows": server.df_to_records(sheet.frame), "row_numbers": sheet.row_numbers, "wide": sheet.wide,
            "raw_headers": sheet.raw_headers, "first_col": sheet.first_col, "title_currency": sheet.currency,
            "unit_scale": sheet.unit_scale, "sheet": sheet.sheet, "file": name, "file_hash": "h", "dtype": "pnl"}


def line(found: dict, label: str) -> dict:
    return next(x for x in found["lines"] if x["label"] == label)


def values(found: dict, label: str) -> dict:
    return {v["target_date"]: (v["value"], v["cell"]) for v in line(found, label)["values"]}


def forecast_candidates(client):
    return [c for c in client.db[decks.CANDIDATES_COLLECTION].docs if c.get("origin") == fc.ORIGIN]


# ---------------------------------------------------------------------------
# 20.1: which lines are claims
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("label, metric", [
    ("Revenue", "revenue"), ("Total revenue", "revenue"), ("Revenue (EUR k)", "revenue"), ("Subscription revenue", "revenue"),
    ("Sales", "revenue"), ("Net sales", "revenue"), ("ARR", "arr"), ("Annual recurring revenue", "arr"), ("MRR", "mrr"),
    ("Bookings", "bookings"), ("Gross margin", "gross_margin"), ("Gross profit", "gross_margin"), ("Gross margin %", "gross_margin"),
    ("EBITDA", "ebitda"), ("Adjusted EBITDA", "ebitda"), ("Cash balance", "cash_balance"), ("Closing cash", "cash_balance"),
    ("Cash", "cash_balance"), ("Headcount (FTE)", "headcount"), ("Employees", "headcount"), ("Installed units", "installed_units"),
    ("Installed base", "installed_units"), ("Customers", "customers"), ("Customers at year-end", "customers"),
    # not claims: the cost sub-lines, changes, per-unit figures, rates other than gross margin, turnover
    ("Cost of revenue", None), ("Cost of goods sold", None), ("Personnel costs", None), ("Marketing expenses", None),
    ("Sales and marketing", None), ("Sales headcount", "headcount"), ("Revenue growth", None), ("Revenue growth %", None),
    ("Revenue per customer", None), ("New customers", None), ("Churned customers", None), ("Customer acquisition cost", None),
    ("EBITDA margin", None), ("EBITDA (% of revenue)", None), ("Cash flow", None), ("Cash burn", None), ("Deferred revenue", None),
    ("Turnover", None), ("Payroll", None), ("Line", None), ("", None),
])
def test_plan_lines_are_found_by_their_synonyms_and_cost_sub_lines_are_not_claims(label, metric):
    assert fc.metric_of(label) == metric


# ---------------------------------------------------------------------------
# 20.2 and 20.3: an annual forecast (an appendix P&L, EUR thousands, a leading empty column)
# ---------------------------------------------------------------------------
def test_an_annual_forecast_reads_each_plan_line_and_year_from_its_cell_scaled_by_its_title():
    found = fc.read(stored(ANNUAL))
    assert [x["row"] for x in found["lines"]] == PLAN_ROWS, "cost sub-lines, growth, EBITDA margin and new customers are dropped"
    assert (found["sheet"], found["range"], found["count"], found["total"], found["capped"]) == ("CSV", "C5:H18", 48, 48, False)
    revenue = line(found, "Revenue")
    assert (revenue["claim_type"], revenue["unit"], revenue["currency"]) == ("revenue", None, "EUR")
    assert values(found, "Revenue")["2025"] == (1980000, "E5"), "EUR thousands: ×1,000; column A is empty, so 2025F is in E"
    assert [v["period_text"] for v in revenue["values"]] == ["2023A", "2024A", "2025F", "2026F", "2027F", "2028F"]
    assert line(found, "Gross margin")["claim_type"] == "gross_profit" and values(found, "Gross margin")["2023"] == (510000, "C7")
    rate = line(found, "Gross margin %")
    assert (rate["claim_type"], rate["unit"], rate["currency"]) == ("gross_margin", "%", None)
    assert values(found, "Gross margin %")["2025"] == (65.2, "E8"), "a rate is never scaled by 1,000; a fraction reads in percent"
    for label, kind, unit, figure in (("Headcount (FTE)", "people", "people", 26), ("Installed units", "installed_units", "units", 480),
                                      ("Customers", "customers", "customers", 125)):
        assert (line(found, label)["claim_type"], line(found, label)["unit"], line(found, label)["currency"]) == (kind, unit, None)
        assert values(found, label)["2025"][0] == figure, f"{label}: a count is not money and is never scaled"
    assert values(found, "Cash balance")["2028"] == (3900000, "H15")
    assert (line(found, "EBITDA")["claim_type"], line(found, "Cash balance")["claim_type"]) == ("ebitda", "cash")


def test_the_upload_view_lists_the_claims_and_nothing_is_stored_before_confirm(api):  # noqa: F811
    out = upload(api, ANNUAL, (FORECAST / ANNUAL).read_bytes()).json()
    assert out["dtype"] == "pnl" and out["miss"]["looks"]["shape"] == "summary"
    claims = out["forecast_claims"]
    assert (claims["count"], claims["sheet"], claims["range"], claims["saved"], claims["saved_lines"]) == (48, "CSV", "C5:H18", 0, 0)
    assert [x["row"] for x in claims["lines"]] == PLAN_ROWS
    assert view(api, "pnl")["forecast_claims"]["count"] == 48, "the list is rebuilt on reload from the stored rows"
    assert forecast_candidates(api) == [], "nothing is stored until the analyst confirms"
    assert not any("forecast" in str(k) for d in api.db["datasets"].docs for k in d), "the list itself is not stored"


def test_confirm_stores_the_ticked_lines_in_the_table_row_shape_and_drops_the_unticked(api):  # noqa: F811
    upload(api, ANNUAL, (FORECAST / ANNUAL).read_bytes())
    res = api.post(f"/api/audits/{AUDIT}/datasets/pnl/forecast-claims", json={"rows": [5, 16]})
    assert res.status_code == 200 and res.json() == {"saved": 12, "lines": 2}
    made = sorted(forecast_candidates(api), key=lambda c: c["sheet_row"])
    assert [c["snippet"] for c in made] == ["Revenue", "Headcount (FTE)"], "unticked lines are dropped; the label is as in the file"
    revenue = made[0]
    assert (revenue["status"], revenue["deck_id"], revenue["claim_type"], revenue["currency"], revenue["value"]) == \
        ("approved", None, "revenue", "EUR", None)
    first = revenue["by_period"][2]
    assert (first["value"], first["target_date"], first["period_text"]) == (1980000, "2025", "2025F")
    assert (first["period_start"], first["period_end"]) == ("2025-01-01", "2025-12-31")
    assert first["source"] == {"file": ANNUAL, "sheet": "CSV", "cell": "E5", "kind": "sheet"}
    assert view(api, "pnl")["forecast_claims"]["saved"] == 12, "a reload shows what was saved"
    listed = api.get(f"/api/audits/{AUDIT}/decks")
    assert listed.status_code == 200, "the deck list reads candidates with no deck and sheet sources"
    assert {c["snippet"] for c in listed.json()["candidates"]} == {"Revenue", "Headcount (FTE)"}
    assert api.get(f"/api/audits/{AUDIT}/claims").status_code == 200


def test_confirm_refuses_a_row_that_is_not_a_line_of_the_list_and_a_second_confirm(api):  # noqa: F811
    upload(api, ANNUAL, (FORECAST / ANNUAL).read_bytes())
    for rows in ([6], [5, 99]):                      # row 6 is Cost of goods sold, a cost sub-line
        res = api.post(f"/api/audits/{AUDIT}/datasets/pnl/forecast-claims", json={"rows": rows})
        assert res.status_code == 400, rows
    assert forecast_candidates(api) == [], "a refused confirm stores nothing"
    assert api.post(f"/api/audits/{AUDIT}/datasets/pnl/forecast-claims", json={"rows": [5]}).status_code == 200
    assert api.post(f"/api/audits/{AUDIT}/datasets/pnl/forecast-claims", json={"rows": [7]}).status_code == 409
    assert len(forecast_candidates(api)) == 1


def test_a_wide_table_that_maps_is_not_read_as_claims(api):  # noqa: F811
    """A monthly revenue table by customer maps (no miss): its lines are customers, even when a name holds a plan word."""
    months = ",".join(f"{m}-24" for m in "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())
    body = "".join(f"Client {n},EUR," + ",".join(str(100 + i) for i in range(12)) + "\n" for n in ("Alpha", "Beta", "Gamma"))
    out = upload(api, "wide.csv", f"Customer,Currency,{months}\n{body}".encode()).json()
    assert (out["dtype"], out["miss"]) == ("revenue", None), "fixture: the table maps as the revenue file"
    assert out["forecast_claims"] is None
    assert api.post(f"/api/audits/{AUDIT}/datasets/revenue/forecast-claims", json={"rows": [2]}).status_code == 400
    assert forecast_candidates(api) == []


# ---------------------------------------------------------------------------
# 20.2: a monthly five-year model (July 2025 to June 2030) rolls up to years
# ---------------------------------------------------------------------------
def test_a_monthly_model_rolls_up_flows_by_sum_and_balances_at_the_year_end():
    found = fc.read(stored(MONTHLY))
    assert [x["label"] for x in found["lines"]] == ["Revenue", "EBITDA", "Cash balance", "Customers", "Headcount"], \
        "cost of sales is a cost sub-line; a monthly gross margin % has no annual figure without weights"
    revenue = values(found, "Revenue")
    assert sorted(revenue) == ["2026", "2027", "2028", "2029"], "2025 (from July) and 2030 (to June) are partial: no flow"
    assert revenue["2026"] == (sum(100 + k for k in range(6, 18)), "H5:S5"), "the sum of Jan-26 to Dec-26, citing the twelve cells"
    assert line(found, "Revenue")["values"][0]["period"] == "Jan-26–Dec-26" and line(found, "Revenue")["values"][0]["period_text"] is None
    customers = values(found, "Customers")
    assert sorted(customers) == ["2025", "2026", "2027", "2028", "2029"], "a balance needs the year-end month only"
    assert customers["2025"] == (15, "G10") and customers["2026"] == (27, "S10"), "the December value, not a sum"
    assert values(found, "Cash balance")["2029"] == (4470, "BC9")
    assert (found["count"], found["capped"]) == (23, False)


def test_a_june_year_end_groups_july_to_june_and_reads_five_full_years():
    found = fc.read(stored(MONTHLY), fiscal_year_end=6)
    revenue = values(found, "Revenue")
    assert sorted(revenue) == ["2026", "2027", "2028", "2029", "2030"]
    assert revenue["2026"] == (sum(100 + k for k in range(12)), "B5:M5") and revenue["2030"][0] == sum(100 + k for k in range(48, 60))
    assert values(found, "Customers")["2026"] == (21, "M10"), "June 2026 closes FY2026"


def test_a_new_year_end_reads_the_saved_month_claims_again(api):  # noqa: F811
    upload(api, MONTHLY, (FORECAST / MONTHLY).read_bytes())
    assert api.post(f"/api/audits/{AUDIT}/datasets/pnl/forecast-claims", json={"rows": [5]}).json()["saved"] == 4
    assert api.put(f"/api/audits/{AUDIT}", json={"fiscal_year_end": 6}).status_code == 200
    (revenue,) = forecast_candidates(api)
    assert [(i["target_date"], i["value"]) for i in revenue["by_period"]][0] == ("2026", sum(100 + k for k in range(12)))
    assert len(revenue["by_period"]) == 5 and revenue["by_period"][0]["source"]["cell"] == "B5:M5"
    assert (revenue["by_period"][0]["period_start"], revenue["by_period"][0]["period_end"]) == ("2025-07-01", "2026-06-30")


def test_quarters_roll_up_and_a_stated_year_column_wins():
    content = (b"Line,Q1 2025,Q2 2025,Q3 2025,Q4 2025,2025,Q1 2026,Q2 2026,Q3 2026,Q4 2026,Q1 2027\n"
               b"Revenue (USD),10,20,30,40,999,11,21,31,41,12\nCustomers,5,6,7,8,8,9,10,11,12,13\n")
    sheet = cr.read_workbook(content, "q.csv")[0]
    found = fc.read({"columns": sheet.columns, "rows": server.df_to_records(sheet.frame), "row_numbers": sheet.row_numbers,
                     "wide": sheet.wide, "raw_headers": sheet.raw_headers, "first_col": 1, "unit_scale": 1, "sheet": "q"})
    assert values(found, "Revenue (USD)") == {"2025": (999, "F2"), "2026": (104, "G2:J2")}, "2027 has one quarter: no flow"
    assert line(found, "Revenue (USD)")["currency"] == "USD", "no title rows: the label names the currency"
    assert values(found, "Customers") == {"2025": (8, "F3"), "2026": (12, "J3")}, "a balance reads Q4"


# ---------------------------------------------------------------------------
# 20.2: the cap
# ---------------------------------------------------------------------------
def test_eighty_lines_cap_at_sixty_claims_by_row_order(api):  # noqa: F811
    found = fc.read(stored(EIGHTY))
    assert (found["count"], found["total"], found["capped"], found["range"]) == (60, 560, True, "B2:H10")
    assert [x["row"] for x in found["lines"]] == list(range(2, 11)), "lines 1 to 9: the first 60 claims by row order"
    assert len(line(found, "Revenue region 09")["values"]) == 4, "the ninth line keeps its first four years"
    out = upload(api, EIGHTY, (FORECAST / EIGHTY).read_bytes(), dtype="pnl").json()["forecast_claims"]
    assert (out["count"], out["total"], out["capped"]) == (60, 560, True)
    res = api.post(f"/api/audits/{AUDIT}/datasets/pnl/forecast-claims", json={"rows": list(range(2, 11))})
    assert res.json() == {"saved": 60, "lines": 9}
    assert api.post(f"/api/audits/{AUDIT}/datasets/pnl/forecast-claims", json={"rows": [11]}).status_code in (400, 409)


# ---------------------------------------------------------------------------
# 20.3: the register
# ---------------------------------------------------------------------------
def _register(candidates):
    tested = {"id": "t1", "status": "approved", "claim_type": "revenue", "value": 200000, "currency": "EUR", "unit": None,
              "target_date": "2024-02", "period_start": "2024-02-01", "period_end": "2024-02-29", "snippet": "ARR €200,000",
              "label_from": None, "file": "deck.pptx", "order": 0, "sources": [{"file": "deck.pptx", "slide": 3}]}
    unsupported = {**tested, "id": "t2", "claim_type": "market", "value": 2e9, "target_date": None, "period_start": None,
                   "period_end": None, "snippet": "TAM €2bn", "order": 99}        # last in register order: only the rank puts it first
    claims = [tested] + [{**c, "id": f"f{i}", "status": "approved", "file": ANNUAL, "order": i + 1}
                         for i, c in enumerate(candidates)] + [unsupported]
    return cm.build_register(claims, support.engine_results(), SETTINGS)


def test_a_forecast_claim_is_unverified_with_no_value_at_stake_overlaps_metric_or_gate_and_ranks_last():
    found = fc.read(stored(ANNUAL))
    rows = _register(fc.candidates(found, {5, 15}, stored(ANNUAL)))
    forecast = [r for r in rows if r["claim_id"] not in ("t1", "t2")]
    assert len(forecast) == 12 and [r["claim_id"] for r in rows[:2]] == ["t1", "t2"], "forecast-table claims rank after every other row"
    assert rows[1]["evidence_label"] == "Unsupported", "fixture: a row with no gap, which ranks before the untested rows"
    for r in forecast:
        assert (r["evidence_label"], r["reason"]) == ("Unverified", cm.FORECAST_NOTE)
        assert r["value_at_stake_arr"] is None and r["overlaps_with"] is None, "value at stake and overlaps are null"
        assert (r["metric"], r["observed_value"], r["gap"], r["gate_needed"]) == (None, None, None, False)
        assert r["deck_reading"] == cm.FORECAST_READING
    first = next(r for r in forecast if r["claim_id"] == "f0#3")
    assert (first["claimed_value"], first["period"], first["page_ref"]) == (1980000, "2025F", "CSV!E5")
    assert vd.proposal(rows) == ["t1", "t2"], "out of the top 5"
    assert set(vd.gate_prefill(rows, "2026-12-31")) == {"t2"}, "no gate is prefilled on a forecast-table claim"


def test_an_edited_forecast_claim_stays_a_forecast_table_claim():
    found = fc.read(stored(ANNUAL))
    (c,) = fc.candidates(found, {5}, stored(ANNUAL))
    rows = _register([{**c, "status": "edited", "parsed": {"by_period": c["by_period"]}}])
    assert all(r["evidence_label"] == "Unverified" and r["deck_reading"] == cm.FORECAST_READING
               for r in rows if r["claim_id"] not in ("t1", "t2"))


def test_the_ic_memo_and_the_baseline_csv_carry_forecast_claims_whose_overlaps_are_null():
    """The memo's register appendix and the baseline CSV read `overlaps_with`; a forecast-table row holds null there (section 20.3)."""
    import test_ic_memo as memo_t
    from test_claim_matching import RUNS, settings
    kw = memo_t.inputs()
    extra = [{**c, "id": f"f{i}", "status": "approved", "file": ANNUAL, "order": 1000 + i}
             for i, c in enumerate(fc.candidates(fc.read(stored(ANNUAL)), {5}, stored(ANNUAL)))]
    added = cm.build_register(extra, kw["results"], settings(RUNS["A"]))
    for rank, r in enumerate(added, len(kw["rows"]) + 1):
        r["rank"] = rank
    rows = kw["rows"] + added
    top = kw["ver"]["top5"]["claim_ids"]
    kw.update(rows=rows, ver=vd.verdict(rows, kw["results"], {"claim_ids": top}), key=vd.key_gates(rows))
    text = im.build_memo(**kw)
    assert text.count(cm.FORECAST_NOTE) == len(added) == 6, "each forecast-table row is listed in the register appendix"
    csv_rows, _, _ = vd.parse_baseline(vd.baseline_csv(rows, [], top, None))
    assert [r["overlaps_with"] for r in csv_rows if r["reason"] == cm.FORECAST_NOTE] == [[]] * 6, "a null reads back as no overlap"
