"""The manual scripts in scripts/ run on Python 3.11 as well as on the backend venv's Python (3.13).

consistency_run.py had a double-quoted key inside a double-quoted f-string (PEP 701, Python 3.12+): it imported on the venv
and failed on 3.11 with "f-string: unmatched '['". An import under the venv cannot see that, so the syntax is also checked
without the interpreter (tokens and ast with feature_version 3.11) and, where a python3.11 exists, by compiling under it."""
import ast
import io
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
FILES = sorted(SCRIPTS.glob("*.py"))
_PREFIX = "rRfFbBuU"


def py312_only_syntax(source):
    """Lines where the source needs Python 3.12 or later: what ast.parse(feature_version=(3, 11)) refuses (type statements and
    parameters), and a string quote reused inside an f-string's own braces (PEP 701), which the parser accepts on 3.12+ whatever
    the feature version."""
    problems = []
    try:
        ast.parse(source, feature_version=(3, 11))
    except SyntaxError as exc:
        problems.append((exc.lineno, exc.msg))
    if sys.version_info >= (3, 12):
        open_quotes = []
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.FSTRING_START:
                quote = tok.string.lstrip(_PREFIX)
                if quote in open_quotes:
                    problems.append((tok.start[0], f"f-string reuses the quote {quote} of an enclosing f-string"))
                open_quotes.append(quote)
            elif tok.type == tokenize.FSTRING_END:
                open_quotes.pop()
            elif tok.type == tokenize.STRING and open_quotes:
                quote = tok.string.lstrip(_PREFIX)[:len(open_quotes[-1])]
                if quote in open_quotes:
                    problems.append((tok.start[0], f"string reuses the quote {quote} of an enclosing f-string"))
    return problems


def test_the_syntax_check_sees_a_quote_reused_inside_an_fstring():
    """A deliberate violation: the line that broke consistency_run.py on 3.11."""
    if sys.version_info < (3, 12):
        pytest.skip("the tokenizer of this interpreter has no f-string tokens")
    assert py312_only_syntax('x = f"{report["prompt_version"]}"\n')
    assert py312_only_syntax("x = f'{report['prompt_version']}'\n")
    assert py312_only_syntax('x = f"{f"{a}"}"\n')
    assert py312_only_syntax("type Pair = tuple[int, int]\n")
    assert not py312_only_syntax("x = f\"{report['prompt_version']}\"\n")
    assert not py312_only_syntax('x = f"{a}" "{b}" f\'{c["k"]}\'\n')


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_a_script_uses_no_syntax_from_python_312(path):
    assert FILES and not py312_only_syntax(path.read_text(encoding="utf-8")), path.name


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_a_script_compiles_under_python_311(path):
    python = shutil.which("python3.11")
    if not python:
        pytest.skip("no python3.11 on this machine")
    done = subprocess.run([python, "-I", "-c", "import sys; compile(open(sys.argv[1], encoding='utf-8').read(), sys.argv[1], 'exec')",
                           str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_a_script_imports_under_the_backend_venv_python(path):
    code = ("import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('script_under_test', sys.argv[1])\n"
            "spec.loader.exec_module(importlib.util.module_from_spec(spec))\n")
    done = subprocess.run([sys.executable, "-I", "-c", code, str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
