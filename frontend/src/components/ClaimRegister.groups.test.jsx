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
    expect(q(host, "register-group-toggle").textContent).toBe("Details · 4 parts · 1 contradicted");     // the collapsed line carries the part's contradiction
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

test("the collapsed line shows the contradiction of a part before Details is opened, and a total whose parts are all verified shows none", async () => {
  const { host, done } = await mount(GROUPED);
  try {
    expect(q(host, "register-group-toggle").textContent).toContain("1 contradicted");
    expect(q(host, "register-group-parts")).toBeNull();
  } finally { await done(); }
  const clean = GROUPED.map((r) => (r.claim_id === "q2" ? { ...r, evidence_label: "Verified", reason: "within ±5% of the claim" } : r));
  const again = await mount(clean);
  try { expect(q(again.host, "register-group-toggle").textContent).toBe("Details · 4 parts"); } finally { await again.done(); }
});

test("the parts of another set and the figures stated again sit under Details; a repeat names its page", async () => {
  const rows = [...GROUPED,
    row("h1", 7, "2024-H1", 500000, { group_id: "g1", group_role: "also", relationship: "Halves also reconcile with this total; shown under its Details" }),
    row("a2", 8, "FY2024", 1004000, { group_id: "g1", group_role: "repeat", page_ref: "slide 8", relationship: "Same figure as #1 (slide 1); counted once" })];
  const { host, done } = await mount(rows);
  try {
    expect(host.querySelectorAll('[data-testid="claim-register-row"]').length).toBe(2);
    expect(q(host, "register-group-toggle").textContent).toBe("Details · 4 parts · 1 in another set · 1 repeat · 1 contradicted");
    await act(async () => { q(host, "register-group-toggle").click(); });
    const items = [...host.querySelectorAll('[data-testid="register-group-part"]')];
    expect(items.length).toBe(6);
    expect(items[5].textContent).toContain("Also stated:");
    expect(items[5].textContent).toContain("slide 8");
    expect(items[5].textContent).toContain("Same figure as #1 (slide 1); counted once");
  } finally { await done(); }
});

test("a figure stated twice with no group is one row with Details holding the repeat", async () => {
  const lead = row("a1", 1, "FY2024", 1000000, { group_id: "s1" });
  const repeat = row("a2", 2, "FY2024", 1004000, { group_id: "s1", group_role: "repeat", page_ref: "slide 8", relationship: "Same figure as #1 (slide 1); counted once" });
  const { host, done } = await mount([lead, repeat]);
  try {
    expect(host.querySelectorAll('[data-testid="claim-register-row"]').length).toBe(1);
    expect(q(host, "register-group-toggle").textContent).toBe("Details · 1 repeat");
    expect(q(host, "claim-register-counts")).toBeNull();
  } finally { await done(); }
});

test("the segment parts of a total sit under its Details with the segment named, beside the period parts, and are no rows of the list", async () => {
  const rows = [...GROUPED,
    row("p1", 7, "FY2024", 600000, { group_id: "g1", group_role: "segment_part", segment: "Product A", relationship: "Product A: part of the company total for FY2024, by segment" }),
    row("p2", 8, "FY2024", 400000, { group_id: "g1", group_role: "segment_part", segment: "Product B", relationship: "Product B: part of the company total for FY2024, by segment" })];
  const { host, done } = await mount(rows);
  try {
    expect(host.querySelectorAll('[data-testid="claim-register-row"]').length).toBe(2);
    expect(q(host, "register-group-toggle").textContent).toBe("Details · 4 parts · 2 by segment · 1 contradicted");
    await act(async () => { q(host, "register-group-toggle").click(); });
    const items = [...host.querySelectorAll('[data-testid="register-group-part"]')];
    expect(items.length).toBe(6);
    expect(items[4].textContent).toContain("Product A");
    expect(items[5].textContent).toContain("Product B");
    expect(items[4].textContent).toContain("part of the company total for FY2024, by segment");
  } finally { await done(); }
});
