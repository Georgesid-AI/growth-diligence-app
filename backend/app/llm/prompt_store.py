"""Server-side prompt loading.

This is the ONLY module in `app.llm` permitted to touch the filesystem, and it
may only read `.md` files inside `prompts/`. Prompt text is config, not audit
data - no uploaded file, raw byte stream, or parsed deck text is reachable from
here, because `_resolve` refuses any path that escapes the prompts directory.

Prompt text never leaves the server. The gateway surfaces the version string
only; `load()` returns the body for internal use and callers must not put it in
an API response. `tests/test_llm_gateway.py::test_prompt_text_never_returned`
guards that.

The prompts serve the two paths of CLAUDE.md rules 16-18: `growth_engine` writes from computed
results; `structure_reading` reads redacted deck structures and spreadsheet header rows (at most 3,
with up to 3 samples per numeric or date column or a profile per text column), sent only with the
audit's consent as extracted text with cell positions, a deck structure with the item list Python
made from its cells. It asks for structured JSON with no free text, so a reply cannot carry deck
prose into a log (rule 17): the model labels the figures Python listed, so every value and cell is
Python's, and Python rebuilds every period before an item can be Verified (rule 18). A prompt's
version is part of every cache key and of the stored model output.

Build rule (architecture note of 2026-10-07): any change to a prompt's text bumps its `version:`
line, whether or not that version has run live. A version names exactly one text, so readings
stored under it stay comparable; the release stamp then moves too, as below. RELEASE.md records
each prompt's version beside its hash, and `--record` refuses a changed text under its old version.
"""
from pathlib import Path
from typing import NamedTuple

PROMPTS_DIR = Path(__file__).parent / "prompts"

_VERSION_MARKER = "version:"
_RELEASE_MARKER = "release:"

# The release every run is on. A release is one stamp shared by all prompt files:
# changing any prompt means bumping it, so a run never mixes prompt versions.
# RELEASE.md records the stamp and each prompt file's hash; a test fails if a prompt
# is edited without the stamp being bumped.
RELEASE_FILE = "RELEASE"
# The first release. Its cache tag is the plain prompt version, exactly what the
# cache keys were before releases existed, so adopting releases invalidated nothing.
BASELINE_RELEASE = "r1"


class Prompt(NamedTuple):
    name: str
    version: str
    text: str


def _resolve(name: str) -> Path:
    """Map a prompt name to a path inside PROMPTS_DIR, or refuse.

    Rejects traversal (`../`), absolute paths, and anything that resolves
    outside the prompts directory. A prompt name is a flat identifier.
    """
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(f"invalid prompt name: {name!r}")
    path = (PROMPTS_DIR / f"{name}.md").resolve()
    if path.parent != PROMPTS_DIR.resolve():
        raise ValueError(f"prompt path escapes prompts dir: {name!r}")
    return path


def load(name: str) -> Prompt:
    """Read a versioned prompt. Raises FileNotFoundError if it does not exist."""
    path = _resolve(name)
    if not path.is_file():
        raise FileNotFoundError(f"no prompt file for step {name!r} at {path.name}")
    raw = path.read_text(encoding="utf-8")
    version = _parse_version(raw, name)
    return Prompt(name=name, version=version, text=raw)


def _release_lines() -> list:
    path = _resolve(RELEASE_FILE)
    if not path.is_file():
        raise FileNotFoundError(f"no {RELEASE_FILE}.md in the prompts directory")
    return path.read_text(encoding="utf-8").splitlines()


def release() -> str:
    """The prompt release stamp for this deployment, e.g. "r1"."""
    for line in _release_lines()[:10]:
        stripped = line.strip().lstrip("<!-").strip()
        if stripped.lower().startswith(_RELEASE_MARKER):
            value = stripped[len(_RELEASE_MARKER):].strip().rstrip("->").strip()
            if value:
                return value
    raise ValueError(f"{RELEASE_FILE}.md has no 'release:' line in its first 10 lines")


def _manifest_entries() -> dict:
    """{prompt name: (version or None, sha256)} from RELEASE.md's `name.md vN sha256:...` lines (a line
    written before versions were recorded has no vN)."""
    out = {}
    for line in _release_lines():
        parts = line.split()
        if len(parts) in (2, 3) and parts[0].endswith(".md") and parts[-1].startswith("sha256:"):
            out[parts[0][:-3]] = (parts[1] if len(parts) == 3 else None, parts[-1][len("sha256:"):])
    return out


def release_manifest() -> dict:
    """{prompt name: sha256 of its file} as recorded in RELEASE.md."""
    return {name: digest for name, (_, digest) in _manifest_entries().items()}


def recorded_versions() -> dict:
    """{prompt name: the version RELEASE.md recorded its hash under}."""
    return {name: version for name, (version, _) in _manifest_entries().items()}


def file_hash(name: str) -> str:
    import hashlib
    return hashlib.sha256(_resolve(name).read_bytes()).hexdigest()


def tag_for(release_stamp: str, version: str) -> str:
    """The prompt identity used in a cache key for a given release and file version.

    The baseline release keeps the plain version - exactly what keys were before
    releases existed - so adopting the stamp invalidated nothing. Any later release
    yields "rN:version": bumping the release moves every step's key at once.
    """
    return version if release_stamp == BASELINE_RELEASE else f"{release_stamp}:{version}"


def cache_tag(prompt: Prompt) -> str:
    """The prompt identity for the cache key under the current release."""
    return tag_for(release(), prompt.version)


def version_of(name: str) -> str:
    """The version string alone - safe to log and to return to clients."""
    return load(name).version


def _parse_version(raw: str, name: str) -> str:
    """Pull `version: vN` out of the prompt's leading comment block."""
    for line in raw.splitlines()[:10]:
        stripped = line.strip().lstrip("<!-").strip()
        if stripped.lower().startswith(_VERSION_MARKER):
            version = stripped[len(_VERSION_MARKER):].strip().rstrip("->").strip()
            if version:
                return version
    raise ValueError(f"prompt {name!r} has no 'version:' line in its first 10 lines")


def _record() -> None:
    """Rewrite RELEASE.md's hashes from the prompt files on disk (keeps the stamp). Refuses a prompt whose
    text changed while its version did not: a version names one text (build rule above)."""
    stamp = release()
    recorded = _manifest_entries()
    names = sorted(p.stem for p in PROMPTS_DIR.glob("*.md") if p.stem != RELEASE_FILE)
    for name in names:
        version, digest = recorded.get(name, (None, None))
        if version == version_of(name) and digest not in (None, file_hash(name)):
            raise SystemExit(f"{name}.md changed but is still {version}: bump its version: line, then record.")
    body = [
        f"<!-- release: {stamp} -->",
        "<!-- One stamp shared by every prompt. Editing any prompt file means bumping its version: line",
        "     and the release, then re-recording its hash below (python -m app.llm.prompt_store --record);",
        "     --record refuses a changed text under its old version, and the test suite fails if a hash",
        "     is stale. -->",
    ] + [f"{n}.md {version_of(n)} sha256:{file_hash(n)}" for n in names]
    (PROMPTS_DIR / f"{RELEASE_FILE}.md").write_text("\n".join(body) + "\n", encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    import sys
    if "--record" in sys.argv:
        _record()
