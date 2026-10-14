import React, { act } from "react";
import { createRoot } from "react-dom/client";

import Review from "./Review";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), getReview: jest.fn(), getDatasets: jest.fn(), getDecks: jest.fn(), getClaimRegister: jest.fn(), getVerdict: jest.fn(),
  getNarrativeEstimate: jest.fn(), decideColumns: jest.fn(), updateCandidate: jest.fn(), approveAll: jest.fn(), answerTurnover: jest.fn(),
  putIcInputs: jest.fn(), updateClaimInputs: jest.fn(), generateNarrative: jest.fn(), getMemo: jest.fn(), reportUsage: jest.fn(),
  getBlockers: jest.fn(), saveAllGatesCall: jest.fn(), uploadChatFile: jest.fn(), uploadDeck: jest.fn(), runStage: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({
  useParams: () => ({ id: "a1" }), useNavigate: () => jest.fn(), useLocation: () => ({ pathname: "/audit/a1/review" }),
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a>,
}), { virtual: true });

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
const qa = (id) => [...document.body.querySelectorAll(`[data-testid="${id}"]`)];
const AUDIT = { id: "a1", company_name: "TestCo", reporting_currency: "EUR", target_arr: 1000000 };

const col = (column, over = {}) => ({ column, field: "sm_expense", state: "auto", confidence: 100, pending: false, source: "rules", decision: null, money_ask: false, ...over });
const VIEW_OPEN = {
  dtype: "pnl", file: "pnl.csv", status: "ok", pending: 1, missing_required: [], fields: { required: ["sm_expense"], optional: [] },
  columns: [col("S&M Expense", { state: "ai", pending: true, source: "ai", confidence: null }), col("Month", { field: "month" })],
};
const VIEW_DONE = { ...VIEW_OPEN, pending: 0, columns: VIEW_OPEN.columns.map((c) => ({ ...c, state: c.pending ? "confirmed" : c.state, pending: false })) };
const cand = (id, over = {}) => ({ id, status: "pending", group: 1, claim_type: "revenue", value: 100, unit: null, currency: "EUR", target_date: "2024",
  sources: [{ file: "board.pptx", slide: 3 }], turnover: null, ...over });

const VERDICT = {
  verdict: { top5: { proposed: ["c1"], confirmed: true, claim_ids: ["c1"], void: false, in_force: ["c1"] }, status: "blocked", message: "Verdict blocked", outcome: null,
    rule: null, blocked: [], five: [{ claim_id: "c1", rank: 1, claim: "Revenue 100", evidence_label: "Contradicted", reason: "outside ±5%" }], reasons: [] },
  data_gaps: [], top_gaps: [], key_gates: { note: null, ok: true, sentences: [] }, gates_still_needed: 0, deal_terms: "x",
  candidates: [{ claim_id: "c1", rank: 1, claim: "Revenue 100", evidence_label: "Contradicted", reason: "outside" }],
  ic_inputs: { ratings: {}, thesis: {}, first_quarterly_review: null }, ratings: ["Strong", "Adequate", "Weak"],
  ratings_for: { data_reliability: "Data reliability", growth_engine: "Growth engine" }, thesis_labels: { plan: "Plan", evidence: "Evidence", condition: "Condition" },
};
const REGISTER = { register: [{ claim_id: "c1", rank: 1, claim: "Revenue 100", evidence_label: "Contradicted", gate_needed: true, gate_saved: false, key_gate: false,
  reason: "x", claimed_value: 100, unit: null, currency: "EUR", observed_value: 50, metric: "Revenue", gap: -50 }] };
const ESTIMATE = { model: "claude-sonnet-5-5", total_usd: 0.1234, basis: "upper bound", steps: [
  { step: "growth_engine", label: "Growth engine", cached: false, estimate_usd: 0.05, available: true },
  { step: "data_inventory", label: "Data inventory", cached: false, estimate_usd: 0.04, available: true },
  { step: "data_integrity", label: "Data integrity", cached: false, estimate_usd: 0.0334, available: true }] };
const SUMMARY = { mappings: { auto: 5, open: 0, missing_required: [] }, claims: { auto_accepted: 12, auto_accepted_ids: ["x1"], open: 1, turnover_open: 0 }, computed: true, blockers: [] };

