import React, { act } from "react";
import { createRoot } from "react-dom/client";

import ClaimRegister from "./ClaimRegister";
import { REGISTER_COLUMNS } from "@/lib/claimRegister";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getClaimRegister: jest.fn(),
  updateClaimInputs: jest.fn(),
  claimsCsvUrl: (id) => `http://api/api/audits/${id}/claims.csv`,
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ROW = {
  claim_id: "c01", claim_type: "revenue", claimed_value: 200000, claimed_high: null, unit: null, currency: "EUR", period: "Feb 2024",
  period_note: null, segment: "Whole company", segment_set_by: "python", metric: "ARR", metric_set_by: "python", direction: "higher",
  observed_value: 202125.48, observed_at: "2024-02", observed_source: { file: "revenue.csv", sheet: "CSV", rows: "rows 2–71", rule: "ARR" },
  gap: -2125.48, gap_normalised: -0.010627, gap_kind: "beat", gloss: "€2,125 better than claimed", evidence_label: "Verified",
  reason: "within ±5% of the claim", tolerance: "±5%", rank: 1, value_at_stake_arr: null,
  gate_sentence: null, gate_threshold: null, gate_budget_decision: null,
  gate_date: "2024-03-31", gate_saved: false, deck_reading: "parser", page_ref: "slide 4",
};
const RESULTS = { reporting_currency: "EUR", mrr_series: { segments: ["Enterprise", "SMB"] } };

async function mount(rows) {
  api.getClaimRegister.mockResolvedValue({ claims: [], register: rows });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<ClaimRegister auditId="a1" results={RESULTS} />); });
  return { host, root };
}

test("the section has its title, the download button and one row per claim with the spec's columns", async () => {
  const { host } = await mount([ROW, { ...ROW, claim_id: "c02", rank: 2 }]);
  expect(host.querySelector("h2").textContent).toBe("Claim register");
  const button = host.querySelector('[data-testid="claim-register-csv"]');
  expect(button.textContent).toBe("Download baseline (CSV)");
  expect(button.getAttribute("href")).toBe("http://api/api/audits/a1/claims.csv");
  expect([...host.querySelectorAll("thead th")].map((th) => th.textContent)).toEqual(REGISTER_COLUMNS);
  expect(host.querySelectorAll('[data-testid="claim-register-row"]').length).toBe(2);
  const row = host.querySelector('[data-testid="claim-register-row"]');
  expect(row.textContent).toContain("Revenue · 200,000 EUR");
  expect(row.textContent).toContain("Feb 2024");
  expect(row.textContent).toContain("slide 4");
  expect(row.textContent).toContain("Read by the parser");
  expect(row.querySelector('[data-testid="register-observed"]').textContent).toContain("202,125 EUR");
  expect(row.querySelector('[data-testid="register-gap"]').textContent).toBe("beat 2,125 EUR · 1.1%");
  expect(row.querySelector('[data-testid="register-gloss"]').textContent).toBe("€2,125 better than claimed");
  expect(row.querySelector('[data-testid="register-evidence"]').textContent).toBe("Verified");
  expect(row.textContent).toContain("within ±5% of the claim");
  expect(row.querySelector('[data-testid="register-gate-context"]').textContent).toBe("Claimed 200,000 EUR (Feb 2024) · Observed 202,125 EUR (2024-02)");
  expect(row.querySelector('[data-testid="register-gate-threshold"]').value).toBe("");
  expect(row.querySelector('[data-testid="register-gate-sentence"]')).toBeNull();
  expect(host.textContent.toLowerCase()).not.toContain("value at stake");
});

test("the segment and metric are selects of the right options; the rest is text", async () => {
  const { host } = await mount([ROW]);
  const segment = host.querySelector('[data-testid="register-segment"]');
  expect([...segment.options].map((o) => o.value)).toEqual(["Whole company", "Enterprise", "SMB", "Not in the data"]);
  const metric = host.querySelector('[data-testid="register-metric"]');
  expect(metric.value).toBe("ARR");
  expect([...metric.options].map((o) => o.value)).toEqual(["Revenue", "ARR", "MRR", "New MRR", "ACV", "none"]);
  expect(host.querySelectorAll("select").length).toBe(2);
});

test("choosing a segment saves it and the rows follow the server's answer", async () => {
  const { host } = await mount([ROW]);
  api.updateClaimInputs.mockResolvedValue({ register: [{ ...ROW, segment: "Enterprise", segment_set_by: "analyst" }] });
  const segment = host.querySelector('[data-testid="register-segment"]');
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
    setter.call(segment, "Enterprise");
    segment.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(api.updateClaimInputs).toHaveBeenCalledWith("a1", "c01", { segment: "Enterprise" });
  expect(host.querySelector('[data-testid="register-segment"]').value).toBe("Enterprise");
  expect(host.textContent).toContain("set by you");
});

test("a row with no observed value has no gate, a saved gate shows its sentence", async () => {
  const saved = { ...ROW, claim_id: "c2", gate_saved: true, gate_threshold: 195000, gate_budget_decision: "the plan",
    gate_sentence: "Before the plan, ARR must be at least €195,000 by 2024-03-31. Observed €202,125 (2024-02); claimed €200,000 (Feb 2024)." };
  const { host } = await mount([{ ...ROW, observed_value: null }, saved]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(rows[0].querySelector('[data-testid="register-gate-context"]')).toBeNull();
  expect(rows[0].querySelector('[data-testid="register-gate-edit"]')).toBeNull();
  expect(rows[1].querySelector('[data-testid="register-gate-sentence"]').textContent).toContain("Before the plan");
  expect(rows[1].querySelector('[data-testid="register-gate-saved"]').textContent).toBe("Gate saved");
});

test("no claim yet gives a line that says so", async () => {
  const { host } = await mount([]);
  expect(host.querySelector('[data-testid="claim-register-empty"]')).not.toBeNull();
  expect(host.querySelector("table")).toBeNull();
});
