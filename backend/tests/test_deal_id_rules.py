"""Deal ID and stage, and the threshold (2026-10-17, docs/specs/chat-upload.md sections 4.1 and 21). The reported file: a CRM
export headed opportunity_id, sales_agent, product, account, deal_stage, engage_date, close_date, close_value, where the
rules mapped deal_stage to deal id at 80, accepted it without a click and left opportunity_id unmapped. The rows below
are invented (CLAUDE.md rule 15): 20 deals, no client name, figure or export text."""
import io
import csv

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("motor")

import test_chat_upload as chat  # noqa: E402
from test_chat_upload import AUDIT  # noqa: E402

from app import column_rules as cr, usage as usage_mod  # noqa: E402

HEADERS = ["opportunity_id", "sales_agent", "product", "account", "deal_stage", "engage_date", "close_date", "close_value"]
STAGES = ["Won", "Lost", "Engaging", "Prospecting"]


def opportunities() -> bytes:
    """20 deals: a unique code each, 5 agents, 3 products, 4 accounts, 4 stages. Won and Lost deals have a close date, Won
    deals a value and Lost ones 0; open deals neither."""
    rows = []
    for i in range(20):
        stage = STAGES[i % 4]
        closed = stage in ("Won", "Lost")
        rows.append([f"Q{i:02d}K{i % 7}Z", f"Agent {'ABCDE'[i % 5]}", ["Alpha", "Beta", "Gamma"][i % 3],
                     ["Alder Works", "Birch Labs", "Cedar Foods", "Dune Print"][i % 4], stage, f"2024-{i % 12 + 1:02d}-03",
                     f"2024-{i % 12 + 1:02d}-24" if closed else "", (str(900 + 45 * i) if stage == "Won" else "0") if closed else ""])
    return table(HEADERS, rows)


def table(headers, rows) -> bytes:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([headers] + rows)
    return buf.getvalue().encode()


def columns(**cols) -> cr.Sheet:
    """A sheet of the given columns (header: 20 values)."""
    return cr.read_sheet(table(list(cols), [list(r) for r in zip(*cols.values())]), "x.csv")


def proposals(dtype, sheet):
    return {p.column: p for p in cr.analyse(dtype, sheet)[0]}


CODES = [f"R{i:03d}X" for i in range(20)]
LABELS = STAGES * 5
NAMES = [f"Order {w}" for w in "Alder Birch Cedar Dune Elm Fern Gorse Holly Iris Juniper Kale Lime Moss Nettle Oak Pine Quince Rowan Sage Teak".split()]


# ---------------------------------------------------------------------------
# The reported file
# ---------------------------------------------------------------------------
def test_the_reported_file_maps_deal_stage_to_stage_and_opportunity_id_to_deal_id():
    by = proposals("crm", cr.read_sheet(opportunities(), "deals.csv"))
    assert {c: (p.field, p.state, p.confidence) for c, p in by.items()} == {
        "opportunity_id": ("deal_id", "auto", 100),
        "sales_agent": (None, "undecided", None),
        "product": (None, "undecided", None),
        "account": (None, "undecided", None),
        "deal_stage": ("stage", "auto", 100),
        "engage_date": (None, "undecided", None),
        "close_date": ("close_date", "auto", 100),
        "close_value": ("amount", "unsure", 60),
    }


def test_the_reported_file_shows_deal_stage_as_stage_and_close_value_for_confirmation(api):
    api.db["audits"].docs[0]["structure_reading_consent"] = False         # the rules' proposals as the analyst sees them
    rows = chat.by_column(chat.upload(api, "deals.csv", opportunities(), dtype="crm").json())
    assert (rows["deal_stage"]["field"], rows["deal_stage"]["state"], rows["deal_stage"]["pending"]) == ("stage", "auto", False)
    assert (rows["opportunity_id"]["field"], rows["opportunity_id"]["state"]) == ("deal_id", "auto")
    assert (rows["close_value"]["field"], rows["close_value"]["state"], rows["close_value"]["pending"]) == ("amount", "unsure", True)
    assert [c for c, r in rows.items() if r["field"] == "deal_id"] == ["opportunity_id"]


def test_underscores_are_read_as_spaces_so_snake_case_headers_score_as_their_synonyms():
    assert cr.field_score("crm", "stage", "deal_stage") == 100
    assert cr.field_score("crm", "deal_id", "opportunity_id") == 100
    assert cr.field_score("crm", "close_date", "close_date") == 100
    assert cr.field_score("revenue", "customer_id", "customer_id") == 100
    assert cr.field_score("revenue", "invoice_date", "invoice_date") == 100


# ---------------------------------------------------------------------------
# Rule 1: a stage is never a deal id
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("header", ["deal_stage", "Deal Stage", "Deal - Status", "deal_status", "Deal phase", "Stage ID", "DealStatus"])
def test_a_header_with_stage_status_or_phase_never_maps_to_deal_id_even_over_unique_codes(header):
    assert cr.field_score("crm", "deal_id", header) == 0
    by = proposals("crm", columns(**{header: CODES}))
    assert by[header].field != "deal_id"


