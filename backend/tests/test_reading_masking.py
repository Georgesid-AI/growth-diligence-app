"""Masking of a spreadsheet reading (docs/design/read-check-review.md section 8, PR 2): the metric vocabulary the masker never tokenises,
name learning, figures left alone, idempotence. Synthetic cells only."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.structures import redact  # noqa: E402
from schemas.metrics import MAP_METRICS, MAP_ROLES  # noqa: E402

COMPANY = "Orchid Test Co"


def text_of(*cells, name="Report"):
    return redact.reading_text([{"name": name, "cells": [{"row": r, "col": c, "text": t} for r, c, t in cells]}])


def page_of(*lines):
    return redact.page_text([(3, [{"row": i, "col": 1, "text": t} for i, t in enumerate(lines, 1)])])


def mask(text, mapping=None, company=COMPANY):
    mapping = dict(mapping or {})
    for name in redact.reading_company_names(text, company, mapping):          # name learning, as the gateway does it
        mapping[name] = f"Client-{len(set(mapping.values())) + 1:02d}"
    return redact.mask_reading(text, company, mapping), mapping


def test_revenue_under_a_customers_title_goes_out_unchanged():
    text = text_of((1, 1, "Customers"), (2, 1, "Revenue"), (2, 2, "100"))
    (masked, counts), mapping = mask(text)
    assert masked == text and mapping == {} and counts.get("customer", 0) == 0


def test_a_company_name_under_the_same_title_is_learned_and_tokenised():
    text = text_of((1, 1, "Customers"), (2, 1, "Revenue"), (3, 1, "Zenith Retail Ltd"), (3, 2, "7"))
    (masked, _), mapping = mask(text)
    assert "A3: Client-01" in masked and "A2: Revenue" in masked and mapping == {"Zenith Retail Ltd": "Client-01"}


@pytest.mark.parametrize("word", ["revenue", "sales", "bookings", "ARR", "MRR", "churn", "growth", "margin", "gross", "net", "cost", "opex",
                                  "EBITDA", "cash", "customers", "users", "subscriptions", "plan", "budget", "forecast", "actual",
                                  "variance", "total"])
def test_every_word_of_the_vocabulary_the_task_lists_is_a_metric_label(word):
    assert redact.metric_label(word) and redact.metric_label(word.upper()) and redact.metric_label(word.title())
    text = text_of((1, 1, "Customers"), (2, 1, word.title()))
    assert mask(text)[0][0] == text, "never tokenised under a company-name header"


def test_the_role_and_metric_names_of_the_schema_are_in_the_vocabulary():
    for name in (*MAP_ROLES, *MAP_METRICS):
        assert redact.metric_label(name.replace("_", " ")), name


def test_a_label_with_a_word_outside_the_vocabulary_is_not_a_metric_label():
    assert not redact.metric_label("Revenue - Zenith Retail") and not redact.metric_label("") and not redact.metric_label("123")
    text = text_of((1, 1, "Customers"), (2, 1, "Revenue - Zenith Retail"))
    (masked, _), mapping = mask(text)
    assert "Zenith" not in masked and mapping, "a name with a metric word beside it is still a name"


def test_a_name_the_map_already_holds_is_tokenised_whatever_word_it_is_on_a_sheet_and_on_a_page():
    """F5 of the review of PR 205: the vocabulary applies only when a name is learned. A customer called "Balance" or "Closing" that the
    audit already tokenised goes out as its token in every payload."""
    mapping = {"Balance": "Client-04", "Closing": "Client-05", "Support": "Client-06"}
    sheet = text_of((1, 1, "Customer"), (2, 1, "Balance"), (2, 2, "100"), (3, 1, "Closing Ltd"), (4, 1, "Support"))
    masked, counts = redact.mask_reading(sheet, COMPANY, mapping)
    assert "A2: Client-04" in masked and "A3: Client-05 Ltd" in masked and "A4: Client-06" in masked and counts["company"] >= 3
    page, _ = redact.mask_pages(page_of("Balance renewed", "Closing signed for 120", "Support tier"), COMPANY, mapping)
    assert [line.split(": ", 1)[1] for line in page.splitlines()] == ["Client-04 renewed", "Client-05 signed for 120", "Client-06 tier"]
    row, _ = redact.mask_reading(text_of((1, 1, "Metric"), (2, 1, "Balance"), (2, 2, "100")), COMPANY, mapping)
    assert "A2: Client-04" in row, "once mapped, the word is a name in every file of the audit"


def test_a_metric_label_on_a_sheet_with_no_such_customer_is_unchanged_and_is_not_learned():
    text = text_of((1, 1, "Customers"), (2, 1, "Balance"), (2, 2, "100"), (3, 1, "Closing"), (4, 1, "Support"), (5, 1, "Total"))
    (masked, _), mapping = mask(text)
    assert masked == text and mapping == {}, "the vocabulary decides what is learned"
    text = page_of("Closing balance 120")
    assert redact.mask_pages(text, COMPANY, {})[0] == text


def test_a_metric_label_under_a_people_header_is_not_a_person_and_a_name_is():
    text = text_of((1, 1, "Owner"), (2, 1, "Revenue"), (3, 1, "Pat Sample"), (4, 1, "Total"))
    (masked, counts), _ = mask(text)
    assert "A2: Revenue" in masked and "A4: Total" in masked and "A3: [person]" in masked and counts["people_columns"] == 1


def test_a_figure_is_never_rewritten_a_fraction_with_many_decimals_is_no_phone_number():
    cells = [(1, 1, "Rate")] + [(r, 2, v) for r, v in enumerate(
        ["0.0123456789012", "0123456789", "+447223", "447,223.43", "2024-06-30", "-12.5%", "TRUE", "(1,200)"], 2)]
    text = text_of(*cells)
    (masked, counts), _ = mask(text)
    assert masked == text and counts.get("phone", 0) == 0 and counts.get("id", 0) == 0


def test_personal_data_is_removed_and_the_target_company_is_tokenised():
    text = text_of((1, 1, f"{COMPANY} report for pat@example.test"), (2, 1, "IBAN GB82 WEST 1234 5698 7654 32"), (3, 1, "Call +44 20 7946 0958"),
                   name=f"{COMPANY} 2024")
    (masked, counts), _ = mask(text, {COMPANY: "Client-01"})
    assert COMPANY not in masked and "example.test" not in masked and "GB82" not in masked and "7946" not in masked
    assert "sheet 1: Client-01 2024" in masked and counts["email"] == 1 and counts["iban"] == 1 and counts["phone"] == 1
    assert redact.personal_items(masked) == []


def test_masking_a_masked_text_changes_nothing_and_a_foreign_text_comes_back_as_it_was():
    text = text_of((1, 1, "Customers"), (2, 1, "Zenith Retail Ltd"), (2, 2, "5"), (3, 1, "Contact: x@example.test"), (4, 1, f"{COMPANY} Ltd"))
    (masked, _), mapping = mask(text)
    again, _ = redact.mask_reading(masked, COMPANY, mapping)
    assert again == masked
    assert redact.mask_reading("r1c1: not a reading text", COMPANY, mapping) == ("r1c1: not a reading text", {})


def test_the_reading_text_round_trips_and_refuses_what_is_not_one():
    cells = [{"row": 1, "col": 1, "text": "Revenue: gross"}, {"row": 12, "col": 28, "text": "9"}]
    text = redact.reading_text([{"name": "S1", "cells": cells}, {"name": "S2", "cells": cells}])
    assert redact.parse_reading_text(text) == [{"name": "S1", "cells": cells}, {"name": "S2", "cells": cells}]
    assert redact.reading_text_problem(text) is None and "AB12: 9" in text
    for bad in ("A1: before any sheet", "sheet 2: skips one", "sheet 1: ok\nA1: x\nA1: twice", "sheet 1: ok\nr1c1: wrong form", ""):
        assert redact.reading_text_problem(bad) == "not_cells", bad
    assert redact.reading_text_problem("sheet 1: empty") == "no_cells"
    many = redact.reading_text([{"name": f"S{i}", "cells": cells} for i in range(redact.READING_MAX_SHEETS + 1)])
    assert redact.reading_text_problem(many) == "too_many_sheets"


def test_a_customers_row_label_followed_by_figures_does_not_make_the_labels_below_it_names():
    """A monthly report has "Customers 10981 11003 ..." as a row; "Logo churn %" and "Pipeline" under it are metric rows, not customers."""
    text = text_of((1, 1, "Metric"), (1, 2, "Jan-25"), (2, 1, "Customers"), (2, 2, "10981"), (3, 1, "Logo churn %"), (3, 2, "0.1118"),
                   (4, 1, "Pipeline"), (4, 2, "11529"))
    (masked, counts), mapping = mask(text)
    assert masked == text and mapping == {}


def test_a_customer_header_with_year_headers_beside_it_still_heads_a_column_of_names():
    """Years are not amounts: "Customer | 2023 | 2024" heads the names below it, which must leave as tokens."""
    text = text_of((1, 1, "Customer"), (1, 2, "2023"), (1, 3, "2024"), (2, 1, "Zenith Retail Ltd"), (2, 2, "100"), (2, 3, "120"))
    (masked, _), mapping = mask(text)
    assert "A2: Client-01" in masked and mapping == {"Zenith Retail Ltd": "Client-01"}
    dated = text_of((1, 1, "Customer name"), (1, 2, "2024-01-31"), (2, 1, "Birch Labs Ltd"), (2, 2, "5"))
    assert "Birch" not in mask(dated)[0][0]


def test_a_merged_cell_carries_its_span_after_its_text_and_the_span_survives_masking():
    cells = [{"row": 3, "col": 2, "text": "Q1 2024", "col_span": 3}, {"row": 3, "col": 5, "text": "Q2 2024", "col_span": 3, "row_span": 2},
             {"row": 4, "col": 2, "text": "Zenith Retail Ltd (B4:D4)"}]
    text = redact.reading_text([{"name": "S", "cells": cells}])
    assert "B3: Q1 2024 (B3:D3)" in text and "E3: Q2 2024 (E3:G4)" in text
    assert redact.parse_reading_text(text)[0]["cells"][:2] == cells[:2]
    (masked, _), _ = mask(text)
    assert "B3: Q1 2024 (B3:D3)" in masked and redact.parse_reading_text(masked)[0]["cells"][0]["col_span"] == 3
    assert redact.parse_reading_text("sheet 1: S\nB3: x (B3:A3)") is None, "a span that runs backwards is not a reading text"
