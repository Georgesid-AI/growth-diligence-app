"""Series differences in the Uncertain list (brief of George, 2026-11-05): two series are equal when every period matches and every value
matches within 0.5% or 1 unit; a formatting-only difference is no item; a series item names the first differing period with both values
and how many periods differ. Synthetic maps only."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pdfplumber")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app import consistency  # noqa: E402
from test_reading_consistency_pass2 import a_row, map_of  # noqa: E402


def months(n=30, start_year=2019):
    return [f"{start_year + i // 12}-{i % 12 + 1:02d}" for i in range(n)]


def ser(values, periods=None):
    periods = periods or months(len(values))
    return {"periods": periods, "values": values, "refs": [f"B{i}" for i in range(len(values))]}


def pair(first, second, field="series"):
    return consistency.compare(map_of(a_row(4, **{field: first})), map_of(a_row(4, **{field: second})))


def test_rule1_a_formatting_only_difference_is_no_item():
    base = [1200, 1300, 1400]
    assert pair(ser(base, ["2021-01", "2021-02", "2021-03"]), ser([1200.0, 1300.0, 1400.0], ["2021-1", "2021-2", "2021-3"])) == []
    assert pair(ser([1200, 1300], ["2021-03", "2021-04"]), ser([1200.0, 1300.0], ["2021-3", "2021-4"])) == []


def test_rule1_values_within_half_a_percent_or_one_unit_are_equal():
    assert pair(ser([100_000.0, 5.0]), ser([100_400.0, 5.9])) == []          # 0.4 % of a large value; 0.9 of a unit on a small one
    assert pair(ser([0.0, 10.0]), ser([0.9, 10.5])) == []


def test_rule1_a_value_beyond_both_tolerances_is_a_difference():
    (item,) = pair(ser([100_000.0]), ser([100_600.0]))
    assert item["fields"] == ["series"]
    (item,) = pair(ser([10.0]), ser([11.5]))
    assert item["fields"] == ["series"]


def test_rule1_a_period_one_read_lacks_is_a_difference_and_the_plan_series_is_compared_alike():
    (item,) = pair(ser([1, 2, 3]), ser([1, 2]))
    assert item["series_diff"]["series"]["differing"] == 1
    assert pair(ser([1, 2]), ser([1.0, 2.0], ["2019-1", "2019-2"]), "plan_series") == []
    (item,) = pair(ser([100, 200]), ser([100, 900]), "plan_series")
    assert item["fields"] == ["plan_series"] and "series" not in item["series_diff"]


def test_rule2_the_item_names_the_first_differing_period_with_both_values_and_the_count():
    a = [1000.0] * 30
    b = list(a)
    for i in (26, 27, 29):
        b[i] = 2000.0
    b[25] = 1003.0                      # 0.3 % apart: equal under rule 1, so not counted
    (item,) = pair(ser(a), ser(b))
    d = item["series_diff"]["series"]
    assert d == {"period": "2021-03", "first": 1000.0, "second": 2000.0, "differing": 3, "total": 30}


def test_rule2_the_first_period_is_the_earliest_in_time_not_the_first_the_code_meets():
    (item,) = pair(ser([5, 5, 900], ["2021-03", "2021-01", "2021-02"]), ser([5, 5, 100], ["2021-3", "2021-1", "2021-2"]))
    assert item["series_diff"]["series"]["period"] == "2021-02"


def test_rule2_a_missing_period_shows_none_for_the_read_that_lacks_it():
    (item,) = pair(ser([1, 2, 3]), ser([1, 2]))
    d = item["series_diff"]["series"]
    assert (d["period"], d["first"], d["second"], d["total"]) == ("2019-03", 3, None, 3)


def test_rule3_equal_series_with_another_field_differing_names_only_that_field():
    first, second = map_of(a_row(4, series=ser([1200])), ), map_of(a_row(4, series=ser([1200.0], ["2019-1"]), role="arr"))
    (item,) = consistency.compare(first, second)
    assert item["fields"] == ["role"] and "series_diff" not in item


def test_rows_with_the_same_series_difference_group_and_rows_with_another_do_not():
    one = [a_row(n, series=ser([100, 100])) for n in (4, 5)]
    two = [a_row(n, series=ser([100, 900])) for n in (4, 5)]
    (item,) = consistency.compare(map_of(*one), map_of(*two))
    assert item["rows"] == [4, 5]
    three = [a_row(4, series=ser([100, 100])), a_row(5, series=ser([100, 100]))]
    four = [a_row(4, series=ser([100, 900])), a_row(5, series=ser([100, 700]))]
    assert len(consistency.compare(map_of(*three), map_of(*four))) == 2


# --- combined fixes, item 10 (2026-11-05): an item stored before the series difference was kept gets it when served ---------------------------------

def stored_without_diff(first, second, field="series"):
    (item,) = pair(first, second, field)
    item.pop("series_diff")
    return item


def test_item10_a_stored_item_with_no_series_difference_gets_the_first_differing_period_when_served():
    a, b = ser([100, 200, 300]), ser([100, 200, 999])
    old = stored_without_diff(a, b)
    (served,) = consistency.with_series_diffs([old], map_of(a_row(4, series=a)), map_of(a_row(4, series=b)))
    assert served["series_diff"] == {"series": {"period": "2019-03", "first": 300, "second": 999, "differing": 1, "total": 3}}


def test_item10_the_plan_series_is_filled_alike_and_an_item_that_has_its_difference_is_left_as_it_is():
    a, b = ser([1, 2]), ser([1, 9])
    old = stored_without_diff(a, b, "plan_series")
    (served,) = consistency.with_series_diffs([old], map_of(a_row(4, plan_series=a)), map_of(a_row(4, plan_series=b)))
    assert served["series_diff"]["plan_series"]["period"] == "2019-02" and served["series_diff"]["plan_series"]["differing"] == 1
    kept = {**old, "series_diff": {"plan_series": {"period": "x", "first": 1, "second": 2, "differing": 1, "total": 1}}}
    assert consistency.with_series_diffs([kept], map_of(a_row(4, plan_series=a)), map_of(a_row(4, plan_series=b)))[0] is kept


def test_item10_no_second_reading_or_an_item_with_no_series_field_is_returned_as_it_is():
    a, b = ser([1, 2]), ser([1, 9])
    old = stored_without_diff(a, b)
    assert consistency.with_series_diffs([old], map_of(a_row(4, series=a)), None) == [old]
    other = {"key": "k", "kind": "row", "sheet": "S", "row": 4, "rows": [4], "fields": ["role"], "first": {}, "second": {}}
    assert consistency.with_series_diffs([other], map_of(a_row(4, series=a)), map_of(a_row(4, series=b))) == [other]
