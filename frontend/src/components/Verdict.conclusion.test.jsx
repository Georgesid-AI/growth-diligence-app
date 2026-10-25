// docs/specs/claim-review-conclusion.md (plan section 1 and 7.1) and docs/design/simplified-flow.md: the conclusion, the contradictions outside the five, the computed ratings and lists.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import { Conclusion, VerdictDetail } from "./Verdict";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({ getMemo: jest.fn(), putIcInputs: jest.fn(() => Promise.resolve({})), getBlockers: jest.fn(() => Promise.resolve([])),
  getClaimRegister: jest.fn(), updateClaimInputs: jest.fn(() => Promise.resolve({})) }));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
beforeEach(() => {
  api.getBlockers.mockResolvedValue([]); api.putIcInputs.mockResolvedValue({}); api.updateClaimInputs.mockResolvedValue({});
  api.getClaimRegister.mockResolvedValue({ claims: [], register: [] });
});

const HEADING = "Claim-review conclusion — assessment of the five selected claims";
const SCOPE = "This assesses the five claims the analyst selected. It is not an investment recommendation.";
const SELECTED = ["c01", "c21", "c23", "c27", "c31"];
const five = SELECTED.map((id, n) => ({ claim_id: id, rank: n + 2, claim: `Claim ${id}`, evidence_label: "Verified", reason: "within ±5% of the claim" }));

// GET /audits/{id}/verdict for plan test 1: five Verified selected claims, one Contradicted claim outside them.
const RESPONSE = {
  verdict: {
    heading: HEADING, scope_sentence: SCOPE, status: "ok", outcome: "Selected claims supported", outcome_code: "supported",
    rule: "All 5 selected claims are Verified.", message: null, five, reasons: [],
    top5: { proposed: SELECTED, changed: false, claim_ids: [], set_at: null, in_force: SELECTED },
    other_contradictions: [{ claim_id: "c05", rank: 1, metric: "ARR, FY2023", gap: "€41,857 lower (miss)",
      source: "Monthly MRR by Segment · mrr_series.data.total · revenue.csv · CSV · rows 2–71 · testco_board.pptx slide 7" }],
    other_contradictions_text: null,
  },
  data_gaps: [], top_gaps: [], key_gates: { note: "No key gates: every selected claim is Verified.", ok: true, all_key: true, saved: 0, sentences: [] },
  deal_terms: "Deal terms: not available – the execution capacity review has not been run.",
  selection_sentence: "Selected by the app by value at stake; the analyst may change the selection", benchmark_label: "benchmark, not company data",
  candidates: [...five, { claim_id: "c05", rank: 1, claim: "ARR, FY2023", evidence_label: "Contradicted", reason: "outside ±5%: a miss" }],
  ic_inputs: { first_quarterly_review: "2027-01-13", thesis: null, note: null },
  ratings: { data_reliability: { rating: "Weak", line: "Weak (Material concerns; 5 of 5 checks)", rule: "Weak: at least one check Red, 5 of 5 completed", benchmark: false },
    growth_engine: { rating: null, line: "not rated – data missing", rule: "not rated – data missing: NRR not computed", benchmark: true } },
  unresolved_questions: ["Required vs observed net-new customers (12m): Blocks Path to Plan."],
  thesis_draft: { plan: "The plan targets ARR of 1,000,000 EUR by 2026-12-31.", evidence: "Selected claims supported: All 5 selected claims are Verified.", condition: "No condition: every selected claim is Verified." },
  thesis_labels: { plan: "Plan", evidence: "Evidence", condition: "Condition" }, thesis_max: 300, note_max: 1000,
};

async function mount(response) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<><Conclusion auditId="a1" verdict={response} onChanged={() => {}} /><VerdictDetail auditId="a1" verdict={response} onChanged={() => {}} /></>); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}

