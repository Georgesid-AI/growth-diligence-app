"""Claim-review conclusion (docs/specs/claim-review-conclusion.md; plan of 15 Oct 2026, section 1 and 7.1).

The outcome describes the five claims the analyst selected, never a recommendation; the contradictions outside the five
and the analyst's own judgment stand beside it, on the screen and in the memo. Python only, no network, no model.
"""
import ast
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from test_claim_register_api import AUDIT, api  # noqa: E402,F401  (the fixture)
from test_ic_memo import RATINGS, THESIS  # noqa: E402

from app import decks  # noqa: E402

# Committed before the code (docs/specs/claim-review-conclusion.md): strict expected failures until the code PR removes it.
pytestmark = pytest.mark.xfail(strict=True, reason="docs/specs/claim-review-conclusion.md: not built yet")

ROOT = Path(__file__).resolve().parents[2]
HEADING = "Claim-review conclusion — assessment of the five selected claims"
SCOPE = "This assesses the five claims the analyst selected. It is not an investment recommendation."
BANNED = re.compile(r"(?i)\b(?:underwrite|re-plan|invest|pass|proceed)\b")
SELECTED = ["c01", "c21", "c23", "c27", "c31"]          # five Verified claims with a stated period
UNSELECTED_CONTRADICTED = "c05"                          # ARR €240,000 for FY2023: 198,142.68 observed
JUDGMENT = {"reasons": "The selected revenue claims agree with the revenue file.",
            "unresolved_questions": "Why the FY2023 ARR on slide 7 is higher than the file."}


def _only(db, ids):
    col = db[decks.CANDIDATES_COLLECTION]
    col.docs[:] = [c for c in col.docs if c.get("id") in ids]


def _confirmed(client):
    r = client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"top5": SELECTED})
    assert r.status_code == 200, r.text
    return r.json()


def test_plan_1_five_verified_selected_claims_and_one_contradicted_unselected_show_supported_and_the_contradiction_in_one_block(api):  # noqa: F811
    client, db = api
    _only(db, SELECTED + [UNSELECTED_CONTRADICTED])
    body = _confirmed(client)
    block = body["verdict"]
    assert block["heading"] == HEADING
    assert block["outcome"] == "Selected claims supported" and block["outcome_code"] == "supported"
    assert block["scope_sentence"] == SCOPE
    others = block["other_contradictions"]
    assert [o["claim_id"] for o in others] == [UNSELECTED_CONTRADICTED], "the contradiction sits in the same block"
    assert others[0]["metric"] == "ARR, FY2023" and others[0]["gap"] == "€41,857 lower (miss)"
    assert "revenue.csv" in others[0]["source"] and "slide 7" in others[0]["source"]

    # the memo: the same block in its summary
    r = client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"ratings": RATINGS, "thesis": THESIS, "judgment": JUDGMENT})
    assert r.status_code == 200, r.text
    memo = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert memo.status_code == 200, memo.text
    summary = memo.text.split("## Summary")[1].split("## Deal thesis")[0]
    assert HEADING in summary and "Conclusion: Selected claims supported – All 5 selected claims are Verified." in summary
    assert SCOPE in summary
    assert re.search(r"Other contradictions:\n- ARR(?: \(see glossary\))?, FY2023: €41,857 lower \(miss\)", summary), summary
    assert f"Reasons: {JUDGMENT['reasons']}" in summary and f"Unresolved questions: {JUDGMENT['unresolved_questions']}" in summary


def test_no_other_contradiction_reads_none_found_among_tested_claims(api):  # noqa: F811
    client, db = api
    _only(db, SELECTED)
    block = _confirmed(client)["verdict"]
    assert block["other_contradictions"] == [] and block["other_contradictions_text"] == "None found among tested claims."


def test_the_memo_refuses_without_both_judgment_fields_and_never_prefills_them(api):  # noqa: F811
    client, db = api
    _only(db, SELECTED)
    body = _confirmed(client)
    assert body["ic_inputs"].get("judgment") in (None, {}), "never pre-filled"
    client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"ratings": RATINGS, "thesis": THESIS, "judgment": {"reasons": "Agree."}})
    r = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert r.status_code == 409 and r.json()["detail"] == "Memo not exported: write the analyst judgment: Unresolved questions."


def test_the_five_words_never_appear_in_the_conclusion_response_or_the_memo(api):  # noqa: F811
    client, db = api
    _only(db, SELECTED + [UNSELECTED_CONTRADICTED])
    body = _confirmed(client)
    client.put(f"/api/audits/{AUDIT}/ic-inputs", json={"ratings": RATINGS, "thesis": THESIS, "judgment": JUDGMENT})
    memo = client.get(f"/api/audits/{AUDIT}/memo.md").text
    assert not BANNED.search(str(body)), BANNED.search(str(body))
    assert not BANNED.search(memo), BANNED.search(memo)


def _python_strings(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


_JS_STRING = re.compile(r"""(["'`])((?:\\.|(?!\1).)*)\1""")


def _js_strings(path: Path):
    out = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        code = line.split("//")[0] if "://" not in line else line
        if code.strip().startswith(("*", "/*")):
            continue
        out += [m.group(2) for m in _JS_STRING.finditer(code)]
    return out


def test_no_user_facing_string_of_the_app_holds_one_of_the_five_words():
    hits = []
    for path in [ROOT / "backend" / "server.py", *sorted((ROOT / "backend" / "app").rglob("*.py"))]:
        hits += [f"{path.name}: {s!r}" for s in _python_strings(path) if BANNED.search(s)]
    for path in sorted((ROOT / "frontend" / "src").rglob("*.js*")):
        if ".test." in path.name or "/ui/" in str(path):
            continue
        hits += [f"{path.name}: {s!r}" for s in _js_strings(path) if BANNED.search(s)]
    assert not hits, "\n".join(hits)
