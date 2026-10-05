"""The gateway's data boundary: what may leave the server, and what never does.

The outbound payload is built from an allowlist. File and sheet names, column
headers and raw cell values stay in Mongo for the dashboard; segment names go
out as stable labels and come back as real names. Every test runs against the
in-memory Mongo stub and the fake adapter - no test can reach a real provider.
"""
import asyncio
import copy
import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app.llm import gateway, redaction  # noqa: E402
import test_llm_gateway as t  # noqa: E402

RUN_ID = t.RUN_ID
FILE = "Revenue_Lines.xlsx"
SHEET = "Billing"
PERSON = "Jane Doe (CEO)"                     # a raw cell value from the founder-involved column
HEADERS = ("Deal Opened On", "Signed Date")   # column headers in the upload

SOURCE = {"file": FILE, "sheet": SHEET, "rows": "rows 2–40 (39 rows)", "row_numbers": [2, 3, 4],
          "rule": "ARR = current-month recurring MRR × 12"}

RESULTS = {
    "as_of_month": "2026-12",
    "reporting_currency": "EUR",
    "arr": {"value": 3129600, "mrr": 260800, "month": "2026-12", "source": SOURCE},
    "nrr": {"overall_pct": 104.0, "nrr_base_customers": 110, "month": "2026-12", "trailing_window_months": 12,
            "by_segment": {"Enterprise": {"nrr_pct": 112.0, "nrr_base_customers": 40},
                           "Mid-Market": {"nrr_pct": 96.0, "nrr_base_customers": 70}},
            "source": {**SOURCE, "rule": "NRR = base-cohort MRR now ÷ MRR 12 months ago"}},
    "win_rate": {"won": 30, "lost": 70, "win_rate_pct": 30.0,
                 "founder_involved_excluded": {"count": 1, "rows": [7], "values": [PERSON]},
                 "source": {"file": "CRM_Deals.csv", "sheet": "Deals", "rule": "Win rate = won ÷ (won + lost)"}},
    "sales_cycle": {"median_days": 45, "n": 30, "status": "Computed - management to explain",
                    "source": {"file": FILE, "sheet": SHEET, "rule": "Median days from created to close",
                               "dataset": "revenue",
                               "columns": {"created_date": HEADERS[0], "close_date": HEADERS[1]}}},
    "segment_paths": {"available": True, "stage_one": {"segments": {
        "Enterprise": {"start_arr": 2000000, "customers": 40},
        "Mid-Market": {"start_arr": 1129600, "customers": 70}}},
        "reverse_solve": {"12": {"window_months": 12, "best_segment": "Enterprise",
                                 "reason": "no landed ACV for Mid-Market"}}},
    "missing_data": [{"metric": "CRM rows with unrecognized founder-involved value", "status": "Missing",
                      "reason": f"1 row(s) have a founder-involved value that isn't yes/no-like ({PERSON})",
                      "unlocked_by": "Use a yes/no style value", "file": "CRM_Deals.csv"}],
    "questions_for_management": [{
        "metric": "Sales cycle", "status": "Computed - management to explain", "result_key": "sales_cycle",
        "dataset": "revenue", "file": FILE,
        "columns": {"created_date": HEADERS[0], "close_date": HEADERS[1]},
        "question": (f"Sales cycle was computed from the revenue upload (created_date = '{HEADERS[0]}', "
                     f"close_date = '{HEADERS[1]}') because it was not available from the crm upload."),
    }],
}

NARRATIVE = {
    "headline": "Segment A retains 112% of its revenue over twelve months.",
    "what_this_means": "Segment A expands while Segment B contracts.",
    "table_rows": [{"label": "Segment A NRR", "value": "112%",
                    "source_key": "metrics.nrr.by_segment.Segment A.nrr_pct"}],
    "worth_flagging": ["Segment B is at 96%."],
    "next_actions": ["Ask why Segment B churns."],
    "source_keys": ["metrics.nrr.by_segment"],
}


def _db():
    db = t.FakeDB()
    doc = copy.deepcopy(t.RESULTS_DOC)
    doc["results"] = copy.deepcopy(RESULTS)
    db["audits"].docs.append(doc)
    return db


def _generate(db, reply=NARRATIVE):
    adapter = t.FakeAdapter(replies=[json.dumps(reply)])
    result = asyncio.run(gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=adapter, sleep=t._noop_sleep))
    assert adapter.calls == 1
    return result, json.loads(adapter.payloads[0])


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for i in node:
            yield from _keys(i)


def test_outbound_payload_has_no_file_sheet_header_or_raw_cell_value():
    db = _db()
    _, sent = _generate(db)
    blob = json.dumps(sent, ensure_ascii=False)
    for secret in (FILE, "CRM_Deals.csv", SHEET, "Deals", *HEADERS, PERSON, "Jane Doe"):
        assert secret not in blob, f"{secret!r} reached the provider"
    keys = set(_keys(sent))
    for dropped in ("file", "sheet", "columns", "rows", "row_numbers", "unlocked_by", "run_id", "computed_at"):
        assert dropped not in keys, dropped
    assert "values" not in sent["metrics"]["win_rate"]["founder_involved_excluded"]
    # What the model needs is still there.
    assert sent["metrics"]["arr"]["source"] == {"rule": "ARR = current-month recurring MRR × 12"}
    assert sent["metrics"]["win_rate"]["founder_involved_excluded"]["count"] == "1"
    question = sent["metrics"]["questions_for_management"][0]["question"]
    assert "close_date, created_date" in question and "revenue upload" in question
    assert sent["metrics"]["missing_data"][0]["reason"] == (
        "1 row(s) have a founder_involved value that isn't yes/no-like — excluded from the founder split, not guessed")


def test_full_versions_stay_in_mongo_for_the_dashboard():
    db = _db()
    _generate(db)
    stored = db["audits"].docs[0]["results"]
    assert stored == RESULTS
    assert HEADERS[0] in stored["questions_for_management"][0]["question"]


