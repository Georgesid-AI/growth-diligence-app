import React, { act } from "react";
import { createRoot } from "react-dom/client";

import { s2Explainer, S4_DROP_ZONE_LEAD } from "@/lib/chatUpload";

const S2_EXPLAINER_CONSENT = s2Explainer(true);

const load = () => ({ RecognitionLine: require("./RecognitionLine").default, ...require("@/lib/recognition") });

/**
 * The detected-type line and the Correct / Change controls under a revenue file (docs/specs/revenue-file-recognition.md section 7,
 * S31a-S31k). The component renders from a fixed API response (the `recognition` block of a dataset view) and sends each decision
 * through the `decide(view, body)` it is given. Run with --no-cache (CLAUDE.md rule 25).
 */
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
const all = (id) => [...document.body.querySelectorAll(`[data-testid="${id}"]`)];
const click = (el) => act(async () => { el.click(); });
const choose = async (el, value) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(el, value);
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
};

const AUTO = {
  recognised: true, missing: [], message: null, sheet: "KPIs", header_row: 3,
  file_type: "monthly_revenue_report", type_state: "auto", type_source: "rules", type_candidates: [],
  label_mode: "metric", label_share: 1, confidence: 100, series_basis: "row", periods: 12,
  revenue_row: {
    row: 4, label: "Recognised revenue (EUR)", kind: "recognised", confidence: 100, state: "auto", reason: null,
    candidates: [{ row: 4, label: "Recognised revenue (EUR)", kind: "recognised", confidence: 100 },
                 { row: 5, label: "MRR", kind: "recurring", confidence: 100 }],
  },
  last_actual: { column: 7, month: "2025-06", label: "FY 2025", as_of: "2025-06", state: "auto", reason: null, candidates: [] },
  excluded_columns: [8, 9, 10, 11, 12, 13],
  currency: { code: "EUR", state: "seen" }, money_kind: { asked: false },
  non_revenue_rows: [{ row: 9, label: "Forecast revenue", kind: "forecast" }, { row: 10, label: "Bookings", kind: "bookings" }],
  supports: ["trend"],
  blocked: [{ analysis: "customer_level", needs: "revenue by customer and month (one row per customer, or one row per invoice with a customer column)" }],
  other_sheets: [{ sheet: "P&L", file_type: "financial_statements", recognised: true }],
  needs_click: false,
};
const CLICK = {
  ...AUTO, type_state: "auto", needs_click: true,
  revenue_row: { ...AUTO.revenue_row, row: 4, state: "click", reason: "rules_and_model_disagree" },
  last_actual: { ...AUTO.last_actual, state: "click", reason: "after_as_of" },
  currency: { code: null, state: "confirm" },
};
const view = (recognition, over = {}) => ({ dtype: "revenue", file: "report.csv", recognition, ...over });

let root, host, decide;
async function unmount() {
  if (!root) return;
  await act(async () => { root.unmount(); });
  host.remove();
  root = null;
}
async function mount(recognition, over) {
  await unmount();         // a test may mount several states one after the other
  const { RecognitionLine } = load();
  decide = jest.fn().mockResolvedValue({});
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<RecognitionLine view={view(recognition, over)} decide={decide} />); });
}
afterEach(unmount);

