// docs/specs/forecast-and-payback.md section 5 (design note section 6): the four columns, the calculation lines of a forecast and of an annual payback in
// the Evidence / calculation column, the one forecast note above the register and on no row, no rank prefix, the corrections under Details.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import ClaimRegister from "./ClaimRegister";
import claimColumns from "@/lib/claim_columns.json";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getClaimRegister: jest.fn(), getBlockers: jest.fn(), updateClaimInputs: jest.fn(), answerTurnover: jest.fn(), answerDefinitionCheck: jest.fn(),
  claimsCsvUrl: (id) => `http://api/api/audits/${id}/claims.csv`,
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
beforeEach(() => { api.getBlockers.mockResolvedValue([]); });

const NOTE = "Forecast calculations describe assumptions; future outcomes are unverified.";
const BASE = {
  claim_type: "revenue", claimed_value: 2073600, claimed_high: null, unit: null, currency: "EUR", period: "FY2026", period_note: null, period_start: "2026-01-01",
  period_end: "2026-12-31", as_of_month: "2024-12", segment: "Whole company", segment_set_by: "python", metric: "Revenue", metric_set_by: "python",
  direction: "higher", observed_value: null, observed_at: null, observed_source: null, observed_citation: null, gap: null, gap_normalised: null,
  gap_kind: null, gloss: null, evidence_label: "Unverified", tolerance: "±5%", value_at_stake_arr: null, shortfall: null, overlaps_with: [],
  gate_sentence: null, deck_reading: "parser", page_ref: "slide 3", figure_type: "target", group_id: null, group_role: null, relationship: null,
  extraction_confidence: "High", calc_lines: [], calc_details: [],
};
const FORECAST = {
  ...BASE, claim_id: "f1", rank: 1, reason: "Forecast: required growth 20.0% a year against 20.0% historical",
  calc_lines: ["Required growth: 20.0% a year (€2,073,600 for FY2026 against €1,440,000 for FY2024, 24 months)", "Historical growth: 20.0% (FY2023 → FY2024)",
    "Difference: +0.0 percentage points (required less historical)"],
  calc_details: ["required annual growth = (forecast ÷ base) ^ (12 ÷ elapsed months) − 1", "base €1,440,000 for FY2024 (2024-01 to 2024-12), elapsed 24 months"],
};
const ACTUAL = { ...BASE, claim_id: "a1", rank: 2, claim_type: "revenue", claimed_value: 1440000, period: "FY2024", period_end: "2024-12-31", figure_type: "actual",
  observed_value: 1440000, observed_at: "2024-01 to 2024-12", observed_citation: "(revenue_series.data.total, CSV, rows 2–71, Jan–Dec 2024)",
  gap: 0, gap_normalised: 0, gloss: "as claimed", evidence_label: "Verified", reason: "within ±5% of the claim" };

async function mount(rows) {
  api.getClaimRegister.mockResolvedValue({ claims: [], register: rows });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<ClaimRegister auditId="a1" results={{ reporting_currency: "EUR" }} />); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}
const q = (host, id) => host.querySelector(`[data-testid="${id}"]`);

test("the four columns are the shared list, in order, and nothing else is a column", async () => {
  const { host, done } = await mount([FORECAST, ACTUAL]);
  try {
    expect(claimColumns.columns).toEqual(["Claim and period", "Evidence / calculation", "Result", "Source"]);
    expect([...host.querySelectorAll("thead th")].map((th) => th.firstChild.textContent)).toEqual(claimColumns.columns);
    for (const tbody of host.querySelectorAll('[data-testid="claim-register-row"]')) expect(tbody.querySelector("tr").querySelectorAll("td").length).toBe(4);
  } finally { await done(); }
});

test("a forecast shows its required growth, its historical comparator and the gap in the calculation column, and its reason in the result", async () => {
  const { host, done } = await mount([FORECAST]);
  try {
    const lines = [...host.querySelectorAll('[data-testid="register-calc-line"]')].map((n) => n.textContent);
    expect(lines).toEqual(FORECAST.calc_lines);
    expect(q(host, "register-calc").closest("td")).toBe(host.querySelector("tbody tr td:nth-child(2)"));
    expect(q(host, "register-evidence").textContent).toBe("Unverified");
    expect(q(host, "register-evidence-reason").textContent).toBe(FORECAST.reason);
    expect(q(host, "register-observed")).toBeNull();                      // a forecast reads its calculation, not an observed figure
  } finally { await done(); }
});