def test_segment_names_are_labelled_outbound_and_restored_in_the_reply():
    db = _db()
    result, sent = _generate(db)
    blob = json.dumps(sent)
    assert "Enterprise" not in blob and "Mid-Market" not in blob
    assert set(sent["metrics"]["nrr"]["by_segment"]) == {"Segment A", "Segment B"}
    assert set(sent["metrics"]["segment_paths"]["stage_one"]["segments"]) == {"Segment A", "Segment B"}
    assert sent["metrics"]["segment_paths"]["reverse_solve"]["12"]["best_segment"] == "Segment A"
    assert sent["metrics"]["segment_paths"]["reverse_solve"]["12"]["reason"] == "no landed ACV for Segment B"

    assert result.narrative_status == "ok", result.reason
    n = result.narrative
    assert n.headline == "Enterprise retains 112% of its revenue over twelve months."
    assert n.what_this_means == "Enterprise expands while Mid-Market contracts."
    assert n.table_rows[0].label == "Enterprise NRR"
    assert n.table_rows[0].source_key == "metrics.nrr.by_segment.Enterprise.nrr_pct"
    assert n.worth_flagging == ["Mid-Market is at 96%."]


def test_segment_labels_are_stable_for_a_run():
    db = _db()
    computed = asyncio.run(gateway.load_computed_results(db, RUN_ID, "growth_engine"))
    first = asyncio.run(redaction.get_or_create_map(db, RUN_ID, computed))
    second = asyncio.run(redaction.get_or_create_map(db, RUN_ID, computed))
    assert first == second
    assert first["Enterprise"] == "Segment A" and first["Mid-Market"] == "Segment B"


def test_identifier_12_never_changes_a_date_or_a_number():
    mapping = {"12": "Customer_01", "Acme": "Customer_02"}
    payload = {"month": "2026-12", "target_date": "2027-12-31", "trailing_window_months": "12",
               "value": "1,212 EUR", "nrr_pct": "112%", "ratio": "1.12x", "window": "12-month NRR",
               "reason": "Acme churned in 2026-12", "series": ["12", "2026-12"], "n": 12}
    out = redaction.redact(payload, mapping)
    assert out == {**payload, "reason": "Customer_02 churned in 2026-12"}
    assert redaction.substitute("2026-12", mapping) == "2026-12"
    assert redaction.find_leaks(out, mapping) == []


def test_field_name_keys_are_never_rewritten():
    mapping = {"arr": "Customer_01", "value": "Customer_02"}
    payload = {"arr": {"value": "1 EUR"}, "by_segment": {"arr": {"value": "2 EUR"}}}
    out = redaction.redact(payload, mapping)
    assert set(out) == {"arr", "by_segment"} and set(out["arr"]) == {"value"}
    assert set(out["by_segment"]) == {"Customer_01"}, "only segment-container keys are data"


def test_word_boundary_matching_does_not_touch_longer_words():
    mapping = {"Acme": "Customer_01"}
    assert redaction.substitute("Acme, Acmes and AcmeCorp", mapping) == "Customer_01, Acmes and AcmeCorp"
    assert redaction.restore("Customer_01 and Customer_010", {"Acme": "Customer_01"}) == "Acme and Customer_010"


def test_numeric_guard_allowed_set_is_unchanged_by_redaction():
    db = _db()
    computed = asyncio.run(gateway.load_computed_results(db, RUN_ID, "growth_engine"))
    mapping = {**asyncio.run(redaction.get_or_create_map(db, RUN_ID, computed)), "12": "Customer_01"}
    windows = gateway.STEP_CONFIG["growth_engine"]["windows"]
    plain = gateway.build_outbound(computed, {})
    redacted = gateway.build_outbound(computed, mapping)
    assert redacted != plain, "segments were relabelled"
    assert gateway.allowed_numerals(redacted, windows) == gateway.allowed_numerals(plain, windows)
    assert gateway.allowed_numerals(redaction.redact(plain, mapping), windows) == gateway.allowed_numerals(plain, windows)


def test_demo_upload_leaks_no_file_sheet_header_or_cell_value():
    """A real engine run over the demo upload, renamed to carry identifying strings."""
    pytest.importorskip("pandas")
    pytest.importorskip("fastapi")
    pytest.importorskip("motor")
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "data_boundary_test")
    import demo_data
    import growth_engine as ge
    import server

    file, sheet, header, cell = "Acme_Revenue.xlsx", "Acme Data", "Acme Segment", "Jane Doe (CEO)"
    spec = demo_data.DEMO_AUDITS[0]
    datasets, meta = demo_data.build(spec)
    uploads = {}
    for dtype, (df, mapping) in datasets.items():
        rows, mapping = server.df_to_records(df), dict(mapping)
        if dtype == "revenue":
            for r in rows:
                r[header] = r.pop(mapping["segment"])
            mapping["segment"] = header
            rows[0][mapping["currency"]] = cell            # a currency cell the engine quotes in a reason
        if dtype == "crm":
            rows[0][mapping["founder_involved"]] = cell    # a founder cell the engine quotes in a reason
        name, tab = (file, sheet) if dtype == "revenue" else (meta[dtype]["file"], meta[dtype]["sheet"])
        uploads[dtype] = {"file": name, "sheet": tab, "columns": list(rows[0]), "rows": rows, "mapping": mapping}

    norm = {d: server.normalize(u["rows"], d, u["mapping"]) for d, u in uploads.items()}
    fx = {k.upper(): v for k, v in meta.get("fx", {}).items()}
    fx[spec["reporting_currency"].upper()] = 1.0
    cfg = {"reporting_currency": spec["reporting_currency"], "target_arr": spec["target_arr"],
           "target_date": spec["target_date"], "fx": fx, "billing_terms": {}, "default_l": 1, "as_of_month": None}
    sources = {d: {"file": u["file"], "sheet": u["sheet"]} for d, u in uploads.items()}
    results = server.sanitize(ge.compute_all(norm["revenue"], norm["crm"], norm["pnl"], cfg, sources,
                                             files=server.candidate_views(uploads)))

    stored = json.dumps(results, ensure_ascii=False).lower()
    # The header is stored only when a management question cites it; that path is covered above.
    for needle in (file, sheet, cell):
        assert needle.lower() in stored, f"fixture did not exercise {needle!r}"

    db = t.FakeDB()
    db["audits"].docs.append({"id": RUN_ID, "results": results, "reporting_currency": spec["reporting_currency"],
                              "target_arr": spec["target_arr"], "target_date": spec["target_date"]})
    adapter = t.FakeAdapter()
    asyncio.run(gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=adapter, sleep=t._noop_sleep))
    assert adapter.calls == 1
    sent = adapter.payloads[0].lower()
    for needle in (file, sheet, header, cell, "jane doe", "acme"):
        assert needle.lower() not in sent, f"{needle!r} reached the provider"
    assert json.dumps(db["audits"].docs[0]["results"], ensure_ascii=False).lower() == stored, "Mongo keeps the full text"


