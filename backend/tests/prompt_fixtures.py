"""The fake prompt store for tests (docs/specs/prompt-store.md; CLAUDE.md rule 26).

The real prompts are never in the repository. Each name the gateway reads has a one-line stub in
tests/fixtures/prompts/, marked "test only"; `stub_documents()` returns them as `prompts` collection documents
(v1 each, exactly what `prompt_store.upload` writes), and FakeDB and the consistency script's MemoryDB start with them.
A test that needs an empty store clears `db["prompts"].docs`.
"""
import hashlib
from pathlib import Path

STUBS = Path(__file__).resolve().parent / "fixtures" / "prompts"
UPLOADED_AT = "2026-01-01T00:00:00+00:00"


def stub_documents():
    docs = []
    for path in sorted(STUBS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        assert "TEST ONLY" in text, f"{path.name} must be marked as a test-only stub"
        docs.append({"name": path.stem, "version": "v1", "text": text, "uploaded_at": UPLOADED_AT,
                     "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    return docs