describe("the detected-type line", () => {
  test("shows the type with how it was found and a Change button that offers the other five types", async () => {
    await mount(AUTO);
    expect(q("recognition-type-revenue").textContent).toBe("Type: Monthly revenue report (by rules)");
    expect(q("recognition-type-change-revenue").textContent).toBe("Change");
    await click(q("recognition-type-change-revenue"));
    const options = [...q("recognition-type-select-revenue").querySelectorAll("option")].map((o) => o.value).filter(Boolean);
    expect(options).toEqual(["invoice_transactions", "customer_revenue", "revenue_summary", "financial_statements", "arr_mrr_snapshot"]);
    await choose(q("recognition-type-select-revenue"), "customer_revenue");
    expect(decide).toHaveBeenCalledWith(expect.objectContaining({ dtype: "revenue" }), { action: "change", part: "file_type", file_type: "customer_revenue" });
  });

  test("names the six types and the source of the type: rules, AI suggestion or your choice", async () => {
    const { TYPE_LABELS } = load();
    expect(Object.values(TYPE_LABELS)).toEqual(["Invoice transactions", "Customer revenue", "Monthly revenue report", "Revenue summary",
      "Financial statements", "ARR/MRR snapshot"]);
    await mount({ ...AUTO, type_source: "ai", type_state: "click", type_reason: "type_unsure", needs_click: true });
    expect(q("recognition-type-revenue").textContent).toBe("Type: Monthly revenue report (AI suggestion, not verified). Choose the type.");
    await mount({ ...AUTO, type_source: "you" });
    expect(q("recognition-type-revenue").textContent).toBe("Type: Monthly revenue report (your choice)");
  });

  test("a type the rules could not class asks for a choice between the two candidates", async () => {
    await mount({ ...AUTO, file_type: null, type_state: "click", type_candidates: ["customer_revenue", "revenue_summary"], needs_click: true });
    expect(q("recognition-type-revenue").textContent).toBe("Type: choose the type");
    const options = [...q("recognition-type-select-revenue").querySelectorAll("option")].map((o) => o.value).filter(Boolean);
    expect(options).toEqual(["customer_revenue", "revenue_summary"]);
    expect(q("recognition-reupload-note-revenue")).toBeNull();
  });

  test("metric labels under a customer header say that switching back to Customer revenue needs a re-upload (issue #136)", async () => {
    await mount({ ...AUTO, file_type: null, type_state: "click", type_candidates: ["customer_revenue", "monthly_revenue_report"], needs_click: true });
    expect(q("recognition-reupload-note-revenue").textContent).toBe("Switching back to Customer revenue needs a re-upload.");
    await mount({ ...AUTO, type_source: "you" }, { mapping_dropped: true });       // the report chosen: the mapping was dropped
    expect(q("recognition-reupload-note-revenue").textContent).toBe("Switching back to Customer revenue needs a re-upload.");
    await mount({ ...AUTO, type_source: "you" });
    expect(q("recognition-reupload-note-revenue")).toBeNull();
  });
});

describe("what the file supports and what it blocks", () => {
  test("one line: the analyses it supports, then each blocked analysis with the data that would unblock it", async () => {
    await mount(AUTO);
    expect(q("recognition-supports-revenue").textContent).toBe(
      "Supports: trend analysis (MRR/ARR, growth, run-rate). Blocked: customer-level analysis (NRR, gross churn, concentration, cohorts), " +
      "needs revenue by customer and month (one row per customer, or one row per invoice with a customer column).");
  });

  test("a file that supports everything has no Blocked part, and a snapshot supports claim matching only", async () => {
    await mount({ ...AUTO, file_type: "customer_revenue", supports: ["customer_level", "trend"], blocked: [] });
    expect(q("recognition-supports-revenue").textContent).toBe(
      "Supports: customer-level analysis (NRR, gross churn, concentration, cohorts) and trend analysis (MRR/ARR, growth, run-rate).");
    await mount({ ...AUTO, file_type: "arr_mrr_snapshot", supports: ["claim_matching"], blocked: [
      { analysis: "customer_level", needs: "revenue by customer and month" }, { analysis: "trend", needs: "ARR or MRR for at least two periods (one column per month)" }] });
    expect(q("recognition-supports-revenue").textContent).toBe(
      "Supports: claim matching only. Blocked: customer-level analysis (NRR, gross churn, concentration, cohorts), needs revenue by customer and month; " +
      "trend analysis (MRR/ARR, growth, run-rate), needs ARR or MRR for at least two periods (one column per month).");
  });
});

