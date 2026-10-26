// docs/specs/claim-groups.md section 4: a reconciled annual total is shown once, its parts under Details, each with its own label; the counts
// of items and claims are told apart; a relationship note says why a set of parts was not grouped.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import ClaimRegister from "./ClaimRegister";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getClaimRegister: jest.fn(), getBlockers: jest.fn(), updateClaimInputs: jest.fn(), answerTurnover: jest.fn(), answerDefinitionCheck: jest.fn(),
  claimsCsvUrl: (id) => `http://api/api/audits/${id}/claims.csv`,
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
beforeEach(() => { api.getBlockers.mockResolvedValue([]); });

const row = (id, rank, period, value, extra = {}) => ({
  claim_id: id, claim_type: "revenue", claimed_value: value, claimed_high: null, unit: null, currency: "EUR", period, period_note: null,
  segment: "Whole company", segment_set_by: "python", metric: "Revenue", metric_set_by: "python", direction: "higher", observed_value: value,
  observed_at: null, observed_source: null, observed_citation: null, gap: 0, gap_normalised: 0, gap_kind: null, gloss: "as claimed",
  evidence_label: "Verified", reason: "within ±5% of the claim", tolerance: "±5%", rank, value_at_stake_arr: null, shortfall: null, overlaps_with: [],
  gate_sentence: null, deck_reading: "parser", page_ref: `slide ${rank}`, group_id: null, group_role: null, relationship: null, ...extra,
});
const GROUPED = [
  row("a1", 1, "FY2024", 1000000, { group_id: "g1", group_role: "total", relationship: "Annual total: quarters reconcile with it (€1,000,000 against €1,000,000, within ±2%)" }),
  row("q1", 2, "2024-Q1", 250000, { group_id: "g1", group_role: "part", relationship: "Part of the annual total for FY2024" }),
  row("q2", 3, "2024-Q2", 250000, { group_id: "g1", group_role: "part", evidence_label: "Contradicted", reason: "outside ±5%: a miss" }),
  row("q3", 4, "2024-Q3", 250000, { group_id: "g1", group_role: "part" }),
  row("q4", 5, "2024-Q4", 250000, { group_id: "g1", group_role: "part" }),
  row("x1", 6, "FY2023", 400000),
];

async function mount(register) {
  api.getClaimRegister.mockResolvedValue({ claims: [], register });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<ClaimRegister auditId="a1" results={{ reporting_currency: "EUR" }} />); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}
const q = (host, id) => host.querySelector(`[data-testid="${id}"]`);

test("the total is shown once and its four parts are not rows of the list", async () => {
  const { host, done } = await mount(GROUPED);
  try {
    expect(host.querySelectorAll('[data-testid="claim-register-row"]').length).toBe(2);
    expect(q(host, "claim-register-counts").textContent).toBe("2 items shown for 6 claims; 1 annual total stands for its parts.");
    expect(q(host, "register-relationship").textContent).toContain("quarters reconcile with it");
    expect(q(host, "register-group-parts")).toBeNull();
  } finally { await done(); }
});

test("Details opens the parts, each with its own period, label and reason; a contradicted part is not hidden", async () => {
  const { host, done } = await mount(GROUPED);
  try {
    expect(q(host, "register-group-toggle").textContent).toBe("Details · 4 parts");
    await act(async () => { q(host, "register-group-toggle").click(); });
    const parts = [...host.querySelectorAll('[data-testid="register-group-part"]')];
    expect(parts.map((p) => p.textContent.includes("2024-Q"))).toEqual([true, true, true, true]);
    expect(parts[1].textContent).toContain("Contradicted");
    expect(parts[1].textContent).toContain("outside ±5%: a miss");
    await act(async () => { q(host, "register-group-toggle").click(); });
    expect(q(host, "register-group-parts")).toBeNull();
  } finally { await done(); }
});

test("with nothing grouped there is no count line and a row says why its parts were not grouped", async () => {
  const { host, done } = await mount([row("a1", 1, "FY2024", 1000000, { relationship: "Quarters: 3 of 4 stated; kept as independent claims" }), row("q1", 2, "2024-Q1", 250000)]);
  try {
    expect(host.querySelectorAll('[data-testid="claim-register-row"]').length).toBe(2);
    expect(q(host, "claim-register-counts")).toBeNull();
    expect(q(host, "register-relationship").textContent).toBe("Quarters: 3 of 4 stated; kept as independent claims");
    expect(q(host, "register-group-toggle")).toBeNull();
  } finally { await done(); }
});
