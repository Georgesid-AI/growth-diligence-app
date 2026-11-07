"""The fixture set of the sheet reader (docs/design/read-check-review.md section 10), offline: every file is synthetic, every expected map
is consistent with its file, and the ideal reading of each file goes through the masker, the gateway and the cell checks to the expected
as-of month. The job that reads each file once with the real model is scripts/run_reading_fixtures.py (CI, only when the reading path changes)."""
import asyncio
import copy
import json
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import reading_fixtures as rf  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from app import checks, readings, sheet_reader  # noqa: E402
from app import column_rules as cr  # noqa: E402
from app.llm import gateway  # noqa: E402
from app.structures import reading_input, redact, workbook_facts  # noqa: E402
from schemas.metrics import FileMap  # noqa: E402

MODEL = "claude-sonnet-5-5"
SHEETS = rf.sheet_fixtures()
IDS = [f["name"] for f in SHEETS]
VARIANTS = ["monthly_report_merged_year", "monthly_report_quarters", "monthly_report_dates"]      # perturbed layouts of monthly_report (structure-extraction.md)


def workbook(fixture):
    path = fixture["path"]
    return cr.read_workbook(path.read_bytes(), path.name)


class Ideal(t.FakeAdapter):
    """Answers a sheet reading with the expected map's ideal reading; refuses everything else."""

    def __init__(self, file_map):
        super().__init__()
        self.file_map, self.reads = file_map, 0

    def complete(self, **kw):
        sent = json.loads(kw["user_payload"])
        if sent["type"] != "sheet_reading" or "recheck" in sent:
            raise gateway.GatewayError("model_refused", "not scripted")
        self.reads += 1
        self.payloads.append(kw["user_payload"])
        # The reader is sent one sheet to a call (George, 2026-11-05): it answers for that sheet only, and a figure belongs to the sheet it cites.
        asked = {ln.split(": ", 1)[1] for ln in sent["text"].split("\n") if ln.startswith("sheet ")}
        mine = {**self.file_map, "sheets": [sh for sh in self.file_map["sheets"] if sh["sheet"] in asked],
                "figures": [f for f in self.file_map.get("figures") or [] if ((f.get("source") or {}).get("sheet") or next(iter(asked), None)) in asked]}
        return json.dumps(mine), 3000, 400


def cells_part(text):
    """The reading text of a sheet call without the lines before its "sheet 1:" line (the sheets in the file and the structure facts)."""
    lines = text.split("\n")
    return "\n".join(lines[next(i for i, ln in enumerate(lines) if ln.startswith("sheet 1:")):])


def structure_of(fixture):
    """The facts the upload extracts from an .xlsx fixture (a CSV has none)."""
    return workbook_facts.extract(fixture["path"].read_bytes()) if fixture["path"].suffix == ".xlsx" else None


def run(fixture, file_map=None):
    """The whole pipeline on one fixture with a scripted model: (the stored outcome, the adapter, the db)."""
    db = t.FakeDB()
    db["audits"].docs.append({"id": "fx", "company_name": rf.COMPANY, "structure_reading_consent": True})
    adapter = Ideal(file_map or fixture["expected_map"]["file_map"])
    doc = asyncio.run(sheet_reader.read_file(db, {"id": "fx"}, workbook(fixture), "f" * 64, fixture["path"].name, 12, adapter=adapter,
                                             structure=structure_of(fixture)))
    return doc, adapter, db


@pytest.fixture(autouse=True)
def reader_env(monkeypatch):
    monkeypatch.setenv("SHEET_READER_MODEL", MODEL)


def test_the_set_is_the_six_layouts_of_the_design_note():
    names = [e["name"] for e in rf.manifest()]
    assert names == ["monthly_report", "yearly_pnl", "actual_budget_variance", "budget_separate_sheet", "deck_rotated_axis", "testco_pnl",
                     "testco_revenue", *VARIANTS]
    for entry in rf.manifest():
        assert rf.path_of(entry).exists(), entry
        assert (rf.FIXTURES / entry["expected"]).exists()
    assert [f["name"] for f in SHEETS] == ["monthly_report", "yearly_pnl", "actual_budget_variance", "budget_separate_sheet", "testco_pnl", *VARIANTS]


def test_no_fixture_carries_a_real_company_a_person_an_address_or_a_phone_number():
    """Rule 15 and section 10: one made-up company, no e-mail, no phone, no IBAN, no legal-form name, no person."""
    texts = []
    for f in SHEETS:
        for sheet in workbook(f):
            texts += [str(v) for row in sheet.grid for v in row if v is not None]
    for name in ("deck_rotated_axis",):
        from pptx import Presentation
        for slide in Presentation(str(rf.FIXTURES / f"{name}.pptx")).slides:
            texts += [s.text_frame.text for s in slide.shapes if s.has_text_frame]
    blob = " | ".join(texts)          # cells are separate: "Jan" and "Feb" in neighbouring header cells are no first name and surname
    assert redact.personal_items(blob) == [] and not re.search(r"(?i)\b(?:ltd|gmbh|inc|corp|llc|s\.a\.|ag|bv|plc)\b", blob)
    assert not redact._FIRST_NAME.search(blob), "no first name followed by a surname"
    named = {m for m in re.findall(r"[A-Z][a-z]+ Co\b", blob)}
    assert named <= {"Fixture Co"}, named
    for f in rf.manifest():
        raw = json.dumps(rf.expected(f["name"]))
        assert not re.search(r"@|\+\d{6,}", raw)


@pytest.mark.parametrize("fixture", SHEETS, ids=IDS)
def test_the_expected_map_is_a_valid_file_map_and_the_ideal_reading_agrees_with_its_own_expectations(fixture):
    exp = fixture["expected_map"]
    ideal = FileMap.model_validate(exp["file_map"]).model_dump()
    assert rf.compare(exp, exp["as_of_month"], ideal) == []


@pytest.mark.parametrize("fixture", [f for f in SHEETS if f["name"] != "testco_pnl"], ids=[n for n in IDS if n != "testco_pnl"])
def test_the_ideal_reading_of_each_workbook_is_confirmed_cell_by_cell_and_gives_the_expected_month(fixture):
    doc, adapter, _ = run(fixture)
    sent_sheets = len(gateway.sheet_units(reading_input.reading_text(workbook(fixture))))
    assert doc["status"] == "read" and adapter.reads == 2 * sent_sheets, "the reading and the consistency read, one call per sheet each"
    rejected = [i for i in doc["items"] if i["outcome"] == checks.REJECTED]
    assert rejected == [], [(i["key"], i["reason"]) for i in rejected]
    assert doc["month"] == fixture["expected_map"]["as_of_month"], doc["evidence"]
    assert doc["evidence"] and "confirmed on sheet" in doc["evidence"]
    assert doc["counts"]["confirmed"] >= 5 and doc["rereads"] == []
    stored = readings.effective(adapter.file_map, [])
    assert rf.compare(fixture["expected_map"], doc["month"], stored) == []