describe("yearly columns and recurring rows (decisions of 19 Oct 2026)", () => {
  test("a file with yearly columns supports trend and its blocked part says the monthly series is missing", async () => {
    await mount({ ...AUTO, file_type: "financial_statements", supports: ["trend"], blocked: [
      { analysis: "customer_level", needs: "revenue by customer and month" }, { analysis: "monthly_series", needs: "one column per month" }] });
    expect(q("recognition-supports-revenue").textContent).toBe(
      "Supports: trend analysis (MRR/ARR, growth, run-rate). Blocked: customer-level analysis (NRR, gross churn, concentration, cohorts), " +
      "needs revenue by customer and month; monthly series missing, needs one column per month.");
  });

  test("a recurring row is called a recurring row and never a revenue row", async () => {
    await mount({ ...AUTO, revenue_row: { ...AUTO.revenue_row, row: 5, label: "MRR", kind: "recurring" } });
    expect(q("recognition-row-revenue").textContent).toBe("Recurring row: MRR (row 5)");
    expect(q("recognition-row-correct-revenue")).toBeNull();
    expect(host.textContent).not.toMatch(/Revenue row/);
  });
});

describe("the proposed revenue row and the last actual column", () => {
  test("an accepted proposal shows the row with Change only, and the last actual column read-only", async () => {
    await mount(AUTO);
    expect(q("recognition-row-revenue").textContent).toBe("Revenue row: Recognised revenue (EUR) (row 4)");
    expect(q("recognition-row-revenue").parentElement.textContent).toBe("Revenue row: Recognised revenue (EUR) (row 4) · Change");
    expect(q("recognition-last-revenue").textContent).toBe("Last actual column: FY 2025 (from as-of month Jun 2025)");
    expect(q("recognition-row-correct-revenue")).toBeNull();
    expect(q("recognition-row-change-revenue").textContent).toBe("Change");
    for (const gone of ["last-correct", "last-change", "last-select"]) expect(q(`recognition-${gone}-revenue`)).toBeNull();
  });

  test("a column with no header reads as the last actual month", async () => {
    await mount({ ...AUTO, last_actual: { ...AUTO.last_actual, label: null } });
    expect(q("recognition-last-revenue").textContent).toBe("Last actual month: Jun 2025 (from as-of month Jun 2025)");
  });

  test("Change opens the candidate rows and sends the choice", async () => {
    await mount(AUTO);
    await click(q("recognition-row-change-revenue"));
    const rows = [...q("recognition-row-select-revenue").querySelectorAll("option")].filter((o) => o.value).map((o) => [o.value, o.textContent]);
    expect(rows).toEqual([["4", "Recognised revenue (EUR) (row 4)"], ["5", "MRR (row 5)"]]);
    await choose(q("recognition-row-select-revenue"), "5");
    expect(decide).toHaveBeenLastCalledWith(expect.objectContaining({ dtype: "revenue" }), { action: "change", part: "revenue_row", row: 5 });
  });

  test("an unsure row asks the analyst to choose, with the reason, and offers no Correct; a file that starts after the as-of month says so", async () => {
    await mount(CLICK);
    expect(q("recognition-row-revenue").textContent).toBe("Revenue row: choose the row. Two readings differ. Choose the revenue row.");
    expect(q("recognition-last-revenue").textContent).toBe(
      "Last actual column: not read. The file starts after the as-of month, so no column is read. Set the as-of month in the set-up section.");
    expect(q("recognition-row-correct-revenue")).toBeNull();
    expect(q("recognition-row-select-revenue")).not.toBeNull();
    await choose(q("recognition-row-select-revenue"), "4");
    expect(decide).toHaveBeenLastCalledWith(expect.objectContaining({ dtype: "revenue" }), { action: "change", part: "revenue_row", row: 4 });
  });

  test("after the analyst decides, the row reads as decided and only Change stays", async () => {
    await mount({ ...AUTO, revenue_row: { ...AUTO.revenue_row, state: "you" } });
    expect(q("recognition-row-correct-revenue")).toBeNull();
    expect(q("recognition-row-change-revenue").textContent).toBe("Change");
  });

  test("a file with no revenue row (customers by periods) shows no revenue-row line", async () => {
    await mount({ ...AUTO, file_type: "customer_revenue", revenue_row: null, series_basis: "sum_of_rows", non_revenue_rows: [],
                  supports: ["customer_level", "trend"], blocked: [] });
    expect(q("recognition-row-revenue")).toBeNull();
    expect(q("recognition-last-revenue")).not.toBeNull();
  });

  test("a turnover row asks the revenue or volume question and sends the answer", async () => {
    await mount({ ...AUTO, money_kind: { asked: true }, revenue_row: { ...AUTO.revenue_row, label: "Turnover", state: "click", reason: "turnover_question" } });
    expect(q("recognition-money-kind-revenue").textContent).toContain("Is this money the company earned (revenue) or the value of transactions processed (volume)?");
    await click(q("recognition-money-kind-revenue-revenue"));
    expect(decide).toHaveBeenLastCalledWith(expect.objectContaining({ dtype: "revenue" }), { action: "change", part: "money_kind", money_kind: "revenue" });
  });
});

