// docs/specs/claim-groups.md section 4: a reconciled group is one of the five; the item says it stands for parts and which of them are contradicted.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import FiveClaims from "./FiveClaims";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({ getClaimRegister: jest.fn() }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ROW = { claim_id: "a1", claim_type: "revenue", claimed_value: 1000000, claimed_high: null, unit: null, currency: "EUR", period: "FY2024", rank: 1,
  metric: "Revenue", observed_value: 1000000, observed_at: null, observed_source: null, evidence_label: "Verified", reason: "within ±5% of the claim",
  deck_reading: "parser", page_ref: "slide 3", overlaps_with: [], value_at_stake_arr: null, group_id: "g1", group_role: "total",
  relationship: "Annual total: quarters reconcile with it (€1,000,000 against €1,000,000, within ±2%)" };

async function mount(five) {
  api.getClaimRegister.mockResolvedValue({ register: [ROW] });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<FiveClaims auditId="a1" ccy="EUR" tick={0} verdict={{ verdict: { five } }} />); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}

test("a group item says it is an annual total with its parts, and how many of them are contradicted", async () => {
  const { host, done } = await mount([{ claim_id: "a1", rank: 1, claim: "Revenue, FY2024", evidence_label: "Contradicted", reason: "#4 Revenue, 2024-Q3: Contradicted",
    group: { id: "g1", parts: 4, contradicted: ["q3"] } }]);
  try {
    expect(host.querySelector('[data-testid="five-group"]').textContent).toBe("Annual total with 4 parts · 1 contradicted");
    expect(host.querySelector('[data-testid="five-result"]').textContent).toContain("Contradicted");
    await act(async () => { host.querySelector('[data-testid="five-details-toggle"]').click(); });
    expect(host.querySelector('[data-testid="five-relationship"]').textContent).toContain("quarters reconcile with it");
  } finally { await done(); }
});

test("an item that is no group has no group line", async () => {
  const { host, done } = await mount([{ claim_id: "a1", rank: 1, claim: "Revenue, FY2024", evidence_label: "Verified", reason: "within ±5% of the claim", group: null }]);
  try { expect(host.querySelector('[data-testid="five-group"]')).toBeNull(); } finally { await done(); }
});