let state, root, host;
beforeEach(() => {
  jest.resetAllMocks();
  state = { views: [VIEW_DONE], candidates: [cand("p1")], verdict: JSON.parse(JSON.stringify(VERDICT)), summary: SUMMARY, estimate: ESTIMATE };
  api.getAudit.mockResolvedValue(AUDIT);
  api.getReview.mockImplementation(async () => state.summary);
  api.getDatasets.mockImplementation(async () => state.views);
  api.getDecks.mockImplementation(async () => ({ decks: [], candidates: state.candidates }));
  api.getClaimRegister.mockResolvedValue(REGISTER);
  api.getVerdict.mockImplementation(async () => state.verdict);
  api.getNarrativeEstimate.mockImplementation(async () => state.estimate);
  api.getBlockers.mockResolvedValue([]);
  api.reportUsage.mockResolvedValue(null);
  api.putIcInputs.mockImplementation(async (id, body) => {
    if (body.ratings) state.verdict.ic_inputs.ratings = { ...state.verdict.ic_inputs.ratings, ...body.ratings };
    return {};
  });
  api.runStage.mockResolvedValue({ status: "done" });
  URL.createObjectURL = jest.fn(() => "blob:x"); URL.revokeObjectURL = jest.fn();
});
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });

async function mount() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Review />); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

test("the sections come in this order: open mappings, open claims, Revenue / Volume answers, top 5, deal thesis, gates, ratings", async () => {
  await mount();
  const ids = ["review-mappings", "review-claims", "review-turnover", "review-top5", "review-thesis", "review-gates", "review-ratings", "review-finish"];
  const found = [...document.body.querySelectorAll("section[data-testid^='review-']")].map((s) => s.getAttribute("data-testid"));
  expect(found).toEqual(ids);
  expect(["1", "2", "3", "4", "5", "6", "7"].map((n, i) => q(ids[i]).textContent.startsWith(n))).toEqual(Array(7).fill(true));
});

test("what the app settled itself is a count with a Show link: columns mapped and claims within tolerance", async () => {
  await mount();
  expect(q("review-mappings-auto-count").textContent).toBe("5 columns mapped");
  expect(q("review-claims-auto-count").textContent).toBe("12 claims within tolerance");
  expect(q("review-mappings-auto").textContent).toContain("Show");
  expect(q("review-mappings-none").textContent).toContain("No column waits");
});