test("the forecast note is one sentence above the register when a forecast appears, once for any number of forecasts, and on no row", async () => {
  const { host, done } = await mount([FORECAST, { ...FORECAST, claim_id: "f2", rank: 3 }, ACTUAL]);
  try {
    const notes = host.querySelectorAll('[data-testid="forecast-note"]');
    expect(notes.length).toBe(1);
    expect(notes[0].textContent).toBe(NOTE);
    expect(notes[0].textContent).toBe(claimColumns.forecast_note);
    for (const row of host.querySelectorAll('[data-testid="claim-register-row"]')) expect(row.textContent).not.toContain("future outcomes are unverified");
    expect(host.textContent).not.toMatch(/cannot be tested until that period/);
  } finally { await done(); }
});

test("with no forecast there is no note", async () => {
  const { host, done } = await mount([ACTUAL]);
  try { expect(q(host, "forecast-note")).toBeNull(); } finally { await done(); }
});

test("a claim of an actual type for a later period is not a forecast: no note, no calculation", async () => {
  const later = { ...ACTUAL, claim_id: "l1", period: "FY2026", period_end: "2026-12-31", evidence_label: "Unverified",
    reason: "claim period not in supplied data: after the latest valid source period, 2024-12", observed_value: null, gap: null };
  const { host, done } = await mount([later]);
  try {
    expect(q(host, "forecast-note")).toBeNull();
    expect(q(host, "register-calc")).toBeNull();
  } finally { await done(); }
});

test("no row carries a rank prefix and no column is a rank", async () => {
  const { host, done } = await mount([FORECAST, ACTUAL]);
  try {
    expect(host.textContent).not.toMatch(/#\d/);
    expect([...host.querySelectorAll("thead th")].map((th) => th.textContent)).not.toContain("#");
  } finally { await done(); }
});

test("the formula inputs and the corrections sit under Details, which stays closed until it is opened", async () => {
  const { host, done } = await mount([FORECAST]);
  try {
    expect(q(host, "register-calc-details")).toBeNull();
    expect(q(host, "register-segment")).toBeNull();
    await act(async () => { q(host, "register-details-toggle").click(); });
    expect([...q(host, "register-calc-details").querySelectorAll("li")].map((li) => li.textContent)).toEqual(FORECAST.calc_details);
    expect(q(host, "register-segment")).not.toBeNull();
    expect(q(host, "register-metric")).not.toBeNull();
    expect(q(host, "register-confidence").textContent).toBe("High");
  } finally { await done(); }
});

test("a question a row asks stays visible with Details closed", async () => {
  const asking = { ...ACTUAL, claim_id: "k1", evidence_label: null, definition_check: "ask", definition_question: "Observed 26, claimed 1. Same metric and period?",
    reason: "definition check: the gap is beyond 50% of the claim" };
  const { host, done } = await mount([asking]);
  try {
    expect(q(host, "definition-check").textContent).toContain("Same metric and period?");
    expect(q(host, "register-segment")).toBeNull();
  } finally { await done(); }
});

// docs/specs/forecast-and-payback.md section 4: an annual payback claim lists both proxies, the S&M scope and the claim's definition.
const PAYBACK = { ...ACTUAL, claim_id: "p1", claim_type: "cac_payback", unit: "months", currency: null, claimed_value: 16, period: "FY2024", metric: "CAC payback",
  observed_value: 16, observed_at: "FY2024 (annual)", observed_citation: "(yearly_basis.years.cac_payback_net_new_arr_months, P&L, rows 3–5, FY2024 (annual))",
  gap: 0, gap_normalised: 0, gloss: "as claimed",
  calc_lines: ["CAC payback FY2024: 24.0 months (yearly, revenue-based) = 12 × S&M €336,000 ÷ (revenue growth €240,000 × gross margin 70.0%)",
    "Annual payback FY2024 (net-new-ARR proxy): 16.0 months = 12 × S&M €336,000 ÷ (net new ARR €360,000 × gross margin 70.0%)", "S&M scope: sales and marketing",
    "Claim definition: net new ARR, gross margin, sales and marketing"] };

test("an annual payback claim shows both named proxies, the S&M scope and the definition it states, and the note stays off", async () => {
  const { host, done } = await mount([PAYBACK]);
  try {
    const lines = [...host.querySelectorAll('[data-testid="register-calc-line"]')].map((n) => n.textContent);
    expect(lines).toEqual(PAYBACK.calc_lines);
    expect(q(host, "forecast-note")).toBeNull();
    expect(q(host, "register-observed-citation").textContent).toContain("yearly_basis.years.cac_payback_net_new_arr_months");
  } finally { await done(); }
});