def test_the_variance_columns_of_actual_budget_variance_are_tested_in_every_row_that_names_them():
    """F2 of the review of PR 205: layout 3's defining feature, the variance column of each month, is inside the comparison."""
    fixture = next(f for f in SHEETS if f["name"] == "actual_budget_variance")
    doc, _, _ = run(fixture)
    tested = {i["row"]: i["outcome"] for i in doc["items"] if i["kind"] == "variance"}
    assert tested == {5: checks.CONFIRMED, 6: checks.CONFIRMED, 7: checks.CONFIRMED}, "S5 = Q5 - R5, and the same for the other rows"


@pytest.mark.parametrize("fixture", [f for f in SHEETS if f["name"] != "testco_pnl"], ids=[n for n in IDS if n != "testco_pnl"])
def test_every_non_empty_cell_of_every_sheet_is_sent_none_sampled_none_cut(fixture):
    _, adapter, _ = run(fixture)
    sent = "\n".join(json.loads(p)["text"] for p in adapter.payloads)
    parsed = [sh for p in adapter.payloads for sh in redact.parse_reading_text(cells_part(json.loads(p)["text"]))]      # the first line names the file's sheets
    expected_cells = {s.sheet: sum(1 for c in reading_input.sheet_cells(s)) for s in workbook(fixture)}
    assert {s["name"]: len(s["cells"]) for s in parsed} == expected_cells
    assert rf.COMPANY not in sent and "Client-01" in sent, "the target's name is a token"


def test_a_merged_month_header_is_read_with_its_span_and_the_budget_columns_take_its_period():
    fixture = next(f for f in SHEETS if f["name"] == "actual_budget_variance")
    _, adapter, _ = run(fixture)
    sent = json.loads(adapter.payloads[0])["text"]
    assert "B3: Jan-24 (B3:D3)" in sent and "Q3: Jun-24 (Q3:S3)" in sent
    doc, _, _ = run(fixture)
    budget = next(i for i in doc["items"] if i["key"] == "figure:Actual vs budget:R5:revenue")
    assert budget["outcome"] == checks.CONFIRMED, "R3 is blank in the file: the header is the merged June cell to its left"


@pytest.mark.parametrize("fixture", [f for f in SHEETS if f["name"] != "testco_pnl"], ids=[n for n in IDS if n != "testco_pnl"])
def test_a_reading_that_moves_the_boundary_one_period_is_rejected_by_the_checks_and_by_the_comparison(fixture):
    bad = copy.deepcopy(fixture["expected_map"]["file_map"])
    sheet = next(s for s in bad["sheets"] if s.get("last_actual"))
    la = sheet["last_actual"]
    from app.structures.redact import col_letters, col_number
    la["column"] = col_letters(col_number(la["column"]) + {"actual_budget_variance": 3, "monthly_report_quarters": 2}.get(fixture["name"], 1))     # a whole month in the triples; past the quarter column
    doc, _, _ = run(fixture, bad)
    assert doc["month"] != fixture["expected_map"]["as_of_month"] or doc["month"] is None
    assert rf.compare(fixture["expected_map"], doc["month"], bad), "the comparison names the difference"


def test_the_ideal_reading_of_the_test_companys_pnl_is_confirmed_with_its_periods_down_the_sheet():
    fixture = next(f for f in SHEETS if f["name"] == "testco_pnl")
    doc, adapter, _ = run(fixture)
    assert doc["status"] == "read" and adapter.reads == 2
    by_key = {i["key"]: i for i in doc["items"]}
    assert by_key["periods:CSV"]["outcome"] == checks.CONFIRMED, "the first and last month sit in column A, down the sheet"
    assert by_key["figure:CSV:C15:revenue"]["outcome"] == checks.CONFIRMED, "June 2024's neighbour: the period of C15 is the A15 cell of its row"
    assert not [i for i in doc["items"] if i["outcome"] == checks.REJECTED] and doc["month"] is None, "no boundary of its own: the rules give the month"
    wrong = copy.deepcopy(fixture["expected_map"]["file_map"])
    wrong["figures"][0]["period"] = "2024-01"
    doc, _, _ = run(fixture, wrong)
    bad = next(i for i in doc["items"] if i["key"] == "figure:CSV:C15:revenue")
    assert (bad["outcome"], bad["reason"]) == (checks.REJECTED, "Reading says 2024-01; cell A15 is the header for 2024-02.")


def test_the_comparison_names_a_wrong_boundary_column_even_when_the_month_agrees():
    exp = next(f for f in SHEETS if f["name"] == "actual_budget_variance")["expected_map"]
    moved = copy.deepcopy(exp["file_map"])
    moved["sheets"][0]["last_actual"]["column"] = "R"                 # inside the same merged month: the month is still June 2024
    assert rf.compare(exp, "2024-06", moved) == ["Actual vs budget: last actual column R, expected Q"]


def test_expected_figures_are_a_required_subset_and_extra_returned_figures_are_no_difference():
    exp = next(f for f in SHEETS if f["name"] == "actual_budget_variance")["expected_map"]
    assert len(exp["figures"]) == 1, "the plan and variance cells are covered by the row entries, not by figures"
    full = copy.deepcopy(exp["file_map"])
    assert len(full["figures"]) == 3 and rf.compare(exp, "2024-06", full) == []
    full["figures"] = full["figures"][1:]
    assert rf.compare(exp, "2024-06", full) == ["figure revenue at Actual vs budget!Q5 missing"]


def test_the_comparison_names_a_wrong_revenue_row_a_wrong_role_and_a_wrong_figure():
    fixture = next(f for f in SHEETS if f["name"] == "monthly_report")
    exp = fixture["expected_map"]
    bad = copy.deepcopy(exp["file_map"])
    bad["sheets"][0]["rows"][0]["role"] = "bookings"
    bad["figures"][0]["value"] = 450000.0
    bad["figures"][1]["source"]["cell"] = "F6"
    diffs = rf.compare(exp, "2024-05", bad)
    assert any("as-of month" in d for d in diffs) and any("revenue row" in d for d in diffs) and any("role bookings" in d for d in diffs)
    assert any("figure revenue" in d for d in diffs) and any("figure customers" in d and "missing" in d for d in diffs)
    assert rf.compare(exp, "2024-06", exp["file_map"]) == []




def test_the_deck_fixture_has_rotated_axis_labels_and_parts_that_sum_to_its_headline():
    from pptx import Presentation
    exp = rf.expected("deck_rotated_axis")
    assert FileMap.model_validate(exp["file_map"]).kind == "deck"
    parts = exp["parts_sum"]
    assert sum(parts["parts"]) == parts["headline"] == 1200.0
    figs = exp["file_map"]["figures"]
    assert figs[0]["value"] == 1200 and sum(f["value"] for f in figs[1:]) == figs[0]["value"]
    prs = Presentation(str(rf.FIXTURES / "deck_rotated_axis.pptx"))
    slide = prs.slides[1]
    assert any(s.has_text_frame and "1,200" in s.text_frame.text for s in slide.shapes)
    chart = next(s.chart for s in slide.shapes if s.has_chart)
    assert chart.category_axis._element.xpath(".//a:bodyPr/@rot") == ["-2700000"]
    assert [round(v) for v in chart.plots[0].series[0].values] == [300, 280, 320, 300]


# ---------------------------------------------------------------------------
# The job (section 10): the live run reads each fixture once, skips with a notice without the key, and runs only on the reading path
# ---------------------------------------------------------------------------
ROOT = BACKEND.parent


