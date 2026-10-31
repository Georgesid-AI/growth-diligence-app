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
from app import as_of, checks, readings, sheet_reader  # noqa: E402
from app import column_rules as cr  # noqa: E402
from app.llm import gateway  # noqa: E402
from app.structures import reading_input, redact  # noqa: E402
from schemas.metrics import FileMap  # noqa: E402

MODEL = "claude-sonnet-5-5"
SHEETS = rf.sheet_fixtures()
IDS = [f["name"] for f in SHEETS]


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
        return json.dumps(self.file_map), 3000, 400


def run(fixture, file_map=None):
    """The whole pipeline on one fixture with a scripted model: (the stored outcome, the adapter, the db)."""
    db = t.FakeDB()
    db["audits"].docs.append({"id": "fx", "company_name": rf.COMPANY, "structure_reading_consent": True})
    adapter = Ideal(file_map or fixture["expected_map"]["file_map"])
    doc = asyncio.run(sheet_reader.read_file(db, {"id": "fx"}, workbook(fixture), "f" * 64, fixture["path"].name, 12, adapter=adapter))
    return doc, adapter, db


@pytest.fixture(autouse=True)
def reader_env(monkeypatch):
    monkeypatch.setenv("SHEET_READER_MODEL", MODEL)


def test_the_set_is_the_six_layouts_of_the_design_note():
    names = [e["name"] for e in rf.manifest()]
    assert names == ["monthly_report", "yearly_pnl", "actual_budget_variance", "budget_separate_sheet", "deck_rotated_axis", "testco_pnl",
                     "testco_revenue"]
    for entry in rf.manifest():
        assert rf.path_of(entry).exists(), entry
        assert (rf.FIXTURES / entry["expected"]).exists()
    assert [f["name"] for f in SHEETS] == ["monthly_report", "yearly_pnl", "actual_budget_variance", "budget_separate_sheet", "testco_pnl"]


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
    blob = "\n".join(texts)
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
    assert doc["status"] == "read" and adapter.reads == 1
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
    sent = json.loads(adapter.payloads[0])["text"]
    parsed = redact.parse_reading_text(sent)
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
    la["column"] = col_letters(col_number(la["column"]) + (3 if fixture["name"] == "actual_budget_variance" else 1))     # a whole month in the triples
    doc, _, _ = run(fixture, bad)
    assert doc["month"] != fixture["expected_map"]["as_of_month"] or doc["month"] is None
    assert rf.compare(fixture["expected_map"], doc["month"], bad), "the comparison names the difference"


def test_the_ideal_reading_of_the_test_companys_pnl_is_confirmed_with_its_periods_down_the_sheet():
    fixture = next(f for f in SHEETS if f["name"] == "testco_pnl")
    doc, adapter, _ = run(fixture)
    assert doc["status"] == "read" and adapter.reads == 1
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


def test_the_test_companys_pnl_has_periods_down_the_sheet_and_its_month_comes_from_the_rules_path():
    fixture = next(f for f in SHEETS if f["name"] == "testco_pnl")
    sheet = workbook(fixture)[0]
    ds = {"dtype": "pnl", "file": "pnl.csv", "mapping": {"month": "Month", "revenue": "Revenue"}, "rows": sheet.frame.to_dict("records")}
    assert as_of.detect({"pnl": ds}) == {"month": "2024-02", "file": "pnl.csv", "evidence": None}
    assert fixture["expected_map"]["as_of_source"] == "rules"
    assert rf.compare(fixture["expected_map"], "2024-03", {"sheets": []}), "a month the rules path does not give is a difference"
    revenue = rf.manifest()[-1]
    sheet = cr.read_workbook(rf.path_of(revenue).read_bytes(), "revenue.csv")
    sent = redact.parse_reading_text(reading_input.reading_text(sheet))
    assert len(sent) == 1 and len(sent[0]["cells"]) == len(reading_input.sheet_cells(sheet[0])), \
        "no rule decides a sheet is a ledger: an invoice list is sent like any sheet, every cell"


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
        self.maps = {tuple(sorted(s["sheet"] for s in f["expected_map"]["file_map"]["sheets"])): f for f in SHEETS}
        self.differ, self.requests = differ, []

    def __call__(self, *a, **k):
        return self

    def count_tokens(self, **kw):
        return 1200

    def complete(self, **kw):
        sent = json.loads(kw["user_payload"])
        self.requests.append(sent)
        names = tuple(sorted(re.findall(r"(?m)^sheet \d+: (.*)$", sent["text"])))
        fixture = self.maps[names]
        file_map = copy.deepcopy(fixture["expected_map"]["file_map"])
        if self.differ and fixture["name"] == self.differ:
            file_map["sheets"][0]["rows"][0]["role"] = "bookings"
        if self.boundary and fixture["name"] == self.boundary:
            la = next(sh for sh in file_map["sheets"] if sh.get("last_actual"))["last_actual"]
            from app.structures.redact import col_letters, col_number
            la["column"] = col_letters(col_number(la["column"]) + 1)          # rejected by the checks, so a re-read is asked for
        return json.dumps(file_map), 3000, 400