# ---------------------------------------------------------------------------
# Boundary invariants (CLAUDE.md rule 14). What may reach the model or the logs
# is enforced here, not in review. A PR that adds a results key, a reason string,
# a log line or a guard word extends the lists in this section.
# ---------------------------------------------------------------------------
import ast  # noqa: E402
import re  # noqa: E402

import test_narrative_model_guard as guard_t  # noqa: E402

SENTINEL = "JANEDOE"            # written into one cell of every mapped column
HEADER_SENTINEL = "Jane Doe"    # every mapped column header is renamed to carry it

# Results keys the engine writes that never leave the server. A key that is in
# neither this set nor gateway.OUTBOUND_FIELDS fails test_every_results_key_is_
# allowlisted_or_declared_server_only: decide where it belongs when you add it.
SERVER_ONLY_TOP_LEVEL = frozenset({"anomalies", "mrr_series", "new_mrr_by_quarter"})
SERVER_ONLY_FIELDS = frozenset({
    "file", "sheet", "columns", "rows", "row_numbers", "unlocked_by",
    "values",                       # founder_involved_excluded.values are raw cells (cohort `data.values` is allowed by parent)
    "value_label",                  # acv_path.overall_band: display string, dashboard only
    "required_vs_observed_12m_reason", "required_vs_observed_24m_reason",   # acv_path: not yet allowlisted
})

# (file, function) of log calls that may carry a traceback. Empty: every log call carries error
# type, run id and engine step only, since an exception message or traceback can quote uploaded cells.
TRACEBACK_ALLOWED = frozenset()


def _engine_results(spec, inject: bool) -> dict:
    """A real engine run over a demo upload. With `inject`, one cell per mapped column and
    every mapped header carry a sentinel, so any reason or metric name that quotes upload
    content shows it."""
    import demo_data
    import growth_engine as ge
    import server

    datasets, meta = demo_data.build(spec)
    uploads = {}
    for dtype, (df, mapping) in datasets.items():
        rows, mapping = server.df_to_records(df), dict(mapping)
        if inject:
            for i, col in enumerate(c for c in mapping.values() if c):
                rows[i][col] = f"{SENTINEL} {col}"                # row i, column i: the other cells stay valid
            for field, col in list(mapping.items()):
                if col:
                    mapping[field] = f"{HEADER_SENTINEL} {field}"
                    for r in rows:
                        r[mapping[field]] = r.pop(col)
        uploads[dtype] = {"file": meta[dtype]["file"], "sheet": meta[dtype]["sheet"],
                          "columns": list(rows[0]), "rows": rows, "mapping": mapping}
    norm = {d: server.normalize(u["rows"], d, u["mapping"]) for d, u in uploads.items()}
    fx = {k.upper(): v for k, v in meta.get("fx", {}).items()}
    fx[spec["reporting_currency"].upper()] = 1.0
    cfg = {"reporting_currency": spec["reporting_currency"], "target_arr": spec["target_arr"],
           "target_date": spec["target_date"], "fx": fx, "billing_terms": {}, "default_l": 1, "as_of_month": None}
    sources = {d: {"file": u["file"], "sheet": u["sheet"]} for d, u in uploads.items()}
    return server.sanitize(ge.compute_all(norm["revenue"], norm["crm"], norm["pnl"], cfg, sources,
                                          files=server.candidate_views(uploads)))


@pytest.fixture(scope="module")
def engine_runs():
    pytest.importorskip("pandas")
    pytest.importorskip("fastapi")
    pytest.importorskip("motor")
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "data_boundary_test")
    import demo_data
    return [(spec, inject, _engine_results(spec, inject)) for spec in demo_data.DEMO_AUDITS for inject in (False, True)]


def _field_keys(node, parent, path, out):
    """Every (parent, key, path) in `node` whose key is a field name, not data."""
    if isinstance(node, list):
        for item in node:
            _field_keys(item, parent, path, out)
    elif isinstance(node, dict):
        for k, v in node.items():
            if parent in redaction.SEGMENT_CONTAINERS or parent in gateway.PERIOD_KEYED:
                _field_keys(v, "_data", f"{path}/{k}", out)       # segment names, periods, window lengths
            elif parent in gateway.DATASET_KEYED:
                assert k in gateway.DATASET_KEYED[parent], f"{path}/{k}: unknown dataset"
                _field_keys(v, k, f"{path}/{k}", out)
            else:
                out.append((parent, k, f"{path}/{k}"))
                _field_keys(v, k, f"{path}/{k}", out)


def test_every_results_key_is_allowlisted_or_declared_server_only(engine_runs):
    """A results key the engine writes is in OUTBOUND_FIELDS (the model sees it) or declared
    server-only here. An unknown key fails: a field added without a decision is otherwise
    dropped silently and the model never sees it (log 2026-10-02 gateway-data-boundary)."""
    assert not (SERVER_ONLY_FIELDS & gateway.OUTBOUND_FIELDS), "a key cannot be both"
    model_facing_top = set()
    for step in gateway.STEP_CONFIG:
        model_facing_top |= set(gateway._slice_for_step({k: [] for k in gateway.OUTBOUND_FIELDS}, step))
    model_facing_top |= set(gateway._GAP_FIELDS)
    allowed_by_parent = set().union(*gateway.OUTBOUND_FIELDS_BY_PARENT.values())
    unknown = []
    for spec, inject, results in engine_runs:
        for top, value in results.items():
            if top in SERVER_ONLY_TOP_LEVEL:
                continue
            if top not in model_facing_top:
                unknown.append(f"/{top} (top-level: not in any step slice and not in SERVER_ONLY_TOP_LEVEL)")
                continue
            found = []
            _field_keys(value, top, f"/{top}", found)
            for parent, key, path in found:
                if key not in gateway.OUTBOUND_FIELDS and key not in SERVER_ONLY_FIELDS \
                        and not (key in allowed_by_parent and key in gateway.OUTBOUND_FIELDS_BY_PARENT.get(parent, ())):
                    unknown.append(path)
    assert not unknown, "results keys that are neither allowlisted nor declared server-only:\n  " + "\n  ".join(sorted(set(unknown)))


