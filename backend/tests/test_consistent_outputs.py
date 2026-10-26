"""One result, three views (docs/specs/forecast-and-payback.md section 5; design note section 6): the same values, status, relationships, sources and
calculation lines in the register the screen reads, the memo's Appendix A and the baseline CSV; the four column names shared with the screen; the
forecast note once; no rank prefix in a text written for a screen. Fixture company: synthetic figures, in-memory Mongo, no network.
"""
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

from test_claim_groups_api import AUDIT, BASE, get  # noqa: E402

from app import claim_matching as cm  # noqa: E402
from app import verdict as vd  # noqa: E402

COLUMNS_JSON = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "claim_columns.json"
MIX = [*BASE, ("c9", 5_000_000, "2026", "revenue", {"basis": "projection"}), ("c10", 187_700, "2023", "revenue", {"basis": "actual"})]


@pytest.fixture()
def mixed(claims_for):
    """An audit of five reconciling claims (a year and its quarters), a forecast and a repeat of the year."""
    from test_claim_groups_api import cand

    from app import decks
    client, db = claims_for([])
    for c in MIX:
        over = c[4] if len(c) > 4 else {}
        db[decks.CANDIDATES_COLLECTION].docs.append(cand(c[0], c[1], c[2], *([c[3]] if len(c) > 3 else []), **over))
    return client


def table(memo: str) -> list:
    """Appendix A of the memo as a list of {column: cell}."""
    block = memo.split("## Appendix A")[1].split("## Appendix B")[0]
    lines = [ln for ln in block.splitlines() if ln.startswith("|")]
    cells = [[c.strip() for c in ln.strip().strip("|").split(" | ")] for ln in lines]
    header = cells[0]
    return [dict(zip(header, row)) for row in cells[2:]]


def flat(text) -> str:
    return re.sub(r"\s+", " ", str(text)).replace("|", "/").strip()


def test_the_four_column_names_are_one_list_shared_by_the_screen_and_the_memo():
    shared = json.loads(COLUMNS_JSON.read_text(encoding="utf-8"))
    assert tuple(shared["columns"]) == vd.FOUR_COLUMNS == ("Claim and period", "Evidence / calculation", "Result", "Source")
    assert shared["forecast_note"] == vd.FORECAST_NOTE


def test_the_register_the_csv_and_the_memo_carry_the_same_values_status_relationships_sources_and_calculations(mixed):
    register = get(mixed, "/claims")["register"]
    csv_text = mixed.get(f"/api/audits/{AUDIT}/claims.csv").text
    memo = mixed.get(f"/api/audits/{AUDIT}/memo.md")
    assert memo.status_code == 200, memo.text
    parsed, _, _ = vd.parse_baseline(csv_text)
    appendix = {c["Ref"]: c for c in table(memo.text)}
    assert [p["claim_id"] for p in parsed] == [r["claim_id"] for r in register] and len(appendix) == len(register) == 7
    for r, p in zip(register, parsed):
        assert {f: p[f] for f in cm.FIELDS} == {f: r[f] for f in cm.FIELDS}, f"{r['claim_id']}: the CSV is the register, field by field"
        cells = appendix[f"#{r['rank']}"]
        assert cells["Result"].startswith(r["evidence_label"]) and flat(r["reason"]) in cells["Result"], r["claim_id"]
        assert cells["Relationship"] == (flat(r["relationship"]) if r["relationship"] else "—"), r["claim_id"]
        assert flat(r["page_ref"]) in cells["Source"], r["claim_id"]
        if r["observed_citation"]:
            assert flat(r["observed_citation"]) in cells["Source"]
        if r["calc_lines"]:
            assert cells["Evidence / calculation"] == " / ".join(flat(line) for line in r["calc_lines"]), r["claim_id"]
        elif r["observed_value"] is not None:
            assert flat(vd.observed_text(r, "EUR")) in cells["Evidence / calculation"], r["claim_id"]


