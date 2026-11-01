"""The path filter of the fixture job covers everything the sheet reader imports (.github/reading-path.txt is the one list)."""
import ast
import fnmatch
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
LISTED = [line.strip() for line in (REPO / ".github" / "reading-path.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]
WORKFLOW = yaml.safe_load((REPO / ".github" / "workflows" / "reading-fixtures.yml").read_text())
# PyYAML reads the key `on` as True.
FILTER = (WORKFLOW.get("on") or WORKFLOW[True])["pull_request"]["paths"]


def matches(path, patterns):
    return any(fnmatch.fnmatch(path, p.replace("**", "*")) for p in patterns)


def imported_modules(path):
    """The app modules a file imports at any depth (module level or inside a function), as repo-relative paths."""
    out = []
    base = path.parent
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                mod = base
                for _ in range(node.level - 1):
                    mod = mod.parent
                mod = mod / node.module.replace(".", "/") if node.module else mod
            elif (node.module or "").split(".")[0] in ("app", "schemas"):
                mod = BACKEND / node.module.replace(".", "/")
            else:
                continue
            names = [a.name for a in node.names]
            for cand in [mod.with_suffix(".py"), mod / "__init__.py"] + [(mod / n).with_suffix(".py") for n in names]:
                if cand.exists():
                    out.append(cand)
    return out


def reading_path():
    """Every app file sheet_reader reaches; app/llm is one boundary, listed whole."""
    seen, stack = set(), [BACKEND / "app" / "sheet_reader.py"]
    while stack:
        f = stack.pop()
        if f in seen:
            continue
        seen.add(f)
        if "app/llm/" in f.as_posix():
            continue
        stack += imported_modules(f)
    return sorted(f.relative_to(REPO).as_posix() for f in seen)


def test_workflow_filter_carries_every_listed_path():
    in_filter = [p for p in FILTER if p.startswith(("backend/app/", "backend/schemas/"))]
    assert sorted(in_filter) == sorted(LISTED)


def test_listed_paths_cover_everything_the_sheet_reader_imports():
    missing = [f for f in reading_path() if not matches(f, LISTED)]
    assert not missing, f"imported by the sheet reader but not in .github/reading-path.txt: {missing}"


def test_the_modules_that_replaced_recognition_are_listed_and_recognition_is_gone():
    assert {"backend/app/periods.py", "backend/app/stored_sheets.py", "backend/app/role_engine.py"} <= set(LISTED)
    assert "backend/app/recognition.py" not in LISTED and not (REPO / "backend" / "app" / "recognition.py").exists()


DECK_LISTED = [line.strip() for line in (REPO / ".github" / "deck-reading-path.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]


def test_the_deck_fixture_has_its_own_narrower_path_that_the_workflow_reads():
    text = (REPO / ".github" / "workflows" / "reading-fixtures.yml").read_text()
    assert DECK_LISTED and ".github/deck-reading-path.txt" in text and "DECK_FIXTURE=1" in text
    assert "env.DECK_FIXTURE == '1'" in text, "the LibreOffice install runs only when the deck fixture does"
    for entry in DECK_LISTED:
        assert (REPO / entry).exists(), entry
        assert matches(entry, FILTER) or matches(entry.rstrip("/") + "/x", FILTER), f"{entry} is not on the reading path, so the job would not run for it"
    assert len(DECK_LISTED) < len(LISTED), "the deck path is narrower than the reading path"
    for sheet_only in ("backend/app/sheet_reader.py", "backend/app/checks.py", "backend/app/readings.py"):
        assert not any(sheet_only.startswith(e) for e in DECK_LISTED), f"{sheet_only} must not run the deck fixture"
