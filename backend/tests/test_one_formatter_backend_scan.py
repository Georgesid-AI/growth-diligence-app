"""One number formatter (docs/design/read-check-review.md section 11.5, PR 3): only app/formatting.py turns a number into display text. This
scan fails on any other file of backend/app that formats a number in an f-string or a str.format template with a precision, a grouping or a
percent spec (`:.1f`, `:,.0f`, `:,`, `:g`, `:.0%`), or that writes a space before a percent sign after a number. Dates and identifiers
(`:02d`, `:04d`) are not numbers for display and are not matched.

An exception is a line with its reason in ALLOWED, kept short: a cost in USD (the display rule would write 0.0123 as "0") and a value inside a
masked payload that is compared, not shown."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SPEC = re.compile(r"\{[^{}]*?:[+]?(?:,?\.\d+[f%]|,?[fg%]|,d?)\}")
DYNAMIC = re.compile(r"\{[^{}]*?:[^{}]*\{[^{}]*\}[^{}]*[fg%]\}")                # {value:,.{places}f}
SPACE_PERCENT = re.compile(r"\{[^{}]*\} %")
ALLOWED = {
    ("llm/guards.py", "spent today against"): "a USD cost to the mill: the display rule would show a cost of 0.0123 as 0",
    ("llm/redaction.py", '.rstrip("0")'): "a token in the masked payload, compared with the cell text, never shown",
}


def offenders():
    found = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        if rel == "formatting.py":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if (SPEC.search(line) or DYNAMIC.search(line) or SPACE_PERCENT.search(line)) and not any(f == rel and w in line for (f, w) in ALLOWED):
                found.append(f"{rel}:{n}: {line.strip()[:120]}")
    return found


def test_only_the_formatting_module_formats_a_number_for_display():
    assert offenders() == []


def test_the_scan_sees_what_it_is_meant_to_see():
    for bad in ('f"{x:.1f}"', 'f"{x:,.0f}"', 'f"{n:,}"', 'f"{x:g}"', 'f"{x:.0%}"', 'f"{x:+.1f}"', 'f"{value:,.{places}f}"', 'f"{x} %"'):
        assert SPEC.search(bad) or DYNAMIC.search(bad) or SPACE_PERCENT.search(bad), bad
    for fine in ('f"{n:02d}"', 'f"{year:04d}"', 'f"{x}"'):
        assert not (SPEC.search(fine) or DYNAMIC.search(fine) or SPACE_PERCENT.search(fine)), fine
