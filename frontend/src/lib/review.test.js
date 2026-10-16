import { mappingSummary } from "./review";

const col = (column, field) => ({ column, field, state: "auto", confidence: 100, pending: false, source: "rules", decision: null });
const VIEW = { dtype: "pnl", file: "pnl.csv", pending: 0, missing_required: [], read_as_claims: null,
  columns: [col("S&M Expense", "sm_expense"), col("Month", "month")] };

describe("the mapping summary and a file read as claims (chat-upload.md section 20)", () => {
  test("a file read as claims is no calculation input: its columns are not listed as matched", () => {
    const label = (f) => f;
    const claims = { ...VIEW, dtype: "revenue", file: "plan.xlsx", read_as_claims: { lines: 2, claims: 12 }, columns: [col("Period", "invoice_date")] };
    expect(mappingSummary([VIEW, claims], label).matched.map(({ view }) => view.file)).toEqual(["pnl.csv", "pnl.csv"]);
    expect(mappingSummary([{ ...claims, read_as_claims: null }], label).matched.length).toBe(1);
  });
});