def test_the_memo_appendix_opens_with_the_four_columns_and_keeps_the_rest_after_them(mixed):
    memo = mixed.get(f"/api/audits/{AUDIT}/memo.md").text
    header = list(table(memo)[0])
    assert tuple(header[:4]) == vd.FOUR_COLUMNS
    assert header[4:] == ["Ref", "Approval", "Basis", "Case", "Relationship", "VaS", "Overlaps with", "Gate", "Key gate", "Top 5"]


def test_the_forecast_row_carries_its_calculation_in_all_three_views(mixed):
    register = get(mixed, "/claims")["register"]
    forecast = next(r for r in register if r["claim_id"] == "c9")
    assert forecast["figure_type"] == "target" and forecast["evidence_label"] == "Unverified" and forecast["calc_lines"]
    memo = mixed.get(f"/api/audits/{AUDIT}/memo.md").text
    assert " / ".join(forecast["calc_lines"]) in memo
    assert "Required growth" in mixed.get(f"/api/audits/{AUDIT}/claims.csv").text


def test_the_forecast_note_is_in_the_memo_summary_once_and_on_no_row(mixed):
    register = get(mixed, "/claims")["register"]
    memo = mixed.get(f"/api/audits/{AUDIT}/memo.md").text
    assert memo.count(vd.FORECAST_NOTE) == 1 and vd.FORECAST_NOTE in memo.split("## Summary")[1].split("## Deal thesis")[0]
    assert vd.FORECAST_NOTE not in json.dumps(register) and vd.FORECAST_NOTE not in mixed.get(f"/api/audits/{AUDIT}/claims.csv").text


def test_no_forecast_no_note(claims_for):
    client, _ = claims_for(BASE)
    assert vd.FORECAST_NOTE not in client.get(f"/api/audits/{AUDIT}/memo.md").text


def test_the_five_selected_claims_read_the_same_label_and_reason_as_the_register(mixed):
    register = {r["claim_id"]: r for r in get(mixed, "/claims")["register"]}
    five = get(mixed, "/verdict")["verdict"]["five"]
    assert five
    for item in five:
        row = register[item["claim_id"]]
        if item["group"] is None:
            assert (item["evidence_label"], item["reason"]) == (row["evidence_label"], row["reason"])


# --- no rank prefix in a text written for a screen -----------------------------------------------------------------------------------

RANK = re.compile(r"(?<![\w&])#\d+")


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            if k not in ("claim_id", "id"):
                yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def test_no_text_the_server_writes_for_a_screen_cites_a_rank(claims_for):
    client, _ = claims_for([*BASE, ("c6", 187_700, "2023"), ("c7", 90_000, "2023-Q1", "costs")])      # a repeat, a contradiction, a cost claim
    for path in ("/claims", "/verdict", "/blockers", "/review"):
        body = client.get(f"/api/audits/{AUDIT}{path}")
        assert body.status_code == 200, (path, body.text)
        offenders = [s for s in strings(body.json()) if RANK.search(s)]
        assert not offenders, f"{path}: {offenders[:3]}"


def test_the_repeat_note_names_the_page_not_a_rank(claims_for):
    client, _ = claims_for([("c1", 187_700, "2023"), ("c6", 187_700, "2023")])
    repeat = next(r for r in get(client, "/claims")["register"] if r["group_role"] == "repeat")
    assert repeat["relationship"] == "Same figure as €187,700 stated on slide 1; counted once"


def test_the_reasons_the_flagged_lines_and_the_gap_lists_name_the_claim(claims_for):
    client, _ = claims_for([("c1", 187_700, "2023"), ("c2", 300_000, "2023-Q1")])
    ver = get(client, "/verdict")["verdict"]
    assert ver["reasons"] and all(not RANK.search(r) and r.split(":")[0].startswith(("Revenue", "ARR")) for r in ver["reasons"])
