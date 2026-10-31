// docs/specs/forecast-and-payback.md section 4: the Years table names both annual payback proxies, says why one has no value, and shows what the
// S&M line covers.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import YearlyBasis, { YEARS_HEADERS } from "./YearlyBasis";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SOURCE = { file: "pnl.xlsx", sheet: "P&L", rows: "rows 3–5", rule: "CAC payback" };
const YEAR = { period: "FY2024", period_start: "2024-01", period_end: "2024-12", revenue: 1440000, new_revenue: 240000, sm_pct_revenue: 0.2333, sm_expense: 336000,
  sm_scope: "sales and marketing", gross_margin_pct: 0.7, gross_margin_change: 0, cac_payback_months: 24, cac_payback_reason: null, arr_year_end: 1440000,
  arr_prior_year_end: 1080000, net_new_arr: 360000, cac_payback_net_new_arr_months: 16, cac_payback_net_new_arr_reason: null, basis: "yearly basis, not monthly",
  source: SOURCE };
const BLOCK = { basis: "yearly basis, not monthly", years: [YEAR, { ...YEAR, period: "FY2022", sm_scope: "marketing only", cac_payback_months: null,
  cac_payback_reason: "no revenue for the year before", cac_payback_net_new_arr_months: null, cac_payback_net_new_arr_reason: "no ARR for the year-end before" }],
  track_record: [], reported_vs_file: [], missing: [{ metric: "CAC payback (monthly timing)", text: "Missing: monthly P&L / revenue by customer, last 24 months" }], source: SOURCE };

async function mount(block) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<YearlyBasis block={block} ccy="EUR" />); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}
const q = (host, id) => host.querySelector(`[data-testid="${id}"]`);

test("both proxies are columns named by their denominators, beside the scope of the S&M line", async () => {
  const { host, done } = await mount(BLOCK);
  try {
    expect(YEARS_HEADERS).toEqual(expect.arrayContaining(["CAC payback (revenue growth)", "CAC payback (net new ARR)", "S&M line"]));
    expect([...host.querySelectorAll('[data-testid="yearly-years"] thead th')].map((th) => th.textContent)).toEqual(YEARS_HEADERS);
    const row = q(host, "yearly-year-FY2024");
    expect(row.querySelector('[data-testid="yearly-payback-revenue"]').textContent).toContain("24 months");
    expect(row.querySelector('[data-testid="yearly-payback-arr"]').textContent).toContain("16 months");
    expect(row.querySelector('[data-testid="yearly-sm-scope"]').textContent).toBe("sales and marketing");
  } finally { await done(); }
});

test("a proxy with no value says why, and a marketing-only line says so", async () => {
  const { host, done } = await mount(BLOCK);
  try {
    const row = q(host, "yearly-year-FY2022");
    expect(row.querySelector('[data-testid="yearly-payback-revenue"]').textContent).toContain("no revenue for the year before");
    expect(row.querySelector('[data-testid="yearly-payback-arr"]').textContent).toContain("no ARR for the year-end before");
    expect(row.querySelector('[data-testid="yearly-sm-scope"]').textContent).toBe("marketing only");
  } finally { await done(); }
});
