import React, { act } from "react";
import { createRoot } from "react-dom/client";

import Dashboard from "./Dashboard";
import * as api from "@/lib/api";
import sample from "./fixtures/sample_results.json";

jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), getResults: jest.fn(), readNarrative: jest.fn(), generateNarrative: jest.fn(), getDisclosure: jest.fn(),
  getClaimRegister: jest.fn(), getBlockers: jest.fn(), updateClaimInputs: jest.fn(), claimsCsvUrl: () => "x", exportUrl: () => "x", reportUsage: jest.fn(),
  getVerdict: jest.fn(), putIcInputs: jest.fn(), getMemo: jest.fn(), getIntegrity: jest.fn(),
  NARRATIVE_TIMEOUT_MS: 150000, NARRATIVE_EXPECTED_SECONDS: 33,
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
beforeEach(() => { api.getBlockers.mockResolvedValue([]); });
jest.mock("react-router-dom", () => ({ useParams: () => ({ id: "a1" }), useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));
jest.mock("recharts", () => new Proxy({}, { get: () => ({ children }) => <div>{children}</div> }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
window.history.pushState({}, "", "/?view=legacy");      // PR 3: the earlier screen, which this file tests, is behind ?view=legacy (lib/legacyView.js)

// What GET /audits/{id}/verdict and GET answer (docs/specs/verdict-and-memo.md). The server tests, ranks and words.
const TOP = {
  proposed: ["c1", "c2"], changed: false, claim_ids: [], set_at: null, in_force: ["c1", "c2"],
};
const CANDIDATES = [
  { claim_id: "c1", rank: 1, claim: "ARR, FY2023", evidence_label: "Contradicted", reason: "outside ±5%: a miss" },
  { claim_id: "c2", rank: 2, claim: "Revenue, Q4 2023", evidence_label: "Contradicted", reason: "outside ±5%: a miss" },
  { claim_id: "c3", rank: 3, claim: "Win rate", evidence_label: "Verified", reason: "within ±1 pp of the claim" },
];
const VERDICT_BASE = {
  verdict: { top5: TOP, status: "no_verdict", message: "No conclusion: compute the audit first.", outcome: null, rule: null, five: [], reasons: [] },
  data_gaps: [{ item: "NRR (12-month)", why: "Blocks NRR; claims #4. Needs 12+ months of history.", requested: "Provide at least 13 months of revenue lines", target_date: null, claims: [], ranks: [4] }],
  top_gaps: [], key_gates: { note: "No key gates: every selected claim is Verified.", ok: true, all_key: true, saved: 0, sentences: [] },
  deal_terms: "Deal terms: not available – the execution capacity review has not been run.",
  selection_sentence: "Selected by the app by value at stake; the analyst may change the selection",
  candidates: CANDIDATES, ic_inputs: { first_quarterly_review: null, thesis: null, note: null }, ratings: null, unresolved_questions: [],
  benchmark_label: "benchmark, not company data", thesis_draft: { plan: "The plan targets ARR of 1,000,000 EUR by 2026-12-31.", evidence: "x", condition: "y" },
  thesis_labels: { plan: "Plan", evidence: "Evidence", condition: "Condition" }, thesis_max: 300, note_max: 1000,
};
const VERDICT_NONE = VERDICT_BASE;

// Degrade, don't die (CLAUDE.md rule 20): the gateway fails, every computed metric still renders with its citation.
test("when the narrative cannot be generated the metrics render with their sources and S17 says why", async () => {
  api.getAudit.mockResolvedValue(sample.audit);
  api.getResults.mockResolvedValue(sample);
  api.readNarrative.mockResolvedValue({ narrative_status: "unavailable", reason: "The provider did not answer" });
  api.getDisclosure.mockResolvedValue(null);
  api.getClaimRegister.mockResolvedValue({ claims: [], register: [] });
  api.getVerdict.mockResolvedValue(VERDICT_NONE);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<Dashboard />); });
  await act(async () => { await Promise.resolve(); });
  const notice = host.querySelector('[data-testid="narrative-unavailable"]');
  expect(notice.textContent).toContain("Narrative could not be generated.");
  expect(notice.textContent).toContain("The computed metrics below are unaffected — they come from the calculation engine, not the narrative.");
  expect(host.textContent).toContain("Ending ARR202,125 EUR");
  // Each figure keeps its citation: a source-lineage trigger wraps it (the card shows file, sheet, rows on hover).
  for (const metric of ["arr", "nrr", "gross_churn"]) {
    expect(host.querySelector(`[data-testid="provenance-hover-${metric}"]`)).not.toBeNull();
  }
  expect(sample.results.arr.source.row_numbers.length).toBeGreaterThan(0);
  await act(async () => { root.unmount(); });
  host.remove();
});

