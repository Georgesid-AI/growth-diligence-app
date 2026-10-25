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

// What GET /audits/{id}/verdict and GET answer (docs/specs/verdict-and-memo.md). The server tests, ranks and words.
const TOP = {
  proposed: ["c1", "c2"], confirmed: false, void: false, claim_ids: [], set_at: null, in_force: ["c1", "c2"],
};
const CANDIDATES = [
  { claim_id: "c1", rank: 1, claim: "ARR, FY2023", evidence_label: "Contradicted", reason: "outside ±5%: a miss" },
  { claim_id: "c2", rank: 2, claim: "Revenue, Q4 2023", evidence_label: "Contradicted", reason: "outside ±5%: a miss" },
  { claim_id: "c3", rank: 3, claim: "Win rate", evidence_label: "Verified", reason: "within ±1 pp of the claim" },
];
const VERDICT_BASE = {
  verdict: { top5: TOP, status: "unconfirmed", message: "No conclusion until the top 5 is confirmed.", outcome: null, rule: null, blocked: [], five: [], reasons: [] },
  data_gaps: [{ item: "NRR (12-month)", why: "Blocks NRR; claims #4. Needs 12+ months of history.", requested: "Provide at least 13 months of revenue lines", target_date: null, claims: [], ranks: [4] }],
  top_gaps: [], key_gates: { note: "No key gates marked.", ok: true, all_key: true, saved: 0, sentences: [] }, gates_still_needed: 0,
  deal_terms: "Deal terms: not available – the execution capacity review has not been run.", top5_statement: "Top 5 set by the analyst pending ARR bridge.",
  candidates: CANDIDATES, ic_inputs: { first_quarterly_review: null, ratings: null, thesis: null }, ratings: ["Strong", "Adequate", "Weak"],
  ratings_for: { data_reliability: "Data reliability", growth_engine: "Growth engine" }, thesis_labels: { plan: "Plan", evidence: "Evidence", condition: "Condition" },
  thesis_max: 300,
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
  verdict: { top5: { ...TOP, confirmed: true, claim_ids: ["c1", "c2"], set_at: "2026-10-08T10:00:00+00:00" }, status: "ok", message: null,
    outcome: "Selected claims not supported", outcome_code: "not_supported", rule: "2 selected claims are Contradicted.", blocked: [],
    five: CANDIDATES.slice(0, 2).map((c) => ({ ...c })), reasons: ["#1 ARR, FY2023: Contradicted, €198,143 against €240,000 (€41,857 lower (miss))."] },
  top_gaps: VERDICT_BASE.data_gaps, gates_still_needed: 3,
  key_gates: { note: null, ok: true, all_key: false, saved: 3, sentences: [{ claim_id: "c1", rank: 1, sentence: "Before the plan, ARR must be at least €100 by 2024-06-30." }] },
};

async function type(el, value) {
  await act(async () => {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement : el.tagName === "SELECT" ? HTMLSelectElement : HTMLInputElement;
    Object.getOwnPropertyDescriptor(proto.prototype, "value").set.call(el, value);
    el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  });
}

test("before the top 5 is confirmed the Verdict section proposes it, gives no outcome and says so (W23)", async () => {
  const { host, unmount } = await mountDashboard(sample);
  const section = host.querySelector('[data-testid="verdict"]');
  expect(section.querySelector("h2").textContent).toBe("Claim-review conclusion — assessment of the five selected claims");
  expect(section.querySelector('[data-testid="verdict-top5"] h3').textContent).toBe("Top 5");
  expect(section.querySelector('[data-testid="verdict-top5-note"]').textContent).toBe("Proposed by shortfall – confirm or replace.");
  expect(section.querySelector('[data-testid="verdict-message"]').textContent).toBe("No conclusion until the top 5 is confirmed.");
  expect(section.querySelector('[data-testid="verdict-outcome"]')).toBeNull();
  expect([...section.querySelectorAll('[data-testid="verdict-pick-row"]')].map((r) => r.querySelector("span").textContent))
    .toEqual(["#1 ARR, FY2023", "#2 Revenue, Q4 2023"]);
  expect(section.querySelector('[data-testid="verdict-confirm"]').textContent).toBe("Confirm top 5");
  await unmount();
});

