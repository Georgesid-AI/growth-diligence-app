"""The two handoffs of docs/specs/interface-contracts.md: engine output -> LLM gateway, engine output -> xlsx export.

One model (schemas/metrics.py) describes the engine output. These tests run the real engine, pass its output through the
gateway's validator and the exporter, open the workbook, and fail when the engine writes a field the model does not
declare. Each failure case is a deliberate violation of the contract, shown to fail. No network, no MongoDB."""
import asyncio
import copy
import logging
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

import pytest

pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
pytest.importorskip("fastapi")
pytest.importorskip("motor")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import openpyxl  # noqa: E402
import pandas as pd  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import contract_fixtures as cf  # noqa: E402
import demo_data  # noqa: E402
import growth_engine as ge  # noqa: E402
import server  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from app import formatting as fmt  # noqa: E402
from app.llm import gateway  # noqa: E402
from schemas import metrics  # noqa: E402
from schemas.metrics import ContractError, MetricsPayload  # noqa: E402

SAMPLE = BACKEND.parent / "sample_data"
FILES = {"revenue": "revenue.csv", "pnl": "pnl.csv", "crm": "crm.csv"}
FIXED_SENTENCE = "Narrative could not be generated. The computed metrics below are unaffected."


# ---------------------------------------------------------------------------
# Real engine runs: the sample files, and the demo companies in their sparse variants
# ---------------------------------------------------------------------------
def _config(ccy="EUR", target_arr=1_000_000, target_date="2026-12-31", fx=None):
    return {"reporting_currency": ccy, "target_arr": target_arr, "target_date": target_date,
            "fx": fx or {ccy: 1.0}, "billing_terms": {}, "default_l": 1, "as_of_month": None}


@lru_cache(maxsize=None)
def _sample_raw() -> dict:
    uploads = {}
    for dtype, name in FILES.items():
        df, sheet = server.parse_file((SAMPLE / name).read_bytes(), name)
        uploads[dtype] = {"file": name, "sheet": sheet, "columns": list(df.columns), "rows": server.df_to_records(df),
                          "mapping": server.suggest_mapping(dtype, list(df.columns))}
    norm = {d: server.normalize(u["rows"], d, u["mapping"]) for d, u in uploads.items()}
    sources = {d: {"file": u["file"], "sheet": u["sheet"]} for d, u in uploads.items()}
    return ge.compute_all_raw(norm["revenue"], norm["crm"], norm["pnl"], _config(), sources,
                              files=server.candidate_views(uploads))


@lru_cache(maxsize=None)
def _demo_raws() -> dict:
    out = {}
    for i, spec in enumerate(demo_data.DEMO_AUDITS):
        datasets, meta = demo_data.build(spec)
        fx = {k.upper(): v for k, v in meta.get("fx", {}).items()}
        fx[spec["reporting_currency"].upper()] = 1.0
        sources = {d: {"file": meta[d]["file"], "sheet": meta[d]["sheet"]} for d in datasets}

        def run(spec=spec, datasets=datasets, drop=(), target_date=None, months=None, fx=fx, sources=sources):
            if months:
                datasets, _ = demo_data.build({**spec, "months": months})
            norm = {d: server.normalize(server.df_to_records(df), d, m) for d, (df, m) in datasets.items()}
            for d in drop:
                norm[d] = pd.DataFrame()
            cfg = _config(spec["reporting_currency"], spec["target_arr"], target_date or spec["target_date"], fx)
            return ge.compute_all_raw(norm["revenue"], norm["crm"], norm["pnl"], cfg, sources)

        out[f"demo{i}"] = run()
        out[f"demo{i}-no-pnl"] = run(drop=("pnl",))
        out[f"demo{i}-no-crm"] = run(drop=("crm",))
        out[f"demo{i}-bad-target-date"] = run(target_date="1999-01-01")
        out[f"demo{i}-8-months"] = run(months=8)
        out[f"demo{i}-14-months"] = run(months=14)
    return out


def all_raws() -> dict:
    return {"sample": _sample_raw(), **_demo_raws()}


RUNS = ["sample"] + [f"demo{i}{v}" for i in range(len(demo_data.DEMO_AUDITS))
                     for v in ("", "-no-pnl", "-no-crm", "-bad-target-date", "-8-months", "-14-months")]