def load_runner():
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_reading_fixtures", ROOT / "scripts" / "run_reading_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.deck_images_problem = lambda: ""          # the job's own preflight is tested below; the CI checks carry no LibreOffice
    return module


def test_the_job_skips_with_a_notice_and_exit_0_when_the_key_the_prompt_or_the_model_is_absent(monkeypatch, capsys):
    runner = load_runner()
    for name in runner.NEEDED:
        monkeypatch.delenv(name, raising=False)
    assert runner.main() == 0
    out = capsys.readouterr().out
    assert out.startswith("::notice title=Reading fixtures skipped::") and all(n in out for n in runner.NEEDED)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("SHEET_READER_MODEL", MODEL)
    assert runner.main() == 0 and "SHEET_READING_PROMPT" in capsys.readouterr().out, "the prompt is a secret: absent, the job skips"


class FixtureRouter:
    """Stands for the provider: answers a reading with the ideal map of the fixture whose sheets it was sent."""

    def __init__(self, differ=None, boundary=None):
        self.boundary = boundary
        self.by_sheet = {}
        for f in rf.live_fixtures():          # the job reads the live fixtures only
            for sh in f["expected_map"]["file_map"]["sheets"]:
                self.by_sheet.setdefault(sh["sheet"], []).append(f)
        self.differ, self.requests = differ, []

    def fixture_of(self, name, text):
        """The fixture a call is for: by its sheet name, and where two live fixtures share one (a layout and its perturbed variant) by the cells of the call."""
        found = self.by_sheet[name]
        if len(found) == 1:
            return found[0]
        sent = {ln for ln in text.split("\n") if re.match(r"^[A-Z]{1,3}\d+: ", ln) and rf.COMPANY not in ln and "Client-" not in ln}
        for f in found:
            theirs = {ln for ln in (reading_input.reading_text(workbook(f), structure_of(f)) or "").split("\n") if rf.COMPANY not in ln}
            if sent and sent <= theirs:
                return f
        return found[0]          # a call that is no fixture's text (a test's own payload): the first of them

    def __call__(self, *a, **k):
        return self

    def count_tokens(self, **kw):
        return 1200

    def complete(self, **kw):
        sent = json.loads(kw["user_payload"])
        self.requests.append(sent)
        names = re.findall(r"(?m)^sheet \d+: (.*)$", sent["text"])
        fixture = self.fixture_of(names[0], sent["text"])
        file_map = copy.deepcopy(fixture["expected_map"]["file_map"])
        if self.differ and fixture["name"] == self.differ:
            file_map["sheets"][0]["rows"][0]["role"] = "bookings"
        if self.boundary and fixture["name"] == self.boundary:
            la = next(sh for sh in file_map["sheets"] if sh.get("last_actual"))["last_actual"]
            from app.structures.redact import col_letters, col_number
            la["column"] = col_letters(col_number(la["column"]) + 1)          # rejected by the checks, so a re-read is asked for
        # One sheet to a call (George, 2026-11-05): the reply holds that sheet, and the figures that cite it.
        file_map["sheets"] = [sh for sh in file_map["sheets"] if sh["sheet"] in names]
        file_map["figures"] = [f for f in file_map.get("figures") or [] if ((f.get("source") or {}).get("sheet") or names[0]) in names]
        return json.dumps(file_map), 3000, 400


def test_the_job_reads_every_fixture_once_and_exits_0_when_every_reading_agrees(monkeypatch, capsys):
    runner = load_runner()
    router = FixtureRouter()
    monkeypatch.setattr(gateway, "AnthropicAdapter", router)
    for name, value in (("ANTHROPIC_API_KEY", "k"), ("SHEET_READING_PROMPT", "TEST ONLY prompt"), ("SHEET_READER_MODEL", MODEL)):
        monkeypatch.setenv(name, value)
    assert runner.main() == 0
    out = capsys.readouterr().out
    calls = {f["name"]: len(gateway.sheet_units(reading_input.reading_text(workbook(f)))) for f in rf.live_fixtures()}
    assert len(router.requests) == 2 * sum(calls.values()), "per sheet of each fixture the reading and its consistency read, no re-read"
    assert "recheck" not in json.dumps(router.requests)
    assert "every fixture agrees with its expected map" in out and all(f["name"] in out for f in rf.live_fixtures())
    assert "recheck" not in json.dumps(router.requests)
    for name, n in calls.items():
        assert f"{6000 * n}/{800 * n}" in next(ln for ln in out.split("\n") if ln.startswith(name)), "the tokens in/out column sums the fixture's calls"
    assert "skipped: deck path unchanged" in out and "differ from" not in out
    assert "Client-01" not in out and "447223" not in out, "no cell text in the job's output"


def test_the_job_exits_1_and_names_the_fixture_whose_reading_differs(monkeypatch, capsys):
    runner = load_runner()
    monkeypatch.setattr(gateway, "AnthropicAdapter", FixtureRouter(differ="monthly_report"))
    for name, value in (("ANTHROPIC_API_KEY", "k"), ("SHEET_READING_PROMPT", "TEST ONLY prompt"), ("SHEET_READER_MODEL", MODEL)):
        monkeypatch.setenv(name, value)
    assert runner.main() == 1
    out = capsys.readouterr().out
    assert "role bookings, expected revenue" in out and "1 fixture(s) differ" in out


def test_a_third_provider_call_for_one_sheet_is_an_error():
    runner = load_runner()
    wrapped = runner.OneCall(FixtureRouter())
    payload = json.dumps({"type": "sheet_reading", "text": "sheet 1: Monthly report\nA1: x"})
    wrapped.complete(user_payload=payload)
    wrapped.complete(user_payload=payload)           # the consistency read: the same request, asked a second time
    with pytest.raises(RuntimeError):
        wrapped.complete(user_payload=payload)       # a third reading of the sheet
    other = json.dumps({"type": "sheet_reading", "text": "sheet 1: Yearly P&L\nA1: x"})
    with pytest.raises(KeyError):                  # another sheet is its own reading: it reaches the router, which has no such fixture
        wrapped.complete(user_payload=other)


class APIConnectionError(Exception):
    """Named as the SDK's connection error, which the gateway treats as retryable."""


