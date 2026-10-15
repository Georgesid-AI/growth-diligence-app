"""Extraction confidence and evidence status (docs/specs/evidence-labels.md; plan of 15 Oct 2026, section 5).

Two separate labels: how well the parser read the figure (extraction confidence, the deck list's level) and how the claim
compares with the supplied company data (evidence status, with the new Inconclusive). Python only, no network, no model.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from test_claim_matching import RUNS, candidates_for, results_for, run_claim, settings  # noqa: E402
from test_claim_register_api import _get, api  # noqa: E402,F401  (the fixture)

from app import claim_matching as cm  # noqa: E402
from app import decks  # noqa: E402

SHARED = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "evidence_labels.json"
EXTRACTION_EXPLAINER = "How well the app read this figure from the deck. Not a statement about whether it is true."
EVIDENCE_EXPLAINER = "How this claim compares with the company data supplied for this audit. Agreement is not independent verification."
QUALIFIED = {"claim_type": "users", "value": 40, "unit": "trial accounts", "currency": None, "target_date": "2024-02",
             "snippet": "40 trial accounts in Feb 2024", "qualifier": "trial"}


def test_plan_5_a_high_confidence_claim_contradicted_by_the_revenue_file_shows_high_and_contradicted_with_the_figure_and_gap(api):  # noqa: F811
    """Plan section 5, the required test: the two labels are two fields, and a well-read claim can be a wrong one."""
    client, db = api
    c05 = next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == "c05")
    # ARR €240,000 for FY2023: a date, a currency, a named type, and the same figure on a second slide (corroborated): High
    c05["sources"] = c05["sources"] + [{"file": "testco_board.pptx", "slide": 12, "kind": "text"}]
    row = next(r for r in _get(client)["register"] if r["claim_id"] == "c05")
    assert row["extraction_confidence"] == "High"
    assert row["evidence_label"] == "Contradicted"
    assert row["observed_value"] == 198142.68 and row["observed_at"] == "2023-12", "the computed figure is on the row"
    assert row["gap"] == 41857.32 and row["gloss"] == "€41,857 lower (miss)", "and so is the gap"


def test_the_extraction_confidence_is_the_deck_lists_level_and_changes_no_label(api):  # noqa: F811
    client, db = api
    rows = {r["claim_id"]: r for r in _get(client)["register"]}
    assert {r["extraction_confidence"] for r in rows.values()} <= {"High", "Medium", "Low", "Analyst-entered"}
    assert rows["c05"]["extraction_confidence"] == "Medium", "one place only: not corroborated"
    before = {cid: (r["evidence_label"], r["rank"]) for cid, r in rows.items()}
    c05 = next(c for c in db[decks.CANDIDATES_COLLECTION].docs if c["id"] == "c05")
    c05["sources"] = c05["sources"] + [{"file": "testco_board.pptx", "slide": 12, "kind": "text"}]
    after = {r["claim_id"]: (r["evidence_label"], r["rank"]) for r in _get(client)["register"]}
    assert after == before, "a confidence changes no label and no rank (claim-matching.md section 1)"


def test_a_qualified_users_claim_is_inconclusive_with_paying_customers_shown_and_no_gap():
    row = run_claim(QUALIFIED)
    assert row["evidence_label"] == "Inconclusive"
    assert row["reason"] == "population differs: deck label 'trial accounts' is not paying customers; the figure shown is paying customers"
    assert (row["metric"], row["observed_value"], row["observed_at"]) == ("Customer count", 5, "2024-02")
    assert row["observed_source"], "the computed figure carries its source"
    assert (row["gap"], row["gap_normalised"], row["gap_kind"], row["gloss"]) == (None, None, None, None)
    assert row["gate_needed"] is True, "an Inconclusive row needs a gate, as an Unverified one does"


def test_an_inconclusive_row_ranks_after_every_tested_row_and_is_never_a_hard_blocker():
    run = RUNS["A"]
    cands = candidates_for(run) + [{"id": "q1", "status": "approved", "value_high": None, "period_text": "Feb 2024",
                                    "label_from": None, "file": "testco_board.pptx", "order": 99,
                                    "sources": [{"file": "testco_board.pptx", "slide": 9}], **QUALIFIED}]
    from app.decks import claims as deck_claims
    deck_claims.resolve_period(cands[-1], run["fiscal_year_end"])
    rows = cm.build_register(cands, results_for(run), settings(run))
    q1 = next(r for r in rows if r["claim_id"] == "q1")
    tested = [r["rank"] for r in rows if r["gap"] is not None and r["gap_kind"] != "to go"]
    assert q1["evidence_label"] == "Inconclusive" and q1["rank"] > max(tested)


def test_the_shared_evidence_labels_json_is_the_backends_list():
    shared = json.loads(SHARED.read_text(encoding="utf-8"))
    assert shared["statuses"] == list(cm.EVIDENCE_STATUSES) == ["Verified", "Contradicted", "Inconclusive", "Unverified", "Unsupported"]
    assert shared["memo_groups"] == cm.MEMO_GROUPS == {"Unverified": ["Unverified", "Inconclusive"]}
    assert shared["explainers"] == {"extraction_confidence": EXTRACTION_EXPLAINER, "evidence_status": EVIDENCE_EXPLAINER}
    assert (cm.EXTRACTION_EXPLAINER, cm.EVIDENCE_EXPLAINER) == (EXTRACTION_EXPLAINER, EVIDENCE_EXPLAINER)


def test_the_baseline_csv_carries_the_extraction_confidence_after_the_deck_reading():
    assert cm.FIELDS.index("extraction_confidence") == cm.FIELDS.index("deck_reading") + 1