test("results of an older engine contract answer 409 Stale – re-run audit: the dashboard says so and shows no figure (George, 2026-10-20)", async () => {
  api.getAudit.mockResolvedValue(sample.audit);
  api.getResults.mockRejectedValue({ response: { status: 409, data: { detail: { code: "results_stale", message: "Stale – re-run audit" } } } });
  api.getVerdict.mockResolvedValue(VERDICT_NONE);
  api.getClaimRegister.mockResolvedValue({ claims: [], register: [] });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<Dashboard />); });
  await act(async () => { await Promise.resolve(); });
  expect(host.querySelector('[data-testid="stale-results"]').textContent).toContain("Stale – re-run audit");
  expect(host.textContent).not.toContain("Ending ARR");
  await act(async () => { root.unmount(); });
  host.remove();
});

test("the dashboard offers one Write narrative button for the data inventory and one for the data integrity, and the metrics render when both fail", async () => {
  const { host, unmount } = await mountDashboard(sample);
  for (const step of ["data_inventory", "data_integrity"]) {
    expect(host.querySelector(`[data-testid="narrative-generate-${step}"]`).textContent).toBe("Write narrative");
    expect(api.readNarrative).toHaveBeenCalledWith("a1", step);
    expect(host.querySelector(`[data-testid="narrative-unavailable-${step}"]`)).not.toBeNull();
  }
  expect(api.generateNarrative).not.toHaveBeenCalled();
  expect(host.textContent).toContain("Ending ARR202,125 EUR");
  await unmount();
});

const CITED_BLOCKS = ["mrr-by-segment-chart", "cohort-retention", "anomaly-flags", "segment-paths", "new-mrr-by-quarter"];

async function mountDashboard(results, verdict = VERDICT_NONE, audit = sample.audit) {
  api.getAudit.mockResolvedValue(audit);
  api.getResults.mockResolvedValue(results);
  api.readNarrative.mockResolvedValue({ narrative_status: "unavailable", reason: "x" });
  api.getDisclosure.mockResolvedValue(null);
  api.getClaimRegister.mockResolvedValue({ claims: [], register: [] });
  api.getVerdict.mockResolvedValue(verdict);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<Dashboard />); });
  await act(async () => { await Promise.resolve(); });
  return { host, unmount: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}

test("the Data integrity section shows the server's conclusion and both blocks above the A2 narrative (integrity-coverage.md)", async () => {
  api.getAudit.mockResolvedValue(sample.audit);
  api.getResults.mockResolvedValue(sample);
  api.readNarrative.mockResolvedValue(null);
  api.getDisclosure.mockResolvedValue(null);
  api.getClaimRegister.mockResolvedValue({ claims: [], register: [] });
  api.getVerdict.mockResolvedValue(VERDICT_NONE);
  api.getIntegrity.mockResolvedValue({ conclusion: "Insufficient assessment coverage (3 of 5)", code: "insufficient", completed: 3, applicable: 5,
    completed_text: "Completed 3 of 5 applicable checks", blocked: [], data_requests: [], results: [], coverage: [] });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<Dashboard />); });
  await act(async () => { await Promise.resolve(); });
  expect(api.getIntegrity).toHaveBeenCalledWith("a1");
  expect(host.querySelector('[data-testid="integrity-conclusion"]').textContent).toBe("Insufficient assessment coverage (3 of 5)");
  const order = [...host.querySelectorAll('[data-testid="integrity"], [data-testid^="step-narrative-data_integrity"]')].map((n) => n.getAttribute("data-testid"));
  expect(order[0]).toBe("integrity");
  await act(async () => { root.unmount(); });
  host.remove();
});

test("segment paths, new MRR, cohort retention, MRR by segment and anomaly flags show their citation like the other blocks", async () => {
  const { host, unmount } = await mountDashboard(sample);
  for (const id of CITED_BLOCKS) {
    expect(host.querySelector(`[data-testid="provenance-hover-${id}"]`)).not.toBeNull();
  }
  await unmount();
});