describe("currency, other sheets, rows kept out of revenue", () => {
  test("a currency in the file is shown; one that is not asks the analyst to confirm it", async () => {
    await mount(AUTO);
    expect(q("recognition-currency-revenue").textContent).toBe("Currency: EUR");
    await mount(CLICK);
    expect(q("recognition-currency-revenue").textContent).toContain("Currency not found in the file. Confirm the currency:");
    await choose(q("recognition-currency-select-revenue"), "EUR");
    expect(decide).toHaveBeenLastCalledWith(expect.objectContaining({ dtype: "revenue" }), { action: "change", part: "currency", currency: "EUR" });
  });

  test("a file that shows several currencies asks for none: the required field stays open (review L3)", async () => {
    await mount({ ...CLICK, currency: { code: null, state: "confirm", mixed: true } });
    expect(q("recognition-currency-revenue")).toBeNull();
    expect(q("recognition-currency-select-revenue")).toBeNull();
  });

  test("the other sheets of the workbook are listed and each can be used instead", async () => {
    await mount(AUTO);
    expect(q("recognition-others-revenue").textContent).toBe("Other sheets in this file: P&L (Financial statements) Use this sheet");
    await click(q("recognition-use-sheet-revenue-P&L"));
    expect(decide).toHaveBeenLastCalledWith(expect.objectContaining({ dtype: "revenue" }), { action: "change", part: "sheet", sheet: "P&L" });
  });

  test("no other sheet, no line", async () => {
    await mount({ ...AUTO, other_sheets: [] });
    expect(q("recognition-others-revenue")).toBeNull();
  });

  test("forecast, bookings and other rows are counted as not used as revenue and kept as claims", async () => {
    await mount(AUTO);
    expect(q("recognition-claims-revenue").textContent).toBe("2 rows (forecast, bookings) are not used as revenue and are kept as claims for matching.");
    await mount({ ...AUTO, non_revenue_rows: [{ row: 9, label: "Forecast revenue", kind: "forecast" }] });
    expect(q("recognition-claims-revenue").textContent).toBe("1 row (forecast) is not used as revenue and is kept as a claim for matching.");
    await mount({ ...AUTO, non_revenue_rows: [] });
    expect(q("recognition-claims-revenue")).toBeNull();
  });
});

describe("a file that is not a revenue file", () => {
  test("shows the server's message, which names what is missing, and none of the other lines", async () => {
    const message = "Not a revenue file. Missing: a revenue measure (recognised revenue, invoiced revenue, sales, turnover, recurring revenue, MRR or ARR).";
    await mount({ recognised: false, missing: ["revenue_measure"], message, sheet: "CSV", file_type: null, revenue_row: null, last_actual: null,
                  non_revenue_rows: [{ row: 3, label: "Bookings", kind: "bookings" }], supports: [], blocked: [], other_sheets: [], needs_click: false });
    expect(q("recognition-message-revenue").textContent).toBe(message);
    for (const id of ["recognition-type-revenue", "recognition-supports-revenue", "recognition-row-revenue", "recognition-last-revenue"]) {
      expect(q(id)).toBeNull();
    }
  });
});