@pytest.mark.parametrize("header", ["Deal", "ID", "deal_owner", "Opportunity"])
def test_a_small_set_of_repeated_labels_is_never_the_deal_id(header):
    assert cr.field_score("crm", "deal_id", header) >= 80, "the header alone would map it"
    by = proposals("crm", columns(**{header: LABELS}))
    assert by[header].field != "deal_id"


def test_what_a_set_of_repeated_labels_is():
    assert cr.label_set(LABELS) and cr.label_set(["Closed won", "Closed lost"] * 10) and cr.label_set(["Agent A", "Agent B"] * 10)
    assert not cr.label_set(NAMES), "unique names"
    assert not cr.label_set(["D1", "D1", "D2", "D2"]), "repeated codes are not labels"
    assert not cr.label_set([f"Stage {c}" for c in "ABCDEFGHIJKLM"] * 2), "13 labels: more than LABEL_SET_MAX"
    assert not cr.label_set([1, 1, 2, 2]) and not cr.label_set(["2024-01-01", "2024-01-01", "2024-02-01", "2024-02-01"])


# ---------------------------------------------------------------------------
# Rule 2: a column of unique codes with an id word in its header is the deal id candidate
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("header,score,state", [
    ("opportunity_id", 100, "auto"), ("Deal ID", 100, "auto"),
    ("Ref", 80, "unsure"), ("Deal ref", 80, "unsure"), ("Opportunity", 80, "unsure"), ("OpportunityID", 80, "unsure"),
])
def test_a_column_of_unique_codes_with_an_id_word_is_the_deal_id_candidate(header, score, state):
    p = proposals("crm", columns(**{header: CODES}))[header]
    assert (p.field, p.confidence, p.state) == ("deal_id", score, state)


@pytest.mark.parametrize("values", [NAMES, CODES[:10] * 2, [f"{v}.5" for v in range(20)]], ids=["names", "repeated", "decimals"])
def test_a_ref_column_that_is_not_unique_codes_is_not_proposed(values):
    assert proposals("crm", columns(Ref=values))["Ref"].field is None


def test_what_unique_codes_are():
    assert cr.unique_codes(CODES) and cr.unique_codes(list(range(5000, 5020))) and cr.unique_codes(["1C1I7A6R", "OPP-0042"])
    assert not cr.unique_codes(["R1"]), "one value"
    assert not cr.unique_codes(["2024-01-01", "2024-01-02"]) and not cr.unique_codes(["03/04/2024", "04/04/2024"]), "dates"
    assert not cr.unique_codes([1.5, 2.5]) and not cr.unique_codes(["Order 1", "Order 2"]) and not cr.unique_codes(["Won", "Lost"])


# ---------------------------------------------------------------------------
# Rule 3: a rule mapping at exactly the threshold waits for a click
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("unreadable,confidence,state", [(4, 80, "unsure"), (3, 85, "auto")])
def test_a_rule_mapping_at_exactly_80_is_unsure_and_above_it_is_accepted(unreadable, confidence, state):
    amounts = ["n/a"] * unreadable + [str(100 + i) for i in range(20 - unreadable)]
    sheet = columns(**{"Customer": [f"C{i % 5}" for i in range(20)], "Invoice Date": [f"2024-01-{i + 1:02d}" for i in range(20)],
                       "Amount": amounts, "Currency": ["EUR"] * 20})
    p = proposals("revenue", sheet)["Amount"]
    assert (p.field, p.confidence, p.state) == ("amount", confidence, state)


def test_a_header_that_scores_80_waits_for_a_click():
    sheet = columns(**{"Customer Name": [f"C{i % 5}" for i in range(20)], "Invoice Date": [f"2024-01-{i + 1:02d}" for i in range(20)],
                       "Amount": [100 + i for i in range(20)], "Currency": ["EUR"] * 20})
    p = proposals("revenue", sheet)["Customer Name"]
    assert (p.field, p.score, p.confidence, p.state) == ("customer_id", 80, 80, "unsure")
    states = cr.states_from_rules(list(proposals("revenue", sheet).values()))
    assert cr.pending_count(states) == 1, "shown for confirmation"


# ---------------------------------------------------------------------------
# "Values do not fit this field" when a rule mapping is corrected to a field of another kind
# ---------------------------------------------------------------------------
def test_values_do_not_fit_is_taken_when_a_rule_mapping_is_corrected_to_a_field_of_another_kind(api):
    api.db["audits"].docs[0]["structure_reading_consent"] = False
    rows = chat.by_column(chat.upload(api, "deals.csv", opportunities(), dtype="crm").json())
    assert (rows["close_value"]["source"], rows["close_value"]["field"]) == ("rules", "amount")
    assert cr.field_kind("crm", "amount") != cr.field_kind("crm", "created_date")
    out = api.post(f"/api/audits/{AUDIT}/datasets/crm/decisions",
                   json=[{"column": "close_value", "action": "correct", "field": "created_date", "reason": "values_do_not_fit"}])
    assert out.status_code == 200
    row = chat.by_column(out.json())["close_value"]
    assert (row["state"], row["decision"], row["reason"], row["field"]) == ("corrected", "correct", "values_do_not_fit", "created_date")
    assert usage_mod.get(api.db["audits"].docs[0])["columns"]["reasons"] == {"values_do_not_fit": 1}