test("a pick replaces a row with another register row and Confirm sends the five claim ids", async () => {
  api.putIcInputs.mockResolvedValue({});
  const { host, unmount } = await mountDashboard(sample);
  const select = host.querySelectorAll('[data-testid="verdict-pick-select"]')[1];
  expect([...select.options].map((o) => o.textContent)).toEqual(["Replace with…", "#3 Win rate"]);
  await type(select, "c3");
  expect([...host.querySelectorAll('[data-testid="verdict-pick-row"]')].map((r) => r.querySelector("span").textContent))
    .toEqual(["#1 ARR, FY2023", "#3 Win rate"]);
  await act(async () => { host.querySelector('[data-testid="verdict-confirm"]').click(); });
  expect(api.putIcInputs).toHaveBeenCalledWith("a1", { top5: ["c1", "c3"] });
  await unmount();
});

test("a confirmed top 5 shows the outcome with its rule and the five claims in the page's blocks, W24 behind Change, and the reasons, key gates, deal terms and top gaps under Supporting detail (W8, W11-W14)", async () => {
  const { host, unmount } = await mountDashboard(sample, OK);
  const section = host.querySelector('[data-testid="verdict"]');
  expect(section.querySelector('[data-testid="verdict-top5"]')).toBeNull();       // a confirmed top 5 sits behind the one Change link
  await act(async () => { section.querySelector('[data-testid="top5-change"]').click(); });
  expect(section.querySelector('[data-testid="verdict-top5-note"]').textContent).toBe("Top 5 set by the analyst pending ARR (see glossary) bridge.");
  expect(section.querySelector('[data-testid="verdict-outcome"]').textContent).toContain("Selected claims not supported");
  expect(section.querySelector('[data-testid="verdict-rule"]').textContent).toBe("2 selected claims are Contradicted.");
  expect(host.querySelectorAll('[data-testid="verdict-five-row"]').length).toBe(2);
  const detail = host.querySelector('[data-testid="supporting-detail"] [data-testid="verdict-detail"]');
  expect(detail.querySelector('[data-testid="verdict-reasons"]').textContent).toContain("#1 ARR (see glossary), FY2023: Contradicted, €198,143 against €240,000");
  expect(detail.querySelector('[data-testid="verdict-key-gates"]').textContent).toContain("Before the plan, ARR (see glossary) must be at least €100 by 2024-06-30.");
  expect(detail.querySelector('[data-testid="verdict-deal-terms"]').textContent).toBe("Deal terms: not available – the execution capacity review has not been run.");
  expect(detail.querySelector('[data-testid="verdict-top-gaps"]').textContent).toContain("NRR (12-month)");
  expect(detail.querySelector('[data-testid="verdict-other-gates"]').textContent).toBe("3 other claims still need a gate.");
  await unmount();
});

test("a blocked verdict shows no outcome, only the claims that need a gate (W9)", async () => {
  const blocked = { ...OK, verdict: { ...OK.verdict, status: "blocked", outcome: null, rule: null, reasons: [], blocked: ["c1"],
    message: "Conclusion blocked: set a gate on #1 (top-5 claims that are not Verified)." } };
  const { host, unmount } = await mountDashboard(sample, blocked);
  expect(host.querySelector('[data-testid="verdict-message"]').textContent).toBe("Conclusion blocked: set a gate on #1 (top-5 claims that are not Verified).");
  expect(host.querySelector('[data-testid="verdict-outcome"]')).toBeNull();
  expect(host.querySelector('[data-testid="verdict-reasons"]')).toBeNull();
  await unmount();
});

test("an open Definition check blocks the verdict (W9b) and its row of the five reads Definition check, not a label", async () => {
  const five = [{ ...OK.verdict.five[0], evidence_label: null, definition_check: "ask", reason: "definition check: the gap is beyond 50% of the claim" },
    OK.verdict.five[1]];
  const blocked = { ...OK, verdict: { ...OK.verdict, status: "blocked", outcome: null, rule: null, reasons: [], blocked: ["c1"], five,
    message: "Conclusion blocked: answer the definition check on #1." } };
  const { host, unmount } = await mountDashboard(sample, blocked);
  expect(host.querySelector('[data-testid="verdict-message"]').textContent).toBe("Conclusion blocked: answer the definition check on #1.");
  const rows = host.querySelectorAll('[data-testid="verdict-five-row"]');
  expect(rows[0].textContent).toContain("Definition check");
  expect(rows[0].textContent).toContain("the gap is beyond 50% of the claim");
  expect(rows[1].textContent).toContain(OK.verdict.five[1].evidence_label);
  await unmount();
});