describe("wording", () => {
  test("no line mentions the model's confidence or a cost", async () => {
    for (const recognition of [AUTO, CLICK, { ...AUTO, type_source: "ai", file_type: "arr_mrr_snapshot", supports: ["claim_matching"] }]) {
      await mount(recognition);
      expect(host.textContent).not.toMatch(/confiden|cost|token|\$|USD|price/i);
    }
  });

  test("every reason code has a closed text that names what to do and mentions neither confidence nor cost", () => {
    const { REASON_TEXT } = load();
    const codes = ["no_candidate", "tie", "row_missing", "label_mismatch", "marked_not_revenue", "not_numeric_enough",
      "no_revenue_word", "rules_and_model_disagree", "after_as_of", "not_a_period", "turnover_question", "type_unsure"];
    expect(Object.keys(REASON_TEXT).sort()).toEqual([...codes].sort());
    for (const code of codes) {
      expect(REASON_TEXT[code].length).toBeGreaterThan(10);
      expect(REASON_TEXT[code]).not.toMatch(/confiden|cost|token|model|\bAI\b/i);
    }
  });

  test("the consent explainer says the AI also sees row labels that are metric names, and Row 1, Row 2 where rows may be customers", () => {
    expect(S2_EXPLAINER_CONSENT).toContain(
      "In a revenue file the AI also sees the row labels when they are metric names such as revenue, ARR or customers; " +
      "where the rows may be customers it sees Row 1, Row 2 instead, never a name.");
    expect(S2_EXPLAINER_CONSENT.startsWith("The model reads every column header and a masked sample to propose the mapping. ")).toBe(true);
    expect(S2_EXPLAINER_CONSENT).toContain("When the rules cannot tell what a file holds, the AI also sees its sheet names and the title rows above each table.");
  });

  test("the consent explainer says deck pages go as printed with an image of the page and no redaction, and carries the disclosure line word for word", () => {
    expect(S2_EXPLAINER_CONSENT).toContain("The AI reads every page of uploaded decks, as printed, to find plan figures: the text of each page that carries a figure and one image of the whole page, with no redaction.");
    expect(S2_EXPLAINER_CONSENT).toContain(
      "Deck pages are processed by Anthropic under a zero-data-retention arrangement. Nothing is retained after the reply and nothing is used for training.");
    expect(S2_EXPLAINER_CONSENT.endsWith("Uploaded files are stored for this audit and deleted with it.")).toBe(true);
  });
});

describe("review follow-ups (second round, 19 Oct 2026)", () => {
  test("a type that waits for a click shows its reason with Correct and Change, for a suggestion and for a disagreement", async () => {
    const { TYPE_REASON_TEXT } = load();
    expect(TYPE_REASON_TEXT).toEqual({ rules_and_model_disagree: "Two readings differ. Choose the type.", type_unsure: "Choose the type." });
    await mount({ ...AUTO, type_state: "click", type_reason: "rules_and_model_disagree", type_candidates: ["monthly_revenue_report", "revenue_summary"], needs_click: true });
    expect(q("recognition-type-revenue").textContent).toBe("Type: Monthly revenue report (by rules). Two readings differ. Choose the type.");
    expect(q("recognition-type-change-revenue")).not.toBeNull();
    await click(q("recognition-type-correct-revenue"));
    expect(decide).toHaveBeenLastCalledWith(expect.objectContaining({ dtype: "revenue" }), { action: "confirm", part: "file_type" });
  });

  test("a row the rules read with confidence 80 is accepted with no Correct button and no confirm state", async () => {
    await mount({ ...AUTO, revenue_row: { ...AUTO.revenue_row, confidence: 80 } });
    expect(q("recognition-row-revenue").textContent).toBe("Revenue row: Recognised revenue (EUR) (row 4)");
    expect(q("recognition-row-correct-revenue")).toBeNull();
    expect(q("recognition-correct-revenue")).toBeNull();
    expect(q("recognition-row-change-revenue")).not.toBeNull();
  });

  test("a row that needs a choice keeps its drop-down and no Correct", async () => {
    await mount({ ...AUTO, needs_click: true, revenue_row: { ...AUTO.revenue_row, state: "click", reason: "rules_and_model_disagree" } });
    expect(q("recognition-row-select-revenue")).not.toBeNull();
    expect(q("recognition-correct-revenue")).toBeNull();
  });

  test("a P&L carries its own recognition line, with ids and decisions of its own dtype", async () => {
    await mount({ ...AUTO, file_type: "financial_statements", other_sheets: [] }, { dtype: "pnl", file: "pnl.csv" });
    expect(q("recognition-type-pnl").textContent).toBe("Type: Financial statements (by rules)");
    expect(q("recognition-type-revenue")).toBeNull();
    expect(q("recognition-row-correct-pnl")).toBeNull();
    await click(q("recognition-row-change-pnl"));
    expect(q("recognition-row-select-pnl")).not.toBeNull();
  });

  test("S4 says what the audit now accepts and keeps the rest of the drop-zone text", () => {
    expect(S4_DROP_ZONE_LEAD).toBe(
      "Drop files here or use the paperclip. Required: a revenue file – revenue by customer, invoices or a monthly revenue report (24–36 months). " +
      "The audit will not run without a revenue file. Optional: CRM export and P&L. ");
  });
});

