"""scripts/consistency_run.py --pages (docs/design/ai-reads-rules-check.md section 7, PR B): the page_claims step on the public decks,
N passes, 5 pages per call, a hard stop at --max-spend, recorded replies and a report, a zip. Tested with a fake adapter: no live call."""
import asyncio
import importlib.util
import json
import os
import re
import sys
import zipfile
from pathlib import Path

import pytest
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("pdfplumber")
pytest.importorskip("pptx")

DECKS = ["03-buffer.pptx", "05-zero2hero.pdf"]


def _script():
    spec = importlib.util.spec_from_file_location("consistency_run", BACKEND.parent / "scripts" / "consistency_run.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


@pytest.fixture
def script(monkeypatch, tmp_path):
    """The script with docs/test-runs and the recorded replies redirected under tmp_path, and the temp folder too."""
    import tempfile
    script = _script()
    monkeypatch.setattr(script, "REPORTS", tmp_path / "docs" / "test-runs")
    monkeypatch.setattr(script, "RECORDED", tmp_path / "recorded")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "temp"))
    (tmp_path / "temp").mkdir()
    monkeypatch.delenv("DECK_PIPELINE", raising=False)
    monkeypatch.delenv("LLM_DAILY_SPEND_CAP_USD", raising=False)
    return script


def _run(script, adapter=None, passes=3, decks=DECKS, **kwargs):
    adapter = adapter or script.PageReplayAdapter()
    return asyncio.run(script.run_pages(decks, passes, script.MemoryDB(), adapter, **kwargs)), adapter


