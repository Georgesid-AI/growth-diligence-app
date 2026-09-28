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
