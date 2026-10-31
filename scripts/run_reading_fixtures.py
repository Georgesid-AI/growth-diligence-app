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
        self.adapter, self.calls = adapter, 0

    def complete(self, **kw):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("the cap is one provider call per fixture per run")
        return self.adapter.complete(**kw)

    def count_tokens(self, **kw):
        return self.adapter.count_tokens(**kw)


def empty_store(prompt_text: str):
    """A fresh in-memory store holding the `sheet_reading` prompt and no stored reading, so each run reads every fixture with the model."""
    import test_llm_gateway as t
    from app import readings
    db = t.FakeDB()
    db["prompts"].docs[:] = [{"name": "sheet_reading", "version": "v1", "text": prompt_text, "uploaded_at": "2026-01-01T00:00:00+00:00",
                              "sha256": hashlib.sha256(prompt_text.encode()).hexdigest()}]
    for collection in readings.COLLECTIONS:
        assert not db[collection].docs, f"the job's store must start without {collection}"
    return db


async def read_all() -> int:
    import reading_fixtures as rf
    from app import checks, column_rules as cr, sheet_reader
    from app.llm import gateway
    db = empty_store(os.environ["SHEET_READING_PROMPT"])
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
        print(f"{name:26} {'read':10} {month or '-':8} {'-':14} "
              f"{'; '.join(diffs) if diffs else 'none'}  [confirmed {counts['confirmed']}, rejected {counts['rejected']}, cannot check {counts['cannot_check']}]")
        result = {"items": doc["items"]}
        for item in result["items"]:
            if item["outcome"] == checks.CANNOT:
                print(f"    cannot check {item['key']}: {item['reason']}")
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
