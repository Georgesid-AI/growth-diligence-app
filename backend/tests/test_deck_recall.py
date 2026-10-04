"""Recall test for the deck parser (docs/specs/deck-parser.md section 3).

Ten public decks in tests/fixtures/decks/decks/ and a hand-checked answer file,
tests/fixtures/decks/expected_claims.json. A listed company claim is found when a candidate
from the same deck cites its slide or page and has the same value (a percentage matches only
a percentage). A listed range needs both ends; a single listed figure is also found at either
end of a candidate range ("from 40-100": 40 today, 100 in two years). A claim listed without a
value is found by its target date. Claims marked "not a company claim" never count toward recall.

Precision - the share of candidates that are a listed company claim - is reported, never
asserted. To see the report: pytest tests/test_deck_recall.py -rP
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

import pytest

pytest.importorskip("pptx")
pytest.importorskip("docx")
pytest.importorskip("pdfplumber")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.decks import claims, parser  # noqa: E402

FIXTURES = BACKEND.parent / "tests" / "fixtures" / "decks"
COMPANY = "company claim"
# Set once expected_claims.json has been reviewed (spec: at least 90% of listed claims).
PASS_MARK = None


def _expected():
    return json.loads((FIXTURES / "expected_claims.json").read_text(encoding="utf-8"))["decks"]


def _pages(candidate):
    return {s.get("slide", s.get("page")) for s in candidate["sources"]}


def matches(candidate, claim) -> bool:
    if claim["page"] not in _pages(candidate):
        return False
    if claim["value"] is None:
        return candidate["target_date"] == claim["target_date"]
    if (candidate["unit"] == "%") != (claim["unit"] == "%"):
        return False
    same = lambda a, b: a is not None and b is not None and math.isclose(a, b, rel_tol=1e-9)  # noqa: E731
    if claim.get("value_high") is not None:
        return same(candidate["value"], claim["value"]) and same(candidate.get("value_high"), claim["value_high"])
    return same(candidate["value"], claim["value"]) or same(candidate.get("value_high"), claim["value"])


@pytest.fixture(scope="module")
def runs():
    out = []
    for deck in _expected():
        parsed = parser.parse_deck((FIXTURES / "decks" / deck["file"]).read_bytes(), deck["file"])
        out.append((deck, claims.detect_candidates(parsed["blocks"], deck["file"])))
    return out


def test_the_test_set_is_the_ten_listed_decks_under_25_mb():
    on_disk = {p.name for p in (FIXTURES / "decks").iterdir() if not p.name.startswith(".")}
    listed = [d["file"] for d in _expected()]
    assert on_disk == set(listed) and len(listed) == 10
    assert Counter(d["format"] for d in _expected()) == {"pdf": 6, "pptx": 2, "docx": 2}
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))["decks"]
    assert {(d["file"], d["format"]) for d in manifest} == {(f"decks/{d['file']}", d["format"]) for d in _expected()}
    assert sum(p.stat().st_size for p in FIXTURES.rglob("*") if p.is_file()) < 25 * 1024 * 1024


def test_answer_file_is_well_formed():
    for deck in _expected():
        for claim in deck["claims"]:
            assert claim["status"] in (COMPANY, "not a company claim"), claim
            assert claim["value"] is not None or claim["target_date"], f"{deck['file']}: nothing to match on: {claim}"
            assert claim.get("value_high") is None or claim["value_high"] > claim["value"], claim
            assert claim["claim_type"] in ("revenue", "retention", "sales", "people", "product", "market"), claim


def test_recall(runs):
    lines, found_total, listed_total, true_total, cand_total, distractor_hits = [], 0, 0, 0, 0, 0
    misses = []
    for deck, candidates in runs:
        listed = [c for c in deck["claims"] if c["status"] == COMPANY]
        distractors = [c for c in deck["claims"] if c["status"] != COMPANY]
        found = [c for c in listed if any(matches(cand, c) for cand in candidates)]
        true = [cand for cand in candidates if any(matches(cand, c) for c in listed)]
        hits = [cand for cand in candidates if any(matches(cand, c) for c in distractors)]
        misses += [f"{deck['file']} p{c['page']}: {c['text']}" for c in listed if c not in found]
        found_total, listed_total = found_total + len(found), listed_total + len(listed)
        true_total, cand_total = true_total + len(true), cand_total + len(candidates)
        distractor_hits += len(hits)
        lines.append(f"{deck['file']:24} recall {len(found):2}/{len(listed):2}   precision {len(true):2}/{len(candidates):2}"
                     f"   distractor candidates {len(hits)}")
    recall = found_total / listed_total
    precision = true_total / cand_total if cand_total else 0.0
    print("\n".join(lines))
    print(f"TOTAL recall {found_total}/{listed_total} = {recall:.0%}   precision {true_total}/{cand_total} = "
          f"{precision:.0%}   distractor candidates {distractor_hits}")
    print("Missed:\n  " + "\n  ".join(misses))
    if PASS_MARK is not None:
        assert recall >= PASS_MARK, f"recall {recall:.0%} is below the pass mark {PASS_MARK:.0%}"