def stored_form(raw: dict) -> dict:
    """What the server stores: the contract's build of the engine output, after sanitize."""
    return server.sanitize(metrics.build(raw))


def undeclared(raw: dict) -> list:
    """Key paths the engine wrote that MetricsPayload does not declare."""
    try:
        MetricsPayload.model_validate({"contract_version": metrics.CONTRACT_VERSION, **raw}, context={"conform": True})
    except ValidationError as exc:
        return sorted(".".join(str(p) for p in e["loc"]) for e in exc.errors() if e["type"] == "extra_forbidden")
    return []


# ---------------------------------------------------------------------------
# 1. The schema covers the engine
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("run", RUNS)
def test_every_engine_field_is_declared_in_the_schema_and_the_output_validates(run):
    raw = all_raws()[run]
    assert undeclared(raw) == [], "the engine writes fields that backend/schemas/metrics.py does not declare"
    stored = stored_form(raw)
    assert metrics.MetricsPayload.model_validate(stored)                      # the stored form validates strictly, no rounding
    assert stored["contract_version"] == metrics.CONTRACT_VERSION


def test_the_coverage_check_fails_when_the_engine_gains_a_field():
    """A deliberate violation: one new field in one block. If this passed, the check above would prove nothing."""
    raw = copy.deepcopy(_sample_raw())
    raw["nrr"]["brand_new_field"] = 1.0
    raw["segment_paths"]["stage_one"]["segments"]["Enterprise"]["another_new_field"] = 3
    assert undeclared(raw) == ["nrr.brand_new_field", "segment_paths.stage_one.segments.Enterprise.another_new_field"]


def test_the_sample_run_exercises_the_blocks_the_contract_exists_for():
    stored = stored_form(_sample_raw())
    for block in ("arr", "nrr", "gross_churn", "cac_payback", "sales_cycle", "win_rate", "acv_path", "segment_paths",
                  "revenue_series", "customers_series", "cohort_retention", "revenue_reconciliation"):
        assert stored[block], f"{block} is empty in the sample run: the contract test would not see it"


CITED_BLOCKS = ("arr", "nrr", "gross_churn", "cac_payback", "sales_cycle", "win_rate", "acv_path", "segment_paths",
                "anomalies", "mrr_series", "revenue_series", "customers_series", "cohort_retention")
CITATION_BESIDE_BLOCK = {"new_mrr_by_quarter": "new_mrr_by_quarter_source"}      # a dict keyed by quarter has no room for a key
NO_OWN_CITATION = {"revenue_reconciliation": "its months and its window carry both sides' citations",
                   "founder_win_rate": "optional twin of win_rate", "missing_data": "gaps, no figure",
                   "questions_for_management": "text, no figure", "contract_version": "", "reporting_currency": "",
                   "as_of_month": ""}


def test_every_block_with_a_figure_carries_a_citation_in_the_model_and_in_the_engine_output():
    """A block added without a citation, or listed nowhere here, fails: the decision is made when the block is added."""
    fields = set(MetricsPayload.model_fields)
    decided = set(CITED_BLOCKS) | set(CITATION_BESIDE_BLOCK) | set(CITATION_BESIDE_BLOCK.values()) | set(NO_OWN_CITATION)
    assert fields == decided, f"decide whether these blocks cite a source: {sorted(fields ^ decided)}"
    for run in ("sample", "demo0-no-pnl", "demo1-no-crm", "demo1-14-months"):
        stored = stored_form(all_raws()[run])
        for block in CITED_BLOCKS:
            if stored[block] is None:                              # a failed calculation is Missing, not cited
                continue
            assert stored[block]["source"]["rule"] and stored[block]["source"]["rows"], f"{run}: {block} has no citation"
        assert stored["new_mrr_by_quarter_source"]["rule"], run
    sample = stored_form(_sample_raw())
    for block in ("segment_paths", "mrr_series", "cohort_retention", "anomalies"):
        assert sample[block]["source"]["row_numbers"] and sample[block]["source"]["file"] == "revenue.csv", block
    assert sample["new_mrr_by_quarter_source"]["row_numbers"]
    assert sample["anomalies"]["deals_source"]["file"] == "crm.csv"
    assert "deals_source" not in stored_form(all_raws()["demo0-no-crm"])["anomalies"], "no CRM, no CRM citation"


