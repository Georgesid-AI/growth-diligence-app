"""Reads each fixture of the sheet reader once with the real model and compares the reading with its expected map
(docs/design/read-check-review.md section 10; CLAUDE.md rule 26).

    python scripts/run_reading_fixtures.py

Runs in CI only when the reading path changes (.github/workflows/reading-fixtures.yml). Needs two things from the environment and skips with a
notice, exit 0, when any is absent:

    ANTHROPIC_API_KEY     the provider key (a GitHub Actions secret)
    SHEET_READING_PROMPT  the text of the `sheet_reading` prompt (a GitHub Actions secret: the prompt is never in the repository)
    SHEET_READER_MODEL    optional: an allow-listed model id (a repository variable); the structure model when unset
    DECK_FIXTURE          "1" when the pull request changed a file of .github/deck-reading-path.txt (the workflow sets it)
    DECK_READING_PROMPT   the text of the `deck_reading` prompt (a secret). The deck fixture is read only when both are set, the workflow's own
                          condition for installing the converter; otherwise it is listed as "skipped: deck path unchanged" and is no difference

The cap is one provider call per fixture per run: each file is read once, with no re-read, and the first reading is what is compared. The
reading goes through the same gateway as the product (masking, token cap, allow-listed model, prompt from a store), with an in-memory store holding
the prompt and nothing else: every run starts from an empty store, and a fixture served from storage instead of the model fails the job. A difference, a refusal or a failed read exits 1. Cost: a few cents per run. Prints a table and the reason text of every cannot-check item (fixtures are synthetic).
"""
import asyncio
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

NEEDED = ("ANTHROPIC_API_KEY", "SHEET_READING_PROMPT")


def notice(text: str) -> None:
    print(f"::notice title=Reading fixtures skipped::{text}")


class OneCall:
    """The provider adapter, counting: one call per fixture is the cap, and a second one is an error."""

    def __init__(self, adapter):
        self.adapter, self.calls, self.tokens_in, self.tokens_out = adapter, 0, 0, 0

    def complete(self, **kw):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("the cap is one provider call per fixture per run")
        reply = self.adapter.complete(**kw)
        self.tokens_in, self.tokens_out = reply[1], reply[2]
        return reply

    def count_tokens(self, **kw):
        return self.adapter.count_tokens(**kw)


def empty_store(prompt_text: str, deck_prompt: str = ""):
    """A fresh in-memory store holding the `sheet_reading` prompt and no stored reading, so each run reads every fixture with the model."""
    import test_llm_gateway as t
    from app import readings
    db = t.FakeDB()
    db["prompts"].docs[:] = [{"name": "sheet_reading", "version": "v1", "text": prompt_text, "uploaded_at": "2026-01-01T00:00:00+00:00",
                              "sha256": hashlib.sha256(prompt_text.encode()).hexdigest()}]
    if deck_prompt.strip():
        db["prompts"].docs.append({"name": "deck_reading", "version": "v1", "text": deck_prompt, "uploaded_at": "2026-01-01T00:00:00+00:00",
                                   "sha256": hashlib.sha256(deck_prompt.encode()).hexdigest()})
    for collection in readings.COLLECTIONS:
        assert not db[collection].docs, f"the job's store must start without {collection}"
    return db


def deck_due() -> bool:
    """The deck fixture is read only when the workflow's condition for installing the converter holds: DECK_FIXTURE=1 and the deck prompt set."""
    return os.environ.get("DECK_FIXTURE") == "1" and bool(os.environ.get("DECK_READING_PROMPT", "").strip())


def converter_detail(fmt: str) -> str:
    """Why the converter did not produce a PDF, for the log: the binary found (or not found), then the exit code and the first line of stderr
    of one conversion of the fixture. Fixtures are synthetic, so their stderr may be logged."""
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    import reading_fixtures as rf
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if not binary:
        return "binary not found (soffice, libreoffice)"
    path = rf.FIXTURES / "deck_rotated_axis.pptx"
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / f"deck.{fmt}"
        source.write_bytes(path.read_bytes())
        try:
            run = subprocess.run([binary, "--headless", "--norestore", f"-env:UserInstallation=file://{tmp}/profile", "--convert-to", "pdf",
                                  "--outdir", tmp, str(source)], capture_output=True, text=True, timeout=120)
        except (subprocess.SubprocessError, OSError) as exc:
            return f"binary {binary}: {type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}".strip()
        stderr = ((run.stderr or run.stdout or "").strip().splitlines() or ["(no output)"])[0]
        produced = (Path(tmp) / "deck.pdf").exists()
        return f"binary {binary}, exit code {run.returncode}, pdf {'produced' if produced else 'not produced'}, stderr: {stderr}"


