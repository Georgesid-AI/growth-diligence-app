"""Server-side prompt loading.

This is the ONLY module in `app.llm` permitted to touch the filesystem, and it
may only read `.md` files inside `prompts/`. Prompt text is config, not audit
data - no uploaded file, raw byte stream, or parsed deck text is reachable from
here, because `_resolve` refuses any path that escapes the prompts directory.

Prompt text never leaves the server. The gateway surfaces the version string
only; `load()` returns the body for internal use and callers must not put it in
an API response. `tests/test_llm_gateway.py::test_prompt_text_never_returned`
guards that.
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
# cache keys were before releases existed, so adopting releases invalidates nothing.
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


def release_manifest() -> dict:
    """{prompt name: sha256 of its file} as recorded in RELEASE.md."""
    out = {}
    for line in _release_lines():
        parts = line.split()
        if len(parts) == 2 and parts[0].endswith(".md") and parts[1].startswith("sha256:"):
            out[parts[0][:-3]] = parts[1][len("sha256:"):]
    return out


def file_hash(name: str) -> str:
    import hashlib
    return hashlib.sha256(_resolve(name).read_bytes()).hexdigest()


def release_in_cache_key() -> bool:
    """Whether the release stamp is part of the cache key.

    Off by default: turning it on makes a release bump invalidate every step's
    cached narrative together. Set LLM_PROMPT_RELEASE_IN_CACHE_KEY=1 to enable.
    """
    import os
    return os.environ.get("LLM_PROMPT_RELEASE_IN_CACHE_KEY", "").strip() == "1"


def cache_tag(prompt: Prompt) -> str:
    """The prompt identity used in the cache key.

    The plain version until the release stamp is enabled in the key; with it
    enabled, the baseline release still yields the plain version (so nothing is
    invalidated by enabling it) and any later release yields "rN:version".
    """
    if not release_in_cache_key():
        return prompt.version
    stamp = release()
    return prompt.version if stamp == BASELINE_RELEASE else f"{stamp}:{prompt.version}"


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


def _record() -> None:  # pragma: no cover - maintenance helper
    """Rewrite RELEASE.md's hashes from the prompt files on disk (keeps the stamp)."""
    stamp = release()
    names = sorted(p.stem for p in PROMPTS_DIR.glob("*.md") if p.stem != RELEASE_FILE)
    body = [
        f"<!-- release: {stamp} -->",
        "<!-- One stamp shared by every prompt. Editing any prompt file means bumping the release",
        "     and re-recording its hash below (python -m app.llm.prompt_store --record); the",
        "     test suite fails if a hash is stale. -->",
    ] + [f"{n}.md sha256:{file_hash(n)}" for n in names]
    (PROMPTS_DIR / f"{RELEASE_FILE}.md").write_text("\n".join(body) + "\n", encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    import sys
    if "--record" in sys.argv:
        _record()
