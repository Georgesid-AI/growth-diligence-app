// Release 1, committed before the code: docs/specs/evidence-labels.md (plan section 5) and the growth basis of
// docs/specs/dates-and-periods.md section 5 (plan 7.1). Each failing() becomes test() in the code PR of its spec.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import ClaimRegister from "./ClaimRegister";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getClaimRegister: jest.fn(),
  getBlockers: jest.fn(), getBlockers: jest.fn(),
  updateClaimInputs: jest.fn(),
  answerTurnover: jest.fn(),
  answerDefinitionCheck: jest.fn(),
  saveAllGatesCall: jest.fn(),
  claimsCsvUrl: (id) => `http://api/api/audits/${id}/claims.csv`,
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
beforeEach(() => { api.getBlockers.mockResolvedValue([]); });

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const EXTRACTION = "How confidently the app extracted and linked the figure to its source. This does not verify the company’s claim.";
const EVIDENCE = "How this claim compares with the company data supplied for this audit. Agreement is not independent verification.";

// ARR €240,000 for FY2023 against 198,142.68 in the revenue file: read well (High), and wrong (Contradicted).
const ROW = {
  claim_id: "c05", claim_type: "revenue", claimed_value: 240000, claimed_high: null, unit: null, currency: "EUR", period: "FY2023",
  period_note: null, segment: "Whole company", segment_set_by: "python", metric: "ARR", metric_set_by: "python", direction: "higher",
  observed_value: 198142.68, observed_at: "2023-12", observed_source: { file: "revenue.csv", sheet: "CSV", rows: "rows 2–71", rule: "ARR" },
  gap: 41857.32, gap_normalised: 0.174405, gap_kind: "miss", gloss: "€41,857 lower (miss)", evidence_label: "Contradicted",
  reason: "outside ±5%: a miss", tolerance: "±5%", rank: 1, value_at_stake_arr: null, shortfall: 0.174405, overlaps_with: [],
  evidence_analysis: "Monthly MRR by Segment", evidence_source_key: "mrr_series.data.total", extraction_confidence: "High",
  gate_sentence: null, gate_threshold: null, gate_budget_decision: null, gate_metric_name: null, gate_direction: null,
  key_gate: false, gate_needed: true, gate_date: null, gate_saved: false, deck_reading: "parser", page_ref: "slide 7",
};
const RESULTS = { reporting_currency: "EUR", mrr_series: { segments: ["Enterprise", "SMB"] } };

async function mount(rows) {
  api.getClaimRegister.mockResolvedValue({ claims: [], register: rows });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<ClaimRegister auditId="a1" results={RESULTS} />); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}

test("plan 5: the evidence status sits in the Result column and the extraction confidence under Details, apart, with the computed figure and the gap", async () => {
  const { host, done } = await mount([ROW]);
  try {
    const heads = [...host.querySelectorAll("thead th")];
    expect(heads.map((th) => th.textContent.split("(")[0].trim())).toEqual(["Claim and period", "Evidence / calculation", "Result", "Source"]);
    expect(heads[2].getAttribute("title")).toBe(EVIDENCE);
    expect(heads[2].textContent).toContain("(within the supplied evidence)");
    const row = host.querySelector('[data-testid="claim-register-row"]');
    await act(async () => { row.querySelector('[data-testid="register-details-toggle"]').click(); });
    const confidence = row.querySelector('[data-testid="register-confidence"]');
    const status = row.querySelector('[data-testid="register-evidence"]');
    expect(confidence.textContent).toBe("High");
    expect(confidence.parentElement.getAttribute("title")).toBe(EXTRACTION);
    expect(status.textContent).toBe("Contradicted");
    expect(confidence.closest("td")).not.toBe(status.closest("td"));
    expect(row.querySelector('[data-testid="register-observed"]').textContent).toContain("198,143 EUR");
    expect(row.querySelector('[data-testid="register-gap"]').textContent).toBe("41,857 EUR · 17.4%");
  } finally { await done(); }
});

test("an Inconclusive row shows its label, its reason and the computed figure, and no gap", async () => {
  const row = { ...ROW, claim_id: "q1", claim_type: "users", currency: null, unit: "trial accounts", claimed_value: 40, metric: "Customer count",
    observed_value: 5, observed_at: "2024-02", gap: null, gap_normalised: null, gap_kind: null, gloss: null, shortfall: null,
    evidence_label: "Inconclusive", reason: "population differs: deck label 'trial accounts' is not paying customers; the figure shown is paying customers" };
  const { host, done } = await mount([row]);
  try {
    const tr = host.querySelector('[data-testid="claim-register-row"]');
    const status = tr.querySelector('[data-testid="register-evidence"]');
    expect(status.textContent).toBe("Inconclusive");
    expect(status.className).toMatch(/border-/);
    expect(tr.querySelector('[data-testid="register-observed"]').textContent).toContain("5");
    expect(tr.querySelector('[data-testid="register-gap"]').textContent).toBe("—");
    expect(host.textContent).toContain("population differs");
  } finally { await done(); }
});

test("the shared evidence_labels.json is the one list the register reads", async () => {
  const labels = require("@/lib/evidence_labels.json");
  const register = require("@/lib/claimRegister");
  expect(labels.statuses).toEqual(["Verified", "Contradicted", "Inconclusive", "Unverified", "Unsupported"]);
  expect(labels.memo_groups).toEqual({ Unverified: ["Unverified", "Inconclusive"] });
  expect(register.EXTRACTION_EXPLAINER).toBe(labels.explainers.extraction_confidence);
  expect(register.EVIDENCE_EXPLAINER).toBe(labels.explainers.evidence_status);
  expect(labels.explainers).toEqual({ extraction_confidence: EXTRACTION, evidence_status: EVIDENCE });
});

test("the deck list's Confidence column is named Extraction confidence and carries the same explainer", async () => {
  const deck = require("@/lib/deckClaims");
  expect(deck.COLUMNS[5]).toBe("Extraction confidence");
  expect(deck.CONFIDENCE_HOVER).toBe(EXTRACTION);
});

// docs/specs/dates-and-periods.md section 5, plan 7.1: "15% growth" with no cue waits for the analyst's one click.
test("plan 7.1: a growth claim with no basis offers Set growth basis, and one click sends the basis", async () => {
  const row = { ...ROW, claim_id: "g1", claim_type: "revenue_growth", currency: null, unit: "%", claimed_value: 15, metric: "Revenue growth",
    observed_value: null, observed_at: null, gap: null, gap_normalised: null, gap_kind: null, gloss: null, shortfall: null,
    evidence_label: "Unverified", reason: "growth basis unknown: set the growth basis", growth_basis: "unknown" };
  api.updateClaimInputs.mockResolvedValue({ claims: [], register: [row] });
  const { host, done } = await mount([row]);
  try {
    const task = host.querySelector('[data-testid="register-growth-basis"]');
    expect(task.textContent).toContain("Set growth basis");
    expect([...task.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["MoM", "YoY", "Annualised", "Cumulative"]);
    await act(async () => { [...task.querySelectorAll("button")][1].click(); });
    expect(api.updateClaimInputs).toHaveBeenCalledWith("a1", "g1", { growth_basis: "yoy" });
  } finally { await done(); }
});