test("plan 1: Selected claims supported and the contradiction outside the five show in the same block", async () => {
  const { host, done } = await mount(RESPONSE);
  try {
    const block = host.querySelector('[data-testid="verdict"]');
    expect(block.querySelector("h2").textContent).toBe(HEADING);
    expect(block.querySelector('[data-testid="verdict-outcome"]').textContent).toContain("Selected claims supported");
    expect(block.querySelector('[data-testid="conclusion-scope"]').textContent).toBe(SCOPE);
    const others = block.querySelector('[data-testid="other-contradictions"]');
    expect(others.textContent).toContain("ARR, FY2023");
    expect(others.textContent).toContain("€41,857 lower (miss)");
    expect(others.textContent).toContain("testco_board.pptx slide 7");
  } finally { await done(); }
});

test("no contradiction outside the five reads None found among tested claims", async () => {
  const response = { ...RESPONSE, verdict: { ...RESPONSE.verdict, other_contradictions: [], other_contradictions_text: "None found among tested claims." } };
  const { host, done } = await mount(response);
  try {
    expect(host.querySelector('[data-testid="other-contradictions"]').textContent).toContain("None found among tested claims.");
  } finally { await done(); }
});

test("the ratings are computed lines, the benchmark label goes with the one that uses a threshold, and the rule sits under details; nothing is selected", async () => {
  const { host, done } = await mount(RESPONSE);
  try {
    const lines = [...host.querySelectorAll('[data-testid="verdict-rating"]')].map((n) => n.textContent);
    expect(lines).toEqual(["Data reliability: Weak (Material concerns; 5 of 5 checks)", "Growth engine: not rated – data missingbenchmark, not company data"]);
    expect(host.querySelectorAll('[data-testid="rating-benchmark"]').length).toBe(1);
    expect(host.querySelector('select')).toBeNull();
    expect(host.querySelector('[data-testid="ratings-rules"]')).toBeNull();
    await act(async () => { host.querySelector('[data-testid="ratings-details"]').click(); });
    expect(host.querySelector('[data-testid="ratings-rules"]').textContent).toContain("Weak: at least one check Red, 5 of 5 completed");
  } finally { await done(); }
});

test("the unresolved questions are a computed list and the old judgment fields are gone", async () => {
  const { host, done } = await mount(RESPONSE);
  try {
    expect(host.querySelector('[data-testid="verdict-unresolved"]').textContent).toContain("Required vs observed net-new customers (12m)");
    expect(host.querySelector('[data-testid="judgment-reasons"]')).toBeNull();
    expect(host.querySelector('[data-testid="judgment-heading"]')).toBeNull();
    expect(host.textContent).toContain(SCOPE);
  } finally { await done(); }
});

// docs/design/simplified-flow.md, The Audit page, item 3: the contradiction lines sit directly under the conclusion and its explanation.
test("the contradicted top-5 lines sit in the conclusion block, under the outcome, its rule and the scope sentence, and above the other contradictions", async () => {
  const lines = ["Top-5 claim contradicted: revenue 156,934.4 EUR vs 136,739.01 EUR observed (test deck (PDF), p5).",
    "Top-5 claim contradicted: revenue 2,000,000 EUR vs 1,500,000 EUR observed (board.pptx, slide 4)."];
  api.getBlockers.mockResolvedValue([{ kind: "revenue_file_missing", text: "Revenue file missing." }, ...lines.map((text) => ({ kind: "claim_contradicted", text }))]);
  const { host, done } = await mount(RESPONSE);
  try {
    await act(async () => { await Promise.resolve(); });
    const block = host.querySelector('[data-testid="verdict"]');
    const banner = block.querySelector('[data-testid="contradiction-banner"]');
    expect([...banner.querySelectorAll("li")].map((li) => li.textContent)).toEqual(lines);
    const follows = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(block.querySelector('[data-testid="verdict-outcome"]'), banner)).toBe(true);
    expect(follows(block.querySelector('[data-testid="verdict-rule"]'), banner)).toBe(true);
    expect(follows(block.querySelector('[data-testid="conclusion-scope"]'), banner)).toBe(true);
    expect(follows(banner, block.querySelector('[data-testid="other-contradictions"]'))).toBe(true);
    expect(block.querySelector('[data-testid="blocker-revenue_file_missing"]')).toBeNull();          // other blockers stay in the header
  } finally { await done(); }
});

