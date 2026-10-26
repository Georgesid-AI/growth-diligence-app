"""Corrections and drops on the page read (George, 2026-10-26, first live run; docs/specs/claim-matching.md section 33).

1. A check that names exactly one correction applies it before the register: the row says what changed, Undo restores it, Diagnostics
   logs the original and the corrected value and no card is asked. More than one candidate: the row waits with one option each.
2. A value on no cell that the figures of the page compute is a derived figure: no row, a Diagnostics line.
3. A launch date whose text names no product: no row, a Diagnostics line.
Fixtures are built here from synthetic pages; no client deck.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

pytest.importorskip("pdfplumber")

import test_checker as tc  # noqa: E402
import test_llm_gateway as t  # noqa: E402
from test_structure_reading import AUDIT  # noqa: E402

from app import structures  # noqa: E402
from app.decks import CANDIDATES_COLLECTION, TEXT_COLLECTION  # noqa: E402
from app.llm.schemas import PAGE_CLAIMS  # noqa: E402
from app.structures import checker, corrections  # noqa: E402


def read(parsed, *claims_):
    """The rows and the deck document after the model answered `claims_` for the one page of `parsed`."""
    db = tc._page_db(parsed)
    adapter = t.FakeAdapter(replies=[json.dumps({"type": PAGE_CLAIMS, "claims": list(claims_)})])
    assert asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep)) == "read"
    deck_doc, = db[TEXT_COLLECTION].docs
    return sorted(db[CANDIDATES_COLLECTION].docs, key=lambda r: r["order"]), deck_doc


def at(parsed, text):
    return f"p1{tc.cell_of(parsed, text)}"


# ---------------------------------------------------------------------------
# 1. One correction applies, several wait
# ---------------------------------------------------------------------------
def test_the_year_under_a_bar_is_applied_when_the_model_dated_the_bar_otherwise():
    parsed = tc.bars()
    first = at(parsed, "€1.48MM")
    item = tc.one(parsed, tc.claim(first, 1_480_000, unit="EUR", period="2023"))
    plan, = item["corrections"]
    assert (plan["flag"], plan["field"], plan["original"]) == (checker.BAR_YEAR, "period", "2023")
    assert [o["period"] for o in plan["options"]] == ["2022"]
    rows, deck = read(parsed, tc.claim(first, 1_480_000, unit="EUR", period="2023"))
    row, = rows
    assert checker.BAR_YEAR not in row["flags"] and not checker.review_flags(row["flags"]), "applied: no card"
    assert row["target_date"] == "2022" and row["period_start"] == "2022-01-01"
    entry, = row["corrections"]
    assert (entry["state"], entry["field"], entry["original"], entry["corrected"]) == ("applied", "period", "2023", "2022")
    assert entry["undo"]["target_date"] == "2023" and entry["undo"]["period_start"] == "2023-01-01"
    line, = deck["diagnostics"]
    assert line == {"page": 1, "kind": "corrected", "field": "period", "reason": checker.BAR_YEAR, "original": "2023", "corrected": "2022"}


def test_a_period_rebuilt_from_another_cell_is_applied_and_logged():
    parsed = tc.deck([tc.TITLE, (50, 480, 12, "$150,000 annual revenue run rate"), (400, 300, 12, "Plan year 2024")])
    cell = at(parsed, "$150,000 annual revenue run rate")
    other = at(parsed, "Plan year 2024")
    rows, deck = read(parsed, tc.claim(cell, 150_000, period="2023", period_cell=other))
    row, = rows
    assert row["target_date"] == "2024" and row["corrections"][0]["reason"] == checker.PERIOD_FROM_OTHER_CELL
    assert (row["corrections"][0]["original"], row["corrections"][0]["corrected"]) == ("2023", "2024")
    assert deck["diagnostics"][0]["original"] == "2023" and deck["diagnostics"][0]["corrected"] == "2024"


def test_a_period_on_no_cell_with_one_heading_period_is_applied_and_with_two_it_waits_with_a_button_each():
    one_heading = tc.deck([(50, 560, 20, "Plan 2025"), (50, 480, 12, "$150,000 annual revenue run rate")])
    cell = at(one_heading, "$150,000 annual revenue run rate")
    row, = read(one_heading, tc.claim(cell, 150_000, period="2027"))[0]
    assert checker.PERIOD_NOT_ON_PAGE not in row["flags"] and row["target_date"] == "2025" and row["corrections"][0]["state"] == "applied"
    two = tc.deck([(50, 560, 20, "Plan 2025"), (300, 540, 12, "Actuals 2024"), (50, 480, 12, "$150,000 annual revenue run rate")])
    cell = at(two, "$150,000 annual revenue run rate")
    rows, deck = read(two, tc.claim(cell, 150_000, period="2027"))
    row, = rows
    assert checker.PERIOD_NOT_ON_PAGE in row["flags"], "stays a card"
    entry, = row["corrections"]
    assert entry["state"] == "choose" and [o["value"] for o in entry["options"]] == ["2025", "2024"]
    assert entry["options"][1]["set"]["target_date"] == "2024"
    assert "diagnostics" not in deck or deck["diagnostics"] == [], "nothing applied, nothing logged"


def test_a_label_cell_the_figure_is_not_next_to_is_applied_with_one_candidate_and_left_alone_with_several():
    # the label the model cited stands far from the figure; the page offers "Paying customers" above it and nothing else
    one = tc.deck([(50, 500, 12, "Paying customers"), (50, 480, 12, "800"), (400, 200, 12, "Footnote words")])
    cell, far = at(one, "800"), at(one, "Footnote words")
    item = tc.one(one, tc.claim(cell, 800, metric="customers", unit="count", label_cell=far))
    plan, = item["corrections"]
    assert plan["field"] == "label" and [o["value"] for o in plan["options"]] == ["Paying customers"] and checker.LABEL_MISMATCH not in item["flags"]
    row, = read(one, tc.claim(cell, 800, metric="customers", unit="count", label_cell=far))[0]
    entry, = row["corrections"]
    assert (entry["state"], entry["reason"], entry["corrected"]) == ("applied", checker.LABEL_MISMATCH, "Paying customers")
    assert row["label_from"] == "Paying customers" and checker.LABEL_MISMATCH not in row["flags"]
    assert entry["undo"]["label_from"] is None
    # a title and a line above: two candidates, nothing changes and no card is asked (a label that stays as the model cited it)
    many = tc.deck([tc.TITLE, (50, 500, 12, "Paying customers"), (50, 480, 12, "800"), (400, 200, 12, "Footnote words")])
    cell, far = at(many, "800"), at(many, "Footnote words")
    item = tc.one(many, tc.claim(cell, 800, metric="customers", unit="count", label_cell=far))
    assert item["corrections"] == [] and item["flags"] == [] and item["label_cell"] is None
    row, = read(many, tc.claim(cell, 800, metric="customers", unit="count", label_cell=far))[0]
    assert "corrections" not in row and row["flags"] == []


def test_a_label_in_the_log_is_a_cell_id_never_its_text():
    parsed = tc.deck([(50, 500, 12, "Paying customers"), (50, 480, 12, "800"), (400, 200, 12, "Footnote words")])
    cell = at(parsed, "800")
    _, deck = read(parsed, tc.claim(cell, 800, metric="customers", unit="count", label_cell=at(parsed, "Footnote words")))
    assert "Paying customers" not in json.dumps(deck["diagnostics"]) and "Footnote" not in json.dumps(deck["diagnostics"])


# ---------------------------------------------------------------------------
# 2. Derived figures
# ---------------------------------------------------------------------------
def test_a_value_on_no_cell_that_the_page_computes_is_dropped_with_a_diagnostics_line():
    parsed = tc.deck([tc.TITLE, (50, 500, 12, "$150,000 annual revenue run rate"), (50, 480, 12, "$50,000 from services"),
                      (50, 460, 12, "800 Paying Users")])
    cell = at(parsed, "800 Paying Users")
    derived = tc.claim(cell, 200_000)                       # 150,000 + 50,000, written nowhere
    item = tc.one(parsed, derived)
    assert checker.VALUE_NOT_ON_PAGE in item["flags"] and item["drop"] == checker.DERIVED_FIGURE
    stray = tc.claim(cell, 999_000)
    assert tc.one(parsed, stray)["drop"] is None, "a value the page cannot compute stays a flagged claim"
    rows, deck = read(parsed, derived, stray)
    assert [r["value"] for r in rows] == [999_000], "the derived figure is no row"
    assert [(d["kind"], d["value"]) for d in deck["diagnostics"]] == [("derived figure, not a claim", 200_000)]


def test_sums_differences_ratios_and_percentages_of_page_figures_are_computable():
    figures = [150_000.0, 50_000.0, 800.0, 20.0]
    assert corrections.computable(200_000, figures) and corrections.computable(100_000, figures)         # sum, difference
    assert corrections.computable(25, [100.0, 4.0]) and corrections.computable(50, [1.0, 2.0])         # ratio, percentage
    assert not corrections.computable(7, [150_000.0, 50_000.0]) and not corrections.computable(0, figures)
    assert not corrections.computable(200_000, [150_000.0])
    assert not corrections.computable(150_040, [150_000.0, 40.0]), "a figure next to a rounding-sized one is no sum: the claim just sits near a figure"


# ---------------------------------------------------------------------------
# 3. A launch date with no product name
# ---------------------------------------------------------------------------
LAUNCH = dict(metric="product", unit=None)


def test_a_launch_date_whose_text_names_no_product_is_dropped_and_one_that_names_it_stays():
    parsed = tc.deck([tc.TITLE, (50, 500, 12, "Launch Q3 2025"), (50, 480, 12, "Launch of Aurora in Q3 2025"),
                      (50, 440, 12, "$150,000 annual revenue run rate")])
    bare, named = at(parsed, "Launch Q3 2025"), at(parsed, "Launch of Aurora in Q3 2025")
    assert tc.one(parsed, tc.claim(bare, None, period="2025-Q3", period_cell=bare, **LAUNCH))["drop"] == checker.LAUNCH_NO_PRODUCT
    assert tc.one(parsed, tc.claim(named, None, period="2025-Q3", period_cell=named, **LAUNCH))["drop"] is None
    rows, deck = read(parsed, tc.claim(bare, None, period="2025-Q3", period_cell=bare, **LAUNCH),
                      tc.claim(named, None, period="2025-Q3", period_cell=named, **LAUNCH))
    assert [r["snippet"] for r in rows] == ["Launch of Aurora in Q3 2025"]
    assert [d["kind"] for d in deck["diagnostics"]] == ["launch date without product name"]


def test_a_page_read_again_replaces_its_diagnostics_lines():
    parsed = tc.deck([tc.TITLE, (50, 500, 12, "Launch Q3 2025"), (50, 440, 12, "$150,000 annual revenue run rate")])
    bare = at(parsed, "Launch Q3 2025")
    db = tc._page_db(parsed)
    for _ in range(2):
        adapter = t.FakeAdapter(replies=[json.dumps({"type": PAGE_CLAIMS, "claims": [tc.claim(bare, None, period="2025-Q3", period_cell=bare, **LAUNCH)]})])
        asyncio.run(structures.process_deck(db, AUDIT, "d1", adapter=adapter, sleep=t._noop_sleep, **({"use_cache": False} if False else {})))
    deck_doc, = db[TEXT_COLLECTION].docs
    assert len(deck_doc["diagnostics"]) == 1


# ---------------------------------------------------------------------------
# The controls on the row: Undo a correction, choose a candidate, Undo a rejection
# ---------------------------------------------------------------------------
def _api(run_api, *candidates):
    from test_claims_enter_on_their_own import prepared
    prepared(run_api, *candidates)
    return run_api


def _url(cid):
    return f"/api/audits/{AUDIT_RUN}/decks/candidates/{cid}"


from test_claims_enter_on_their_own import AUDIT as AUDIT_RUN, claim as run_claim, stored  # noqa: E402

APPLIED = {"field": "period", "reason": "year under bar differs", "original": "2023", "corrected": "2022", "state": "applied",
           "undo": {"target_date": "2023", "period_text": "2023", "period_start": "2023-01-01", "period_end": "2023-12-31"}}
WAITING = {"field": "period", "reason": "period not on page", "original": "2027", "state": "choose",
           "undo": {"target_date": "2027", "period_text": "2027", "period_start": "2027-01-01", "period_end": "2027-12-31"},
           "options": [{"value": "2025", "set": {"target_date": "2025", "period_text": "2025", "period_start": "2025-01-01", "period_end": "2025-12-31"}},
                       {"value": "2024", "set": {"target_date": "2024", "period_text": "2024", "period_start": "2024-01-01", "period_end": "2024-12-31"}}]}


def test_undo_restores_the_model_period_and_the_row_keeps_its_place(run_api):
    client = _api(run_api, run_claim("c1", target_date="2022", corrections=[dict(APPLIED)]))
    r = client.post(_url("c1") + "/correction", json={"index": 0, "action": "undo"})
    assert r.status_code == 200, r.text
    got = stored(client)["c1"]
    assert (got["target_date"], got["period_start"], got["corrections"][0]["state"]) == ("2023", "2023-01-01", "undone")
    assert client.post(_url("c1") + "/correction", json={"index": 0, "action": "undo"}).status_code == 400, "an undone correction is not undone twice"


def test_choosing_a_candidate_sets_the_field_removes_the_flag_and_keeps_the_claim(run_api):
    client = _api(run_api, run_claim("c1", status="pending", flags=["period not on page"], corrections=[dict(WAITING)]))
    assert client.post(_url("c1") + "/correction", json={"index": 0, "action": "choose", "option": 5}).status_code == 400
    r = client.post(_url("c1") + "/correction", json={"index": 0, "action": "choose", "option": 1})
    assert r.status_code == 200, r.text
    got = stored(client)["c1"]
    assert (got["target_date"], got["status"], got["flags"], got["corrections"][0]["state"], got["corrections"][0]["corrected"]) \
        == ("2024", "approved", [], "applied", "2024")
    assert client.post(_url("c1") + "/correction", json={"index": 0, "action": "undo"}).status_code == 200, "a chosen candidate can be undone too"
    assert stored(client)["c1"]["target_date"] == "2027"


def test_a_rejected_row_is_restored_to_the_status_it_had(run_api):
    client = _api(run_api, run_claim("c1", status="pending", flags=["axis tick"]), run_claim("c2", status="approved", auto_accepted=True))
    for cid in ("c1", "c2"):
        before = stored(client)[cid]["status"]
        assert client.put(_url(cid), json={"status": "rejected"}).status_code == 200
        assert stored(client)[cid]["status"] == "rejected"
        r = client.put(_url(cid), json={"undo": True})
        assert r.status_code == 200, r.text
        assert stored(client)[cid]["status"] == before
    assert stored(client)["c2"]["auto_accepted"] is True, "Python's own entry is restored as it was"
    assert client.put(_url("c1"), json={"undo": True}).status_code == 400, "only a rejected row is restored"


# ---------------------------------------------------------------------------
# 4. Population from the label
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("label, population", [
    ("Paying users", "paying"), ("Registered users", "registered"), ("Monthly active users", "active"), ("Sign-ups", "registered"),
    ("Users", None), ("Paying and active users", None), ("", None),
])
def test_the_population_is_read_from_the_label_when_it_holds_one_noun(label, population):
    from app import claim_matching as cm
    assert cm.population_in_label(label) == population
    c = {"claim_type": "users", "label_from": label, "snippet": "10,000"}
    assert cm._population(c, None) == ((population, "python") if population else (None, None))


def test_a_users_claim_whose_label_names_the_population_asks_nothing_and_one_that_does_not_still_asks():
    from claim_matching_support import engine_results  # noqa: F401
    from app import claim_matching as cm
    base = {"id": "u", "status": "approved", "claim_type": "users", "value": 10000, "unit": "users", "currency": None, "target_date": "2024-02",
            "period_text": "Feb 2024", "snippet": "10,000 users", "file": "deck.pptx", "order": 0, "sources": [{"file": "deck.pptx", "page": 3}]}
    assert cm.candidate_fields({**base, "label_from": "Paying users"}, None)["population"] == "paying"
    assert cm.candidate_fields({**base, "label_from": "Users"}, None)["population"] is None