test("a block stored without its citation shows no source trigger (the contract test refuses such a payload)", async () => {
  const results = JSON.parse(JSON.stringify(sample));
  delete results.results.mrr_series.source;
  const { host, unmount } = await mountDashboard(results);
  expect(host.querySelector('[data-testid="provenance-hover-mrr-by-segment-chart"]')).toBeNull();
  expect(host.querySelector('[data-testid="provenance-hover-cohort-retention"]')).not.toBeNull();
  await unmount();
});


test("the FX line shows the audit's rates, the audit's winning over those saved with an older revenue file", async () => {
  const withFx = async (audit) => {
    const { host, unmount } = await mountDashboard(sample, VERDICT_NONE, audit);
    const text = host.textContent;
    await unmount();
    return text;
  };
  expect(await withFx({ ...sample.audit, datasets: {} })).toContain("FX: N/A (single-currency reporting)");
  expect(await withFx({ ...sample.audit, datasets: {}, fx: { EUR: 1, USD: 0.9 } })).toContain("FX: 1 USD = 0.9 EUR");
  const both = await withFx({ ...sample.audit, datasets: { revenue: { fx: { USD: 0.5, GBP: 1.2 } } }, fx: { EUR: 1, USD: 0.9 } });
  expect(both).toContain("FX: 1 USD = 0.9 EUR · 1 GBP = 1.2 EUR");
});


// --- the Verdict, Data gaps and AI usage and cost sections (docs/specs/verdict-and-memo.md sections 4, 6.4, 8) ---------------------------

const OK = {
  ...VERDICT_BASE,
  verdict: { top5: TOP, status: "ok", message: null,
    outcome: "Selected claims not supported", outcome_code: "not_supported", rule: "2 selected claims are Contradicted.",
    five: CANDIDATES.slice(0, 2).map((c) => ({ ...c })), reasons: ["#1 ARR, FY2023: Contradicted, €198,143 against €240,000 (€41,857 lower (miss))."] },
  top_gaps: VERDICT_BASE.data_gaps,
  key_gates: { note: null, ok: true, all_key: false, saved: 3, sentences: [{ claim_id: "c1", rank: 1, status: "proposed",
    sentence: "ARR must be at least €240,000 by 2023-12-31.", text: "ARR must be at least €240,000 by 2023-12-31. (proposed)" }] },
  ratings: { data_reliability: { rating: "Strong", line: "Strong (Reliable; 5 of 5 checks)", rule: "Strong: every completed check Green, 5 of 5 completed", benchmark: false },
    growth_engine: { rating: "Adequate", line: "Adequate (NRR 104%, gross churn 11%, CAC payback 14 months)", rule: "Adequate: NRR 104%", benchmark: true } },
  unresolved_questions: ["NRR (12-month): Blocks NRR; claims #4. Needs 12+ months of history."],
};

async function type(el, value) {
  await act(async () => {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement : el.tagName === "SELECT" ? HTMLSelectElement : HTMLInputElement;
    Object.getOwnPropertyDescriptor(proto.prototype, "value").set.call(el, value);
    el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  });
}

test("the five are in force at once: the outcome is shown with the selection sentence and one Change link, and nothing asks for a confirmation", async () => {
  const { host, unmount } = await mountDashboard(sample, OK);
  const section = host.querySelector('[data-testid="verdict"]');
  expect(section.querySelector("h2").textContent).toBe("Claim-review conclusion — assessment of the five selected claims");
  expect(section.querySelector('[data-testid="verdict-outcome"]').textContent).toContain("Selected claims not supported");
  expect(section.querySelector('[data-testid="verdict-top5-note"]')).toBeNull();
  expect(section.textContent.split("by value at stake").length - 1).toBe(1);
  expect(section.querySelector('[data-testid="top5-change"]').textContent).toBe("Change");
  expect(section.querySelector('[data-testid="verdict-top5"]')).toBeNull();
  expect(host.querySelector('[data-testid="verdict-confirm"]')).toBeNull();
  expect(host.textContent).not.toMatch(/Confirm top 5|Proposed by shortfall|confirm or replace|pending ARR bridge/);
  await unmount();
});

