import { ANOMALIES_NOT_COMPUTED, NOT_APPLICABLE, anomalyFlags } from "./gapLists";

const anomalies = {
  negative_mrr_months: ["2024-03"],
  revenue_gap_then_resume: [],
  revenue_missing_customer_id: { count: 2 },
  deals_close_before_created: { excluded_count: 0 },
  date_order_from_data: [{ field: "invoice_date", dataset: "revenue", order: "DD/MM/YYYY", rows: 1200 }],
  source: { file: "revenue.csv", row_numbers: [2, 3] },
  deals_source: { file: "crm.csv", row_numbers: [2] },
};

test("computed flags are listed with their counts", () => {
  const flags = anomalyFlags({ anomalies });
  expect(flags.map((f) => f.count)).toEqual([1, 0, 2, 0, 1]);
  expect(flags[0].detail).toBe("2024-03");
  expect(flags[4].detail).toBe("invoice_date (revenue): DD/MM/YYYY, 1,200 rows");
});

test("a failed anomaly calculation is never shown as zero anomalies", () => {
  expect(anomalyFlags({ anomalies: null })).toBeNull();
  expect(ANOMALIES_NOT_COMPUTED).toMatch(/calculation error/);
});

test("CRM rows sharing a deal ID follow the deals closed before created, with the collapsed rows and the distinct IDs", () => {
  const flags = anomalyFlags({ anomalies: { ...anomalies, deals_duplicate_id: { rows: 9, distinct_ids: 3, collapsed: 6, rows_list: [2, 3] } } });
  const at = flags.findIndex((f) => f.label === "Deals with close before created (excluded)");
  expect(flags[at + 1]).toEqual({ label: "CRM rows sharing a deal ID", count: 6, detail: "3 distinct deal IDs" });
  expect(flags).toHaveLength(6);
});

test("results stored before the flag existed show no row for it, never a zero", () => {
  expect(anomalyFlags({ anomalies }).map((f) => f.label)).not.toContain("CRM rows sharing a deal ID");
});

test("a flag whose input file is absent is Not applicable, never 0 (PR 4f)", () => {
  const { deals_source, ...noCrm } = anomalies;
  const flags = anomalyFlags({ anomalies: { ...noCrm, deals_duplicate_id: { rows: 0, distinct_ids: 0, collapsed: 0, rows_list: [] } } });
  const by = Object.fromEntries(flags.map((f) => [f.label, f.count]));
  expect(by["Deals with close before created (excluded)"]).toBeNull();
  expect(by["CRM rows sharing a deal ID"]).toBeNull();
  expect(by["Months with negative MRR"]).toBe(1);
  const none = anomalyFlags({ anomalies: { ...noCrm, source: { file: "revenue", row_numbers: [] } } });
  expect(none.every((f) => f.count === null)).toBe(true);
  expect(NOT_APPLICABLE).toBe("Not applicable");
});