def test_the_engine_rounds_counts_and_days_once_and_percents_are_fractions():
    s = stored_form(_sample_raw())
    assert isinstance(s["sales_cycle"]["median_days"], float), "days stay unrounded; the display and the export round up"
    assert isinstance(s["acv_path"]["total_customers_at_target"], int)
    assert isinstance(s["acv_path"]["required_net_new_per_year"], int)
    assert 0 < s["nrr"]["overall_pct"] < 10 and 0 <= s["win_rate"]["win_rate_pct"] <= 1
    assert all(0 <= v <= 10 for r in s["cohort_retention"]["data"] for v in r["values"].values())
    assert s["contract_version"] == 2 and s["reporting_currency"] == "EUR"


@pytest.mark.parametrize("model, value, expected", [
    (metrics.CountUp, 128.3, 129), (metrics.CountUp, 129.00000000001, 129), (metrics.CountUp, -3.2, -3),
    (metrics.Count, 2.5, 3), (metrics.Count, 2.4, 2)])
def test_the_engine_rounds_up_or_to_nearest_by_the_unit_of_the_field(model, value, expected):
    from pydantic import TypeAdapter
    assert TypeAdapter(model).validate_python(value, context={"conform": True}) == expected


@pytest.mark.parametrize("model", [metrics.Count, metrics.CountUp])
def test_a_stored_count_or_day_count_with_a_fraction_is_refused_not_rounded(model):
    from pydantic import TypeAdapter
    with pytest.raises(ValidationError):
        TypeAdapter(model).validate_python(42.5)


# ---------------------------------------------------------------------------
# 2. The gateway's validator and the exporter accept what the engine stores
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("run", RUNS)
def test_the_stored_output_passes_the_gateway_validator_and_the_exporter(run):
    stored = stored_form(all_raws()[run])
    assert gateway.contract_problems(stored) == []
    metrics.validate_for_export(stored)
    buf = server.build_export_workbook({"company_name": "Acme", "as_of_month": stored["as_of_month"]}, stored)
    assert openpyxl.load_workbook(buf).sheetnames[0] == "Headline"


# ---------------------------------------------------------------------------
# 3. The workbook shows the NRR as a whole percent, not "1%"
# ---------------------------------------------------------------------------
def _cell(wb, sheet, label):
    for row in wb[sheet].iter_rows(min_row=2):
        if row[0].value and str(row[0].value).startswith(label):
            return row[1]
    raise AssertionError(f"no row {label!r} on {sheet}")


def _excel_displays(cell) -> str:
    """What Excel shows for a numeric cell formatted "0%": the value times 100, to the nearest whole, with a %."""
    assert cell.number_format == "0%", cell.number_format
    return f"{int(cell.value * 100 + 0.5)}%"


