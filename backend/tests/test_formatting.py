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
                        "L1": {"months": 12.24, "sm_expense": 9000.0, "reason": None}}}},
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
    assert m["cac_payback"]["quarters"]["2026-Q1"]["L1"]["months"] == "12.2 months"
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


def test_xlsx_values_display_like_the_formatter():
    # The cell holds a number; the Excel format shows what fmt() would.
    assert f.xlsx_value(f.PCT, 106.41) == pytest.approx(1.0641)   # "0%" -> 106%
    assert f.xlsx_value(f.COUNT_UP, 128.3) == 129                # formats cannot round up
    assert f.xlsx_value(f.DAYS, 42.1) == 43
    assert f.xlsx_value(f.MONTHS, 12.24) == 12.24                # "0.0" -> 12.2
    assert f.xlsx_value(f.CURRENCY, 3129104.4) == 3129104.4      # "#,##0" -> 3,129,104
    assert f.xlsx_value(f.RATIO, 1.28) == 1.28                   # 0.00"x"
    assert f.xlsx_value(f.COUNT, None) is None
    assert f.XLSX_NUMBER_FORMAT[f.RATIO] == '0.00"x"'


# ---------------------------------------------------------------------------
# Registry coverage: every numeric field the gateway can send has a display kind
# ---------------------------------------------------------------------------
def _numeric_leaves(node, key=None, parent=None):
    """Yield (key, parent, value) for every number, with list items inheriting their list's key."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _numeric_leaves(v, k, key)
    elif isinstance(node, list):
        for item in node:
            yield from _numeric_leaves(item, key, parent)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield key, parent, node


def _unregistered(payload):
    return sorted({
        str(k) for k, parent, _ in _numeric_leaves(payload)
        if not (f.KIND_BY_KEY.get(k) or f.KIND_BY_PARENT.get(parent))
    })


def test_provenance_row_references_are_registered():
    """Regression: the gateway raised format_failed on 'row_numbers'."""
    payload = {"metrics": {"arr": {"value": 1.0, "source": {
        "file": "r.xlsx", "sheet": "S", "row_numbers": [2, 3, 500]}}}}
    out = f.format_payload(payload)
    assert out["metrics"]["arr"]["source"]["row_numbers"] == ["2", "3", "500"]


# Fields the engine emits only on rare branches, which the demo data never hits.
# Keep this in step with growth_engine.py; the engine scan below catches the rest.
RARE_BRANCH_FIELDS = {
    "nrr": {"insufficient_history": True, "months_available": 7},
    "gross_churn": {"insufficient_history": True, "months_available": 7},
    "win_rate": {"founder_involved_excluded": {"count": 2, "rows": [4, 9], "values": ["maybe"]}},
    "acv_path": {"target_date_error": "bad date", "required_net_new_per_year": None},
}


def test_rare_branch_fields_are_registered():
    assert _unregistered({"metrics": RARE_BRANCH_FIELDS}) == []


def test_every_numeric_field_the_gateway_can_send_has_a_display_kind():
    """Run the real engine over demo data (including sparse variants) and push every
    step's payload through the gateway's own outbound builder. An unregistered
    numeric field fails here instead of as format_failed at runtime."""
    pytest.importorskip("pandas")
    pytest.importorskip("fastapi")
    pytest.importorskip("motor")
    import os
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "format_coverage_test")
    import pandas as pd
    import demo_data
    import growth_engine as ge
    import server
    from app.llm import gateway

    def run(spec, drop=(), target_date=None):
        datasets, meta = demo_data.build(spec)
        norm = {t: server.normalize(server.df_to_records(df), t, m) for t, (df, m) in datasets.items()}
        for t in drop:
            norm[t] = norm[t].iloc[0:0] if isinstance(norm[t], pd.DataFrame) else pd.DataFrame()
        fx = {k.upper(): v for k, v in meta.get("fx", {}).items()}
        fx[spec["reporting_currency"].upper()] = 1.0
        cfg = {"reporting_currency": spec["reporting_currency"], "target_arr": spec["target_arr"],
               "target_date": target_date or spec["target_date"], "fx": fx, "billing_terms": {},
               "default_l": 1, "as_of_month": None}
        src = {t: {"file": meta[t]["file"], "sheet": meta[t]["sheet"]} for t in datasets}
        return server.sanitize(ge.compute_all(norm["revenue"], norm["crm"], norm["pnl"], cfg, src))

    runs = []
    for spec in demo_data.DEMO_AUDITS:
        runs += [
            run(spec), run(spec, drop=("pnl",)), run(spec, drop=("crm",)),
            run(spec, target_date="1999-01-01"),
            run({**spec, "months": 8}), run({**spec, "months": 14}),
        ]

    for results in runs:
        for step in gateway.STEP_CONFIG:
            computed = {
                "reporting_currency": results.get("reporting_currency"),
                "target_arr": 1_000_000.0,
                "metrics": gateway._slice_for_step(results, step),
            }
            assert _unregistered(computed) == [], f"step {step}"
            gateway.build_outbound(computed, {})  # raises GatewayError(format_failed) otherwise