def test_no_reason_or_metric_name_reaches_the_model_with_upload_content(engine_runs):
    """Every Missing Data reason and metric name the engine can write, with a sentinel in one cell
    of every mapped column and in every header: the model's version carries none of it. A reason
    that quotes a cell value needs a _NEUTRAL_REASONS entry (log 2026-10-02 gateway-data-boundary-2)."""
    injected = [(spec, results) for spec, inject, results in engine_runs if inject]
    stored_all = json.dumps([r for _, r in injected], ensure_ascii=False).lower()
    assert SENTINEL.lower() in stored_all, "fixture did not exercise the cell sentinel"
    # Headers reach results only through a management question (covered by the fixture test above).
    quoting = [item["metric"] for _, r in injected for item in r["missing_data"] if SENTINEL.lower() in item["reason"].lower()]
    assert quoting, "fixture: at least one stored reason quotes a cell value, so the neutral path is exercised"

    for spec, results in injected:
        db = t.FakeDB()
        db["audits"].docs.append({"id": RUN_ID, "results": results, "reporting_currency": spec["reporting_currency"],
                                  "target_arr": spec["target_arr"], "target_date": spec["target_date"]})
        computed = asyncio.run(gateway.load_computed_results(db, RUN_ID, "growth_engine"))
        mapping = asyncio.run(redaction.get_or_create_map(db, RUN_ID, computed))
        for item in results["missing_data"]:
            assert SENTINEL.lower() not in item["metric"].lower(), f"metric name quotes a cell: {item['metric']!r}"
            assert HEADER_SENTINEL.lower() not in item["metric"].lower(), f"metric name quotes a header: {item['metric']!r}"
            reason = redaction.substitute(gateway._outbound_gap_value("reason", item), mapping)
            assert SENTINEL.lower() not in reason.lower(), (
                f"{item['metric']!r} quotes a cell value in its reason; add a _NEUTRAL_REASONS entry: {reason!r}")
            assert HEADER_SENTINEL.lower() not in reason.lower(), f"{item['metric']!r} quotes a header: {reason!r}"
        adapter = t.FakeAdapter()
        asyncio.run(gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=adapter, sleep=t._noop_sleep))
        assert adapter.calls == 1
        sent = adapter.payloads[0].lower()
        for needle in (SENTINEL, HEADER_SENTINEL):
            assert needle.lower() not in sent, f"{needle!r} reached the provider"


_LOG_LEVELS = frozenset({"debug", "info", "warning", "warn", "error", "critical", "exception", "log"})
# The only calls that may take the exception object: they return a class name or a code name, never its text.
SAFE_EXCEPTION_READERS = frozenset({"type", "_engine_step"})
# A parameter with one of these names, or typed as an exception, is treated as the exception object.
_EXCEPTION_PARAM_NAMES = frozenset({"exc", "e", "err", "error", "exception"})


def _log_calls():
    """(file, function, lineno, call text, problems) for every log call in the backend."""
    out = []
    files = [BACKEND / "server.py", BACKEND / "growth_engine.py", BACKEND / "demo_data.py",
             *sorted((BACKEND / "app").rglob("*.py"))]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _LOG_LEVELS and isinstance(node.func.value, ast.Name)
                    and "log" in node.func.value.id.lower()):
                continue
            # Names bound to an exception where this call sits: `except X as name` around it, and
            # parameters of the enclosing functions that are typed or named as an exception.
            bound, function, up = set(), "<module>", node
            while up in parents:
                up = parents[up]
                if isinstance(up, ast.ExceptHandler) and up.name:
                    bound.add(up.name)
                if isinstance(up, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function = up.name if function == "<module>" else function
                    for a in [*up.args.posonlyargs, *up.args.args, *up.args.kwonlyargs]:
                        annotation = ast.unparse(a.annotation) if a.annotation else ""
                        if a.arg in _EXCEPTION_PARAM_NAMES or annotation.endswith(("Exception", "Error")):
                            bound.add(a.arg)
            problems = []
            if node.func.attr == "exception":
                problems.append("logger.exception appends the traceback")
            for kw in node.keywords:
                if kw.arg in ("exc_info", "stack_info"):
                    problems.append(f"{kw.arg}= appends the traceback")
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Call) and ast.unparse(sub.func).endswith(("format_exc", "format_exception")):
                        problems.append("traceback text is formatted into the message")
                    if isinstance(sub, ast.Name) and sub.id in bound:
                        owner = parents.get(sub)
                        if not (isinstance(owner, ast.Call) and ast.unparse(owner.func) in SAFE_EXCEPTION_READERS):
                            problems.append(f"the exception {sub.id!r} is formatted into the message")
            out.append((str(path.relative_to(BACKEND)), function, node.lineno, ast.unparse(node), problems))
    return out


def test_no_log_call_formats_an_exception_message_or_traceback():
    """A log call may use an exception only through SAFE_EXCEPTION_READERS, whether it sits in an
    `except` block or in a helper that takes the exception as a parameter. The message and the
    traceback can quote uploaded cell values (log 2026-10-02 fix-calc-correctness-2). The two sites
    TRACEBACK_ALLOWED is empty; a new entry is a decision, not a default."""
    calls = _log_calls()
    assert len(calls) >= 8, "the scan found fewer log calls than the codebase is known to have"
    violations = [f"{file}:{line} in {func}(): {text}  <- {'; '.join(problems)}"
                  for file, func, line, text, problems in calls
                  if problems and (file, func) not in TRACEBACK_ALLOWED]
    assert not violations, "log calls that can carry upload content:\n  " + "\n  ".join(violations)
    allowed_in_use = {(file, func) for file, func, _, _, problems in calls if problems}
    assert allowed_in_use == set(TRACEBACK_ALLOWED), "TRACEBACK_ALLOWED lists a site that no longer exists; remove it"


def _alternatives(pattern: re.Pattern) -> list:
    """The top-level words of a `\\b(?:a|b(?:s|es)|c)\\b` direction regex."""
    body = pattern.pattern
    assert body.startswith(r"\b(?:") and body.endswith(r")\b"), "direction regex shape changed; update _alternatives"
    body, out, depth, cur = body[5:-3], [], 0, ""
    for ch in body:
        depth += (ch == "(") - (ch == ")")
        if ch == "|" and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


