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
  reason: "within ±5% of the claim", tolerance: "±5%", rank: 1, value_at_stake_arr: null, shortfall: null, overlaps_with: [],
  evidence_analysis: "Monthly MRR by Segment", evidence_source_key: "mrr_series.data.total",
  gate_sentence: null, gate_threshold: null, gate_budget_decision: null, gate_metric_name: null, gate_direction: null,
  key_gate: false, gate_needed: false, gate_date: null, gate_saved: false, deck_reading: "parser", page_ref: "slide 4",
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
  expect(row.querySelector('[data-testid="register-value-at-stake"]').textContent).toBe("not yet computed");
  expect(row.querySelector('[data-testid="register-overlaps"]').textContent).toBe("—");
  expect(row.querySelector('[data-testid="register-evidence-source"]').textContent).toBe("Monthly MRR by Segment · mrr_series.data.total (2024-02)");
  expect(row.querySelector('[data-testid="register-gate-date"]').textContent).toBe("Gate date", "the gate date starts empty");
  expect(row.querySelector('[data-testid="register-gate-needed"]')).toBeNull();
  expect(row.querySelector('[data-testid="register-gate-context"]').textContent).toBe("Claimed 200,000 EUR (Feb 2024) · Observed 202,125 EUR (2024-02)");
  expect(row.querySelector('[data-testid="register-gate-threshold"]').value).toBe("");
  expect(row.querySelector('[data-testid="register-gate-sentence"]')).toBeNull();
});

test("overlaps show the other rows' ranks and a shortfall shows beside the value at stake", async () => {
  const { host } = await mount([{ ...ROW, overlaps_with: ["c02"], shortfall: 0.183 }, { ...ROW, claim_id: "c02", rank: 2, overlaps_with: ["c01"] }]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(rows[0].querySelector('[data-testid="register-overlaps"]').textContent).toBe("#2");
  expect(rows[1].querySelector('[data-testid="register-overlaps"]').textContent).toBe("#1");
  expect(rows[0].querySelector('[data-testid="register-value-at-stake"]').textContent).toBe("not yet computed · shortfall 18.3%");
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

test("every row has a gate: Gate needed until it is saved, then its sentence; a row with no figure shows only the claimed one", async () => {
  const saved = { ...ROW, claim_id: "c2", gate_saved: true, gate_threshold: 195000, gate_budget_decision: "the plan", gate_date: "2024-06-30",
    gate_sentence: "Before the plan, ARR must be at least €195,000 by 2024-06-30. Observed €202,125 (2024-02); claimed €200,000 (Feb 2024)." };
  const { host } = await mount([{ ...ROW, observed_value: null, evidence_label: "Unverified", gate_needed: true }, saved]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(rows[0].querySelector('[data-testid="register-gate-context"]').textContent).toBe("Claimed 200,000 EUR (Feb 2024)");
  expect(rows[0].querySelector('[data-testid="register-gate-needed"]').textContent).toBe("Gate needed");
  expect(rows[1].querySelector('[data-testid="register-gate-needed"]')).toBeNull();
  expect(rows[1].querySelector('[data-testid="register-gate-sentence"]').textContent).toContain("Before the plan");
  expect(rows[1].querySelector('[data-testid="register-gate-saved"]').textContent).toBe("Gate saved");
});

test("the key gate checkbox is off until the gate is saved, saves on a click and sends false to clear it", async () => {
  const saved = { ...ROW, gate_saved: true, gate_threshold: 1, gate_budget_decision: "x", gate_date: "2024-06-30" };
  const { host } = await mount([ROW, saved]);
  const boxes = host.querySelectorAll('[data-testid="register-key-gate"]');
  expect([boxes[0].disabled, boxes[1].disabled]).toEqual([true, false]);
  expect(host.textContent).toContain("Key gate");
  api.updateClaimInputs.mockResolvedValue({ register: [{ ...saved, key_gate: true }] });
  await act(async () => { boxes[1].click(); });
  expect(api.updateClaimInputs).toHaveBeenCalledWith("a1", "c01", { key_gate: true });
  api.updateClaimInputs.mockResolvedValue({ register: [saved] });
  await act(async () => { host.querySelector('[data-testid="register-key-gate"]').click(); });
  expect(api.updateClaimInputs).toHaveBeenLastCalledWith("a1", "c01", { key_gate: false });
});

test("a refused key gate shows the server's reason", async () => {
  const { toast } = require("sonner");
  const saved = { ...ROW, gate_saved: true, gate_threshold: 1, gate_budget_decision: "x", gate_date: "2024-06-30" };
  const { host } = await mount([saved]);
  api.updateClaimInputs.mockRejectedValue({ response: { status: 400, data: { detail: "At most 5 key gates." } } });
  await act(async () => { host.querySelector('[data-testid="register-key-gate"]').click(); });
  expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("At most 5 key gates."));
});

test("a row with no metric of the app asks for the metric (max 100 characters) and At least / At most", async () => {
  const none = { ...ROW, metric: null, reason: "no metric", observed_value: null, evidence_label: "Unsupported", evidence_analysis: null, gate_needed: true };
  const { host } = await mount([none, ROW]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  const name = rows[0].querySelector('[data-testid="register-gate-metric-name"]');
  expect(name.getAttribute("placeholder")).toBe("Metric (max 100 characters)");
  expect(name.maxLength).toBe(100);
  expect([...rows[0].querySelector('[data-testid="register-gate-direction"]').options].map((o) => o.textContent)).toEqual(["", "At least", "At most"]);
  expect(rows[1].querySelector('[data-testid="register-gate-metric-name"]')).toBeNull();
});

test("no claim yet gives a line that says so", async () => {
  const { host } = await mount([]);
  expect(host.querySelector('[data-testid="claim-register-empty"]')).not.toBeNull();
  expect(host.querySelector("table")).toBeNull();
});