test("a pick replaces a row with another register row and Use this selection sends the claim ids", async () => {
  api.putIcInputs.mockResolvedValue({});
  const { host, unmount } = await mountDashboard(sample, OK);
  await act(async () => { host.querySelector('[data-testid="top5-change"]').click(); });
  const select = host.querySelectorAll('[data-testid="verdict-pick-select"]')[1];
  expect([...select.options].map((o) => o.textContent)).toEqual(["Replace with…", "Win rate"]);
  await type(select, "c3");
  expect([...host.querySelectorAll('[data-testid="verdict-pick-row"]')].map((r) => r.querySelector("span").textContent))
    .toEqual(["ARR, FY2023", "Win rate"]);
  await act(async () => { host.querySelector('[data-testid="verdict-use"]').click(); });
  expect(api.putIcInputs).toHaveBeenCalledWith("a1", { top5: ["c1", "c3"] });
  await unmount();
});

test("the outcome shows its rule and the five claims in the page's blocks, and the reasons, key gates, ratings, deal terms, top gaps and unresolved questions sit under Supporting detail", async () => {
  const { host, unmount } = await mountDashboard(sample, OK);
  const section = host.querySelector('[data-testid="verdict"]');
  expect(section.querySelector('[data-testid="verdict-outcome"]').textContent).toContain("Selected claims not supported");
  expect(section.querySelector('[data-testid="verdict-rule"]').textContent).toBe("2 selected claims are Contradicted.");
  expect(host.querySelectorAll('[data-testid="verdict-five-row"]').length).toBe(2);
  const detail = host.querySelector('[data-testid="supporting-detail"] [data-testid="verdict-detail"]');
  expect(detail.querySelector('[data-testid="verdict-reasons"]').textContent).toContain("#1 ARR (see glossary), FY2023: Contradicted, €198,143 against €240,000");
  expect(detail.querySelector('[data-testid="verdict-key-gates"]').textContent).toContain("ARR (see glossary) must be at least €240,000 by 2023-12-31. (proposed)");
  expect(detail.querySelector('[data-testid="verdict-deal-terms"]').textContent).toBe("Deal terms: not available – the execution capacity review has not been run.");
  expect(detail.querySelector('[data-testid="verdict-top-gaps"]').textContent).toContain("NRR (12-month)");
  const ratings = [...detail.querySelectorAll('[data-testid="verdict-rating"]')].map((n) => n.textContent);
  expect(ratings[0]).toBe("Data reliability: Strong (Reliable; 5 of 5 checks)");
  expect(ratings[1]).toBe("Growth engine: Adequate (NRR 104%, gross churn 11%, CAC payback 14 months)benchmark, not company data");
  expect(detail.querySelector('[data-testid="verdict-unresolved"]').textContent).toContain("NRR (see glossary) (12-month): Blocks NRR");
  expect(detail.querySelector('[data-testid="verdict-other-gates"]')).toBeNull();
  await unmount();
});

test("an open question is a count on the rule line, never a state: the outcome is shown", async () => {
  const open = { ...OK, verdict: { ...OK.verdict, rule: "1 selected claim is Contradicted. 1 question open.", open_questions: 1 } };
  const { host, unmount } = await mountDashboard(sample, open);
  expect(host.querySelector('[data-testid="verdict-outcome"]').textContent).toContain("Selected claims not supported");
  expect(host.querySelector('[data-testid="verdict-rule"]').textContent).toBe("1 selected claim is Contradicted. 1 question open.");
  expect(host.querySelector('[data-testid="verdict-message"]')).toBeNull();
  await unmount();
});

test("a row of the five with an open Definition check reads Definition check, not a label", async () => {
  const five = [{ ...OK.verdict.five[0], evidence_label: null, definition_check: "ask", reason: "definition check: the gap is beyond 50% of the claim" },
    OK.verdict.five[1]];
  const { host, unmount } = await mountDashboard(sample, { ...OK, verdict: { ...OK.verdict, five } });
  const rows = host.querySelectorAll('[data-testid="verdict-five-row"]');
  expect(rows[0].textContent).toContain("Definition check");
  expect(rows[0].textContent).toContain("the gap is beyond 50% of the claim");
  expect(rows[1].textContent).toContain(OK.verdict.five[1].evidence_label);
  await unmount();
});

test("an audit with no claims says so (W10) and offers no top 5", async () => {
  const none = { ...VERDICT_BASE, candidates: [], verdict: { ...VERDICT_BASE.verdict, status: "no_verdict", message: "No testable claims found. Upload a deck or plan with revenue targets.",
    top5: { ...TOP, proposed: [], in_force: [] } } };
  const { host, unmount } = await mountDashboard(sample, none);
  expect(host.querySelector('[data-testid="verdict-message"]').textContent).toBe("No testable claims found. Upload a deck or plan with revenue targets.");
  expect(host.querySelector('[data-testid="verdict-outcome"]')).toBeNull();
  expect(host.querySelector('[data-testid="verdict-top5"]')).toBeNull();
  await unmount();
});