# One false friend per direction word: the word in another sense, or the confusable form that
# sits next to it, with the verdict the strict reading gives. "passes" means the dropped minus
# sign on change_arr -77,949 is accepted; "flagged" means 77949 stays unverified.
# A realistic false friend that passes is a hole in the list: "contracts", "down" and "lower" were
# removed for that (test_removed_direction_words_no_longer_accept_a_dropped_sign).
FALSE_FRIENDS = {
    # decline words
    "fall": ("The fall in ARR, 77,949 EUR, is in Segment B.", "passes"),
    "fell": ("Costs rose, ARR fell 77,949 EUR.", "flagged"),
    "decline": ("The decline of 77,949 EUR is in Segment B.", "passes"),
    "drop": ("The drop-off is 77,949 EUR.", "passes"),
    "decrease": ("The decrease is 77,949 EUR.", "passes"),
    "shrink": ("The shrink in Segment B is 77,949 EUR.", "passes"),
    "loss of": ("A loss of 77,949 EUR of ARR.", "passes"),
    # growth words: a growth word in a decline sentence keeps the figure unverified (a reask, never a wrong figure)
    "grows": ("Segment B grows while ARR falls by 77,949 EUR.", "flagged"),
    "grew": ("Costs grew; ARR fell by 77,949 EUR.", "flagged"),
    "rise": ("The rise in churn cut ARR by 77,949 EUR.", "flagged"),
    "rose": ("Churn rose, so ARR fell by 77,949 EUR.", "flagged"),
    "increase": ("The increase in churn cut ARR by 77,949 EUR.", "flagged"),
    "up": ("ARR falls by up to 77,949 EUR.", "flagged"),
    "higher": ("Higher churn cut ARR by 77,949 EUR.", "flagged"),
    "gains": ("Gains of 77,949 EUR offset the decline.", "flagged"),
    "adds": ("Segment B adds 77,949 in new contracts.", "flagged"),
    "expands": ("ARR declines by 77,949 EUR as the base expands.", "flagged"),
    "improves": ("Margin improves as ARR declines by 77,949 EUR.", "flagged"),
    "accelerates": ("Churn accelerates; ARR falls by 77,949 EUR.", "flagged"),
    "wins": ("ARR declines by 77,949 EUR after two wins.", "flagged"),
    "won": ("Won deals fell; ARR dropped 77,949 EUR.", "flagged"),
}


def test_every_direction_word_has_a_false_friend_case():
    """A word added to _DECLINE or _GROWTH without its own entry in FALSE_FRIENDS fails here.
    Keys are the form of the word its case uses; each key must match exactly one direction word."""
    uncovered, matched = [], {}
    for name, rx in (("_DECLINE", gateway._DECLINE), ("_GROWTH", gateway._GROWTH)):
        for alt in _alternatives(rx):
            keys = [k for k in FALSE_FRIENDS if re.fullmatch(alt, k, re.IGNORECASE)]
            if not keys:
                uncovered.append(f"{name}: {alt}")
            for k in keys:
                matched[k] = matched.get(k, 0) + 1
    assert not uncovered, "direction words without their own case in FALSE_FRIENDS:\n  " + "\n  ".join(uncovered)
    for key, (text, _) in FALSE_FRIENDS.items():
        assert matched.get(key) == 1, f"{key!r} is not exactly one direction word"
        assert re.search(rf"\b{re.escape(key)}\b", text, re.IGNORECASE), f"{key!r}: its case does not contain the word"


@pytest.mark.parametrize("word", sorted(FALSE_FRIENDS))
def test_false_friend_verdict(word):
    text, expected = FALSE_FRIENDS[word]
    payload = gateway.build_outbound(guard_t.COMPUTED, {})
    assert "-77,949" in str(payload), "fixture: the engine figure is signed"
    flagged = gateway.numeric_guard(guard_t._narrative(text), payload).all
    assert flagged == ([] if expected == "passes" else ["77949"]), f"{word!r}: {text!r} -> {flagged}"


@pytest.mark.parametrize("text", ["A 77,949 EUR down payment was booked.", "The lower band is 77,949 EUR.",
                                  "ARR is down 77,949 EUR.", "ARR is lower by 77,949 EUR."])
def test_removed_direction_words_no_longer_accept_a_dropped_sign(text):
    """"down" and "lower" read as a decline in a down payment or the lower band, so the words were
    dropped; the figure stays unverified until the sentence uses a decline verb."""
    payload = gateway.build_outbound(guard_t.COMPUTED, {})
    assert gateway.numeric_guard(guard_t._narrative(text), payload).all == ["77949"]
    for word in ("down", "lower"):
        assert not gateway._DECLINE.search(word)


def test_the_outermost_500_handler_and_the_gateway_failure_log_type_run_id_and_step_only(monkeypatch, caplog):
    """An error whose message quotes a cell reaches both catch-all handlers: the log carries the
    error type and the request or run, never the message or a traceback."""
    pytest.importorskip("fastapi")
    import logging
    from fastapi.testclient import TestClient
    import server

    def boom(*args, **kwargs):
        raise RuntimeError("cannot parse cell 'Jane Doe (CEO)'")

    async def aboom(*args, **kwargs):
        boom()

    generate = gateway.generate_narrative            # server.llm_gateway is this module; keep the real one
    monkeypatch.setattr(server, "db", t.make_db())
    monkeypatch.setattr(server.llm_gateway, "generate_narrative", aboom)
    client = TestClient(server.app, raise_server_exceptions=False)
    with caplog.at_level(logging.DEBUG):
        assert client.post("/api/runs/run-abc/narrative/growth_engine").status_code == 500
    assert "unexpected error handling POST /api/runs/run-abc/narrative/growth_engine: error=RuntimeError" in caplog.text
    caplog.clear()

    db = _db()
    monkeypatch.setattr(gateway.guards, "check_call_cap", aboom)
    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(generate(db, RUN_ID, "growth_engine", adapter=t.FakeAdapter(), sleep=t._noop_sleep))
    assert result.narrative_status != "ok"
    assert f"unexpected gateway failure for run {RUN_ID} step growth_engine: error=RuntimeError" in caplog.text
    for text in (caplog.text, *[r.getMessage() for r in caplog.records]):
        assert "Jane Doe" not in text and "Traceback" not in text
    assert all(r.exc_info is None for r in caplog.records), "no traceback in the log"


# ---------------------------------------------------------------------------
# Deck text never reaches the model (docs/specs/deck-parser.md section 4). The deck parser has
# no path to the gateway, and the gateway reads no parsed text, no snippet and no source
# reference. If it ever reads claim candidates, it projects decks.GATEWAY_READABLE_FIELDS only.
# ---------------------------------------------------------------------------
import subprocess  # noqa: E402

from app import decks  # noqa: E402

DECK_SENTINEL = "DECKTEXT Jane Doe"            # in the parsed text and the snippet
DECK_FILE = "Acme_Board_Q3.pptx"               # in the source references


