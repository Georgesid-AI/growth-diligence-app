import { ANOMALIES_NOT_COMPUTED, anomalyFlags } from "./gapLists";

const anomalies = {
  negative_mrr_months: ["2024-03"],
  revenue_gap_then_resume: [],
  revenue_missing_customer_id: { count: 2 },
  deals_close_before_created: { excluded_count: 0 },
  date_order_from_data: [{ field: "invoice_date", dataset: "revenue", order: "DD/MM/YYYY", rows: 1200 }],
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