test("the inputs: the review date and the thesis (300 characters each, drafted from computed text); no rating select exists; the report button sits outside them (W21)", async () => {
  api.putIcInputs.mockResolvedValue({});
  const { host, unmount } = await mountDashboard(sample, OK);
  const inputs = host.querySelector('[data-testid="verdict-inputs"]');
  expect(host.querySelector('[data-testid="report-download"] [data-testid="verdict-memo"]').textContent).toBe("Download report");
  expect(inputs.querySelector('[data-testid="verdict-memo"]')).toBeNull();
  expect(host.querySelector('[data-testid^="inputs-rating-"]')).toBeNull();
  expect(host.querySelector('[data-testid^="judgment-"]')).toBeNull();
  expect(inputs.querySelector('[data-testid="inputs-thesis-plan"]').maxLength).toBe(300);
  expect(inputs.querySelector('[data-testid="inputs-thesis-plan"]').value).toBe("The plan targets ARR of 1,000,000 EUR by 2026-12-31.");
  expect(inputs.querySelector('[data-testid="inputs-thesis-plan-draft"]').textContent).toContain("draft from computed text");
  await type(inputs.querySelector('[data-testid="inputs-review-date"]'), "2024-09-30");
  expect(api.putIcInputs).toHaveBeenCalledWith("a1", { first_quarterly_review: "2024-09-30" });
  const plan = inputs.querySelector('[data-testid="inputs-thesis-plan"]');
  await act(async () => { plan.focus(); plan.blur(); });
  expect(api.putIcInputs).not.toHaveBeenCalledWith("a1", expect.objectContaining({ thesis: expect.anything() }));       // the draft is stored only once changed
  await type(plan, "Reach the target with the current mix.");
  await act(async () => { plan.dispatchEvent(new FocusEvent("focusout", { bubbles: true })); plan.blur(); });
  await act(async () => { plan.focus(); plan.blur(); });
  expect(api.putIcInputs).toHaveBeenCalledWith("a1", { thesis: { plan: "Reach the target with the current mix." } });
  await unmount();
});

test("the analyst note sits beside Download report: optional, 1,000 characters, saved on blur, never required", async () => {
  api.putIcInputs.mockResolvedValue({});
  const { host, unmount } = await mountDashboard(sample, OK);
  const note = host.querySelector('[data-testid="report-download"] [data-testid="analyst-note-text"]');
  expect(note.maxLength).toBe(1000);
  expect(host.querySelector('[data-testid="analyst-note"]').textContent).toContain("Analyst note (optional)");
  await type(note, "  Call with the CFO booked for 3 Nov.  ");
  await act(async () => { note.dispatchEvent(new FocusEvent("focusout", { bubbles: true })); note.blur(); });
  await act(async () => { note.focus(); note.blur(); });
  expect(api.putIcInputs).toHaveBeenCalledWith("a1", { note: "Call with the CFO booked for 3 Nov." });
  await unmount();
});

test("a refused memo shows the server's reason and downloads nothing", async () => {
  const { toast } = require("sonner");
  api.getMemo.mockRejectedValue({ response: { status: 409, data: JSON.stringify({ detail: "Memo not exported: 1 numbers are not in the stored results: 37." }) } });
  const { host, unmount } = await mountDashboard(sample, OK);
  await act(async () => { host.querySelector('[data-testid="verdict-memo"]').click(); });
  expect(toast.error).toHaveBeenCalledWith("Memo not exported: 1 numbers are not in the stored results: 37.");
  await unmount();
});

test("Data gaps: the columns of W7, the gap with why it matters and what is requested, and a date the analyst sets", async () => {
  api.putIcInputs.mockResolvedValue({});
  const { host, unmount } = await mountDashboard(sample, OK);
  const section = host.querySelector('[data-testid="data-gaps"]');
  expect(section.querySelector("h2").textContent).toBe("Data gaps");
  expect([...section.querySelectorAll("th")].map((th) => th.textContent)).toEqual(["What the company cannot measure", "Why it matters", "Requested", "Target date"]);
  expect(section.textContent).toContain("First quarterly review");
  const row = section.querySelector('[data-testid="data-gap-row"]');
  expect(row.querySelector('[data-testid="data-gap-why"]').textContent).toBe("Blocks NRR (see glossary); claims #4. Needs 12+ months of history.");
  expect(row.textContent).toContain("Provide at least 13 months of revenue lines");
  await type(row.querySelector('[data-testid="data-gap-date"]'), "2024-08-31");
  expect(api.putIcInputs).toHaveBeenCalledWith("a1", { gap_target_dates: { "NRR (12-month)": "2024-08-31" } });
  await unmount();
});