class _Table(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None:
            self._row.append(" ".join(x for x in self._cell if x))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _libreoffice_shows(xlsx: bytes, label: str):
    """The text a spreadsheet application displays in the cell beside `label` on the first sheet (None: none installed)."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "e.xlsx").write_bytes(xlsx)
        subprocess.run([soffice, "--headless", "--norestore", f"-env:UserInstallation=file://{tmp}/profile",
                        "--convert-to", "html", "--outdir", tmp, str(Path(tmp) / "e.xlsx")],
                       check=True, capture_output=True, timeout=120, cwd=tmp)
        table = _Table()
        table.feed((Path(tmp) / "e.html").read_text(encoding="utf-8", errors="ignore"))
    return next(r[1] for r in table.rows if r and r[0] == label)


def test_the_nrr_cell_of_the_sample_run_displays_the_whole_percent_not_one_percent():
    stored = stored_form(_sample_raw())
    nrr = stored["nrr"]["overall_pct"]
    assert nrr == pytest.approx(1.1268)
    buf = server.build_export_workbook({"company_name": "Acme"}, stored)
    cell = _cell(openpyxl.load_workbook(buf), "Headline", "NRR overall")
    assert cell.value == pytest.approx(nrr), "the cell holds the fraction"
    assert _excel_displays(cell) == "113%" and _excel_displays(cell) != "1%"
    shown = _libreoffice_shows(buf.getvalue(), "NRR overall")
    if shown is not None:
        assert shown == "113%", f"a spreadsheet application shows {shown!r}"


def test_a_stored_nrr_of_1_0641_displays_106_percent():
    stored = cf.stored(nrr=cf.nrr(1.0641, 100), arr=cf.arr())
    buf = server.build_export_workbook({"company_name": "Acme"}, stored)
    cell = _cell(openpyxl.load_workbook(buf), "Headline", "NRR overall")
    assert _excel_displays(cell) == "106%"
    shown = _libreoffice_shows(buf.getvalue(), "NRR overall")
    if shown is not None:
        assert shown == "106%"


# ---------------------------------------------------------------------------
# 4. Violations: each one fails the gateway validator and the exporter (shown to fail)
# ---------------------------------------------------------------------------
def _sample_stored() -> dict:
    return stored_form(_sample_raw())


def _set(path, value):
    def mutate(p):
        node = p
        *head, last = path.split(".")
        for part in head:
            node = node[int(part)] if isinstance(node, list) else node[part]
        node[last] = value
        return p
    return mutate


def _drop(path):
    def mutate(p):
        node = p
        *head, last = path.split(".")
        for part in head:
            node = node[part]
        del node[last]
        return p
    return mutate


VIOLATIONS = {
    "nrr as a whole-number percent": _set("nrr.overall_pct", 112.68),
    "churn as a whole-number percent, above the range": _set("gross_churn.overall_pct", 35.0),
    "a fractional customer count": _set("acv_path.current_customers", 24.5),
    "a fractional required count": _set("acv_path.total_customers_at_target", 24.7),
    "a count as text": _set("nrr.nrr_base_customers", "5"),
    "a missing contract version": _drop("contract_version"),
    "a missing field": _drop("nrr.series"),
    "an undeclared field": _set("arr.extra", 1),
    "a percent as text": _set("win_rate.win_rate_pct", "40%"),
    "a number that is not finite": _set("arr.value", float("nan")),
    "segment_paths without a citation": _drop("segment_paths.source"),
    "new_mrr_by_quarter without a citation": _drop("new_mrr_by_quarter_source"),
    "cohort_retention without a citation": _drop("cohort_retention.source"),
    "mrr_series without a citation": _drop("mrr_series.source"),
    "anomalies without a citation": _drop("anomalies.source"),
    "a citation without its rule": _drop("mrr_series.source.rule"),
}


@pytest.mark.parametrize("name", list(VIOLATIONS))
def test_a_violation_fails_the_gateway_validator_and_the_exporter(name):
    good = _sample_stored()
    assert gateway.contract_problems(good) == [] and metrics.validate_for_export(good)
    bad = VIOLATIONS[name](copy.deepcopy(good))
    assert gateway.contract_problems(bad), f"the gateway accepts {name}"
    with pytest.raises(ContractError):
        server.build_export_workbook({"company_name": "Acme"}, bad)


def test_a_unit_slip_inside_the_range_is_what_the_contract_version_is_for():
    """A whole-number percent between 0 and 10 (churn 6.1 for 6.1%) cannot be told from a fraction by its size. The stored
    payload of the old engine has no contract_version, so it is refused whatever its values are."""
    old = copy.deepcopy(_sample_stored())
    del old["contract_version"]
    old["gross_churn"]["overall_pct"] = 6.1
    assert gateway.contract_problems(old)
    with pytest.raises(ContractError):
        metrics.validate_for_export(old)


@pytest.mark.parametrize("path, value, ok", [
    ("gross_churn.overall_pct", 10.0, True), ("gross_churn.overall_pct", 10.01, False), ("gross_churn.overall_pct", -0.01, False),
    ("nrr.overall_pct", -0.5, True), ("nrr.overall_pct", -10.5, False),                       # a credit note can sink NRR
    ("cac_payback.quarters.2023-Q1.gross_margin_pct", -0.3, True),                              # a loss-making quarter
    ("cac_payback.quarters.2023-Q1.gross_margin_pct", 71.2, False),
    ("revenue_reconciliation.gap_pct", 35.0, True)])                                            # a gap against the P&L is unbounded
def test_the_unit_check_bounds_each_percent_by_what_it_measures(path, value, ok):
    stored = _sample_stored()
    node = stored
    *head, last = path.split(".")
    for part in head:
        node = node[part]
    node[last] = value
    assert gateway.contract_problems(stored) == [] if ok else gateway.contract_problems(stored)


def test_the_export_writes_no_file_on_a_violation_and_says_which_field():
    bad = VIOLATIONS["nrr as a whole-number percent"](copy.deepcopy(_sample_stored()))
    with pytest.raises(ContractError) as exc:
        server.build_export_workbook({"company_name": "Acme"}, bad)
    assert "nrr.overall_pct" in str(exc.value) and "112.68" in str(exc.value)
    assert "112.68" not in exc.value.log_text and "overall_pct" in exc.value.log_text, "the log text names fields, no value"
    with pytest.raises(fmt.UnitError):
        fmt.xlsx_value(fmt.PCT, 112.68)           # and no path around the model writes the cell


# ---------------------------------------------------------------------------
# 5. The gateway: a bad payload makes no model call and the metrics still come back
# ---------------------------------------------------------------------------
def _db_with(results):
    db = t.make_db()
    db["audits"].docs[0]["results"] = results
    return db


def _generate(db):
    adapter = t.FakeAdapter()
    result = asyncio.run(gateway.generate_narrative(db, t.RUN_ID, "growth_engine", adapter=adapter, sleep=t._noop_sleep))
    return result, adapter


def test_the_gateway_does_not_call_the_model_on_a_payload_that_breaks_the_contract():
    good_db = _db_with(cf.stored(arr=cf.arr(), nrr=cf.nrr(1.042), gross_churn=cf.gross_churn(0.061), win_rate=cf.win_rate()))
    ok, adapter = _generate(good_db)
    assert ok.narrative_status == "ok" and adapter.calls == 1, "the same payload, unbroken, is read"
    for broken in (cf.broken(good_db["audits"].docs[0]["results"], "nrr.overall_pct", 104.2),
                   cf.broken(good_db["audits"].docs[0]["results"], "contract_version", drop=True),
                   cf.broken(good_db["audits"].docs[0]["results"], "win_rate.won", 26.9)):
        result, adapter = _generate(_db_with(broken))
        assert adapter.calls == 0, "no model call"
        assert (result.narrative_status, result.reason) == ("unavailable", FIXED_SENTENCE)
        assert result.narrative is None


def test_the_metrics_still_come_back_with_their_citation_when_the_narrative_cannot_be_generated():
    stored = cf.broken(cf.stored(arr=cf.arr(), nrr=cf.nrr(1.042)), "nrr.overall_pct", 104.2)
    result, adapter = _generate(_db_with(stored))
    assert result.metrics["nrr"]["overall_pct"] == 104.2 and result.metrics["nrr"]["source"]["rows"]
    assert result.metrics["arr"]["value"] == 3129600.0 and result.metrics["arr"]["source"]["rule"]
    assert adapter.calls == 0


def test_a_read_of_the_cached_narrative_checks_the_contract_too():
    stored = cf.broken(cf.stored(arr=cf.arr(), nrr=cf.nrr(1.042)), "contract_version", drop=True)
    result = asyncio.run(gateway.read_cached_narrative(_db_with(stored), t.RUN_ID, "growth_engine"))
    assert (result.narrative_status, result.reason) == ("unavailable", FIXED_SENTENCE) and result.metrics["arr"]


def test_the_gateway_logs_the_violation_with_paths_and_types_and_no_value(caplog):
    stored = cf.broken(cf.stored(arr=cf.arr(), nrr=cf.nrr(1.042, by_segment={"Zeta Holdings": cf.nrr_group(1.1)})),
                       "nrr.by_segment.Zeta Holdings.nrr_base_customers", "Zeta Holdings 4242 secret")
    with caplog.at_level(logging.INFO):
        _generate(_db_with(stored))
    line = next(r.getMessage() for r in caplog.records if "metrics contract violated" in r.getMessage())
    assert "nrr.by_segment.*.nrr_base_customers" in line, "the segment's name is not in the path"
    assert "Zeta" not in caplog.text and "4242" not in caplog.text and "secret" not in caplog.text


# ---------------------------------------------------------------------------
# 6. Results stored before the contract are recomputed on read, never shown 100 times too large
# ---------------------------------------------------------------------------
OLD_RESULTS = {"reporting_currency": "EUR", "nrr": {"overall_pct": 106.41, "n": 100}}
AUDIT_ID = "audit-1"


@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient
    db = t.FakeDB()
    db["audits"].docs.append({"id": AUDIT_ID, "company_name": "Acme", "reporting_currency": "EUR", "status": "computed",
                              "results": copy.deepcopy(OLD_RESULTS)})
    monkeypatch.setattr(server, "db", db)
    calls = []

    async def recompute(audit_id):
        calls.append(audit_id)
        return cf.stored(nrr=cf.nrr(1.0641, 100), arr=cf.arr())

    monkeypatch.setattr(server, "_run_compute", recompute)
    client = TestClient(server.app, raise_server_exceptions=False)
    client.db, client.recomputed = db, calls
    return client


def test_old_results_are_recomputed_on_the_first_read(api):
    r = api.get(f"/api/audits/{AUDIT_ID}/results")
    assert r.status_code == 200 and api.recomputed == [AUDIT_ID]
    assert r.json()["results"]["nrr"]["overall_pct"] == 1.0641 and r.json()["results"]["contract_version"] == 2


def test_results_stored_before_the_citations_were_added_are_recomputed_on_the_first_read(api):
    """Version 1 results have no citation on five blocks: they would fail the gateway and the export, so they are recomputed."""
    api.db["audits"].docs[0]["results"] = {**cf.stored(nrr=cf.nrr(1.0641, 100)), "contract_version": 1}
    r = api.get(f"/api/audits/{AUDIT_ID}/results")
    assert r.status_code == 200 and api.recomputed == [AUDIT_ID] and r.json()["results"]["contract_version"] == 2


def test_the_narrative_endpoints_recompute_old_results_before_the_gateway_reads_them(api):
    api.get(f"/api/runs/{AUDIT_ID}/narrative/growth_engine")
    assert api.recomputed == [AUDIT_ID]
    api.recomputed.clear()
    api.post(f"/api/runs/{AUDIT_ID}/narrative/growth_engine")
    assert api.recomputed == [AUDIT_ID]


def test_current_results_are_not_recomputed(api):
    api.db["audits"].docs[0]["results"] = cf.stored(nrr=cf.nrr(1.0641, 100))
    assert api.get(f"/api/audits/{AUDIT_ID}/results").status_code == 200 and api.recomputed == []


def test_old_results_that_cannot_be_recomputed_are_refused_not_shown(api, monkeypatch):
    async def cannot(audit_id):
        raise server.HTTPException(409, "A required field is not mapped")

    monkeypatch.setattr(server, "_run_compute", cannot)
    r = api.get(f"/api/audits/{AUDIT_ID}/results")
    assert r.status_code == 409 and "106.41" not in r.text and "predate the current engine contract" in r.text
    assert api.get(f"/api/audits/{AUDIT_ID}/export").status_code == 409


def test_the_banner_keeps_working_when_old_results_cannot_be_recomputed(api, monkeypatch):
    async def cannot(audit_id):
        raise server.HTTPException(409, "A required field is not mapped")

    monkeypatch.setattr(server, "_run_compute", cannot)
    r = api.get(f"/api/audits/{AUDIT_ID}/blockers")
    assert r.status_code == 200 and [b["kind"] for b in r.json()["blockers"]] == ["revenue_file_missing"]


def test_the_export_endpoint_answers_with_the_reason_and_no_workbook_on_a_violation(api, caplog):
    api.db["audits"].docs[0]["results"] = cf.broken(cf.stored(nrr=cf.nrr(1.042), arr=cf.arr()), "nrr.overall_pct", 104.2)
    with caplog.at_level(logging.INFO):
        r = api.get(f"/api/audits/{AUDIT_ID}/export")
    assert r.status_code == 500 and "Export blocked, no file written" in r.json()["detail"]
    assert "nrr.overall_pct" in r.json()["detail"] and "spreadsheetml" not in r.headers.get("content-type", "")
    assert "export blocked" in caplog.text and "104.2" not in caplog.text


# ---------------------------------------------------------------------------
# 7. One table of units: the formatter reads the schema
# ---------------------------------------------------------------------------
def test_the_formatters_kind_table_is_the_schemas_with_one_stated_exception():
    by_name, by_parent, ambiguous = metrics.kinds_by_name()
    assert set(ambiguous) == {"total"}, f"a name now means two units: {ambiguous}"
    assert fmt.KIND_BY_KEY == {**by_name, "total": fmt.CURRENCY} and fmt.KIND_BY_PARENT == by_parent
    assert by_name["nrr_pct"] == fmt.PCT and by_name["median_days"] == fmt.DAYS and by_name["current_customers"] == fmt.COUNT


def test_every_numeric_leaf_of_a_stored_payload_has_a_display_kind():
    for run in ("sample", "demo0-no-pnl", "demo1-14-months"):
        stored = {k: v for k, v in stored_form(all_raws()[run]).items() if k != "contract_version"}   # server-only, in no slice
        leaves = {(k, parent) for k, parent, _ in _leaves(stored)}
        missing = sorted(k for k, parent in leaves if not (fmt.KIND_BY_KEY.get(k) or fmt.KIND_BY_PARENT.get(parent))
                         and k not in _SEGMENT_NAMED_LEAVES(stored))
        assert missing == [], run


def _leaves(node, key=None, parent=None):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _leaves(v, k, key)
    elif isinstance(node, list):
        for v in node:
            yield from _leaves(v, key, parent)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield key, parent, node


def _SEGMENT_NAMED_LEAVES(stored):
    """A monthly row holds one amount per segment under the segment's own name: data, not a field."""
    return set(stored["mrr_series"]["segments"]) | set(stored["customers_series"]["segments"])


def test_a_new_unit_type_without_a_display_kind_is_caught():
    """The kinds in the schema are the formatter's kinds: a unit the formatter cannot show fails here, not in production."""
    kinds = {u.kind for cls in metrics._all_models() for f in cls.model_fields.values() if (u := metrics._field_unit(f))}
    assert kinds <= set(fmt.XLSX_NUMBER_FORMAT), kinds - set(fmt.XLSX_NUMBER_FORMAT)


def test_sales_cycle_days_are_stored_unrounded_and_rounded_up_by_the_export_and_the_display():
    stored = _sample_stored()
    median = stored["sales_cycle"]["median_days"]
    assert median == 58.5, "claim matching reads this value"
    cell = _cell(openpyxl.load_workbook(server.build_export_workbook({"company_name": "Acme"}, stored)), "Headline", "Median sales cycle")
    assert cell.value == 59 and fmt.fmt_days(median) == "59 days"


# ---------------------------------------------------------------------------
# 8. Verdict and IC memo (docs/specs/verdict-and-memo.md section 9)
# ---------------------------------------------------------------------------
import typing  # noqa: E402

from pydantic import BaseModel  # noqa: E402

import test_ic_memo as icm  # noqa: E402
from app import claim_matching as cm  # noqa: E402
from app import ic_memo  # noqa: E402


def _declared(model, parts) -> bool:
    """Whether a source-key path is a path MetricsPayload declares: `*` stands for a data key, a list is transparent."""
    if not parts:
        return True
    head, *rest = parts
    if head in model.model_fields:
        return _declared_in(model.model_fields[head].annotation, rest)
    return model.model_config.get("extra") == "allow" and head == "*" and not rest      # a segment's own amount


def _declared_in(annotation, rest) -> bool:
    if not rest:
        return True
    origin = typing.get_origin(annotation)
    if origin is typing.Union:                                    # Optional[...]
        return any(_declared_in(arg, rest) for arg in typing.get_args(annotation))
    if origin is typing.Annotated:
        return _declared_in(typing.get_args(annotation)[0], rest)
    if origin is dict:                                            # the key is data: `*`
        return rest[0] == "*" and _declared_in(typing.get_args(annotation)[1], rest[1:])
    if origin is list:                                            # a list is transparent
        return _declared_in(typing.get_args(annotation)[0], rest)
    return isinstance(annotation, type) and issubclass(annotation, BaseModel) and _declared(annotation, rest)


def _pattern(key: str) -> str:
    return key.replace("{seg}", "*").replace("{q}", "*").replace("{l}", "1")


def test_every_source_key_of_the_memos_evidence_table_is_a_path_the_model_declares():
    for metric, (_, whole, by_segment) in cm.EVIDENCE.items():
        for key in filter(None, (whole, by_segment)):
            assert _declared(MetricsPayload, _pattern(key).split(".")), f"{metric}: {key} is not declared by MetricsPayload"
    assert set(cm.EVIDENCE) == set(cm.METRICS), "every metric of the register has an evidence row"


def test_a_wrong_source_key_is_caught_by_the_declared_path_check():
    """A deliberate violation: if this passed, the check above would prove nothing."""
    for bad in ("nrr.series.nrr", "mrr_series.data.total.extra", "nrr.by_segment.nrr_pct", "arr.value.x", "gross_churn.series.churn_percent"):
        assert not _declared(MetricsPayload, bad.split(".")), bad
    assert _declared(MetricsPayload, "nrr.by_segment.*.nrr_pct".split("."))


def test_a_memo_is_built_from_the_sample_data_engine_run_and_every_figure_in_it_is_in_the_stored_results():
    stored = copy.deepcopy(_sample_stored())
    meta = {"company_name": "TestCo", "as_of_month": stored["as_of_month"], "results": stored}
    tables = ic_memo.workbook_tables(server.build_export_workbook(meta, stored))          # Appendix C: the export's own tables
    assert {t["sheet"] for t in tables} >= {"Headline", "By Segment", "CAC by Quarter", "Path to Plan", "Segment Base", "Anomalies"}
    assert "Missing Data" not in {t["sheet"] for t in tables}
    kw = icm.inputs(stored=stored, tables=tables)
    text = ic_memo.build_memo(**kw)
    assert "## Appendix D" in text and ic_memo.word_count_of(text) <= 1500
    assert "81,431" in text, "a total the export derives from the stored results is in Appendix C"
    assert f"ARR {fmt.fmt_currency(stored['arr']['value'], 'EUR')}" in text


def test_nrr_written_as_106_41_refuses_the_memo_and_names_the_field():
    stored = _set("nrr.overall_pct", 106.41)(copy.deepcopy(_sample_stored()))
    kw = icm.inputs(stored=stored)
    with pytest.raises(ic_memo.MemoRefused) as exc:
        ic_memo.build_memo(**kw)
    assert exc.value.code == "contract" and "nrr.overall_pct" in exc.value.message and "106.41" not in exc.value.message


@pytest.mark.parametrize("run", RUNS)
def test_a_memo_is_built_from_every_engine_run_the_contract_covers_with_no_false_refusal(run):
    """The number check must not refuse a figure the engine stored or the export's own tables derive: the sample run, both demo
    companies and their sparse variants (no P&L, no CRM, 8 and 14 months, a bad target date)."""
    from test_claim_matching import RUNS as CLAIM_RUNS, candidates_for, settings
    from app import verdict as vd
    stored = copy.deepcopy(stored_form(all_raws()[run]))
    tables = ic_memo.workbook_tables(server.build_export_workbook({"company_name": "TestCo", "results": stored}, stored))
    base = CLAIM_RUNS["A"]
    cands = candidates_for(base)
    sets = {**settings(base), "as_of_month": None}
    top = vd.proposal(cm.build_register(cands, stored, sets))
    for c in cands:
        for cid in top:
            if cid.split("#")[0] == c["id"]:
                c.setdefault("claim_inputs", {}).setdefault(cid, {}).update({
                    "gate_threshold": 5.0, "gate_budget_decision": "the plan", "gate_date": "2030-01-01", "gate_metric_name": "Pipeline",
                    "gate_direction": "at least", "key_gate": True})
    rows = cm.build_register(cands, stored, sets)
    state = vd.top5_state(rows, {"claim_ids": top})
    text = ic_memo.build_memo(
        audit={"company_name": "TestCo", "target_arr": 1e6, "target_date": "2026-12-31", "as_of_month": stored["as_of_month"]},
        results=stored, rows=rows, ver=vd.verdict(rows, stored, {"claim_ids": top}), key=vd.key_gates(rows),
        gaps=vd.data_gaps(stored, rows, state["in_force"]), ic={"ratings": icm.RATINGS, "thesis": {"plan": "p", "evidence": "e", "condition": "c"}},
        blockers=[], narratives=[], usage=icm.USAGE, files=icm.FILES, decks=icm.DECKS, tables=tables, today="2026-10-08")
    assert ic_memo.word_count_of(text) <= 1500 and "## Appendix D" in text