def deck_images_problem() -> str:
    """Draws the page images of the deck fixture before anything is read: "" when they can be made, else the reason. The job never reads a
    deck as text alone, so a missing converter fails here, before the first provider call."""
    import reading_fixtures as rf
    from app.decks import render
    path = rf.FIXTURES / "deck_rotated_axis.pptx"
    fmt = path.suffix.lstrip(".").lower()
    problem = render.converter_problem(fmt)
    if problem:
        return f"{problem} [{converter_detail(fmt)}]"
    try:
        pdf = render.to_pdf(path.read_bytes(), fmt)
        if not render.page_count(pdf):
            return "the deck fixture has no page"
        render.render_page(pdf, 1)
    except render.PageImageError as exc:
        return f"{exc.reason} [{converter_detail(fmt)}]"
    except Exception as exc:
        return f"the deck fixture could not be drawn ({type(exc).__name__})"
    return ""


async def read_all() -> int:
    import reading_fixtures as rf
    from app import checks, column_rules as cr, sheet_reader
    from app.llm import gateway
    from app.llm.schemas import SHEET_READING
    from app.structures import reading_input
    db = empty_store(os.environ["SHEET_READING_PROMPT"], os.environ.get("DECK_READING_PROMPT", ""))
    failed = 0
    print(f"{'fixture':26} {'status':10} {'month':8} {'tokens in/out':14} differences")
    for fixture in rf.sheet_fixtures():
        name, path = fixture["name"], fixture["path"]
        audit = f"fx-{name}"
        db["audits"].docs.append({"id": audit, "company_name": rf.COMPANY, "structure_reading_consent": True})
        sheets = cr.read_workbook(path.read_bytes(), path.name)
        adapter = OneCall(gateway.AnthropicAdapter(timeout=gateway.SHEET_READING_TIMEOUT_SECONDS))
        got = {}
        doc = await sheet_reader.read_file(db, {"id": audit}, sheets, hashlib.sha256(path.read_bytes()).hexdigest(), path.name, 12, adapter=adapter,
                                           capture=got)
        if doc["status"] != "read":
            failed += 1
            print(f"{name:26} {doc['status']:10} {'-':8} {'-':14} {doc.get('reason')}")
            continue
        if doc["cache_hit"]:
            failed += 1
            print(f"{name:26} {'stored':10} {'-':8} {'-':14} served from storage, not read by the model: a stored reading must never be reused here")
            continue
        # The job's cap is one call per fixture, so a re-read of rejected items is refused by the cap and fails; the first reading stands
        # and the file is reported as read, with the rejected count (a failed re-read never makes a file not read).
        month = doc["month"]
        diffs = rf.compare(fixture["expected_map"], month, got["file_map"])
        failed += bool(diffs)
        counts = doc["counts"]
        print(f"{name:26} {'read':10} {month or '-':8} {f'{adapter.tokens_in}/{adapter.tokens_out}':14} "
              f"{'; '.join(diffs) if diffs else 'none'}  [confirmed {counts['confirmed']}, rejected {counts['rejected']}, cannot check {counts['cannot_check']}]")
        result = {"items": doc["items"]}
        for item in result["items"]:
            if item["outcome"] == checks.CANNOT:
                print(f"    cannot check {item['key']}: {item['reason']}")
    if deck_due():
        failed += await read_decks(db)
    else:
        print(f"{'deck_rotated_axis':26} {'skipped':10} {'-':8} {'-':14} skipped: deck path unchanged")
    print(f"{failed} fixture(s) differ from their expected map" if failed else "every fixture agrees with its expected map")
    return 1 if failed else 0


