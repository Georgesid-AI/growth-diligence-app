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
    assert m["sales_cycle"]["median_days"] == "43 days" and m["sales_cycle"]["iqr"] == ["17 days", "59 days"]
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


# ---------------------------------------------------------------------------
# Readable labels for cited paths (display only)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path,label", [
    ("metrics.acv_path.total_customers_at_target", "Total customers at target ARR"),
    ("metrics.acv_path.additional_customers_needed", "Additional customers needed"),
    ("metrics.acv_path.customers_needed", "Total customers at target ARR"),   # legacy key, same wording
    ("metrics.nrr.overall_pct", "NRR"),
    ("metrics.gross_churn.overall_pct", "Gross churn"),
    ("metrics.arr.value", "Ending ARR"),
    ("metrics.acv_path.current_arr", "Ending ARR"),      # same figure, same name as the ARR tile
    ("metrics.acv_path.acv", "ACV (average contract value)"),
    ("metrics.cac_payback.quarters.2026-Q1.L1.months", "CAC payback"),
    ("metrics.nrr.by_segment.Enterprise.nrr_pct", "NRR"),
    ("metrics.cohort_retention.data.values.3", "Cohort MRR retained"),
    ("acv", "ACV (average contract value)"),          # bare leaf, also an accepted citation
    ("metrics.acv_path.overall_band", "Overall ACV band"),
])
def test_label_for_cited_paths(path, label):
    assert f.label_for(path) == label


def test_unmapped_path_degrades_to_a_readable_leaf_not_the_raw_path():
    assert f.explicit_label("metrics.acv_path.brand_new_field") is None
    assert f.label_for("metrics.acv_path.brand_new_field") == "Brand new field"


def test_every_numeric_engine_field_the_gateway_can_send_has_an_explicit_label():
    """Same engine runs as the display-kind coverage test: a new numeric field must get a
    readable name, not silently fall back to a humanised leaf."""
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

    def run(spec, drop=()):
        datasets, meta = demo_data.build(spec)
        norm = {t: server.normalize(server.df_to_records(df), t, m) for t, (df, m) in datasets.items()}
        for t in drop:
            norm[t] = norm[t].iloc[0:0] if isinstance(norm[t], pd.DataFrame) else pd.DataFrame()
        fx = {k.upper(): v for k, v in meta.get("fx", {}).items()}
        fx[spec["reporting_currency"].upper()] = 1.0
        cfg = {"reporting_currency": spec["reporting_currency"], "target_arr": spec["target_arr"],
               "target_date": spec["target_date"], "fx": fx, "billing_terms": {},
               "default_l": 1, "as_of_month": None}
        src = {t: {"file": meta[t]["file"], "sheet": meta[t]["sheet"]} for t in datasets}
        return server.sanitize(ge.compute_all(norm["revenue"], norm["crm"], norm["pnl"], cfg, src))

    def numeric_paths(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from numeric_paths(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for item in node:
                yield from numeric_paths(item, path)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            yield path

    unlabelled = set()
    for spec in demo_data.DEMO_AUDITS:
        for results in (run(spec), run(spec, drop=("pnl",)), run(spec, drop=("crm",)),
                        run({**spec, "months": 8}), run({**spec, "months": 14})):
            for step in gateway.STEP_CONFIG:
                metrics = gateway.strip_row_references(gateway._slice_for_step(results, step))
                for path in numeric_paths({"metrics": metrics}):
                    if f.explicit_label(path) is None:
                        unlabelled.add(path)
    assert sorted(unlabelled) == []


def test_row_labels_are_added_to_the_response_and_not_to_the_model_contract():
    from app.llm.schemas import Narrative, NarrativeResponse, TableRow, narrative_output_schema

    n = Narrative(
        headline="h", what_this_means="w",
        table_rows=[
            TableRow(label="metrics.acv_path.customers_needed", value="129",
                     source_key="metrics.acv_path.customers_needed"),
            TableRow(label="NRR", value="106%", source_key="metrics.nrr.overall_pct"),
        ],
    )
    resp = NarrativeResponse(run_id="r", step="growth_engine", narrative_status="ok", narrative=n)
    assert resp.row_labels == {
        "metrics.acv_path.customers_needed": "Total customers at target ARR (at current ACV)",
        "metrics.nrr.overall_pct": "NRR (trailing 12 months)",
    }
    # Citations are untouched, and the model is never asked for or sent labels.
    assert [r.source_key for r in resp.narrative.table_rows] == [
        "metrics.acv_path.customers_needed", "metrics.nrr.overall_pct"]
    assert "row_labels" not in json.dumps(narrative_output_schema())
    assert NarrativeResponse(run_id="r", step="s", narrative_status="unavailable").row_labels == {}


# ---------------------------------------------------------------------------
# Qualifiers: uniform bracket format, one wording for tile and table
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path,name", [
    ("metrics.nrr.overall_pct", "NRR (trailing 12 months)"),
    ("metrics.sales_cycle.median_days", "Median sales cycle (all won deals)"),
    ("metrics.gross_churn.overall_pct", "Gross churn (trailing 12 months)"),
    ("metrics.win_rate.win_rate_pct", "Win rate (closed deals)"),
    ("metrics.arr.value", "Ending ARR (latest month MRR × 12)"),
    ("metrics.cac_payback.months", "CAC payback (latest complete quarter)"),
    ("metrics.cac_payback.quarters.2026-Q1.L1.months", "CAC payback (2026-Q1)"),  # a named quarter says which
    ("metrics.acv_path.observed_net_new_per_year_12m", "Observed net-new customers per year (last 12 months)"),
    ("metrics.acv_path.total_customers_at_target", "Total customers at target ARR (at current ACV)"),
    ("metrics.acv_path.additional_customers_needed", "Additional customers needed (at current ACV)"),
    ("metrics.acv_path.customers_needed", "Total customers at target ARR (at current ACV)"),
])
def test_display_name_puts_the_qualifier_in_brackets(path, name):
    assert f.display_name(path) == name