class Flaky(FixtureRouter):
    """The provider failing the first attempt of every reply of every sheet with a connection error, as an overloaded API does: the gateway
    retries it (backoff, MAX_PROVIDER_RETRIES). Per sheet, so fixtures read side by side do not change one another's luck."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.failed_since_reply, self.failed, self.ok = {}, 0, 0

    def complete(self, **kw):
        names = tuple(re.findall(r"(?m)^sheet \d+: (.*)$", json.loads(kw["user_payload"])["text"]))
        if not self.failed_since_reply.get(names):
            self.failed_since_reply[names] = True
            self.failed += 1
            raise APIConnectionError("Connection error.")
        self.failed_since_reply[names] = False
        self.ok += 1
        return super().complete(**kw)


def _job_env(monkeypatch):
    for name, value in (("ANTHROPIC_API_KEY", "k"), ("SHEET_READING_PROMPT", "TEST ONLY prompt"), ("SHEET_READER_MODEL", MODEL)):
        monkeypatch.setenv(name, value)

    async def instant(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", instant)          # the gateway's retry backoff


def test_two_reads_of_every_sheet_of_every_fixture_never_raise_when_the_provider_fails_transiently(monkeypatch, capsys):
    """A failed attempt the gateway retries is no reading: the cap counts the replies it gets, so the consistency read is never refused."""
    runner = load_runner()
    router = Flaky()
    monkeypatch.setattr(gateway, "AnthropicAdapter", router)
    _job_env(monkeypatch)
    assert runner.main() == 0
    out = capsys.readouterr().out
    sheets = sum(len(gateway.sheet_units(reading_input.reading_text(workbook(f)))) for f in rf.live_fixtures())
    assert router.ok == 2 * sheets and router.failed == router.ok, "two replies per sheet, each after one retried failure"
    assert "provider_unreachable" not in out and "RuntimeError" not in out and "not_read" not in out
    assert all(ln.split()[1] == "read" for ln in out.splitlines() if ln.split() and ln.split()[0] in IDS)


def test_a_failed_attempt_is_no_reading_but_failures_are_capped():
    runner = load_runner()
    sheet = json.dumps({"type": "sheet_reading", "text": "sheet 1: Monthly report\nA1: x"})

    class Down:
        def complete(self, **kw):
            raise APIConnectionError("down")
    counter = runner.OneCall(Down())
    for _ in range(runner.OneCall.MAX_FAILED_ATTEMPTS):
        with pytest.raises(APIConnectionError):
            counter.complete(user_payload=sheet)
    with pytest.raises(RuntimeError, match="failed attempts"):
        counter.complete(user_payload=sheet)


def test_a_retried_schema_fix_is_still_the_one_allowed_retry():
    runner = load_runner()
    first = json.dumps({"type": "sheet_reading", "text": "sheet 1: A\nA1: 1"})
    fix = json.dumps({"type": "sheet_reading", "fix": "x", "errors": []})

    class Once(t.FakeAdapter):
        def __init__(self):
            super().__init__(replies=[json.dumps({"map_version": 1})])
            self.n = 0

        def complete(self, **kw):
            self.n += 1
            if self.n == 2:
                raise APIConnectionError("blip")           # the fix request's first attempt
            return super().complete(model="m", system="s", max_tokens=1, json_schema=None, **kw)
    counter = runner.OneCall(Once())
    counter.complete(user_payload=first)
    with pytest.raises(APIConnectionError):
        counter.complete(user_payload=fix)
    counter.complete(user_payload=fix)                     # the gateway's retry of it
    with pytest.raises(RuntimeError):
        counter.complete(user_payload=fix)                 # a second fix is refused


def test_the_workflow_runs_only_on_the_reading_path_and_skips_without_the_key():
    import yaml
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "reading-fixtures.yml").read_text(encoding="utf-8"))
    triggers = flow.get("on") or flow.get(True)
    paths = triggers["pull_request"]["paths"]
    for needed in ("backend/app/llm/**", "backend/app/checks.py", "backend/app/structures/**", "backend/app/sheet_reader.py", "backend/schemas/metrics.py",
                   "backend/tests/fixtures/reading/**", "backend/tests/fixtures/prompts/sheet_reading.md"):
        assert needed in paths, needed
    assert "push" not in triggers and set(triggers) == {"pull_request"}
    job = flow["jobs"]["reading"]
    assert job["env"]["ANTHROPIC_API_KEY"] == "${{ secrets.ANTHROPIC_API_KEY }}"
    skip = job["steps"][0]
    assert skip["if"] == "env.ANTHROPIC_API_KEY == ''" and "::notice" in skip["run"]
    assert all(step.get("if", "").startswith("env.ANTHROPIC_API_KEY != ''") for step in job["steps"][1:]), "nothing else runs without the key"
    assert any("scripts/run_reading_fixtures.py" in step.get("run", "") for step in job["steps"])
    assert job["timeout-minutes"] == 45, "a hung provider call must not hold the runner for the 6-hour default"
    tests_flow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" not in tests_flow, "the general checks stay free of secrets"


def test_the_job_starts_from_an_empty_store_and_fails_with_a_clear_line_when_a_fixture_is_served_from_storage(monkeypatch, capsys):
    runner = load_runner()
    db = runner.empty_store("TEST ONLY prompt")
    assert [d["name"] for d in db["prompts"].docs] == ["sheet_reading"]
    assert all(not db[c].docs for c in readings.COLLECTIONS), "no stored reading at the start of a run"
    # a store that already holds a reading is never what the job reads from: the job builds its own, so a cache hit can only be a bug
    monkeypatch.setattr(gateway, "AnthropicAdapter", FixtureRouter())
    fx = SHEETS[0]
    served = gateway.StructureRead(status="read", type="sheet_reading", cache_hit=True, file_map=fx["expected_map"]["file_map"], payload="x", reading_key="k")

    async def stored(*a, **k):
        return served
    monkeypatch.setattr(gateway, "read_structure", stored)
    for name, value in (("ANTHROPIC_API_KEY", "k"), ("SHEET_READING_PROMPT", "TEST ONLY prompt"), ("SHEET_READER_MODEL", MODEL)):
        monkeypatch.setenv(name, value)
    assert runner.main() == 1
    out = capsys.readouterr().out
    assert out.count("served from storage, not read by the model") == len(rf.live_fixtures()) and "fixture(s) differ" in out


# ---------------------------------------------------------------------------
# PR 3, item 4: the deck fixture joins the job. The page reader's figures are checked against the stored page text.
# ---------------------------------------------------------------------------
class DeckModel(t.FakeAdapter):
    """Answers a page read with one claim for the figure written as digits in the page text (the headline), as an ideal reader would."""

    def __init__(self, extra=()):
        super().__init__()
        self.extra = list(extra)

    def complete(self, **kw):
        self.calls += 1
        sent = json.loads(kw["user_payload"])
        claims = []
        for line in sent["text"].split("\n"):
            m = re.match(r"^(p\d+r\d+c\d+): .*?([\d,]+)$", line)
            if m and "revenue" in line.lower():
                claims.append({"metric": "revenue", "value": float(m.group(2).replace(",", "")), "value_high": None, "unit": "EUR", "unit_other": None,
                               "period": "2024", "basis": "actual", "scenario": "none", "value_cell": m.group(1), "label_cell": None,
                               "period_cell": None})
        return json.dumps({"type": "page_claims", "claims": claims + self.extra}), 1000, 100


def deck_job(adapter):
    runner = load_runner()
    db = runner.empty_store("TEST ONLY sheet prompt", "TEST ONLY deck prompt")
    return runner, db, asyncio.run(runner.read_decks(db, adapter=adapter))


def test_the_deck_fixture_runs_in_the_job_and_its_figures_are_checked_against_the_page_text(monkeypatch, capsys):
    monkeypatch.setenv("PAGE_READER_MODEL", MODEL)
    runner, db, failed = deck_job(DeckModel())
    out = capsys.readouterr().out
    assert "deck_rotated_axis" in out
    # The headline is read and confirmed by the page text; the four quarters need the image (the offline model does not read it), so the
    # job reports them as a difference: the comparison names what the reading lacks.
    assert failed == 1 and "no figure 300 read" in out and "confirmed 1" in out


def test_the_deck_comparison_passes_when_every_expected_figure_is_read_and_confirmed_and_the_parts_sum_to_the_headline():
    exp = rf.expected("deck_rotated_axis")
    figs = [{"value": f["value"], "outcome": "confirmed", "source": {"page": f["page"]}} for f in exp["figures"]]
    assert rf.compare_deck(exp, figs) == []
    assert any("not confirmed" in d for d in rf.compare_deck(exp, [{**figs[0], "outcome": "rejected"}, *figs[1:]]))
    assert any("add up" in d for d in rf.compare_deck(exp, [figs[0], *[{**f, "value": f["value"] + 50} for f in figs[1:]]]))


def test_the_job_skips_the_deck_alone_with_a_notice_without_the_deck_prompt(capsys):
    runner = load_runner()
    db = runner.empty_store("TEST ONLY sheet prompt")
    assert asyncio.run(runner.read_decks(db, adapter=DeckModel())) == 0
    assert "::notice title=Deck fixture skipped::DECK_READING_PROMPT is not set" in capsys.readouterr().out


def test_the_job_reads_the_deck_fixture_only_when_the_deck_path_changed(monkeypatch, capsys):
    runner = load_runner()
    router = FixtureRouter()
    monkeypatch.setattr(gateway, "AnthropicAdapter", router)
    called = []

    async def fake_decks(db, adapter=None):
        called.append(1)
        return 0
    monkeypatch.setattr(runner, "read_decks", fake_decks)
    for name, value in (("ANTHROPIC_API_KEY", "k"), ("SHEET_READING_PROMPT", "TEST ONLY prompt"), ("DECK_READING_PROMPT", "TEST ONLY deck"),
                        ("SHEET_READER_MODEL", MODEL)):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DECK_FIXTURE", raising=False)
    assert runner.main() == 0 and not called
    assert "skipped: deck path unchanged" in capsys.readouterr().out
    monkeypatch.setenv("DECK_FIXTURE", "1")
    monkeypatch.delenv("DECK_READING_PROMPT")
    assert runner.main() == 0 and not called
    assert "skipped: deck path unchanged" in capsys.readouterr().out
    monkeypatch.setenv("DECK_READING_PROMPT", "TEST ONLY deck")
    assert runner.main() == 0 and called == [1]


def test_deck_differences_are_printed_but_never_fail_the_job_while_a_sheet_difference_does(monkeypatch, capsys):
    runner = load_runner()
    monkeypatch.setattr(gateway, "AnthropicAdapter", FixtureRouter())

    async def deck_differs(db, adapter=None):
        print("deck_rotated_axis  read  differs")
        return 1
    monkeypatch.setattr(runner, "read_decks", deck_differs)
    for name, value in (("ANTHROPIC_API_KEY", "k"), ("SHEET_READING_PROMPT", "TEST ONLY prompt"), ("DECK_READING_PROMPT", "TEST ONLY deck"),
                        ("DECK_FIXTURE", "1"), ("SHEET_READER_MODEL", MODEL)):
        monkeypatch.setenv(name, value)
    assert runner.main() == 0
    out = capsys.readouterr().out
    assert "deck_rotated_axis  read  differs" in out and "deck fixture: report-only until the converter works in CI (issue #207)" in out
    monkeypatch.setattr(gateway, "AnthropicAdapter", FixtureRouter(differ=SHEETS[0]["name"]))
    assert runner.main() == 1, "a sheet fixture still fails the job"


def test_a_failing_re_read_leaves_the_file_read_with_its_rejected_items_noted_and_the_job_reports_the_count(monkeypatch, capsys):
    runner = load_runner()
    router = FixtureRouter(boundary="monthly_report")
    monkeypatch.setattr(gateway, "AnthropicAdapter", router)
    for name, value in (("ANTHROPIC_API_KEY", "k"), ("SHEET_READING_PROMPT", "TEST ONLY prompt"), ("SHEET_READER_MODEL", MODEL)):
        monkeypatch.setenv(name, value)
    runner.main()                                  # the cap refuses the second call: the re-read fails
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if ln.startswith("monthly_report"))
    assert " read " in line and "not_read" not in line and re.search(r"rejected [1-9]", line), line
    sheets_sent = len(gateway.sheet_units(reading_input.reading_text(workbook(next(f for f in SHEETS if f["name"] == "monthly_report")))))
    assert len(router.requests) == 2 * sum(len(gateway.sheet_units(reading_input.reading_text(workbook(f)))) for f in rf.live_fixtures()), "the failed re-read made no provider call beyond the cap"
    assert sheets_sent >= 1


def test_every_rejected_piece_is_printed_with_its_fixture_sheet_kind_cell_and_reason_like_a_cannot_check_one(monkeypatch, capsys):
    runner = load_runner()
    monkeypatch.setattr(gateway, "AnthropicAdapter", FixtureRouter(boundary="monthly_report"))
    _job_env(monkeypatch)
    assert runner.main() == 1, "both reads put the boundary one column late: they agree, so the job fails"
    out = capsys.readouterr().out
    pieces = [ln for ln in out.splitlines() if ln.startswith("    rejected monthly_report | ")]
    assert pieces, out
    for ln in pieces:
        assert re.fullmatch(r"    rejected monthly_report \| sheet [^|]+ \| [a-z_ ]+ \| cell [^|]+ \| [^|]+?: .+", ln), ln
    item = {"outcome": "cannot_check", "key": "k", "kind": "row", "sheet": "S", "cell": "B2", "reason": "why"}
    assert runner.piece_lines("fx", [item]) == ["    cannot check fx | sheet S | row | cell B2 | k: why"]
    evidence = {"outcome": "rejected", "key": "e", "kind": "evidence", "evidence_kind": "layout", "sheet": "S", "cell": None, "reason": "no"}
    assert runner.piece_lines("fx", [evidence]) == ["    rejected fx | sheet S | layout | cell - | e: no"]
    assert runner.piece_lines("fx", [{**item, "outcome": "confirmed"}]) == []


def test_one_progress_line_is_printed_per_model_call_with_fixture_sheet_read_and_elapsed_time(monkeypatch, capsys):
    runner = load_runner()
    router = FixtureRouter()
    monkeypatch.setattr(gateway, "AnthropicAdapter", router)
    _job_env(monkeypatch)
    assert runner.main() == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("progress ")]
    assert len(lines) == len(router.requests), "one line per reply"
    for ln in lines:
        assert re.fullmatch(r"progress [a-z_]+ \| .+ \| read [12]/2 \| call \d+\.\ds, job \d+\.\ds", ln), ln
    assert {ln.split(" | ")[0].split()[1] for ln in lines} == {f["name"] for f in rf.live_fixtures()}
    assert sum(" | read 2/2 | " in ln for ln in lines) == len(lines) // 2


def test_fixtures_are_read_in_parallel_and_the_table_keeps_the_manifest_order(monkeypatch, capsys):
    runner = load_runner()
    live, peak, lock = [0], [0], __import__("threading").Lock()

    class Slow(FixtureRouter):
        def complete(self, **kw):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            __import__("time").sleep(0.05)
            try:
                return super().complete(**kw)
            finally:
                with lock:
                    live[0] -= 1
    monkeypatch.setattr(gateway, "AnthropicAdapter", Slow())
    _job_env(monkeypatch)
    assert runner.main() == 0
    assert peak[0] > 1, "more than one fixture was in a provider call at the same time"
    names = [ln.split()[0] for ln in capsys.readouterr().out.splitlines() if ln.split() and ln.split()[0] in IDS and " read " in ln]
    assert names == [f["name"] for f in rf.live_fixtures()]
    monkeypatch.setenv("READING_FIXTURES_PARALLEL", "1")
    peak[0] = 0
    assert runner.main() == 0 and peak[0] == 1


def test_a_re_read_that_fails_never_marks_the_reading_not_read_and_notes_each_rejected_item():
    fixture = next(f for f in SHEETS if f["name"] == "monthly_report")
    bad = copy.deepcopy(fixture["expected_map"]["file_map"])
    la = next(s for s in bad["sheets"] if s.get("last_actual"))["last_actual"]
    from app.structures.redact import col_letters, col_number
    la["column"] = col_letters(col_number(la["column"]) + 1)
    for failure in (RuntimeError("cap"), gateway.GatewayError("model_refused", "no")):
        class Failing(Ideal):
            def complete(self, **kw):
                if "recheck" in json.loads(kw["user_payload"]):
                    raise failure
                return super().complete(**kw)
        db = t.FakeDB()
        db["audits"].docs.append({"id": "fx", "company_name": rf.COMPANY, "structure_reading_consent": True})
        doc = asyncio.run(sheet_reader.read_file(db, {"id": "fx"}, workbook(fixture), "f" * 64, fixture["path"].name, 12, adapter=Failing(bad)))
        assert doc["status"] == "read" and doc["counts"]["rejected"] >= 1
        assert doc["rereads"] and all(r["reason"].startswith("re-read not completed: ") for r in doc["rereads"])
        assert all(i["reread_note"].startswith("re-read not completed: ") for i in doc["items"] if i["outcome"] == "rejected")


def test_the_converter_presence_check_names_what_is_missing(monkeypatch):
    from app.decks import render
    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    assert render.converter_problem("pptx") == "no converter: soffice/libreoffice not found on the path"
    assert render.converter_problem("docx") is not None
    assert render.converter_problem("pdf") is None, "a PDF needs no converter"
    monkeypatch.setattr(render.shutil, "which", lambda name: "/usr/bin/soffice" if name == "soffice" else None)
    assert render.converter_problem("pptx") is None


def test_the_deck_fixture_is_not_read_and_is_report_only_when_its_page_images_cannot_be_made(monkeypatch, capsys):
    import importlib.util
    from app.decks import render
    spec = importlib.util.spec_from_file_location("run_reading_fixtures_real", ROOT / "scripts" / "run_reading_fixtures.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)                 # the real preflight
    router = FixtureRouter()
    monkeypatch.setattr(gateway, "AnthropicAdapter", router)
    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    for name, value in (("ANTHROPIC_API_KEY", "k"), ("SHEET_READING_PROMPT", "TEST ONLY prompt"), ("DECK_READING_PROMPT", "TEST ONLY deck"),
                        ("DECK_FIXTURE", "1"), ("SHEET_READER_MODEL", MODEL)):
        monkeypatch.setenv(name, value)
    runner.read_decks = lambda *a, **k: (_ for _ in ()).throw(AssertionError("the deck must not be read as text alone"))
    code = runner.main()
    out = capsys.readouterr().out
    assert out.splitlines()[0] == ("page images unavailable: no converter: soffice/libreoffice not found on the path "
                                   "[binary not found (soffice, libreoffice)]")
    assert "deck fixture: report-only until the converter works in CI (issue #207)" in out
    assert not any("deck_rotated_axis" in r for r in map(str, router.requests)), "no text-only read of the deck"
    assert code == 0 or "differ from their expected map" in out, "only a sheet difference may fail the job"


def test_the_preflight_line_carries_the_converters_exit_code_and_first_stderr_line(monkeypatch):
    import importlib.util
    import subprocess
    from app.decks import render
    spec = importlib.util.spec_from_file_location("run_reading_fixtures_real2", ROOT / "scripts" / "run_reading_fixtures.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(render.shutil, "which", lambda name: "/usr/bin/soffice" if name == "soffice" else None)
    monkeypatch.setattr(runner.subprocess if hasattr(runner, "subprocess") else subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 81, "", "Error: source file could not be loaded\nsecond line"))
    problem = runner.converter_detail("pptx")
    assert "exit code 81" in problem and "stderr: Error: source file could not be loaded" in problem and "second line" not in problem
    assert "/usr/bin/soffice" in problem


def test_the_workflow_installs_the_converter_the_deck_fixture_needs():
    import yaml
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "reading-fixtures.yml").read_text(encoding="utf-8"))
    steps = flow["jobs"]["reading"]["steps"]
    install = next(i for i, st in enumerate(steps) if "libreoffice" in st.get("run", ""))
    run = next(i for i, st in enumerate(steps) if "scripts/run_reading_fixtures.py" in st.get("run", ""))
    assert install < run and steps[install].get("if") == "env.ANTHROPIC_API_KEY != '' && env.DECK_FIXTURE == '1'"


def test_a_rate_row_the_reader_gave_no_label_cell_keeps_its_label_and_the_shown_under_its_line_note_on_the_yearly_pnl():
    """Regression: a rate row placed under its line lost its label (and with it the placement and the note) when the reading cited no label cell."""
    fixture = next(f for f in SHEETS if f["name"] == "yearly_pnl")
    sheets = workbook(fixture)
    sheets[0].grid[6][0] = "Revenue growth rate"                          # row 7 of the P&L, empty in the fixture
    file_map = copy.deepcopy(fixture["expected_map"]["file_map"])
    file_map["sheets"][0]["rows"].append({**file_map["sheets"][0]["rows"][0], "row": 7, "label_cell": None, "role": "growth_rate", "metric": "revenue",
                                          "basis": "rate", "unit": "rate", "currency": None, "cells": "C7:F7", "evidence": "growth rate across the period columns"})
    cells = checks.Cells(reading_input.reading_text(sheets))
    (entry,) = sheet_reader.sheet_lines(file_map, cells, [])
    line = next(ln for ln in entry["lines"] if ln["row"] == 7)
    assert line["label"] == "Revenue growth rate" and line["moved"] is True and line["indent"] == 1 and line["rate_of"] == 4
    assert [ln["row"] for ln in entry["lines"]][:2] == [4, 7], "directly under the revenue line"


def test_the_jobs_call_cap_is_a_reading_and_its_consistency_read_each_with_the_one_schema_retry_and_item_rereads_stay_blocked():
    runner = load_runner()
    good = json.dumps({"map_version": 1})
    fix = json.dumps({"type": "sheet_reading", "fix": "x", "errors": []})
    reread = json.dumps({"type": "sheet_reading", "text": "sheet 1: A\nA1: 1", "recheck": [{"item": "r3", "reason": "x"}]})
    first = json.dumps({"type": "sheet_reading", "text": "sheet 1: A\nA1: 1"})

    def call(counter, payload):
        return counter.complete(model="m", system="s", user_payload=payload, max_tokens=1, json_schema=None)

    # The reading, its one schema-validation retry, the consistency read and its retry go through, and their tokens add up.
    counter = runner.OneCall(t.FakeAdapter(replies=[good]))
    for payload in (first, fix, first, fix):
        call(counter, payload)
    assert counter.calls == 4 and counter.tokens_in == 4 * t.FakeAdapter.input_tokens and counter.tokens_out == 1200
    for refused in (fix, reread, first):                      # a second retry, an item re-read, a third reading
        with pytest.raises(RuntimeError, match="cap is one reading, one consistency read and one schema-validation retry"):
            call(counter, refused)
    assert counter.calls == 4, "a refused call never reaches the provider"
    call(counter, first.replace("sheet 1: A", "sheet 1: B"))        # another sheet has its own allowance
    assert counter.calls == 5

    # An item re-read is refused even as the second call for its sheet.
    counter = runner.OneCall(t.FakeAdapter(replies=[good]))
    call(counter, first)
    with pytest.raises(RuntimeError):
        call(counter, reread)
    assert counter.calls == 1

    # A fix request cannot be the first call.
    counter = runner.OneCall(t.FakeAdapter(replies=[good]))
    with pytest.raises(RuntimeError):
        call(counter, fix)
    assert counter.calls == 0


class Disagreeing(FixtureRouter):
    """The first reading of each sheet of `fixture` gives a wrong role on the first row; the consistency read gives the expected one."""

    def __init__(self, fixture, **kw):
        super().__init__(**kw)
        self.fixture, self.seen = fixture, set()

    def complete(self, **kw):
        reply = super().complete(**kw)
        text = json.loads(kw["user_payload"])["text"]
        names = tuple(re.findall(r"(?m)^sheet \d+: (.*)$", text))
        if self.fixture_of(names[0], text)["name"] == self.fixture and names not in self.seen:
            self.seen.add(names)
            file_map = json.loads(reply[0])
            file_map["sheets"][0]["rows"][0]["role"] = "bookings"
            return json.dumps(file_map), reply[1], reply[2]
        return reply


def test_a_row_the_two_reads_disagree_on_is_uncertain_prints_and_does_not_fail_the_job(monkeypatch, capsys):
    runner = load_runner()
    monkeypatch.setattr(gateway, "AnthropicAdapter", Disagreeing("monthly_report"))
    for name, value in (("ANTHROPIC_API_KEY", "k"), ("SHEET_READING_PROMPT", "TEST ONLY prompt"), ("SHEET_READER_MODEL", MODEL)):
        monkeypatch.setenv(name, value)
    assert runner.main() == 0
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if ln.startswith("monthly_report"))
    assert "uncertain (the reads disagree)" in line and "first read: " in line and "role bookings, expected revenue" in line
    assert "1 fixture(s) uncertain" in out and "differ from their expected map" not in out


def test_the_verdict_fails_on_a_row_both_reads_get_wrong_or_on_a_sheet_level_field_and_passes_uncertain():
    runner = load_runner()
    exp = SHEETS[0]["expected_map"]
    good = exp["file_map"]
    wrong = copy.deepcopy(good)
    wrong["sheets"][0]["rows"][0]["role"] = "bookings"
    month = exp["as_of_month"]
    assert runner.fixture_verdict(rf, exp, month, good, good)[0] == "none"
    assert runner.fixture_verdict(rf, exp, month, wrong, wrong)[0] == "differs", "both reads agree and differ from the expected map"
    assert runner.fixture_verdict(rf, exp, month, wrong, good)[0] == "uncertain"
    assert runner.fixture_verdict(rf, exp, month, good, wrong)[0] == "uncertain"
    assert runner.fixture_verdict(rf, exp, month, wrong, None)[0] == "uncertain", "one read is missing: nothing confirms the difference"
    assert runner.fixture_verdict(rf, exp, month, good, None)[0] == "none"
    late = copy.deepcopy(good)
    late["sheets"][0]["granularity"] = "yearly" if good["sheets"][0]["granularity"] != "yearly" else "monthly"
    assert runner.fixture_verdict(rf, exp, month, late, good)[0] == "differs", "a sheet-level field differs in one read"
    assert runner.fixture_verdict(rf, exp, "1999-01", good, good)[0] == "differs", "the as-of month is sheet-level"

    # The last actual column is judged like a row: it fails the job only when both reads give it wrongly.
    sheet = next(sh for sh in good["sheets"] if sh.get("last_actual"))
    moved = copy.deepcopy(good)
    shifted = next(sh for sh in moved["sheets"] if sh["sheet"] == sheet["sheet"])
    from app.structures.redact import col_letters, col_number
    shifted["last_actual"]["column"] = col_letters(col_number(sheet["last_actual"]["column"]) + 1)
    other_month = "1999-01"
    assert runner.fixture_verdict(rf, exp, other_month, moved, moved)[0] == "differs", "both reads put the boundary in the same wrong column"
    for pair in ((moved, good), (good, moved)):
        verdict, text = runner.fixture_verdict(rf, exp, month, *pair)
        assert verdict == "uncertain" and "last actual column" in text, "the reads disagree on the boundary"
    assert runner.fixture_verdict(rf, exp, month, moved, None)[0] == "uncertain", "the second read is missing"
    assert runner.fixture_verdict(rf, exp, other_month, moved, good)[0] == "uncertain", "the month follows the boundary: judged with it"
    assert runner.fixture_verdict(rf, exp, other_month, good, good)[0] == "differs", "a month no boundary explains is sheet-level"


def _bare_budget_reading():
    fixture = next(f for f in SHEETS if f["name"] == "budget_separate_sheet")
    bare = copy.deepcopy(fixture["expected_map"]["file_map"])
    actuals = next(s for s in bare["sheets"] if s["sheet"] == "Actuals")
    actuals["last_actual"] = None                    # a stand-in that reads the boundary as null
    return fixture, bare


def test_code_sets_the_last_actual_column_when_the_reading_has_none_another_sheet_is_a_plan_and_the_rows_end_at_the_last_column():
    """George, 2026-11-06: the fallback gives the as-of month, and its piece of evidence says it was set by code."""
    fixture, bare = _bare_budget_reading()
    doc, _, _ = run(fixture, bare)
    assert doc["month"] == "2024-06", doc["evidence"]
    pieces = [i for i in doc["items"] if i["kind"] == "evidence" and i["sheet"] == "Actuals"]
    assert [i["evidence_kind"] for i in pieces] == ["row_ends"] and pieces[0]["outcome"] == checks.CONFIRMED
    assert "Budget" in pieces[0]["text"] and "set by code" in pieces[0]["text"]
    last, = [i for i in doc["items"] if i["key"] == "last_actual:Actuals"]
    assert last["outcome"] == checks.CONFIRMED
    assert [i for i in doc["items"] if i["outcome"] == checks.REJECTED] == []


def _cells_of(sheets):
    return checks.Cells(redact.reading_text(sheets))


def _grid(name, title, last_col_has_value=True):
    cells = [{"row": 1, "col": 1, "text": title}, {"row": 2, "col": 1, "text": "Metric"}, {"row": 2, "col": 2, "text": "Jan-24"},
             {"row": 2, "col": 3, "text": "Feb-24"}, {"row": 3, "col": 1, "text": "Revenue"}, {"row": 3, "col": 2, "text": "10"}]
    if last_col_has_value:
        cells.append({"row": 3, "col": 3, "text": "11"})
    return {"name": name, "cells": cells}


def _map_of(*names):
    return {"map_version": 1, "kind": "sheet", "figures": [], "sheets": [
        {"sheet": n, "header_row": 2, "label_col": "A", "first_period_col": "B", "last_period_col": "C", "granularity": "monthly", "currency": None,
         "currency_cell": None, "last_actual": None, "rows": [{"row": 3, "label_cell": "A3", "role": "revenue", "metric": "revenue", "basis": "monthly",
                                                                "actual_plan": "actual", "cells": "B3:C3", "by_column": False, "evidence": "Revenue"}]}
        for n in names]}


def test_the_fallback_needs_a_plan_word_elsewhere_rows_that_end_at_the_last_column_and_no_plan_word_on_the_sheet_itself():
    two = lambda other_name, other_title, title="Monthly P&L", ends=True: _cells_of(  # noqa: E731
        [_grid("Report", title, ends), _grid(other_name, other_title)])
    ok = checks.plan_fallback(_map_of("Report"), two("Cost plan", "Cost"), 12)
    la = ok["sheets"][0]["last_actual"]
    assert (la["column"], la["period"]) == ("C", "2024-02") and la["evidence"][0]["kind"] == "row_ends"
    assert "Cost plan" in la["evidence"][0]["text"] and "set by code" in la["evidence"][0]["text"]
    titled = checks.plan_fallback(_map_of("Report"), two("Sheet2", "FY24 Budget"), 12)           # the plan word is in the other sheet's first rows
    assert titled["sheets"][0]["last_actual"]["column"] == "C"
    assert checks.plan_fallback(_map_of("Report"), two("Sheet2", "Cost"), 12)["sheets"][0]["last_actual"] is None, "no plan word elsewhere"
    assert checks.plan_fallback(_map_of("Report"), two("Cost plan", "Cost", ends=False), 12)["sheets"][0]["last_actual"] is None, "row stops before the last column"
    assert checks.plan_fallback(_map_of("Report"), two("Cost plan", "Cost", title="Budget 2024"), 12)["sheets"][0]["last_actual"] is None, "the sheet is itself a plan"
    own = _map_of("Report")
    own["sheets"][0]["last_actual"] = {"column": "B", "period": "2024-01", "evidence": []}
    assert checks.plan_fallback(own, two("Cost plan", "Cost"), 12)["sheets"][0]["last_actual"]["column"] == "B", "a reading's own last actual stands"


def test_the_fallback_last_actual_is_stored_on_the_reading_marked_set_by_code():
    """George, 2026-11-06 (approval on PR 244): the stored reading, its series and its exports carry the column the checked map uses."""
    fixture, bare = _bare_budget_reading()
    _, _, db = run(fixture, bare)
    stored, = db[readings.READINGS].docs
    actuals = next(s for s in stored["file_map"]["sheets"] if s["sheet"] == "Actuals")
    assert actuals["last_actual"]["column"] == "G" and actuals["last_actual"]["period"] == "2024-06"
    assert "Budget" in actuals["last_actual"]["evidence"][0]["text"] and "set by code" in actuals["last_actual"]["evidence"][0]["text"]
    budget = next(s for s in stored["file_map"]["sheets"] if s["sheet"] == "Budget")
    assert budget["last_actual"] is None, "the plan sheet itself is left as read"


# ---------------------------------------------------------------------------
# Perturbed variants of the monthly report (docs/specs/structure-extraction.md section 7): the file states more, the expected reading is the same
# ---------------------------------------------------------------------------
def _facts_of(exp):
    """The expected facts without cell letters: what a column insertion cannot change."""
    return {"as_of": exp["as_of_month"], "sheets": [(s["sheet"], s["granularity"], s["revenue_row"]) for s in exp["sheets"]],
            "roles": [(r["sheet"], r["row"], r["role"]) for r in exp["roles"]],
            "figures": [(f["metric"], f["value"], f["period"]) for f in exp["figures"]]}


def test_each_variant_expects_what_the_monthly_report_expects():
    base = rf.expected("monthly_report")
    for name in VARIANTS:
        assert _facts_of(rf.expected(name)) == _facts_of(base), name
    for name in ("monthly_report_merged_year", "monthly_report_dates"):
        assert rf.expected(name) | {"file": base["file"]} == base, "no layout cell moves: the expected map is the same"


def test_only_one_variant_is_read_by_the_live_job():
    live = [e["name"] for e in rf.manifest() if e["name"] in VARIANTS and e.get("live", True)]
    assert live == ["monthly_report_merged_year"]
    assert [f["name"] for f in rf.live_fixtures()].count("monthly_report_merged_year") == 1
    assert not {"monthly_report_quarters", "monthly_report_dates"} & {f["name"] for f in rf.live_fixtures()}


def _variant(name):
    return next(f for f in SHEETS if f["name"] == name)


def test_merged_year_over_year_less_months_gives_the_same_reading_and_the_months_are_dated_from_the_merged_year():
    fixture = _variant("monthly_report_merged_year")
    doc, adapter, _ = run(fixture)
    sent = json.loads(adapter.payloads[0])["text"]
    assert "B2: 2024 (B2:M2)" in sent and "B3: Jan" in sent and "G3: Jun" in sent, "months with no year under a merged year"
    assert doc["month"] == "2024-06" and not [i for i in doc["items"] if i["outcome"] == checks.REJECTED]
    assert workbook_facts.sheet_facts(structure_of(fixture), "Monthly report")["merged"] == ["B2:M2"]


def test_quarter_subtotal_columns_between_the_months_are_sums_and_the_months_are_still_read():
    fixture = _variant("monthly_report_quarters")
    facts = structure_of(fixture)
    sub = workbook_facts.sheet_facts(facts, "Monthly report")["subtotal_cols"]
    assert [s["col"] for s in sub] == ["E", "I", "M", "Q"] and all(len(s["parts"]) == 3 for s in sub)
    doc, adapter, _ = run(fixture)
    sent = json.loads(adapter.payloads[0])["text"].split("\n")
    assert [ln for ln in sent if ln.startswith("subtotal columns")] == ["subtotal columns: E = B-D", "subtotal columns: I = F-H", "subtotal columns: M = J-L",
                                                                         "subtotal columns: Q = N-P"]
    assert doc["month"] == "2024-06" and not [i for i in doc["items"] if i["outcome"] == checks.REJECTED]


def test_date_typed_headers_are_iso_periods_and_the_hardcoded_cell_of_the_formula_row_is_found():
    fixture = _variant("monthly_report_dates")
    doc, adapter, _ = run(fixture)
    sent = json.loads(adapter.payloads[0])["text"]
    assert "B3: 2024-01" in sent and "M3: 2024-12" in sent and "00:00:00" not in sent
    assert doc["structure_findings"]["hardcoded"] == [{"sheet": "Monthly report", "cell": "K5", "hidden": False}]
    assert doc["month"] == "2024-06" and not [i for i in doc["items"] if i["outcome"] == checks.REJECTED]