test("the selection sentence and the one Change link; a changed set reads 'Top 5 changed by the analyst —' with a reset that sends top5 null", async () => {
  const { host, done } = await mount(RESPONSE);
  try {
    expect(host.querySelector('[data-testid="verdict-top5"]')).toBeNull();
    expect(host.querySelector('[data-testid="verdict-top5-note"]').textContent).toBe("Selected by the app by value at stake; the analyst may change the selection");
    expect(host.querySelector('[data-testid="top5-reset"]')).toBeNull();
    expect(host.querySelector('[data-testid="top5-change"]').textContent).toBe("Change");
    await act(async () => { host.querySelector('[data-testid="top5-change"]').click(); });
    expect(host.querySelector('[data-testid="verdict-top5"]')).not.toBeNull();
  } finally { await done(); }
  const changed = await mount({ ...RESPONSE, verdict: { ...RESPONSE.verdict, top5: { ...RESPONSE.verdict.top5, changed: true, claim_ids: SELECTED, set_at: "2026-10-25" } } });
  try {
    expect(changed.host.querySelector('[data-testid="verdict-top5-note"]').textContent).toBe("Top 5 changed by the analyst — reset");
    await act(async () => { changed.host.querySelector('[data-testid="top5-reset"]').click(); });
    expect(api.putIcInputs).toHaveBeenCalledWith("a1", { top5: null });
  } finally { await changed.done(); }
});

// Verdict detail, Key gates: the gate of each non-Verified claim of the five, edited here only.
const GATED = {
  ...RESPONSE,
  key_gates: { note: "1 gates set; all are key gates.", ok: true, all_key: true, saved: 1,
    sentences: [{ claim_id: "c05", rank: 1, status: "proposed", sentence: "ARR must be at least €240,000 by 2023-12-31.", text: "ARR must be at least €240,000 by 2023-12-31. (proposed)" }] },
};
const ROW = { claim_id: "c05", claim_type: "revenue", claimed_value: 240000, currency: "EUR", period: "FY2023", metric: "ARR", reason: "outside ±5%: a miss",
  observed_value: 198143, observed_at: "2023-12", evidence_label: "Contradicted", gate_status: "proposed", gate_saved: false, gate_threshold: 240000, gate_date: "2023-12-31",
  gate_budget_decision: null, gate_metric_name: null, gate_direction: null };

test("a key gate reads (proposed), opens the editor on Edit gate and a change is stored through the claim's inputs", async () => {
  api.getClaimRegister.mockResolvedValue({ claims: [], register: [ROW] });
  const { host, done } = await mount(GATED);
  try {
    await act(async () => { await Promise.resolve(); });
    const gate = host.querySelector('[data-testid="key-gate"]');
    expect(gate.textContent).toContain("ARR (see glossary) must be at least €240,000 by 2023-12-31. (proposed)");
    expect(host.querySelector('[data-testid="gate-editor"]')).toBeNull();
    await act(async () => { host.querySelector('[data-testid="key-gate-edit"]').click(); });
    const input = host.querySelector('[data-testid="gate-threshold"]');
    expect(input.value).toBe("240000");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "195000");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { host.querySelector('[data-testid="gate-save"]').click(); });
    expect(api.updateClaimInputs).toHaveBeenCalledWith("a1", "c05", { gate_threshold: 195000, gate_date: "2023-12-31" });
  } finally { await done(); }
});

test("no key gate has a checkbox, a Set gate button or a Save all gates button, and no gate is required", async () => {
  const { host, done } = await mount(GATED);
  try {
    expect(host.querySelector('input[type="checkbox"]')).toBeNull();
    expect(host.textContent).not.toMatch(/Set gate|Save all gates|Gate needed|Key gate\b|Confirm top 5/);
  } finally { await done(); }
});