async def read_decks(db, adapter=None) -> int:
    """The deck fixtures, read once through the page reader and checked against the stored page text (app/deck_figures.py): every expected
    figure must be read and confirmed, and the parts must add up to the headline. Skipped with a notice when the `deck_reading` prompt is not
    set. The cap is one provider call per page with a figure. Returns the number of fixtures that differ."""
    import reading_fixtures as rf
    from app import deck_figures, structures
    from app.decks import TEXT_COLLECTION, pages as grids_mod, parser
    failed = 0
    for fixture in rf.deck_fixtures():
        name, path = fixture["name"], fixture["path"]
        if not any(p["name"] == "deck_reading" for p in db["prompts"].docs):
            print(f"::notice title=Deck fixture skipped::DECK_READING_PROMPT is not set, so {name} was not read.")
            continue
        audit = f"fx-{name}"
        db["audits"].docs.append({"id": audit, "company_name": rf.COMPANY, "structure_reading_consent": True, "fiscal_year_end": 12})
        db["datasets"].docs.append({"audit_id": audit, "dtype": "revenue", "recognition_only": True, "mapped_at": "2026-01-01T00:00:00+00:00"})
        deck = parser.parse_deck(path.read_bytes(), path.name)
        deck_id = f"deck-{name}"
        sendable = len(grids_mod.sendable(grids_mod.page_grids(deck["blocks"])))
        await db[TEXT_COLLECTION].insert_one({"audit_id": audit, "deck_id": deck_id, "file": deck["file"], "format": deck["format"],
                                              "page_unit": deck["page_unit"], "pages": deck["pages"], "blocks": deck["blocks"],
                                              "layout": deck.get("layout") or [], "structures": deck["structures"], "ai_status": "reading"})
        adapter_in = adapter or CallCap(gateway_adapter(), sendable)
        status = await structures.process_deck(db, audit, deck_id, adapter=adapter_in)
        checked = [d for d in await deck_figures.checked(db, audit) if d["deck_id"] == deck_id]
        figures = checked[0]["figures"] if checked else []
        diffs = rf.compare_deck(fixture["expected_map"], figures)
        failed += bool(diffs)
        counts = {o: sum(1 for f in figures if f["outcome"] == o) for o in ("confirmed", "rejected", "cannot_check")}
        print(f"{name:26} {status[:10]:10} {'-':8} {'-':14} {'; '.join(diffs) if diffs else 'none'}  [confirmed {counts['confirmed']}, "
              f"rejected {counts['rejected']}, cannot check {counts['cannot_check']}]")
        for f in figures:
            if f["outcome"] != "confirmed":
                print(f"    {f['outcome']} page {f['source']['page']}: {f['reason']}")
    return failed


def gateway_adapter():
    from app.llm import gateway
    return gateway.AnthropicAdapter()


class CallCap:
    """The page reader's adapter, counting: one call per page with a figure is the cap."""

    def __init__(self, adapter, limit: int):
        self.adapter, self.limit, self.calls = adapter, limit, 0

    def complete(self, **kw):
        self.calls += 1
        if self.calls > self.limit:
            raise RuntimeError("the cap is one provider call per page with a figure")
        return self.adapter.complete(**kw)

    def count_tokens(self, **kw):
        return self.adapter.count_tokens(**kw)


def main() -> int:
    if "SHEET_READING_PROMPT" in os.environ and not os.environ["SHEET_READING_PROMPT"].strip():
        print("::error title=Reading fixtures::SHEET_READING_PROMPT is set but empty: add the prompt text to the repository secret.")
        return 1
    missing = [n for n in NEEDED if not os.environ.get(n, "").strip()]
    if missing:
        notice("not set: " + ", ".join(missing) + ". The job needs the key and the prompt as secrets and the model as a variable.")
        return 0
    # The deck fixture is drawn first and then read by the model like the sheets (read_all -> read_decks); when it is due and its pages cannot
    # be drawn the job stops before any provider call.
    problem = deck_images_problem() if deck_due() else ""
    if problem:
        print(f"page images unavailable: {problem}")
        return 1
    return asyncio.run(read_all())


if __name__ == "__main__":
    sys.exit(main())
