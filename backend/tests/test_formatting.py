"""Display formatting: the rules, the shared vectors, and the gateway boundary."""
import json
from pathlib import Path

import pytest

from app import formatting as f

VECTORS = json.loads(
    (Path(__file__).parents[2] / "frontend/src/lib/format_vectors.json").read_text("utf-8")
)


@pytest.mark.parametrize("v", VECTORS, ids=lambda v: f"{v['kind']}:{v['in']}")
def test_shared_vectors(v):
    assert f.fmt(v["kind"], v["in"], v.get("ccy")) == v["out"]


RAW = {
    "reporting_currency": "EUR",
    "target_arr": 5000000,
    "metrics": {
        "arr": {"value": 3129104.4, "mrr": 260758.7, "month": "2026-06"},
        "nrr": {"overall_pct": 106.41, "n": 100.0, "series": [{"month": "2026-06", "nrr_pct": 8.38}]},
        "sales_cycle": {"median_days": 42.1, "iqr": [17.0, 58.5], "n": 12},
        "cac_payback": {"default_l": 1, "quarters": {"2026-Q1": {"new_mrr": 1000.4, "gross_margin_pct": 71.2,
                        "L1": {"months": 12.2, "sm_expense": 9000.0, "reason": None}}}},
        "acv_path": {
            "acv": 28451.2, "customers_needed": 128.3, "required_vs_observed_12m": 1.28,
            "bands": [{"key": "k", "label": "Self-serve", "low": 100, "high": 1000,
                       "range_label": "€100–1K", "count": 3}],
            "overall_band": {"key": "k", "label": "x", "value_label": "€28.5K"},
        },
    },
}


def test_format_payload_leaves_no_raw_numbers():
    out = f.format_payload(RAW)

    def walk(n):
        if isinstance(n, dict):
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
        else:
            assert isinstance(n, (str, type(None))), n

    walk(out)
    m = out["metrics"]
    assert out["target_arr"] == "5,000,000 EUR"
    assert m["arr"]["value"] == "3,129,104 EUR"
    assert m["nrr"]["overall_pct"] == "106%" and m["nrr"]["n"] == "100"
    assert m["sales_cycle"]["median_days"] == "43" and m["sales_cycle"]["iqr"] == ["17", "59"]
    assert m["acv_path"]["customers_needed"] == "129"
    assert m["acv_path"]["required_vs_observed_12m"] == "1.28x"
    assert m["acv_path"]["bands"][0]["range_label"] == "100–1,000 EUR"
    assert "value_label" not in m["acv_path"]["overall_band"]
    assert RAW["metrics"]["arr"]["value"] == 3129104.4  # input untouched


def test_unregistered_numeric_field_is_refused():
    with pytest.raises(f.FormattingError):
        f.format_payload({"metrics": {"mystery": 1.5}})


def test_numeric_guard_still_matches_formatted_strings():
    from app.llm import gateway
    from app.llm.schemas import Narrative, TableRow

    out = f.format_payload(RAW)
    n = Narrative(headline="ARR is 3,129,104 EUR", what_this_means="Needs 129 customers at 1.28x.",
                  table_rows=[TableRow(label="NRR", value="106%", source_key="metrics.nrr.overall_pct")])
    assert gateway.numeric_guard(n, out).all == []


def test_acv_defined_once_at_first_use():
    out = f.define_acv_on_first_use(["Headline", "ACV is 28,451 EUR; ACV rose", "ACV again"])
    assert out[1] == "ACV (average contract value) is 28,451 EUR; ACV rose"
    assert out[2] == "ACV again"
    assert f.define_acv_on_first_use(out) == out
    assert f.define_acv_on_first_use(["no term"]) == ["no term"]
