import {
  COMPUTED_STATUS, NONE, RECOMPUTE_TO_CHECK, absentFieldsText, computedValue, missingRows, questionRows,
  questionsEmptyText, sourceText,
} from "./gapLists";

// Shaped like stored results after the V6 engine pass: the sales cycle was computed
// from the revenue upload because the CRM upload has no dates; NRR is truly missing.
const results = {
  sales_cycle: {
    median_days: 45.5, n: 2, status: COMPUTED_STATUS,
    source: { file: "revenue.xlsx", sheet: "Sheet1", rows: "rows 2–14 (13 rows)", dataset: "revenue" },
  },
  win_rate: { won: 1, lost: 1, win_rate_pct: 50 },
  questions_for_management: [{
    metric: "Sales cycle", status: COMPUTED_STATUS, result_key: "sales_cycle", dataset: "revenue",
    question: "Sales cycle was computed from the revenue upload ... Please explain the result.",
  }],
  missing_data: [
    { metric: "NRR (12-month)", status: "Missing", reason: "Needs 12+ months of history; have 6",
      absent_fields: { revenue: [], crm: ["customer_id", "invoice_date", "amount", "currency"] } },
    { metric: "Revenue rows with blank amount", status: "Missing", reason: "1 row(s) have no amount value" },
  ],
};

describe("questions for management", () => {
  test("each item carries metric, computed value, source and status", () => {
    expect(questionRows(results)).toEqual([{
      metric: "Sales cycle",
      value: "46 days",                                   // days round up, as everywhere else
      source: results.sales_cycle.source,
      sourceText: "revenue.xlsx · Sheet1 · rows 2–14 (13 rows)",
      status: "Computed – explanation requested",
      question: results.questions_for_management[0].question,
    }]);
  });

  test("values follow the number display rules", () => {
    expect(computedValue("win_rate", { win_rate: { win_rate_pct: 49.6 } })).toBe("50%");
    expect(computedValue("nrr", { nrr: { overall_pct: 106.41 } })).toBe("106%");
    expect(computedValue("cac_payback", {
      cac_payback: { default_l: 1, headline_quarter: "2024-Q2", quarters: { "2024-Q2": { L1: { months: 12.24 } } } },
    })).toBe("12.2 months (2024-Q2)");
    expect(computedValue("sales_cycle", {})).toBe("—");
  });

  test("an empty or absent list yields no rows, so the card shows None", () => {
    expect(questionRows({ questions_for_management: [] })).toEqual([]);
    expect(questionRows({})).toEqual([]);
    expect(NONE).toBe("None");
  });

  test("results computed after V6 with an empty list say None", () => {
    expect(questionsEmptyText({ questions_for_management: [] })).toBe("None");
  });

  test("results computed before V6 (no field at all) say Recompute to check", () => {
    const preV6 = { ...results };
    delete preV6.questions_for_management;
    expect(questionsEmptyText(preV6)).toBe("Recompute to check");
    expect(RECOMPUTE_TO_CHECK).toBe("Recompute to check");
  });

  test("a missing source reads as the placeholder", () => {
    expect(sourceText(null)).toBe("—");
  });
});

describe("missing data", () => {
  test("absent_fields is plain text per upload type", () => {
    expect(missingRows(results)).toEqual([
      { metric: "NRR (12-month)", reason: "Needs 12+ months of history; have 6",
        absent: "Revenue Lines: columns present, no usable rows; CRM Deals: customer id, invoice date, amount, currency" },
      { metric: "Revenue rows with blank amount", reason: "1 row(s) have no amount value", absent: "" },
    ]);
  });

  test("an empty or absent list yields no rows, so the card shows None", () => {
    expect(missingRows({ missing_data: [] })).toEqual([]);
    expect(missingRows({})).toEqual([]);
    expect(absentFieldsText(undefined)).toBe("");
  });
});