def _imports(tree):
    """(module, name) for every import at any depth, plus importlib / __import__ calls."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(a.name, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            out += [("." * node.level + (node.module or ""), a.name) for a in node.names]
        elif isinstance(node, ast.Call) and ast.unparse(node.func).endswith(("import_module", "__import__")):
            out.append((ast.unparse(node), "<dynamic>"))
    return out


def test_the_deck_parser_never_imports_or_calls_the_gateway():
    offenders = []
    for path in sorted((BACKEND / "app" / "decks").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module, name in _imports(tree):
            parts = set(re.split(r"[.\s\"'()]+", module)) | {name}
            if parts & {"llm", "gateway", "anthropic", "<dynamic>"}:
                offenders.append(f"{path.name}: {module} -> {name}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in ("gateway", "llm_gateway") or \
                    isinstance(node, ast.Attribute) and node.attr in ("gateway", "llm_gateway", "generate_narrative"):
                offenders.append(f"{path.name}:{node.lineno}: {ast.unparse(node)}")
    assert not offenders, "the deck parser reaches for the gateway:\n  " + "\n  ".join(offenders)
    # Transitively too: importing the parser loads neither the gateway nor a provider SDK.
    code = ("import sys, app.decks.parser, app.decks.claims; "
            "print(sorted(m for m in sys.modules if m.startswith('app.llm') or m.split('.')[0] == 'anthropic'))")
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]", out.stdout


def test_the_gateway_names_no_deck_text_snippet_or_source_field():
    """Static: no gateway module imports the deck package, or names the parsed-text collection
    or the parsed-text, snippet, borrowed-label or source-reference fields, or a table row's values
    by period (each keeps its column header's text and its cell)."""
    forbidden = {decks.TEXT_COLLECTION, "blocks", "snippet", "label_from", "date_from", "sources", "by_period"}
    offenders = []
    for path in sorted((BACKEND / "app" / "llm").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [f"{path.name}: {module} -> {name}" for module, name in _imports(tree)
                      if "decks" in re.split(r"[.\s\"'()]+", module) or name == "decks"]
        offenders += [f"{path.name}:{node.lineno}: {node.value!r}" for node in ast.walk(tree)
                      if isinstance(node, ast.Constant) and node.value in forbidden]
    assert not offenders, "the gateway names deck text:\n  " + "\n  ".join(offenders)


def _recording_db():
    """The usual stub plus a stored deck, recording every read the gateway makes."""
    reads = []

    class Collection(t.FakeCollection):
        def __init__(self, name):
            super().__init__()
            self.name = name

        async def find_one(self, flt, projection=None):
            doc = await super().find_one(flt, projection)
            reads.append((self.name, projection, doc))
            return doc

        def find(self, flt, projection=None):
            cursor = super().find(flt, projection)
            reads.append((self.name, projection, cursor._docs))
            return cursor

        def aggregate(self, pipeline):
            cursor = super().aggregate(pipeline)
            reads.append((self.name, None, cursor._docs))
            return cursor

    class DB(t.FakeDB):
        def __getitem__(self, name):
            return self._cols.setdefault(name, Collection(name))

    db = DB()
    doc = copy.deepcopy(t.RESULTS_DOC)
    doc["results"] = copy.deepcopy(RESULTS)
    db["audits"].docs.append(doc)
    db[decks.TEXT_COLLECTION].docs.append({"audit_id": RUN_ID, "file": DECK_FILE, "format": "pptx",
                                           "blocks": [{"slide": 3, "kind": "text", "text": DECK_SENTINEL}]})
    db[decks.CANDIDATES_COLLECTION].docs.append({
        "audit_id": RUN_ID, "id": "c1", "claim_type": "revenue", "value": 3600000, "unit": None, "currency": "USD",
        "target_date": "2024", "status": "approved", "file": DECK_FILE, "snippet": DECK_SENTINEL,
        "label_from": DECK_SENTINEL, "date_from": DECK_SENTINEL, "parsed": {"value": 3600000},
        "sources": [{"file": DECK_FILE, "slide": 3, "kind": "text"}], "inconsistent_dates": ["2024"],
        "by_period": [{"value": 3600000, "value_high": None, "target_date": "2024", "period": DECK_SENTINEL,
                       "source": {"file": DECK_FILE, "slide": 3, "kind": "table", "table": 1, "row": 2, "col": 2}}]})
    return db, reads


def test_the_gateway_reads_no_deck_text_snippet_or_source():
    """Dynamic: every gateway path runs over a database holding a parsed deck. Nothing the gateway
    reads, and nothing it sends, carries the deck's text, snippet or file name."""
    # Spec section 4: type, value, high value (of a range), unit, date, status - nothing else.
    assert decks.GATEWAY_READABLE_FIELDS == {"claim_type", "value", "value_high", "unit", "target_date", "status"}
    db, reads = _recording_db()
    adapter = t.FakeAdapter(replies=[json.dumps(NARRATIVE)])
    asyncio.run(gateway.generate_narrative(db, RUN_ID, "growth_engine", adapter=adapter, sleep=t._noop_sleep))
    asyncio.run(gateway.read_cached_narrative(db, RUN_ID, "growth_engine"))
    asyncio.run(gateway.narratives_for_run(db, RUN_ID))
    asyncio.run(gateway.disclosure_for_run(db, RUN_ID))
    asyncio.run(gateway.usage_for_run(db, RUN_ID))
    assert adapter.calls == 1 and reads, "fixture: the gateway ran and read Mongo"

    assert not [r for r in reads if r[0] == decks.TEXT_COLLECTION], "the gateway read the parsed-text collection"
    for name, projection, _ in reads:
        if name == decks.CANDIDATES_COLLECTION:
            fields = {k for k, v in (projection or {}).items() if v and k != "_id"}
            assert fields and fields <= decks.GATEWAY_READABLE_FIELDS, f"candidate projection {projection!r}"
    returned = json.dumps([doc for _, _, doc in reads], ensure_ascii=False, default=str)
    sent = adapter.payloads[0]
    for needle in (DECK_SENTINEL, DECK_FILE):
        assert needle not in returned, f"{needle!r} was read by the gateway"
        assert needle not in sent, f"{needle!r} reached the provider"


# ---------------------------------------------------------------------------
# The structure path (CLAUDE.md rules 16-18, docs/specs/llm-structure-reading.md section 10).
# Redacted deck structure cells and column-mapping texts (at most 3 header rows, at most 3 samples per
# numeric or date column, a profile per text column) may reach the provider, with the audit's consent,
# as extracted text with cell positions. Nothing else does, and no sent text is stored or logged.
# ---------------------------------------------------------------------------
from app.structures import redact as structure_redact  # noqa: E402
from app import structures  # noqa: E402

STRUCTURE_AUDIT = {"id": "audit-boundary", "company_name": "Target Co", "client_name": "Northbridge Capital",
                   "engagement_reference": "ENG-2026-041", "structure_reading_consent": True, "results": None}
GOOD_STRUCTURE = "r1c2: FY2025\nr1c3: FY2026\nr2c1: Revenue\nr2c2: £1,200,000\nr2c3: £1,500,000"
GOOD_MAPPING = ("r1c1: Customer\nr1c2: Invoice Date\nr1c3: Amount\nc2 sample: 2025-01-31\nc2 sample: 2025-02-28\n"
                "c2 sample: 2025-03-31\nc3 sample: 1200.50\nc1 profile: distinct 42, typical length 12, shape Aa Aa")
STRUCTURE_REPLY = json.dumps({"type": "table", "items": [
    {"metric": "revenue", "period": "FY2025", "value": 1200000, "unit": "GBP", "actual_or_forecast": "forecast",
     "value_cell": "r2c2", "period_cells": ["r1c2"], "proposed_flags": []}]})
MAPPING_REPLY = json.dumps({"type": "column_mapping", "items": [
    {"metric": "customer_id", "period": None, "value": None, "unit": None, "actual_or_forecast": "unknown",
     "value_cell": "r1c1", "period_cells": [], "proposed_flags": []}]})
# Every reason a structure text is refused: codes, never text from the structure.
STRUCTURE_REFUSALS = frozenset({"not_text", "empty", "raw_bytes", "file_name", "client_name", "engagement_reference",
                                "not_cells", "cell_too_long", "redaction_changed", "too_many_header_rows",
                                "too_many_samples", "text_value"})


def _structure_db(mapping=None, **audit):
    db = t.FakeDB()
    db["audits"].docs.append({**STRUCTURE_AUDIT, **audit})
    if mapping:
        db["pseudonym_map"].docs.append({"run_id": STRUCTURE_AUDIT["id"], "mapping": mapping})
    return db


def _send(db, text, kind="table", reply=STRUCTURE_REPLY):
    adapter = t.FakeAdapter(replies=[reply])
    result = asyncio.run(gateway.read_structure(db, STRUCTURE_AUDIT["id"], text, kind, adapter=adapter,
                                                sleep=t._noop_sleep))
    return result, adapter


def test_redacted_structure_cells_reach_the_provider_as_cell_lines_only():
    cells = [{"row": 1, "col": 1, "text": "Contact"}, {"row": 2, "col": 1, "text": "jane.doe@northwind.com"},
             {"row": 3, "col": 1, "text": "Northwind Trading renewed"}, {"row": 4, "col": 1, "text": "Michael Smith"},
             {"row": 5, "col": 1, "text": "+44 20 7946 0958"}, {"row": 6, "col": 1, "text": "£1,200,000"}]
    mapping = {"Northwind Trading": "Customer_01"}
    redacted, _ = structure_redact.redact_structure(cells, "Target Co", mapping)
    text = structure_redact.structure_text(redacted)
    result, adapter = _send(_structure_db(mapping), text, reply=json.dumps({"type": "table", "items": []}))
    assert result.status == "read" and adapter.calls == 1, result.reason
    sent = json.loads(adapter.payloads[0])
    assert set(sent) == {"type", "text"} and sent["text"] == text
    for needle in ("jane.doe@northwind.com", "Northwind Trading", "Michael Smith", "+44 20 7946 0958"):
        assert needle not in sent["text"], f"{needle!r} reached the provider"
    assert all(re.match(r"^r\d+c\d+: ", line) for line in sent["text"].splitlines())


def test_the_client_name_and_engagement_reference_reach_the_provider_only_as_redacted():
    cells = [{"row": 1, "col": 1, "text": "Prepared for Northbridge Capital"}, {"row": 1, "col": 2, "text": "FY2025"},
             {"row": 2, "col": 1, "text": "Revenue, ref ENG-2026-041"}, {"row": 2, "col": 2, "text": "£1,200,000"}]
    redacted, counts = structure_redact.redact_structure(cells, "Target Co", {},
                                                         structure_redact.withheld_values(STRUCTURE_AUDIT))
    text = structure_redact.structure_text(redacted)
    result, adapter = _send(_structure_db(), text)
    assert result.status == "read" and adapter.calls == 1 and counts["withheld"] == 2, result.reason
    sent = json.loads(adapter.payloads[0])["text"]
    assert sent == "r1c1: Prepared for [redacted]\nr1c2: FY2025\nr2c1: Revenue, ref [redacted]\nr2c2: £1,200,000"
    for needle in ("Northbridge", "ENG-2026-041"):
        assert needle.lower() not in sent.lower(), f"{needle!r} reached the provider"


def test_a_longer_word_holding_the_client_name_or_engagement_reference_is_not_refused():
    for text in ("r1c1: ENG-2026-0412\nr1c2: £1M", "r1c1: Northbridge Capitalists\nr1c2: £1M"):
        result, adapter = _send(_structure_db(), text, reply=json.dumps({"type": "table", "items": []}))
        assert (result.status, adapter.calls) == ("read", 1), text


def test_a_column_mapping_text_within_the_caps_reaches_the_provider():
    result, adapter = _send(_structure_db(), GOOD_MAPPING, "column_mapping", MAPPING_REPLY)
    assert result.status == "read" and adapter.calls == 1, result.reason
    sent = json.loads(adapter.payloads[0])["text"]
    parsed = structure_redact.parse_column_text(sent)
    assert len({c["row"] for c in parsed["headers"]}) <= 3 and all(len(v) <= 3 for v in parsed["samples"].values())
    assert set(parsed["profiles"]) == {1}, "the text column sends a profile"


def test_a_sheet_built_by_the_app_sends_no_text_cell_value():
    columns = ["Customer", "Invoice Date", "Amount", "Note"]
    rows = [{"Customer": f"JANEDOE Retail {i}", "Invoice Date": "2025-01-31T00:00:00", "Amount": 100 + i,
             "Note": "JANEDOE called"} for i in range(6)]
    text = structures.column_mapping_text(columns, rows, "Target Co", {}, ("Customer",))
    assert SENTINEL not in text and structure_redact.column_text_problem(text) is None
    result, adapter = _send(_structure_db(), text, "column_mapping", MAPPING_REPLY)
    assert adapter.calls == 1 and SENTINEL not in adapter.payloads[0]


@pytest.mark.parametrize("name, text, kind, reason", [
    ("raw bytes", b"PK\x03\x04 r1c1: x", "table", "not_text"),
    ("control bytes", "r1c1: x\x00\x01", "table", "raw_bytes"),
    ("a full page", "Our mission\nWe grew revenue strongly in 2025 and plan to triple it.\nTeam\nOur founders met at...",
     "table", "not_cells"),
    ("a prose snippet", "Revenue grew from £1.2m to £1.5m between FY2025 and FY2026.", "table", "not_cells"),
    ("a cell over 200 characters", "r1c1: " + "x" * 201, "table", "cell_too_long"),
    ("a file name", "r1c1: See Acme_Board_Q3.pptx", "table", "file_name"),
    ("an unredacted email", "r1c1: jane.doe@northwind.com", "table", "redaction_changed"),
    ("an unredacted phone number", "r1c1: +44 20 7946 0958", "table", "redaction_changed"),
    ("an unredacted name", "r1c1: Michael Smith", "table", "redaction_changed"),
    ("an unredacted customer name", "r1c1: Northwind Trading renewed", "table", "redaction_changed"),
    # Sent as written (not through redaction), the client name or engagement reference is refused as a
    # whole word, with the boundaries redaction uses.
    ("the client name", "r1c1: Prepared for Northbridge Capital", "table", "client_name"),
    ("the client name in any case", "r1c1: NORTHBRIDGE CAPITAL", "table", "client_name"),
    ("the engagement reference", "r1c1: ENG-2026-041", "table", "engagement_reference"),
    ("the engagement reference after a change of case", "r1c1: refENG-2026-041", "table", "engagement_reference"),
    ("the client name in a column-mapping header", GOOD_MAPPING + "\nr1c4: Northbridge Capital share", "column_mapping",
     "client_name"),
    ("more than 3 samples", GOOD_MAPPING + "\nc3 sample: 1\nc3 sample: 2\nc3 sample: 3", "column_mapping",
     "too_many_samples"),
    ("more than 3 header rows", GOOD_MAPPING + "\nr4c1: Customer name", "column_mapping", "too_many_header_rows"),
    ("a text cell value on the column-mapping path", GOOD_MAPPING + "\nr1c4: Note\nc4 sample: Northwind Trading",
     "column_mapping", "text_value"),
    ("a text value as a profile and a sample", GOOD_MAPPING + "\nc1 sample: 12", "column_mapping", "text_value"),
])
def test_the_structure_path_refuses_what_rule_16_does_not_allow(name, text, kind, reason):
    assert reason in STRUCTURE_REFUSALS
    db = _structure_db({"Northwind Trading": "Customer_01"})
    result, adapter = _send(db, text, kind)
    assert adapter.calls == 0 and getattr(adapter, "counted", 0) == 0, f"{name} reached the provider"
    assert (result.status, result.reason) == ("refused", f"refused: {reason}"), name


def test_no_call_is_made_without_consent():
    for audit in ({"structure_reading_consent": False}, {"structure_reading_consent": None}):
        result, adapter = _send(_structure_db(**audit), GOOD_STRUCTURE)
        assert result.status == "no_consent" and adapter.calls == 0
        result, adapter = _send(_structure_db(**audit), GOOD_MAPPING, "column_mapping", MAPPING_REPLY)
        assert result.status == "no_consent" and adapter.calls == 0


def test_no_sent_text_in_a_log_llm_calls_or_llm_structures(caplog):
    import logging
    db = _structure_db()
    with caplog.at_level(logging.DEBUG):
        _send(db, GOOD_STRUCTURE)
        _send(db, GOOD_STRUCTURE.replace("FY2025", "FY2027"),
              reply=json.dumps({"type": "table", "items": [{"bad": 1}]}))           # rejected twice: not read
        _send(db, "r1c1: jane.doe@northwind.com")                                   # refused
    stored = json.dumps(db[gateway.STRUCTURES_COLLECTION].docs + db["llm_calls"].docs, ensure_ascii=False, default=str)
    logs = caplog.text + "".join(r.getMessage() for r in caplog.records)
    for needle in ("Revenue", "£1,200,000", "1,500,000", "jane.doe", GOOD_STRUCTURE):
        assert needle not in stored, f"{needle!r} was stored"
        assert needle not in logs, f"{needle!r} was logged"
    assert "structure read: run_id=audit-boundary step=structures hash=" in caplog.text
    assert "structure refused: run_id=audit-boundary step=structures reason=redaction_changed" in caplog.text
    assert "[redacted]" not in logs, "the placeholder count is not logged either"
    assert all(r.exc_info is None for r in caplog.records)


def test_the_structure_path_never_reads_parsed_deck_text():
    """read_structure is handed the text; it reads consent and names from the audit, the pseudonym map,
    its own cache and the call log, never the parsed-text or candidate collections."""
    db, reads = _recording_db()
    db["audits"].docs[0].update({"company_name": "Target Co", "client_name": "Northbridge Capital",
                                 "engagement_reference": "ENG-2026-041", "structure_reading_consent": True})
    adapter = t.FakeAdapter(replies=[STRUCTURE_REPLY])
    asyncio.run(gateway.read_structure(db, RUN_ID, GOOD_STRUCTURE, "table", adapter=adapter, sleep=t._noop_sleep))
    assert adapter.calls == 1
    touched = {name for name, _, _ in reads}
    assert not touched & {decks.TEXT_COLLECTION, decks.CANDIDATES_COLLECTION}, touched
    audit_reads = [projection for name, projection, _ in reads if name == "audits"]
    assert audit_reads and all(set(p) - {"_id"} <= {"id", "company_name", "client_name", "engagement_reference",
                                                       "structure_reading_consent"} for p in audit_reads)
    assert DECK_SENTINEL not in adapter.payloads[0] and DECK_FILE not in adapter.payloads[0]


def test_the_deck_parser_still_has_no_link_to_the_structure_path_or_the_gateway():
    """app.structures may read deck structures and call the gateway; the deck package imports neither."""
    for path in sorted((BACKEND / "app" / "decks").rglob("*.py")):
        for module, name in _imports(ast.parse(path.read_text(encoding="utf-8"))):
            assert "structures" not in re.split(r"[.\s\"'()]+", module), f"{path.name} imports {module}"