test("Data gaps: a refused date shows the server's wording (W7)", async () => {
  const { toast } = require("sonner");
  api.putIcInputs.mockRejectedValue({ response: { status: 400, data: { detail: "Set the first quarterly review first." } } });
  const { host, unmount } = await mountDashboard(sample, OK);
  await type(host.querySelector('[data-testid="data-gap-date"]'), "2024-08-31");
  expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Set the first quarterly review first."));
  await unmount();
});

test("the Audit page shows no AI usage and cost table and asks for none (usage-and-allowance.md section 9)", async () => {
  const { host, unmount } = await mountDashboard(sample, OK);
  expect(host.querySelector('[data-testid="usage-panel"]')).toBeNull();
  expect(host.textContent).not.toMatch(/AI usage and cost|Cost \(USD\)|Input tokens|Output tokens/);
  expect(api.getLlmUsage).toBeUndefined();
  await unmount();
});

// Section 26.8: the yearly-basis metrics of a P&L read as a statement, each row labelled with its basis (S30g).
const CITE = { file: "plan.csv", sheet: "CSV", rows: "rows 3–13 (7 rows)", row_numbers: [3, 13], rule: "x · yearly basis, not monthly" };
const YEARLY = {
  basis: "yearly basis, not monthly", source: CITE,
  years: [
    { period: "FY2022", revenue: 1000000, new_revenue: 200000, sm_pct_revenue: null, gross_margin_pct: 0.71, gross_margin_change: 0.01,
      cac_payback_months: null, cac_payback_reason: "no S&M line", basis: "yearly basis, not monthly", source: CITE },
    { period: "FY2023", revenue: 1300000, new_revenue: 300000, sm_pct_revenue: 0.4231, gross_margin_pct: 0.7231, gross_margin_change: 0.0131,
      cac_payback_months: 30.43, cac_payback_reason: null, basis: "yearly basis, not monthly", source: CITE },
  ],
  track_record: [{ period: "2023 Actual", line: "Revenue", tag: "budget", forecast: 1000, actual: 900, gap: -100, gap_pct: -0.1,
    basis: "yearly basis, not monthly", source: CITE }],
  reported_vs_file: [],
  missing: [{ metric: "CAC payback (monthly)", text: "Missing: monthly P&L / revenue by customer, last 24 months" }],
};

test("the yearly-basis section shows each year, the track record and the missing lines, every row labelled (S30g)", async () => {
  const results = { ...sample, results: { ...sample.results, yearly_basis: YEARLY } };
  const { host, unmount } = await mountDashboard(results, OK);
  const section = host.querySelector('[data-testid="yearly-basis"]');
  expect(section.textContent).toContain("Yearly basis (P&L summary)");
  const labels = [...section.querySelectorAll('[data-testid="yearly-basis-label"]')].map((x) => x.textContent);
  expect(labels).toEqual(Array(3).fill("yearly basis, not monthly"));
  const y23 = section.querySelector('[data-testid="yearly-year-FY2023"]').textContent;
  expect(y23).toContain("42 %");
  expect(y23).toContain("+1.3 pts");
  expect(y23).toContain("30 months");
  expect(section.querySelector('[data-testid="yearly-year-FY2022"]').textContent).toContain("n/c");
  expect(section.querySelector('[data-testid="yearly-track"]').textContent).toContain("(budget)");
  expect(section.querySelector('[data-testid="yearly-reported"]')).toBeNull();
  expect(section.querySelector('[data-testid="yearly-missing"]').textContent)
    .toBe("CAC payback (monthly) – Missing: monthly P&L / revenue by customer, last 24 months");
  await unmount();
});

test("without a yearly statement there is no yearly-basis section", async () => {
  const { host, unmount } = await mountDashboard(sample, OK);
  expect(host.querySelector('[data-testid="yearly-basis"]')).toBeNull();
  await unmount();
});
