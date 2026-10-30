"""Reads each fixture of the sheet reader once with the real model and compares the reading with its expected map
(docs/design/read-check-review.md section 10; CLAUDE.md rule 26).

    python scripts/run_reading_fixtures.py

Runs in CI only when the reading path changes (.github/workflows/reading-fixtures.yml). Needs two things from the environment and skips with a
notice, exit 0, when any is absent:

    ANTHROPIC_API_KEY     the provider key (a GitHub Actions secret)
    SHEET_READING_PROMPT  the text of the `sheet_reading` prompt (a GitHub Actions secret: the prompt is never in the repository)
    SHEET_READER_MODEL    optional: an allow-listed model id (a repository variable); the structure model when unset

The cap is one provider call per fixture per run: each file is read once, with no re-read, and the first reading is what is compared. The
reading goes through the same gateway as the product (masking, token cap, allow-listed model, prompt from a store), with an in-memory store holding
the prompt. A difference, a refusal or a failed read exits 1. Cost: a few cents per run. Prints a table; no cell text is printed.
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
        self.adapter, self.calls = adapter, 0

    def complete(self, **kw):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("the cap is one provider call per fixture per run")
        return self.adapter.complete(**kw)

    def count_tokens(self, **kw):
        return self.adapter.count_tokens(**kw)


async def read_all() -> int:
    import reading_fixtures as rf
    import test_llm_gateway as t
    from app import checks, column_rules as cr
    from app.llm import gateway
    from app.llm.schemas import SHEET_READING
    from app.structures import reading_input
    db = t.FakeDB()
    db["prompts"].docs[:] = [{"name": "sheet_reading", "version": "v1", "text": os.environ["SHEET_READING_PROMPT"], "uploaded_at": "2026-01-01T00:00:00+00:00",
                              "sha256": hashlib.sha256(os.environ["SHEET_READING_PROMPT"].encode()).hexdigest()}]
    failed = 0
    print(f"{'fixture':26} {'status':10} {'month':8} {'tokens in/out':14} differences")
    for fixture in rf.sheet_fixtures():
        name, path = fixture["name"], fixture["path"]
        audit = f"fx-{name}"
        db["audits"].docs.append({"id": audit, "company_name": rf.COMPANY, "structure_reading_consent": True})
        sheets = cr.read_workbook(path.read_bytes(), path.name)
        text = reading_input.reading_text(sheets)
        adapter = OneCall(gateway.AnthropicAdapter(timeout=gateway.SHEET_READING_TIMEOUT_SECONDS))
        read = await gateway.read_structure(db, audit, text, SHEET_READING, file_hash=hashlib.sha256(path.read_bytes()).hexdigest(), adapter=adapter)
        if read.status != "read":
            failed += 1
            print(f"{name:26} {read.status:10} {'-':8} {'-':14} {read.reason}")
            continue
        result = checks.check_map(checks.Cells(read.payload), read.file_map, 12)
        month = max((m["month"] for m in result["months"]), default=None)
        diffs = rf.compare(fixture["expected_map"], month, read.file_map)
        failed += bool(diffs)
        counts = result["counts"]
        print(f"{name:26} {'read':10} {month or '-':8} {read.input_tokens}/{read.output_tokens:<8} "
              f"{'; '.join(diffs) if diffs else 'none'}  [confirmed {counts['confirmed']}, rejected {counts['rejected']}, cannot check {counts['cannot_check']}]")
    print(f"{failed} fixture(s) differ from their expected map" if failed else "every fixture agrees with its expected map")
    return 1 if failed else 0


def main() -> int:
    if "SHEET_READING_PROMPT" in os.environ and not os.environ["SHEET_READING_PROMPT"].strip():
        print("::error title=Reading fixtures::SHEET_READING_PROMPT is set but empty: add the prompt text to the repository secret.")
        return 1
    missing = [n for n in NEEDED if not os.environ.get(n, "").strip()]
    if missing:
        notice("not set: " + ", ".join(missing) + ". The job needs the key and the prompt as secrets and the model as a variable.")
        return 0
    return asyncio.run(read_all())


if __name__ == "__main__":
    sys.exit(main())
