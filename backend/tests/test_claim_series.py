"""The two engine series claim matching reads (docs/specs/claim-matching.md table 2a): monthly revenue and
active customers. Figures are the spec's section 9 engine figures, measured on sample_data/."""
import pytest

from claim_matching_support import engine_results, fixture

ENGINE = fixture()["engine"]


def _by_month(series, key="total"):
    return {row["month"]: row[key] for row in series["data"]}


def test_revenue_series_sums_to_the_spec_figures():
    series = engine_results()["revenue_series"]
    totals = _by_month(series)
    assert series["months"][0] == ENGINE["first_month"] and series["months"][-1] == "2024-02"
    assert round(sum(v for m, v in totals.items() if m.startswith("2023")), 2) == ENGINE["revenue_FY2023"]
    assert round(sum(totals[m] for m in ("2023-10", "2023-11", "2023-12")), 2) == ENGINE["revenue_2023-Q4"]
    assert round(totals["2024-01"] + totals["2024-02"], 2) == ENGINE["revenue_2024-01_to_2024-02"]


def test_revenue_series_by_segment_adds_up_to_the_total():
    series = engine_results()["revenue_series"]
    assert series["segments"] == ["Enterprise", "Mid-Market", "SMB"]
    for row in series["data"]:
        assert sum(row[s] for s in series["segments"]) == pytest.approx(row["total"], abs=0.02)
    assert round(sum(v for m, v in _by_month(series, "Enterprise").items() if m.startswith("2023")), 2) == 139507.53


def test_revenue_series_carries_its_source_and_rule():
    source = engine_results()["revenue_series"]["source"]
    assert source["file"] == "revenue.csv" and source["rows"].startswith("rows 2")
    assert "one-off" in source["rule"] and "invoice month" in source["rule"]


def test_customers_series_counts_customers_with_mrr_above_zero_each_month():
    series = engine_results()["customers_series"]
    assert series["months"][0] == ENGINE["first_month"]
    assert all(row["total"] == ENGINE["customers_every_month"] for row in series["data"])
    assert {s: series["data"][-1][s] for s in series["segments"]} == ENGINE["customers_by_segment"]
    assert series["source"]["file"] == "revenue.csv" and "MRR above 0" in series["source"]["rule"]


def test_the_two_series_stop_at_the_as_of_month():
    results = engine_results(as_of_month="2023-06")
    assert results["revenue_series"]["months"][-1] == "2023-06" == results["customers_series"]["months"][-1]


def test_a_one_off_line_counts_in_its_invoice_month_and_a_recurring_line_is_spread():
    import growth_engine as ge
    import pandas as pd

    rev = pd.DataFrame({"_row": [2, 3, 4], "customer_id": ["A", "A", "B"],
                        "invoice_date": pd.to_datetime(["2024-01-15", "2024-02-10", "2024-03-05"]),
                        "amount": [1200.0, 500.0, 100.0], "currency": ["EUR", "EUR", "USD"],
                        "revenue_type": ["recurring", "one-off", "one-off"], "segment": ["Big", "Big", "Small"]})
    series = ge.compute_revenue_series(rev, {"A": "annual"}, {"EUR": 1.0, "USD": 0.5})
    assert series["months"][0] == "2024-01" and series["months"][-1] == "2024-12"
    totals = _by_month(series)
    assert totals["2024-01"] == 100.0                      # 1,200 over 12 months
    assert totals["2024-02"] == 600.0                      # 100 spread + the 500 one-off in its invoice month
    assert totals["2024-03"] == 150.0                      # 100 + 100 USD at 0.5, one-off in March
    assert _by_month(series, "Small")["2024-03"] == 50.0
