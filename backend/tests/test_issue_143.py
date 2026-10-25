"""Issue #143, from the artefact (a forecast page titled "2022 FORECAST: CLIENT COMPOSITION" with a bar chart of average revenue per
account by year, 2019-2022, and a y axis 0, 2,000 ... 10,000: the 2021 bar was read as Revenue FY2021 and flagged against the
FY2021 revenue of an earlier page). One failing test per point, synthetic page only (CLAUDE.md rules 13 and 15):

a a figure whose label or context says ARPA, ARPU, per account, per client, per user or average revenue is the unit-economics metric,
  Unsupported, never a deck inconsistency against revenue · b a run of four or more round, equally spaced figures on one page is a
  chart axis and is dropped before claim extraction."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from claim_matching_support import engine_results  # noqa: E402,F401
from pdf_support import pdf_page  # noqa: E402
from test_claim_matching import RUNS, results_for, settings  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app.decks import claims  # noqa: E402
from app.decks.parser import parse_deck  # noqa: E402

BARS = (("2019", "€5,210.40"), ("2020", "€6,102.75"), ("2021", "€7,517.55"), ("2022", "€8,330.10"))
TICKS = ("0", "2,000", "4,000", "6,000", "8,000", "10,000")


def page(caption, title="2022 FORECAST: CLIENT COMPOSITION", ticks=TICKS, stagger=False):
    texts = [(50, 560, 22, title)]
    if caption:
        texts.append((50, 520, 12, caption))
    for i, (year, label) in enumerate(BARS):
        texts += [(150 + 120 * i, 380, 12, label), (150 + 120 * i, 340, 12, year)]
    for i, tick in enumerate(ticks):
        texts.append((10 + 40 * i if stagger else 60, 340 + 30 * i, 9, tick))
    return parse_deck(pdf_page(texts, []), "deck.pdf")["blocks"]


def detect(caption, **kw):
    return claims.detect_candidates(page(caption, **kw), "deck.pdf")


def amounts(found):
    return sorted(v["value"] for c in found for v in claims.claim_values(c) if v["value"] is not None)


def register_of(found):
    for n, c in enumerate(found, 1):
        c.update(id=f"c{n}", status="approved", file="deck.pdf", order=n)
        claims.resolve_period(c, 12)
    run = RUNS["A"]
    return cm.build_register(found, results_for(run), settings(run))


# ---------------------------------------------------------------------------
# a. Per-account figures
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("caption", [
    "Average revenue per account (EUR)", "ARPA by year", "ARPU", "Revenue per client", "Revenue per user", "Average revenue per customer"])
def test_a_a_bar_chart_of_average_revenue_per_account_is_never_revenue_and_never_a_deck_inconsistency(caption):
    found = detect(caption)
    bars = [c for c in found if 7517.55 in [v["value"] for v in claims.claim_values(c)]]
    assert bars, "the 2021 bar is a candidate"
    for c in bars:
        assert c["claim_type"] in ("arpa", "arpu"), c["claim_type"]
        assert claims.deck_label(c) != "Revenue"
        assert not c.get("inconsistent_dates")
    rows = register_of(found)
    bar_rows = [r for r in rows if r["claim_type"] in ("arpa", "arpu")]
    assert bar_rows and {r["evidence_label"] for r in bar_rows} == {"Unverified"}
    assert {r["reason"] for r in bar_rows} == {cm.UNIT_ECONOMICS_REASON}
    assert not any(r["claim_type"] == "revenue" and r["value"] in (5210.4, 6102.75, 7517.55, 8330.1) for r in rows)


# ---------------------------------------------------------------------------
# b. Chart axis ticks
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("stagger", [False, True])
def test_b_a_run_of_four_or_more_round_equally_spaced_figures_on_one_page_is_dropped_before_extraction(stagger):
    found = detect("Revenue by year", stagger=stagger)
    assert not [v for v in amounts(found) if v in (2000, 4000, 6000, 8000, 10000)], amounts(found)


@pytest.mark.parametrize("stagger", [False, True])
def test_b_the_bars_of_the_same_page_are_still_claims(stagger):
    found = detect("Revenue by year", stagger=stagger)
    assert {5210.4, 6102.75, 7517.55, 8330.1} <= set(amounts(found))


@pytest.mark.parametrize("ticks", [("0", "2,000", "4,000"), ("1,000", "2,000", "4,000", "8,000"), ("1,100", "2,300", "3,500", "4,700"),
                                   ("1,000", "2,000", "3,000", "5,000", "6,000")])
def test_b_fewer_than_four_or_unequal_or_non_round_figures_are_not_a_page_level_axis(ticks):
    """Placed apart (no column or row of ticks), so only the page-level rule is in question."""
    found = detect("Revenue by year", ticks=ticks, stagger=True)
    asked = {int(t.replace(",", "")) for t in ticks if t != "0"}
    assert asked <= set(amounts(found)), (ticks, amounts(found))