def test_the_job_reads_every_fixture_once_and_exits_0_when_every_reading_agrees(monkeypatch, capsys):
    runner = load_runner()
    router = FixtureRouter()
    monkeypatch.setattr(gateway, "AnthropicAdapter", router)
    for name, value in (("ANTHROPIC_API_KEY", "k"), ("SHEET_READING_PROMPT", "TEST ONLY prompt"), ("SHEET_READER_MODEL", MODEL)):
        monkeypatch.setenv(name, value)
    assert runner.main() == 0
    out = capsys.readouterr().out
    assert len(router.requests) == len(SHEETS), "one provider call per fixture, no re-read"
    assert "every fixture agrees with its expected map" in out and all(f["name"] in out for f in SHEETS)
    assert "recheck" not in json.dumps(router.requests)
    assert "Client-01" not in out and "447223" not in out, "no cell text in the job's output"


def test_the_job_exits_1_and_names_the_fixture_whose_reading_differs(monkeypatch, capsys):
    runner = load_runner()
    monkeypatch.setattr(gateway, "AnthropicAdapter", FixtureRouter(differ="monthly_report"))
    for name, value in (("ANTHROPIC_API_KEY", "k"), ("SHEET_READING_PROMPT", "TEST ONLY prompt"), ("SHEET_READER_MODEL", MODEL)):
        monkeypatch.setenv(name, value)
    assert runner.main() == 1
    out = capsys.readouterr().out
    assert "role bookings, expected revenue" in out and "1 fixture(s) differ" in out


def test_a_second_provider_call_for_one_fixture_is_an_error():
    runner = load_runner()
    wrapped = runner.OneCall(FixtureRouter())
    payload = json.dumps({"type": "sheet_reading", "text": "sheet 1: Monthly report\nA1: x"})
    wrapped.complete(user_payload=payload)
    with pytest.raises(RuntimeError):
        wrapped.complete(user_payload=payload)


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
    assert out.count("served from storage, not read by the model") == len(SHEETS) and "fixture(s) differ" in out


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
    assert "Deck fixture skipped::DECK_FIXTURE is not 1" in capsys.readouterr().out
    monkeypatch.setenv("DECK_FIXTURE", "1")
    assert runner.main() == 0 and called == [1]


def test_a_failing_re_read_leaves_the_file_read_with_its_rejected_items_noted_and_the_job_reports_the_count(monkeypatch, capsys):
    runner = load_runner()
    router = FixtureRouter(boundary="monthly_report")
    monkeypatch.setattr(gateway, "AnthropicAdapter", router)
    for name, value in (("ANTHROPIC_API_KEY", "k"), ("SHEET_READING_PROMPT", "TEST ONLY prompt"), ("SHEET_READER_MODEL", MODEL)):
        monkeypatch.setenv(name, value)
    runner.main()                                  # the cap refuses the second call: the re-read fails
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("monthly_report"))
    assert " read " in line and "not_read" not in line and re.search(r"rejected [1-9]", line), line
    assert len(router.requests) == len(SHEETS), "the failed re-read made no provider call beyond the cap"


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