describe("a sheet with a metrics block and a dated list (section 6.7, owner request of 19 Oct 2026)", () => {
  const TABLES = [{ kind: "metrics_block", file_type: "monthly_revenue_report" }, { kind: "dated_list", file_type: "monthly_revenue_report" }];
  const MATCH = { status: "match", months: 6, months_off: 0, max_gap_pct: 0 };
  const MISMATCH = { status: "mismatch", months: 6, months_off: 2, max_gap_pct: 0.05 };

  test("a list that matches the revenue row is a cross-check: the row supplies the series and nothing is asked", async () => {
    await mount({ ...AUTO, tables: TABLES, series_source: { supplier: "metrics_block", state: "auto", cross_check: MATCH } });
    expect(q("recognition-tables-revenue").textContent).toBe("Two tables on this sheet: a metrics block and a dated list.");
    expect(q("recognition-source-revenue").textContent).toBe(
      "Revenue series: the revenue row of the metrics block. The dated list matches it month by month (6 months).");
    expect(q("recognition-source-revenue-dated_list")).toBeNull();
  });

  test("a list that does not match asks the analyst which table supplies the series and sends the choice", async () => {
    await mount({ ...AUTO, needs_click: true, tables: TABLES, series_source: { supplier: "metrics_block", state: "click", cross_check: MISMATCH } });
    expect(q("recognition-source-revenue").textContent).toBe(
      "The dated list and the revenue row differ in 2 of 6 months. Choose which table supplies the revenue series:");
    expect(q("recognition-source-revenue-metrics_block").textContent).toBe("Use the revenue row");
    await click(q("recognition-source-revenue-dated_list"));
    expect(decide).toHaveBeenLastCalledWith(expect.objectContaining({ dtype: "revenue" }),
      { action: "change", part: "series_source", series_source: "dated_list" });
  });

  test("after the choice the line says which table is read and the mismatch stays visible", async () => {
    await mount({ ...AUTO, tables: TABLES, series_source: { supplier: "dated_list", state: "you", cross_check: MISMATCH } });
    expect(q("recognition-source-revenue").textContent).toBe(
      "Revenue series: the dated list. The dated list and the revenue row differ in 2 of 6 months.");
    expect(q("recognition-source-revenue-dated_list").disabled).toBe(true);
    expect(q("recognition-source-revenue-metrics_block").disabled).toBe(false);
  });

  test("a sheet with one table shows no tables line", async () => {
    await mount({ ...AUTO, tables: [], series_source: null });
    expect(q("recognition-tables-revenue")).toBeNull();
  });
});