def test_a_fake_pages_run_reads_each_deck_in_every_pass_and_agrees(script, tmp_path, capsys):
    zip_path = tmp_path / "out" / "run.zip"
    report = script.main(["--pages", "--fake", "--deck", DECKS[0], "--deck", DECKS[1], "--zip", str(zip_path)])
    assert report["mode"] == "pages" and report["passes"] == 3 and report["prompt"] == "deck_reading" and not report["stopped"]
    assert report["decks_complete"] == 2 and report["agreement_pct_all"] == 100.0
    for deck in report["per_deck"].values():
        assert len(deck["passes"]) == 3 and deck["complete"] and deck["agreement_pct"] == 100.0
        assert all(p["read"] == p["batches"] > 0 and p["claims"] > 0 and p["matched"] > 0 for p in deck["passes"])
        assert all(p["batches"] == -(-deck["sent"] // 5) for p in deck["passes"]), "5 pages per call"
    assert report["totals"]["calls"] == report["totals"]["batches"] == 15
    out = capsys.readouterr().out
    assert "Report:" in out and "Pages run:" in out and "[2/2] 05-zero2hero.pdf pass 3/3" in out
    temp = tmp_path / "temp"
    assert not script.REPORTS.exists() and not script.RECORDED.exists(), "a fake run writes to the temp folder only"
    assert (temp / "pages_2026-10-22.md").is_file() or list(temp.glob("pages_*.md"))
    assert sorted(p.name for p in (temp.glob("pages_*/pass-1/*.json"))) == \
        ["buffer_p5.json", "buffer_p7.json", "zero2hero_p17.json", "zero2hero_p19.json"]
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
    assert len([n for n in names if n.endswith(".md")]) == 1 and len([n for n in names if n.endswith(".json")]) == 12


def test_the_fake_run_leaves_the_repository_and_the_environment_as_it_found_them(script):
    seen = []

    class Watching(script.PageReplayAdapter):
        def complete(self, **kwargs):
            seen.append((os.environ.get("DECK_PIPELINE"), os.environ.get("LLM_DAILY_SPEND_CAP_USD")))
            return super().complete(**kwargs)
    _run(script, Watching(), passes=1, decks=DECKS[:1], max_spend=2.5)
    assert seen and set(seen) == {("ai", "2.5")}, "the page calls run under DECK_PIPELINE=ai and a cap of --max-spend"
    assert "DECK_PIPELINE" not in os.environ and "LLM_DAILY_SPEND_CAP_USD" not in os.environ, "set for the script's own calls only"


def test_agreement_is_claims_found_in_every_pass_over_claims_found_in_any_pass(script, tmp_path):
    class Drifting(script.PageReplayAdapter):
        """Pass 2 drops the first claim of every reply; pass 3 changes the period of its last."""

        def __init__(self):
            super().__init__()
            self.seen = {}

        def complete(self, **kwargs):
            reply, tokens_in, tokens_out = super().complete(**kwargs)
            body = json.loads(reply)
            n = self.seen[kwargs["user_payload"]] = self.seen.get(kwargs["user_payload"], 0) + 1
            if n == 2:
                body["claims"] = body["claims"][1:]
            if n == 3 and body["claims"]:
                body["claims"][-1]["period"] = "2099"
            return json.dumps(body), tokens_in, tokens_out
    folder = tmp_path / "rec"
    report, _ = _run(script, Drifting(), decks=DECKS[:1], record_folder=folder)
    deck = report["per_deck"][DECKS[0]]
    seen = []
    for n in (1, 2, 3):                 # the same arithmetic from the recorded files, which hold the claims as returned
        seen.append({(c["value_cell"], c["metric"], c["period"]) for f in (folder / f"pass-{n}").glob("*.json")
                     for c in json.loads(f.read_text(encoding="utf-8"))["claims"]})
    assert len({len(x) for x in seen}) > 1 and set.intersection(*seen) < seen[0], "the passes differ"
    assert (deck["agreed"], deck["claims_union"]) == (len(set.intersection(*seen)), len(set.union(*seen)))
    assert deck["agreement_pct"] == round(100.0 * deck["agreed"] / deck["claims_union"], 1) < 100.0
    assert report["agreement_pct_all"] == deck["agreement_pct"]


def test_the_run_stops_before_a_call_that_could_pass_max_spend(script, caplog):
    import logging
    caplog.set_level(logging.WARNING)
    report, adapter = _run(script, max_spend=0.15)           # a call's bound is its counted input plus PAGE_MAX_TOKENS of output
    assert report["stopped"] is True and report["spent_usd"] <= 0.15, "the upper bound never passes --max-spend"
    assert 0 < adapter.calls < 12, "some calls were made, the rest refused without a provider call"
    assert report["decks_complete"] == 1 and report["per_deck"][DECKS[1]]["complete"] is False, "the stopped deck is left out"
    assert report["per_deck"][DECKS[1]]["agreement_pct"] is None and report["agreement_pct_all"] == 100.0, "of the complete deck only"
    assert "STOPPED at --max-spend $0.15" in script.pages_summary(report)
    assert any("reason=spend_stop" in r.getMessage() for r in caplog.records), "a closed word in the gateway's log line"
    again, nothing = _run(script, max_spend=0.0001)
    assert again["stopped"] and nothing.calls == 0 and again["totals"]["calls"] == 0, "a budget below one call makes none"


def test_the_guard_counts_the_input_the_gateway_counted_and_the_whole_max_tokens(script):
    from app.llm import gateway
    inner = script.PageReplayAdapter()
    guard = script.SpendGuard(inner, 10.0)
    payload = json.dumps({"type": "page_claims", "text": "p1r1c1: 5"})
    counted = guard.count_tokens(model=gateway.STRUCTURE_MODEL, system="S" * 1000, user_payload=payload, json_schema={})
    bound = gateway.estimate_cost_usd(gateway.STRUCTURE_MODEL, counted, 4000)
    tight = script.SpendGuard(inner, bound - 1e-9)
    tight.count_tokens(model=gateway.STRUCTURE_MODEL, system="S" * 1000, user_payload=payload, json_schema={})
    with pytest.raises(gateway.GatewayError) as stop:
        tight.complete(model=gateway.STRUCTURE_MODEL, system="S" * 1000, user_payload=payload, max_tokens=4000, temperature=None,
                       json_schema={})
    assert stop.value.reason == "spend_stop" and tight.stopped and inner.calls == 0
    guard.complete(model=gateway.STRUCTURE_MODEL, system="S" * 1000, user_payload=payload, max_tokens=4000, temperature=None, json_schema={})
    assert inner.calls == 1 and 0 < guard.spent < bound


def test_the_prompt_comes_from_the_store_and_a_missing_prompt_stops_the_run(script):
    store = script.MemoryDB()
    scratch = script.MemoryDB()
    scratch["prompts"].docs.clear()
    report = asyncio.run(script.run_pages(DECKS[:1], 1, scratch, script.PageReplayAdapter(), prompt_source=store))
    assert report["prompt_version"] == "v1" and report["decks_complete"] == 1
    assert [d["name"] for d in scratch["prompts"].docs] == ["deck_reading"], "copied from the store, the page prompt only"
    empty = script.MemoryDB()
    empty["prompts"].docs.clear()
    with pytest.raises(SystemExit, match="No prompt loaded"):
        asyncio.run(script.run_pages(DECKS[:1], 1, empty, script.PageReplayAdapter()))


def test_recorded_replies_are_written_per_pass_in_the_format_of_the_handwritten_ones(script, tmp_path):
    folder = tmp_path / "rec"
    _run(script, passes=2, decks=DECKS[:1], record_folder=folder)
    files = sorted(folder.glob("pass-*/*.json"))
    assert [p.parent.name for p in files] == ["pass-1", "pass-1", "pass-2", "pass-2"]
    handwritten = json.loads((BACKEND / "tests" / "fixtures" / "page_replies" / "buffer_p5.json").read_text(encoding="utf-8"))
    for path in files:
        recorded = json.loads(path.read_text(encoding="utf-8"))
        assert set(recorded) == {"file", "page", "match", "pass", "prompt_version", "model", "claims"}
        assert set(handwritten) - {"note"} <= set(recorded), "the hand-written files' keys, and the run's own"
        assert re.fullmatch(rf"p{recorded['page']}r\d+c\d+.*", recorded["match"]) and "\n" not in recorded["match"]
        assert recorded["claims"] and all(c["value_cell"].startswith(f"p{recorded['page']}r") for c in recorded["claims"])
    first = json.loads((folder / "pass-1" / "buffer_p5.json").read_text(encoding="utf-8"))
    # a recorded claim carries the four fields of the page-image answer form (null when the hand-written file has none)
    assert first["claims"] == [{**dict.fromkeys(("label_text", "segment", "share_of", "is_quote")), **c} for c in handwritten["claims"]], \
        "replayed and recorded again, the claims are the same"


def test_a_later_run_the_same_day_never_overwrites_an_earlier_report(script):
    first = script.pages_run_name(script.REPORTS)
    report, _ = _run(script, passes=1, decks=DECKS[:1])
    script.write_pages_report(report, script.REPORTS, first)
    second = script.pages_run_name(script.REPORTS)
    assert second == f"{first}-2" and script.pages_run_name(script.REPORTS) == second


def test_pages_refuses_a_deck_that_is_not_public_and_options_that_do_not_fit(script):
    with pytest.raises(SystemExit, match="--pages runs on the 10 public test decks only"):
        script.main(["--pages", "--fake", "--deck", "11-client.pdf"])
    with pytest.raises(SystemExit, match="cannot be combined"):
        script.main(["--pages", "--probe"])
    with pytest.raises(SystemExit, match="belong to --pages"):
        script.main(["--fake", "--zip", "x.zip"])
    with pytest.raises(SystemExit, match="more than 0"):
        script.main(["--pages", "--fake", "--max-spend", "0"])


def test_a_live_pages_run_needs_the_key_and_the_confirmation(script, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        script.main(["--pages", "--yes", "--deck", DECKS[0]])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-key")
    with pytest.raises(SystemExit, match="Re-run with --yes"):
        script.main(["--pages", "--deck", DECKS[0]])


# ---------------------------------------------------------------------------
# PR B analysis (live run of 2026-10-22): the passes bypass the cache, a cut reply is counted, the report and the recorded files agree
# ---------------------------------------------------------------------------
def test_every_pass_asks_the_model_and_the_report_counts_cache_hits(script):
    """Passes 2 and 3 read the same pages: in one audit they would be cache hits (0 tokens, the same reply) and measure nothing. The
    run bypasses the cache from pass 2 on and reports the hits, so a pass that measured the cache shows as such."""
    from app.structures import pages as pipeline
    seen = []
    original = pipeline.read_pages

    async def watching(*args, **kwargs):
        seen.append(kwargs.get("use_cache"))
        return await original(*args, **kwargs)
    with mock.patch.object(pipeline, "read_pages", watching):
        report, adapter = _run(script, passes=3, decks=DECKS[:1])
    assert seen == [True, False, False], "pass 1 may use the cache; the consistency passes never"
    deck = report["per_deck"][DECKS[0]]
    assert [r["cache_hits"] for r in deck["passes"]] == [0, 0, 0] and report["totals"]["cache_hits"] == 0
    assert adapter.calls == sum(r["batches"] for r in deck["passes"]), "every batch of every pass went to the model"


def test_a_cut_reply_is_counted_as_truncated_and_billed_by_the_guard(script):
    from app.llm import gateway

    class Cutting(script.PageReplayAdapter):
        """The provider cuts the reply of a batch of more than two pages (the first batch of each deck has five)."""

        def complete(self, *, model, system, user_payload, max_tokens, temperature, json_schema, cache_system=False, images=None):
            if json.loads(user_payload)["text"].count("\n") > 60:
                self.calls += 1
                error = gateway.GatewayError("truncated", "cut")
                error.tokens = (1000, max_tokens)
                raise error
            return super().complete(model=model, system=system, user_payload=user_payload, max_tokens=max_tokens,
                                    temperature=temperature, json_schema=json_schema, cache_system=cache_system, images=images)
    report, adapter = _run(script, Cutting(), passes=1, decks=DECKS[1:])
    row, = report["per_deck"][DECKS[1]]["passes"]
    assert row["truncated"] >= 2, "the 5-page batch was cut, then its larger half"
    assert row["batches"] > 2 and row["read"] >= 2 and row["claims"] > 0, "the halves were read"
    assert row["output_tokens"] >= row["truncated"] * gateway.PAGE_MAX_TOKENS, "the cut replies are billed"
    assert report["totals"]["truncated"] == row["truncated"]
    assert report["spent_usd"] >= gateway.estimate_cost_usd(gateway.STRUCTURE_MODEL, 1000, gateway.PAGE_MAX_TOKENS), "the guard counts the cut call"
    assert "truncated" in script.write_pages_report(report, script.REPORTS, "pages_test", fake=True).read_text(encoding="utf-8")


def test_the_report_claims_equal_the_recorded_claims_and_a_run_name_never_reuses_a_recorded_folder(script, tmp_path):
    """The run of 2026-10-22 committed a table and recorded files that disagree (371 claims in the files, 356 in the table): the
    recorded folder had been reused. The run name now skips a name whose recorded folder exists, the report is written after every
    pass beside the files, and each pass's row carries the number of claims recorded."""
    name = script.pages_run_name(script.REPORTS)
    (script.RECORDED / name).mkdir(parents=True)
    assert script.pages_run_name(script.REPORTS) == f"{name}-2", "a recorded folder left by a stopped run is never written into again"
    folder = script.RECORDED / f"{name}-2"
    report, _ = _run(script, passes=2, decks=DECKS[:1], record_folder=folder, report_path=script.REPORTS / f"{name}-2.md")
    for n, row in enumerate(report["per_deck"][DECKS[0]]["passes"], 1):
        recorded = sum(len(json.loads(f.read_text(encoding="utf-8"))["claims"]) for f in (folder / f"pass-{n}").glob("*.json"))
        assert row["recorded"] == recorded == row["claims"] > 0
    assert (script.REPORTS / f"{name}-2.md").is_file(), "written beside the recorded replies"


def test_the_report_is_written_after_every_pass_so_a_crash_keeps_the_figures_paid_for(script, tmp_path):
    """The gateway never raises for a model-side problem, so the crash is the process's own (here: the progress line of pass 2)."""
    path = script.REPORTS / "pages_test.md"

    def crashing(line, **_):
        if "pass 2/3" in line:
            raise RuntimeError("the process died")
    with pytest.raises(RuntimeError):
        _run(script, passes=3, decks=DECKS[:1], report_path=path, out=crashing)
    text = path.read_text(encoding="utf-8")
    assert "| 03-buffer.pptx | 1 |" in text and "| 03-buffer.pptx | 2 |" in text, "the passes paid for are in the report"
    assert "| 03-buffer.pptx | 3 |" not in text and "Fake run" in text


def test_a_page_reader_model_off_the_allow_list_stops_the_pages_run_before_any_file_is_converted_or_drawn(script, monkeypatch):
    from app.decks import render
    monkeypatch.setenv("PAGE_READER_MODEL", "claude-fable-5-1")
    touched = []
    monkeypatch.setattr(render, "to_pdf", lambda *a, **k: touched.append("to_pdf"))
    monkeypatch.setattr(render, "render_page", lambda *a, **k: touched.append("render_page"))
    with pytest.raises(SystemExit) as stop:
        _run(script, decks=DECKS[:1])
    assert "model not permitted" in str(stop.value) and touched == []
