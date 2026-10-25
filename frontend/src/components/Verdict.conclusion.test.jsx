// docs/specs/claim-review-conclusion.md (plan section 1 and 7.1): the conclusion, the contradictions outside the five, the judgment.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import { Conclusion, VerdictDetail } from "./Verdict";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({ getMemo: jest.fn(), putIcInputs: jest.fn(() => Promise.resolve({})), getBlockers: jest.fn(() => Promise.resolve([])) }));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
beforeEach(() => { api.getBlockers.mockResolvedValue([]); });

const HEADING = "Claim-review conclusion — assessment of the five selected claims";
const SCOPE = "This assesses the five claims the analyst selected. It is not an investment recommendation.";
const BANNED = /\b(?:underwrite|re-plan|invest|pass|proceed)\b/i;
const SELECTED = ["c01", "c21", "c23", "c27", "c31"];
const five = SELECTED.map((id, n) => ({ claim_id: id, rank: n + 2, claim: `Claim ${id}`, evidence_label: "Verified", reason: "within ±5% of the claim" }));

// GET /audits/{id}/verdict for plan test 1: five Verified selected claims, one Contradicted claim outside them.
const RESPONSE = {
  verdict: {
    heading: HEADING, scope_sentence: SCOPE, status: "ok", outcome: "Selected claims supported", outcome_code: "supported",
    rule: "All 5 selected claims are Verified.", message: null, blocked: [], five, reasons: [],
    top5: { proposed: SELECTED, confirmed: true, void: false, claim_ids: SELECTED, set_at: "2026-10-15", in_force: SELECTED },
    other_contradictions: [{ claim_id: "c05", rank: 1, metric: "ARR, FY2023", gap: "€41,857 lower (miss)",
      source: "Monthly MRR by Segment · mrr_series.data.total · revenue.csv · CSV · rows 2–71 · testco_board.pptx slide 7" }],
    other_contradictions_text: null,
  },
  data_gaps: [], top_gaps: [], key_gates: { note: "No key gates marked.", ok: true, all_key: true, saved: 0, sentences: [] },
  gates_still_needed: 1, deal_terms: "Deal terms: not available – the execution capacity review has not been run.",
  top5_statement: "Top 5 set by the analyst pending ARR bridge.",
  candidates: [...five, { claim_id: "c05", rank: 1, claim: "ARR, FY2023", evidence_label: "Contradicted", reason: "outside ±5%: a miss" }],
  ic_inputs: { first_quarterly_review: "2027-01-13", ratings: null, thesis: null, judgment: null },
  ratings: ["Strong", "Adequate", "Weak"], ratings_for: { data_reliability: "Data reliability", growth_engine: "Growth engine" },
  thesis_labels: { plan: "Plan", evidence: "Evidence", condition: "Condition" }, thesis_max: 300,
  judgment_labels: { reasons: "Reasons", unresolved_questions: "Unresolved questions" }, judgment_max: 1000,
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

test("the analyst judgment has two empty fields, Reasons and Unresolved questions, never pre-filled", async () => {
  const { host, done } = await mount(RESPONSE);
  try {
    expect(host.querySelector('[data-testid="judgment-reasons"]').value).toBe("");
    expect(host.querySelector('[data-testid="judgment-unresolved_questions"]').value).toBe("");
    expect(host.textContent).toContain("Analyst judgment");
  } finally { await done(); }
});

test("the section never shows Underwrite, Re-plan, invest, pass or proceed", async () => {
  const { host, done } = await mount(RESPONSE);
  try {
    expect(host.textContent).not.toMatch(BANNED);
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

test("a confirmed top 5 sits behind the one Change link; an unconfirmed one is asked for in place", async () => {
  const { host, done } = await mount(RESPONSE);
  try {
    expect(host.querySelector('[data-testid="verdict-top5"]')).toBeNull();
    expect(host.querySelector('[data-testid="top5-change"]').textContent).toBe("Change");
    await act(async () => { host.querySelector('[data-testid="top5-change"]').click(); });
    expect(host.querySelector('[data-testid="verdict-top5"]')).not.toBeNull();
  } finally { await done(); }
  const open = await mount({ ...RESPONSE, verdict: { ...RESPONSE.verdict, status: "unconfirmed", outcome: null, top5: { ...RESPONSE.verdict.top5, confirmed: false } } });
  try {
    expect(open.host.querySelector('[data-testid="top5-change"]')).toBeNull();
    expect(open.host.querySelector('[data-testid="verdict-top5"]')).not.toBeNull();
  } finally { await open.done(); }
});