test("a low-confidence column is a row to decide; deciding the last one carries the run on with no further press", async () => {
  state.views = [VIEW_OPEN];
  state.summary = { ...SUMMARY, computed: false, mappings: { auto: 1, open: 1, missing_required: [] } };
  api.decideColumns.mockImplementation(async () => { state.views = [VIEW_DONE]; return VIEW_DONE; });
  await mount();
  expect(q("review-mapping-pnl").textContent).toContain("1 columns wait for your decision");
  expect(q("review-not-computed")).not.toBeNull();
  await act(async () => { q("confirm-S&M Expense").click(); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  expect(api.decideColumns).toHaveBeenCalledWith("a1", "pnl", [{ column: "S&M Expense", action: "confirm", field: "sm_expense" }]);
  expect(api.runStage.mock.calls.map((c) => c[1])).toEqual(["mapping", "engine", "claims"]);
  expect(api.generateNarrative).not.toHaveBeenCalled();
});

test("a claim outside tolerance is a row: Approve and Reject save it, Approve all approves the category", async () => {
  state.candidates = [cand("p1"), cand("p2")];
  api.updateCandidate.mockResolvedValue({});
  api.approveAll.mockResolvedValue({ approved: 2, skipped: 0 });
  await mount();
  expect(qa("review-claim-row")).toHaveLength(2);
  await act(async () => { qa("review-approve")[0].click(); });
  expect(api.updateCandidate).toHaveBeenCalledWith("a1", "p1", { status: "approved" });
  await act(async () => { qa("review-reject")[1].click(); });
  expect(api.updateCandidate).toHaveBeenCalledWith("a1", "p2", { status: "rejected" });
  await act(async () => { q("review-approve-all-1").click(); });
  expect(api.approveAll).toHaveBeenCalledWith("a1", 1);
});

test("a claim accepted within tolerance is listed under Show and can still be rejected", async () => {
  state.candidates = [cand("x1", { status: "approved", auto_accepted: true })];
  api.updateCandidate.mockResolvedValue({});
  await mount();
  expect(qa("review-auto-claim")).toHaveLength(1);
  await act(async () => { qa("review-auto-claim")[0].querySelector("button").click(); });
  expect(api.updateCandidate).toHaveBeenCalledWith("a1", "x1", { status: "rejected" });
});

test("a turnover claim waits in Revenue / Volume answers, not in the open claims", async () => {
  const views = [{ claim_id: "t1", turnover_state: "ask", turnover_set_by: null, turnover_note: "ask", turnover_reason: null, turnover_suggested: null, file_note: null }];
  state.candidates = [cand("t1", { turnover: views }), cand("p1")];
  await mount();
  expect(qa("review-turnover-claim")).toHaveLength(1);
  expect(qa("review-claim-row")).toHaveLength(1);
  expect(q("review-turnover").querySelector('[data-testid="register-turnover-revenue"]')).not.toBeNull();
});

test("gates are asked for the top-5 claims that are not Verified, and a gate saves through the register's own call", async () => {
  api.updateClaimInputs.mockResolvedValue({});
  await mount();
  expect(qa("review-gate-row")).toHaveLength(1);
  const type = async (id, v) => { const el = q(id); await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, v); el.dispatchEvent(new Event("input", { bubbles: true })); }); };
  await type("register-gate-threshold", "100");
  await type("register-gate-budget", "the Series B hiring plan");
  await type("register-gate-date", "2026-06-30");
  await act(async () => { q("register-gate-save").click(); });
  await act(async () => { await Promise.resolve(); });
  expect(api.updateClaimInputs).toHaveBeenCalledWith("a1", "c1", expect.objectContaining({ gate_threshold: 100, gate_budget_decision: "the Series B hiring plan" }));
});

test("the review screen prefills the gate, marks it, and one Save all gates saves it once the budget decision is typed", async () => {
  api.getClaimRegister.mockResolvedValue({ ...REGISTER, gate_prefill: { c1: { gate_threshold: 250, gate_date: "2025-03-31", key_gate: true } }, budget_decisions: [] });
  api.saveAllGatesCall.mockResolvedValue({ register: [] });
  await mount();
  expect(q("register-gate-threshold").value).toBe("250");
  expect(q("register-gate-prefilled-threshold").textContent).toBe("prefilled – confirm");
  const type = async (id, v) => { const el = q(id); await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, v); el.dispatchEvent(new Event("input", { bubbles: true })); }); };
  await act(async () => { q("review-gates-save-all").click(); });
  expect(api.saveAllGatesCall).not.toHaveBeenCalled();                     // the budget decision is still blank
  await type("register-gate-budget", "the Series B hiring plan");
  await act(async () => { q("review-gates-save-all").click(); });
  expect(api.saveAllGatesCall).toHaveBeenCalledWith("a1", [{ claim_id: "c1", gate_threshold: 250, gate_budget_decision: "the Series B hiring plan", gate_date: "2025-03-31", key_gate: true }]);
});

test("a top-5 claim that is Verified needs no gate", async () => {
  state.verdict.verdict.five[0].evidence_label = "Verified";
  api.getClaimRegister.mockResolvedValue({ register: [{ ...REGISTER.register[0], evidence_label: "Verified" }] });
  await mount();
  expect(q("review-gates-none").textContent).toContain("no gate is needed");
});

test("the ratings are saved as the analyst enters them and the memo button waits for both", async () => {
  await mount();
  expect(q("generate-memo").disabled).toBe(true);
  expect(q("memo-waiting").textContent).toContain("Enter both ratings");
  const pick = async (id, v) => { const el = q(id); await act(async () => { Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(el, v); el.dispatchEvent(new Event("change", { bubbles: true })); }); await act(async () => { await Promise.resolve(); await Promise.resolve(); }); };
  await pick("inputs-rating-data_reliability", "Adequate");
  expect(api.putIcInputs).toHaveBeenCalledWith("a1", { ratings: { data_reliability: "Adequate" } });
  expect(q("generate-memo").disabled).toBe(true);
  await pick("inputs-rating-growth_engine", "Weak");
  expect(api.putIcInputs).toHaveBeenCalledWith("a1", { ratings: { growth_engine: "Weak" } });
  expect(q("generate-memo").disabled).toBe(false);
  expect(q("memo-waiting")).toBeNull();
});

