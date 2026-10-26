// docs/specs/forecast-and-payback.md section 5: the five selected claims use the same four columns and the same calculation lines as the register,
// show the forecast note once under them, and carry no rank prefix.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import FiveClaims from "./FiveClaims";
import claimColumns from "@/lib/claim_columns.json";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({ getClaimRegister: jest.fn() }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const FORECAST = { claim_id: "f1", claim_type: "revenue", claimed_value: 2073600, claimed_high: null, unit: null, currency: "EUR", period: "FY2026", rank: 1,
  period_end: "2026-12-31", as_of_month: "2024-12", figure_type: "target", metric: "Revenue", observed_value: null, observed_source: null, observed_citation: null,
  evidence_label: "Unverified", reason: "Forecast: required growth 20.0% a year against 20.0% historical", deck_reading: "parser", page_ref: "slide 3",
  overlaps_with: [], value_at_stake_arr: null, group_id: null, group_role: null, relationship: null, segment: "Whole company",
  calc_lines: ["Required growth: 20.0% a year (€2,073,600 for FY2026 against €1,440,000 for FY2024, 24 months)", "Historical growth: 20.0% (FY2023 → FY2024)"],
  calc_details: ["required annual growth = (forecast ÷ base) ^ (12 ÷ elapsed months) − 1"] };
const PLAIN = { ...FORECAST, claim_id: "a1", rank: 2, period: "FY2024", period_end: "2024-12-31", figure_type: "actual", calc_lines: [], calc_details: [],
  observed_value: 1440000, observed_at: "2024-01 to 2024-12", gap: 0, gap_normalised: 0, evidence_label: "Verified", reason: "within ±5% of the claim" };

async function mount(five, rows) {
  api.getClaimRegister.mockResolvedValue({ register: rows });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<FiveClaims auditId="a1" ccy="EUR" tick={0} verdict={{ verdict: { five } }} />); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}
const item = (row) => ({ claim_id: row.claim_id, rank: row.rank, claim: `${row.metric}, ${row.period}`, evidence_label: row.evidence_label, reason: row.reason, group: null });

test("the five read the four shared columns and the forecast's calculation lines", async () => {
  const { host, done } = await mount([item(FORECAST), item(PLAIN)], [FORECAST, PLAIN]);
  try {
    const five = host.querySelector('[data-testid="verdict-five"]');
    const heads = [...five.querySelectorAll(".uppercase span")].map((n) => n.textContent);
    expect(heads).toEqual(claimColumns.columns);
    const rows = five.querySelectorAll('[data-testid="verdict-five-row"]');
    expect([...rows[0].querySelectorAll('[data-testid="five-calc-line"]')].map((n) => n.textContent)).toEqual(FORECAST.calc_lines);
    expect(rows[0].querySelector('[data-testid="five-result"]').textContent).toContain(FORECAST.reason);
    expect(rows[1].querySelector('[data-testid="five-calc"]')).toBeNull();
    expect(rows[1].querySelector('[data-testid="five-evidence-cell"]').textContent).toContain("1,440,000");
  } finally { await done(); }
});

test("the forecast note is shown once under the five when one of them is a forecast, and on no row", async () => {
  const { host, done } = await mount([item(FORECAST), item({ ...FORECAST, claim_id: "f2", rank: 3 })], [FORECAST, { ...FORECAST, claim_id: "f2", rank: 3 }]);
  try {
    const notes = host.querySelectorAll('[data-testid="five-forecast-note"]');
    expect(notes.length).toBe(1);
    expect(notes[0].textContent).toBe(claimColumns.forecast_note);
    for (const row of host.querySelectorAll('[data-testid="verdict-five-row"]')) expect(row.textContent).not.toContain("future outcomes are unverified");
  } finally { await done(); }
  const none = await mount([item(PLAIN)], [PLAIN]);
  try { expect(none.host.querySelector('[data-testid="five-forecast-note"]')).toBeNull(); } finally { await none.done(); }
});

test("no row of the five carries a rank prefix, and Details holds the formula inputs", async () => {
  const { host, done } = await mount([item(FORECAST)], [FORECAST]);
  try {
    expect(host.textContent).not.toMatch(/#\d/);
    await act(async () => { host.querySelector('[data-testid="five-details-toggle"]').click(); });
    expect(host.querySelector('[data-testid="five-calc-details"]').textContent).toContain("required annual growth");
  } finally { await done(); }
});