def test_no_display_name_has_a_comma_before_its_bracket():
    for path in list(f.LABEL_BY_PATH) + list(f.QUALIFIER_BY_PATH):
        name = f.display_name(path)
        assert ", (" not in name and ",(" not in name, name
        assert name.count("(") == name.count(")"), name


def test_every_qualified_path_has_a_label():
    assert set(f.QUALIFIER_BY_PATH) <= set(f.LABEL_BY_PATH)


def test_frontend_metric_names_json_is_generated_from_the_backend_maps():
    """The tiles read metric_names.json; the table reads these maps. They must not drift."""
    path = Path(__file__).parents[2] / "frontend/src/lib/metric_names.json"
    assert json.loads(path.read_text("utf-8")) == f.metric_names_export(), (
        "frontend/src/lib/metric_names.json is stale - regenerate it with:\n"
        "  python -c \"import json; from app import formatting as f; "
        "open('../frontend/src/lib/metric_names.json','w').write("
        "json.dumps(f.metric_names_export(), indent=2, ensure_ascii=False)+chr(10))\""
    )


# Every tile on the dashboard, by the path it is looked up under in Dashboard.jsx.
TILE_PATHS = [
    "arr.value", "nrr.overall_pct", "gross_churn.overall_pct", "cac_payback.months",
    "sales_cycle.median_days", "win_rate.win_rate_pct",
    "current_customers", "current_arr", "acv", "total_customers_at_target", "additional_customers_needed",
]


@pytest.mark.parametrize("path", TILE_PATHS)
def test_every_tile_has_a_label_and_a_qualifier(path):
    assert f.explicit_label(path), path
    assert f.qualifier_for(path), f"a tile is read on its own; {path} needs a qualifier"


def test_nrr_and_churn_series_and_segments_carry_the_same_window():
    for path in ("metrics.nrr.by_segment.SMB.nrr_pct", "metrics.nrr.by_cohort.2025-Q1.nrr_pct",
                 "metrics.nrr.series.nrr_pct", "metrics.gross_churn.series.churn_pct"):
        assert f.qualifier_for(path) == "trailing 12 months", path


def test_days_carry_their_unit_and_the_unit_does_not_touch_the_rounding():
    assert f.fmt(f.DAYS, 42.1) == "43 days"
    assert f.fmt(f.DAYS, 42.0) == "42 days"
    assert f.fmt(f.DAYS, 0.4) == "1 day"          # rounds up first, then picks the unit
    assert f.fmt(f.DAYS, 1.0) == "1 day"
    assert f.fmt(f.DAYS, 1.01) == "2 days"
    assert f.fmt_days_number(42.1) == "43"        # bare number, for ranges
    # the number in the string is exactly what the bare rule gives
    for v in (0.2, 7.0, 42.1, 999.99, 1234.5):
        assert f.fmt(f.DAYS, v).split(" ")[0] == f.fmt_days_number(v)