test("Generate IC memo downloads the memo the server builds", async () => {
  state.verdict.ic_inputs.ratings = { data_reliability: "Adequate", growth_engine: "Weak" };
  api.getMemo.mockResolvedValue({ data: "# memo", headers: { "content-disposition": 'attachment; filename="TestCo_ic_memo.md"' } });
  await mount();
  await act(async () => { q("generate-memo").click(); });
  await act(async () => { await Promise.resolve(); });
  expect(api.getMemo).toHaveBeenCalledWith("a1");
});

test("no narrative is written by opening the screen; the one button writes every enabled step in order, with the estimate beside it", async () => {
  await mount();
  expect(api.generateNarrative).not.toHaveBeenCalled();
  expect(q("write-all-estimate").textContent).toBe("Estimated cost: up to $0.12 for 3 narratives");
  expect(q("write-all-narratives").textContent).toBe("Write all narratives");
  expect(q("write-all-help").textContent).toContain("Costs one AI request");
  api.generateNarrative.mockResolvedValue({ narrative_status: "ok" });
  await act(async () => { q("write-all-narratives").click(); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  expect(api.generateNarrative.mock.calls).toEqual([["a1", "growth_engine"], ["a1", "data_inventory"], ["a1", "data_integrity"]]);
});

test("a narrative that cannot be written says so, the others are still written and the page stands", async () => {
  api.generateNarrative.mockImplementation(async (id, step) => { if (step === "data_inventory") throw new Error("down"); return { narrative_status: "ok" }; });
  await mount();
  await act(async () => { q("write-all-narratives").click(); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  expect(api.generateNarrative).toHaveBeenCalledTimes(3);
  expect(q("write-all-unavailable").textContent).toContain("Data inventory");
  expect(q("write-all-unavailable").textContent).toContain("computed metrics are unaffected");
});

test("when every narrative is stored the estimate says there is no cost", async () => {
  state.estimate = { ...ESTIMATE, total_usd: 0, steps: ESTIMATE.steps.map((s) => ({ ...s, cached: true, estimate_usd: 0 })) };
  await mount();
  expect(q("write-all-estimate").textContent).toBe("All narratives are written: no cost.");
});

test("a reconciliation gap is reported in the memo and does not block it", async () => {
  state.summary = { ...SUMMARY, blockers: [{ kind: "revenue_reconciliation", text: "Revenue file and P&L differ by 10%" }] };
  await mount();
  expect(q("memo-blockers").textContent).toBe("A reconciliation gap over 2% is reported in the memo; it does not block it.");
  expect(q("generate-memo")).not.toBeNull();
});

// A failed read must not leave the spinner: the error, a Retry and a link back to the audit list (bug of 2026-10-14).
const httpError = (status, detail) => Object.assign(new Error("failed"), { response: { status, statusText: "", data: { detail } } });

test.each([["getReview"], ["getAudit"]])("when %s fails the spinner stops: the error, Retry and a link to the audit list", async (which) => {
  api[which].mockRejectedValue(httpError(500, "boom"));
  await mount();
  expect(q("review-load-error").textContent).toContain("HTTP 500");
  expect(document.body.querySelector(".animate-spin")).toBeNull();
  expect(q("review-load-retry").textContent).toBe("Retry");
  expect(q("review-load-list").getAttribute("href")).toBe("/");
});

test("Retry reads again and shows the review when the second read works", async () => {
  api.getReview.mockRejectedValueOnce(httpError(500, "boom"));
  await mount();
  expect(q("review-load-error")).not.toBeNull();
  await act(async () => { q("review-load-retry").click(); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  expect(q("review-load-error")).toBeNull();
  expect(q("review-mappings")).not.toBeNull();
});

test("a read that times out ends in the error too, never in a spinner", async () => {
  api.getReview.mockRejectedValue(Object.assign(new Error("timeout of 30000ms exceeded"), { code: "ECONNABORTED" }));
  await mount();
  expect(q("review-load-error").textContent).toContain("No response from the server after 30 seconds");
});
