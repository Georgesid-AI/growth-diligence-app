"""Redaction of deck structure cells (docs/specs/llm-structure-reading.md section 3).

Each rule with a false friend: amounts, years and dates are never phone numbers, "Head of Sales" is
not a person. Customer names are replaced as whole words in any case through the per-audit mapping
the narrative path already keeps (a word ends at a space, punctuation, a hyphen or a change of case);
short, numeric and date names, the target's own name and existing pseudonyms are left alone, so a
second pass changes nothing.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from app.llm import redaction  # noqa: E402
from app.structures import redact  # noqa: E402
import test_llm_gateway as t  # noqa: E402


def _cells(*texts, header=None):
    """One column of cells; an optional header cell on top."""
    rows = ([header] if header else []) + list(texts)
    return [{"row": r, "col": 1, "text": text} for r, text in enumerate(rows, 1)]


def _texts(cells):
    return [c["text"] for c in cells]


# ---------------------------------------------------------------------------
# Emails, phone numbers, names
# ---------------------------------------------------------------------------
def test_emails_become_a_placeholder():
    out, counts = redact.redact_cells(_cells("Contact jane.doe@acme.co.uk today", "Revenue @ 20%"), "Target Ltd")
    assert _texts(out) == ["Contact [email] today", "Revenue @ 20%"] and counts["email"] == 1


@pytest.mark.parametrize("text, expected", [
    ("Call +44 20 7946 0958", "Call [phone]"),
    ("020-7946-0958", "[phone]"),
    ("+359 88 123 4567", "[phone]"),
    ("+1,234,567,890", "+1,234,567,890"),         # an amount
    ("0.123456789", "0.123456789"),               # an amount
    ("2025", "2025"),                             # a year
    ("01/02/2025", "01/02/2025"),                 # a date
    ("Revenue 1,234,567,890", "Revenue 1,234,567,890"),
    ("+12 345", "+12 345"),                       # too few digits
])
def test_phone_numbers_become_a_placeholder_never_an_amount_year_or_date(text, expected):
    out, _ = redact.redact_cells(_cells(text), "Target Ltd")
    assert _texts(out) == [expected]


def test_a_name_under_a_person_role_header_becomes_a_placeholder():
    for header in ("Name", "Founder", "CEO", "Owner", "Contact", "Hire"):
        # "Rand" is not in the first-name list: only the header makes it a person.
        out, counts = redact.redact_cells(_cells("Rand Fishkin", "Head of Sales", "$120,000", header=header), "Target Ltd")
        assert _texts(out) == [header, "[person]", "Head of Sales", "$120,000"], header
        assert counts["person"] == 1
    out, _ = redact.redact_cells(_cells("Rand Fishkin", header="Revenue"), "Target Ltd")
    assert _texts(out) == ["Revenue", "Rand Fishkin"], "no person-role header and no listed first name"


@pytest.mark.parametrize("text, expected", [
    ("Led by Michael Smith since 2019", "Led by [person] since 2019"),
    ("Иван Петров, CTO", "[person], CTO"),
    ("Head of Sales", "Head of Sales"),            # no first name
    ("May Revenue", "May Revenue"),                # a month, not a name
    ("Grace Period", "Grace Period"),              # an everyday word, left out of the list
    ("Martin luther", "Martin luther"),            # the second word is not capitalised
])
def test_two_capitalised_words_starting_with_a_first_name_are_a_person(text, expected):
    out, _ = redact.redact_cells(_cells(text), "Target Ltd")
    assert _texts(out) == [expected]


def test_the_target_company_name_is_never_rewritten():
    out, _ = redact.redact_cells(_cells("Michael Hill Partners plan"), "Michael Hill Partners")
    assert _texts(out) == ["Michael Hill Partners plan"]


# ---------------------------------------------------------------------------
# Customer names: whole words, any case, through the shared per-audit mapping
# ---------------------------------------------------------------------------
MAPPING = {"Northwind Trading": "Customer_01", "Acme": "Customer_02", "ABC": "Customer_03", "12345": "Customer_04",
           "2024-01": "Customer_05", "Cust": "Customer_06", "Enterprise": "Segment A", "Acme Co": "Customer_07"}


def test_customer_names_are_replaced_as_whole_words_in_any_case():
    out, count = redact.pseudonymise_cells(
        _cells("Revenue from Northwind Trading Ltd", "NORTHWIND TRADING renewed", "AcmeCorp expansion"), MAPPING, "Target Ltd")
    assert _texts(out) == ["Revenue from Customer_01 Ltd", "Customer_01 renewed", "Customer_02Corp expansion"]
    assert count == 3


def test_short_numeric_and_date_names_the_target_name_and_pseudonyms_are_left_alone():
    cells = _cells("ABC signed 12345 seats on 2024-01", "Acme Holdings vs Acme", "Customer_01 and Customer_02",
                   "Enterprise accounts")
    out, count = redact.pseudonymise_cells(cells, MAPPING, "Acme Holdings")
    assert _texts(out) == ["ABC signed 12345 seats on 2024-01", "Acme Holdings vs Customer_02",
                           "Customer_01 and Customer_02", "Enterprise accounts"]
    assert count == 1, "Cust is never matched inside Customer_01; segment labels are not customer names"


@pytest.mark.parametrize("text, expected", [
    ("Paying customers", "Paying customers"),                      # "Cust" inside a word
    ("Acmes grew", "Acmes grew"),                                  # no boundary before the "s"
    ("Cust", "Customer_06"),
    ("ACME-led growth", "Customer_02-led growth"),                 # a hyphen
    ("(Acme), Northwind Trading.", "(Customer_02), Customer_01."),  # punctuation
    ("myAcme portal", "myCustomer_02 portal"),                     # a change of case before
    ("ACMECorp", "Customer_02Corp"),                               # capitals, then a capitalised word
    ("Acme Corp", "Customer_02 Corp"),                             # "Acme Co" is no whole word here; "Acme" is
    ("Acme Co renewed", "Customer_07 renewed"),                    # the longest whole-word name wins
])
def test_a_word_boundary_is_a_space_punctuation_a_hyphen_or_a_change_of_case(text, expected):
    out, _ = redact.pseudonymise_cells(_cells(text), MAPPING, "Target Ltd")
    assert _texts(out) == [expected]


def test_a_whole_word_overlapping_a_non_word_match_of_the_same_name_is_still_replaced():
    # "nana" first matches inside "Banana" (no boundary); the whole word "Nana" after the change of case overlaps it.
    out, _ = redact.pseudonymise_cells(_cells("BanaNana"), {"Nana": "Customer_01"}, "Target Ltd")
    assert _texts(out) == ["BanaCustomer_01"]


def test_the_target_name_inside_a_longer_customer_name_does_not_protect_it():
    out, _ = redact.pseudonymise_cells(_cells("Alphabet renewed", "Alpha plan"), {"Alphabet": "Customer_01"}, "Alpha")
    assert _texts(out) == ["Customer_01 renewed", "Alpha plan"]


# ---------------------------------------------------------------------------
# The client name: [redacted], and the structure is still read
# ---------------------------------------------------------------------------
AUDIT = {"company_name": "Target Ltd", "client_name": "Northbridge Capital", "engagement_reference": "ENG-2026-041"}   # a stored old field is ignored


def test_the_client_name_becomes_redacted_as_a_whole_word():
    withheld = redact.withheld_values(AUDIT)
    assert withheld == ("Northbridge Capital",), "an engagement reference left on an old record is not withheld"
    cells = _cells("Prepared for NORTHBRIDGE CAPITAL", "Ref ENG-2026-041.", "Northbridge Capitals")
    out, counts = redact.redact_structure(cells, "Target Ltd", MAPPING, withheld)
    assert _texts(out) == ["Prepared for [redacted]", "Ref ENG-2026-041.", "Northbridge Capitals"]
    assert counts["withheld"] == 1
    again, more = redact.redact_structure(out, "Target Ltd", MAPPING, withheld)
    assert again == out and not any(more.values()), "a second pass changes nothing"
    assert redact.withheld_values({"company_name": "Old Co"}) == (), "an audit without a client name withholds nothing"
    kept, _ = redact.pseudonymise_cells(out, {"Redacted": "Customer_09"}, "Target Ltd")
    assert kept == out, "the placeholder is never rewritten, even by a name that matches it"


def test_the_target_name_never_shields_the_client_name():
    out, _ = redact.redact_structure(_cells("Hill Partners plan"), "Hill Partners", {}, ("Hill",))
    assert _texts(out) == ["[redacted] Partners plan"]


def test_a_second_pass_changes_nothing():
    cells = _cells("jane@northwind.com", "Northwind Trading", "Jane Doe", "+44 20 7946 0958", header="Contact")
    first, _ = redact.redact_structure(cells, "Target Ltd", MAPPING)
    second, counts = redact.redact_structure(first, "Target Ltd", MAPPING)
    assert second == first and not any(counts.values())
    assert _texts(first) == ["Contact", "[email]", "Customer_01", "[person]", "[phone]"]


def test_the_structure_text_carries_cells_and_spans_and_nothing_else():
    cells = [{"row": 1, "col": 3, "text": "FY2025", "col_span": 12}, {"row": 2, "col": 1, "text": "Revenue"}]
    text = redact.structure_text(cells)
    assert text == "r1c3: FY2025 (r1c3:r1c14)\nr2c1: Revenue"
    assert redact.parse_structure_text(text) == cells
    assert redact.parse_structure_text("Revenue grew strongly in 2025") is None, "a prose line is not a cell"


def test_customers_join_the_narrative_mapping_with_the_same_pseudonyms():
    async def run():
        db = t.make_db(t.LEAKY_DOC)           # the names sit where the engine never writes them: redaction is the second wall
        from app.llm import gateway
        computed = await gateway.load_computed_results(db, t.RUN_ID, "growth_engine")
        narrative = await redaction.get_or_create_map(db, t.RUN_ID, computed)
        shared = await redaction.add_customers(db, t.RUN_ID, [t.REAL_NAMES[0], "Zeta Retail", None, " "])
        again = await redaction.get_or_create_map(db, t.RUN_ID, computed)
        return narrative, shared, again
    narrative, shared, again = asyncio.run(run())
    assert shared[t.REAL_NAMES[0]] == narrative[t.REAL_NAMES[0]], "one customer, one pseudonym on both paths"
    customers = [v for v in narrative.values() if v.startswith("Customer_")]
    assert shared["Zeta Retail"] == f"Customer_{len(customers) + 1:02d}"
    assert again == shared, "the narrative path keeps the names the structure path added"


@pytest.fixture()
def api(monkeypatch):
    pytest.importorskip("fastapi")
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "structure_redaction_test")
    from fastapi.testclient import TestClient
    import server
    db = t.FakeDB()
    db["audits"].docs.append({"id": "audit-1", "company_name": "Target Ltd", "results": None})
    monkeypatch.setattr(server, "db", db)
    return TestClient(server.app, raise_server_exceptions=False), db


def test_mapping_the_revenue_and_crm_files_adds_their_customer_names(api):
    client, db = api
    revenue = "Client,Invoice Date,Amount,Currency\nNorthwind Trading,2025-01-31,100,EUR\nAcme,2025-02-28,200,EUR\n"
    client.post("/api/audits/audit-1/datasets/revenue/upload", files={"file": ("rev.csv", revenue)})
    mapping = {"customer_id": "Client", "invoice_date": "Invoice Date", "amount": "Amount", "currency": "Currency"}
    assert client.put("/api/audits/audit-1/datasets/revenue/mapping", json={"mapping": mapping}).status_code == 200
    crm = "Deal ID,Account,Created,Close Date,Stage,Amount\nD1,Zeta Retail,2025-01-01,2025-02-01,won,10\n"
    client.post("/api/audits/audit-1/datasets/crm/upload", files={"file": ("crm.csv", crm)})
    assert client.put("/api/audits/audit-1/datasets/crm/mapping",
                      json={"mapping": {"deal_id": "Deal ID"}}).status_code == 200
    stored = db["pseudonym_map"].docs[0]["mapping"]
    assert set(stored) == {"Acme", "Northwind Trading", "Zeta Retail"}, "the CRM customer column is found by alias"
    assert sorted(stored.values()) == ["Customer_01", "Customer_02", "Customer_03"]