# ---------------------------------------------------------------------------
# Segment paths: every field the engine can emit, on every branch, has a kind and a label
# ---------------------------------------------------------------------------
def test_every_segment_path_field_on_every_branch_has_a_display_kind_and_an_explicit_label():
    """The demo audits only reach the 'unreachable' branch. This runs the engine on the
    hand-built scenarios that reach the others (shift needed, no shift, target met by the
    base, undetermined, unavailable), so a field that appears only there is still covered."""
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).parents[1]))
    pytest.importorskip("pandas")
    import test_growth_engine as tge
    from app.llm import gateway

    _, years, base = tge._seg_paths(target_arr=1_000_000)
    branches = {
        "shift": tge._seg_paths(target_arr=base + 25_000 * 3 * years)[0],
        "no_shift": tge._seg_paths(target_arr=base + 15_000 * 3 * years)[0],
        "unreachable": tge._seg_paths(target_arr=base + 50_000 * 3 * years)[0],
        "met_by_base": tge._seg_paths(target_arr=50_000)[0],
        "undetermined": tge._seg_paths(target_arr=base + 10_000 * years, drop_b_landings=True)[0],
        "no_nrr_for_a_segment": tge._seg_paths(target_arr=1_000_000, only_new_segment=True)[0],
        "window_24_ok": tge._seg_paths(target_arr=base + 25_000 * 3 * years, n_months=26)[0],
        "unavailable": tge._seg_paths(target_arr=1_000_000, no_segments=True)[0],
    }
    unlabelled, unregistered = set(), set()

    def numeric_paths(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from numeric_paths(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for i in node:
                yield from numeric_paths(i, path)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            yield path

    for name, sp in branches.items():
        computed = {"reporting_currency": "EUR", "metrics": {"segment_paths": sp}}
        unregistered |= set(_unregistered(computed))
        unlabelled |= {p for p in numeric_paths({"metrics": {"segment_paths": sp}}) if f.explicit_label(p) is None}
        gateway.build_outbound(computed, {})          # raises if any numeric field has no kind
    assert sorted(unregistered) == []
    assert sorted(unlabelled) == []


def test_segment_path_figures_format_by_the_rules():
    out = f.format_payload({"metrics": {"segment_paths": {
        "horizon_months": 34.03, "gap_arr": 35112601.4, "landed": {"12": {"gross_new_per_year": 24.0}},
        "reverse_solve": {"12": {"new_customers_by_target": 68.05, "required_new_per_year_at_current_mix": 319.41,
                                 "required_vs_observed_gross": 13.31, "required_blended_landed_acv": 515946.03,
                                 "by_segment": {"A": {"current_mix_pct": 29.3, "shift_pct_points": -12.4}}}},
    }}}, "EUR")["metrics"]["segment_paths"]
    assert out["horizon_months"] == "34.0 months"
    assert out["gap_arr"] == "35,112,601 EUR"
    rs = out["reverse_solve"]["12"]
    assert rs["new_customers_by_target"] == "69"            # implied count rounds UP
    assert rs["required_new_per_year_at_current_mix"] == "320"   # required count rounds UP
    assert rs["required_vs_observed_gross"] == "13.31x"
    assert rs["by_segment"]["A"]["shift_pct_points"] == "-12%"
    assert out["landed"]["12"]["gross_new_per_year"] == "24"     # observed rate rounds normally


def test_every_name_the_segment_panel_looks_up_resolves_explicitly():
    """SegmentPaths.jsx takes its names from the shared map; none may fall through."""
    import re as _re
    src = (Path(__file__).parents[2] / "frontend/src/components/SegmentPaths.jsx").read_text("utf-8")
    labels = set(_re.findall(r'\bL\("([a-z_.]+)"\)', src))
    quals = set(_re.findall(r'\bQ\("([a-z_.]+)"\)', src))
    assert labels and quals
    assert [p for p in labels if f.explicit_label(p) is None] == []
    assert [p for p in quals if f.qualifier_for(p) is None] == []
    # and the panel says it is not a forecast in its heading
    assert "Constant-NRR projection (not a forecast)" in src


def test_total_and_additional_customers_are_named_apart_and_round_up():
    out = f.format_payload({"metrics": {"acv_path": {
        "current_customers": 58, "total_customers_at_target": 813.4191920515062,
        "additional_customers_needed": 755.4191920515062}}}, "EUR")["metrics"]["acv_path"]
    assert out["total_customers_at_target"] == "814" and out["additional_customers_needed"] == "756"
    assert int(out["total_customers_at_target"]) - int(out["current_customers"]) == int(out["additional_customers_needed"]), (
        "the rounded-up total minus today's count is the rounded-up additional count")
    # the names say which is which, wherever they are shown
    assert "Total" in f.display_name("metrics.acv_path.total_customers_at_target")
    assert f.display_name("metrics.acv_path.additional_customers_needed").startswith("Additional")
    assert "Additional" not in f.display_name("metrics.acv_path.customers_needed")