test("an audit with no claims says so (W10) and offers no top 5", async () => {
  const none = { ...VERDICT_BASE, candidates: [], verdict: { ...VERDICT_BASE.verdict, status: "no_verdict", message: "No conclusion: the register has no claims.",
    top5: { ...TOP, proposed: [], in_force: [] } } };
  const { host, unmount } = await mountDashboard(sample, none);
  expect(host.querySelector('[data-testid="verdict-message"]').textContent).toBe("No conclusion: the register has no claims.");
  expect(host.querySelector('[data-testid="verdict-top5"]')).toBeNull();
  await unmount();
});

test("a void top 5 shows W23's re-confirm line", async () => {
  const void_ = { ...VERDICT_BASE, verdict: { ...VERDICT_BASE.verdict, status: "void", top5: { ...TOP, void: true },
    message: "A claim of the confirmed top 5 left the register – confirm the top 5 again." } };
  const { host, unmount } = await mountDashboard(sample, void_);
  expect(host.querySelector('[data-testid="verdict-message"]').textContent).toContain("left the register – confirm the top 5 again.");
  await unmount();
});

test("the inputs: the review date, the two ratings, the thesis (300 characters each); the report button sits outside them (W21)", async () => {
  api.putIcInputs.mockResolvedValue({});
  const { host, unmount } = await mountDashboard(sample, OK);
  const inputs = host.querySelector('[data-testid="verdict-inputs"]');
  expect(host.querySelector('[data-testid="report-download"] [data-testid="verdict-memo"]').textContent).toBe("Download report");
  expect(inputs.querySelector('[data-testid="verdict-memo"]')).toBeNull();
  expect([...inputs.querySelector('[data-testid="inputs-rating-data_reliability"]').options].map((o) => o.textContent)).toEqual(["", "Strong", "Adequate", "Weak"]);
  expect(inputs.textContent).toContain("Data reliability");
  expect(inputs.textContent).toContain("Growth engine");
  expect(inputs.querySelector('[data-testid="inputs-thesis-plan"]').maxLength).toBe(300);
  await type(inputs.querySelector('[data-testid="inputs-rating-growth_engine"]'), "Weak");
  expect(api.putIcInputs).toHaveBeenCalledWith("a1", { ratings: { growth_engine: "Weak" } });
  await type(inputs.querySelector('[data-testid="inputs-review-date"]'), "2024-09-30");
  expect(api.putIcInputs).toHaveBeenCalledWith("a1", { first_quarterly_review: "2024-09-30" });
  const plan = inputs.querySelector('[data-testid="inputs-thesis-plan"]');
  await type(plan, "Reach the target with the current mix.");
  await act(async () => { plan.dispatchEvent(new FocusEvent("focusout", { bubbles: true })); plan.blur(); });
  await act(async () => { plan.focus(); plan.blur(); });
  expect(api.putIcInputs).toHaveBeenCalledWith("a1", { thesis: { plan: "Reach the target with the current mix." } });
  await unmount();
});

test("a refused memo shows the server's reason and downloads nothing", async () => {
  const { toast } = require("sonner");
  api.getMemo.mockRejectedValue({ response: { status: 409, data: JSON.stringify({ detail: "Memo not exported: mark 3 to 5 key gates." }) } });
  const { host, unmount } = await mountDashboard(sample, OK);
  await act(async () => { host.querySelector('[data-testid="verdict-memo"]').click(); });
  expect(toast.error).toHaveBeenCalledWith("Memo not exported: mark 3 to 5 key gates.");
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

test("W14 is not shown when no other claim needs a gate", async () => {
  const { host, unmount } = await mountDashboard(sample, { ...OK, gates_still_needed: 0 });
  expect(host.querySelector('[data-testid="verdict-other-gates"]')).toBeNull();
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
  expect(y23).toContain("42%");
  expect(y23).toContain("+1.3 pts");
  expect(y23).toContain("30.4 months");
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
