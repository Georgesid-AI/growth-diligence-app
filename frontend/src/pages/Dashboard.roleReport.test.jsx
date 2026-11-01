// PR 4b step 1 (docs/design/read-check-review.md section 16): the report shows the engine on the file map. Synthetic results only.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import Dashboard from "./Dashboard";
import * as api from "@/lib/api";
import sample from "./fixtures/sample_results.json";

const mockNavigate = jest.fn();
jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), getResults: jest.fn(), readNarrative: jest.fn(), generateNarrative: jest.fn(), getDisclosure: jest.fn(),
  getClaimRegister: jest.fn(), getBlockers: jest.fn(), updateClaimInputs: jest.fn(), claimsCsvUrl: () => "x", exportUrl: () => "x", reportUsage: jest.fn(),
  getVerdict: jest.fn(), putIcInputs: jest.fn(), getMemo: jest.fn(), getIntegrity: jest.fn(), getDatasets: jest.fn(), getDecks: jest.fn(),
  NARRATIVE_TIMEOUT_MS: 150000, NARRATIVE_EXPECTED_SECONDS: 33,
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({ useParams: () => ({ id: "a1" }), useNavigate: () => mockNavigate }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));
jest.mock("recharts", () => new Proxy({}, { get: () => ({ children }) => <div>{children}</div> }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = (cells) => ({ file: "report.xlsx", sheet: "Report", row: 4, cells, rule: "synthetic rule" });
const metric = (m, name, extra = {}) => ({ metric: m, name, status: "computed", reason: null, needs: [], period: "2026-06", basis: "monthly", unit: "count",
  value: 1, label: null, detail: null, source: SRC(["S8"]), ...extra });
const missing = (m, name, reason, needs) => ({ metric: m, name, status: "needs_row", reason, needs, period: null, basis: null, unit: null, value: null,
  label: null, detail: null, source: null });
const RM = {
  as_of_month: "2026-06",
  metrics: [
    metric("customers", "Customers", { value: 67, source: SRC(["S8"]) }),
    metric("monthly_churn", "Monthly churn", { value: 0.03, unit: "rate", source: SRC(["S7"]) }),
    missing("sm_share", "S&M share of revenue", "S&M split only in plan years; actual years carry OPEX total only", ["revenue", "sales_marketing"]),
    missing("cash", "Cash", "needs a cash row", ["cash"]),
  ],
  plan_to_date: { period: "2026-06", basis: "month", actual: 185, plan: 200, variance: -15, variance_pct: -0.075, note: "actual of the as-of month against the plan of the same month",
    source: { file: "report.xlsx", sheet: "Report", row: 4, cells: ["S4", "S9"], rule: "plan rule" } },
  reconciliation: [
    { metric: "revenue", period: "2025", basis: "yearly", status: "differs", reason: null, gap: 300, gap_pct: 0.2,
      sources: [{ kind: "file", file: "report.xlsx", where: "Report!B4:M4", value: 1200 }, { kind: "file", file: "pnl.xlsx", where: "P&L!D4", value: 1300 },
        { kind: "deck", file: "board.pdf", where: "page 7", value: 1500 }],
      also_read: [{ kind: "deck", file: "board.pdf", where: "page 7", value: 400 }] },
  ],
  growth_by_year: [
    { period: "2024", value: 1500, prior: 1000, growth: 0.5, source: SRC(["D4", "E4"]) },
    { period: "2025", value: 2400, prior: 1500, growth: 0.6, source: SRC(["E4", "F4"]) },
  ],
};
const YEARLY = { basis: "yearly", years: [
  { period: "2025", revenue: 2400, new_revenue: 900, sm_pct_revenue: null, sm_expense: null, sm_scope: null, gross_margin_pct: 0.75, gross_margin_change: null,
    cac_payback_months: null, cac_payback_reason: "needs a sales_marketing row", cac_payback_net_new_arr_months: null, cac_payback_net_new_arr_reason: "x",
    cac_payback_label: "yearly, revenue-based", basis: "yearly", source: { file: "pnl.xlsx", sheet: "P&L", rows: "row 4", rule: "r" } }],
  track_record: [], reported_vs_file: [], missing: [], source: { file: "pnl.xlsx", sheet: "P&L", rows: "row 4", rule: "r" } };
const VERDICT = { verdict: { status: "ok", heading: "h", scope_sentence: "s", outcome: "o", outcome_code: "x", rule: "r", message: null, blocked: [], five: [], reasons: [],
  other_contradictions: [], other_contradictions_text: "", top5: { proposed: [], confirmed: true, void: false, claim_ids: [], set_at: null, in_force: [] } },
  data_gaps: [{ item: "S&M share of revenue", analysis: "S&M share of revenue", why: "Blocks S&M share of revenue. S&M split only in plan years; actual years carry OPEX total only.",
    requested: "A file with a sales_marketing row", target_date: null }],
  top_gaps: [], key_gates: { note: null, ok: true, all_key: true, saved: 0, sentences: [] }, gates_still_needed: 0, deal_terms: "n/a",
  candidates: [], ic_inputs: { first_quarterly_review: null, ratings: null, thesis: null }, ratings_for: {}, thesis_labels: {}, judgment_labels: {} };

async function mount(results) {
  api.getBlockers.mockResolvedValue([]);
  api.getAudit.mockResolvedValue({ ...sample.audit, target_arr: 1000000, target_date: "2026-12-31", reporting_currency: "EUR", as_of_month: "2026-06", old_claims: false });
  api.getResults.mockResolvedValue(results);
  api.readNarrative.mockResolvedValue({ narrative_status: "unavailable", reason: "x" });
  api.getDisclosure.mockResolvedValue(null);
  api.getClaimRegister.mockResolvedValue({ claims: [], register: [] });
  api.getVerdict.mockResolvedValue(VERDICT);
  api.getIntegrity.mockResolvedValue(null);
  api.getDatasets.mockResolvedValue([]);
  api.getDecks.mockResolvedValue({ decks: [], candidates: [] });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<Dashboard />); });
  await act(async () => { await Promise.resolve(); });
  await act(async () => { await Promise.resolve(); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}
const q = (host, id) => host.querySelector(`[data-testid="${id}"]`);
const text = (host, id) => q(host, id)?.textContent;
const results = (extra = {}) => ({ ...sample, results: { ...sample.results, cac_payback: null, acv_path: null, role_metrics: RM, yearly_basis: YEARLY, ...extra } });

test("Path to Plan shows actual to the as-of month against the plan of the same month, with the gap in money and in percent", async () => {
  const { host, done } = await mount(results());
  try {
    const panel = q(host, "path-to-plan-panel");
    expect(panel.textContent).not.toContain("No revenue data");
    expect([text(panel, "plan-to-date-actual"), text(panel, "plan-to-date-plan"), text(panel, "plan-to-date-gap")]).toEqual(["185 EUR", "200 EUR", "-15 EUR"]);
    expect(text(panel, "plan-to-date-gap-pct")).toBe("-7.5% against plan");
    expect(q(panel, "provenance-hover-plan-Actual")).not.toBeNull();
  } finally { await done(); }
});

test("a missing plan row says which row it needs", async () => {
  const rm = { ...RM, plan_to_date: null, metrics: [...RM.metrics, missing("plan_to_date", "Plan to date", "needs a forecast row", ["forecast"])] };
  const { host, done } = await mount(results({ role_metrics: rm }));
  try { expect(text(q(host, "path-to-plan-panel"), "plan-to-date-missing")).toBe("needs a forecast row"); } finally { await done(); }
});

test("with only a yearly P&L the CAC card shows the yearly table and says it needs a monthly P&L for quarterly payback", async () => {
  const { host, done } = await mount(results());
  try {
    const card = q(host, "cac-payback-chart");
    expect(text(card, "cac-needs-monthly")).toBe("needs a monthly P&L for quarterly payback");
    expect(q(card, "cac-yearly-table")).not.toBeNull();
    expect(card.textContent).toContain("2025");
    expect(card.textContent).not.toContain("P&L not provided");
  } finally { await done(); }
});

test("customer count, monthly churn and growth by year sit beside Ending ARR, each with its cell", async () => {
  const { host, done } = await mount(results());
  try {
    const strip = q(host, "metric-card-arr").parentElement;
    ["customers", "monthly_churn", "growth_by_year"].forEach((id) => expect(q(strip, `metric-card-${id}`)).not.toBeNull());
    expect(q(strip, "metric-card-customers").textContent).toContain("67");
    expect(q(strip, "metric-card-monthly_churn").textContent).toContain("3%");
    const growth = q(strip, "metric-card-growth_by_year");
    expect(growth.textContent).toContain("+60%");
    expect(growth.textContent).toContain("2024 +50%");
    expect(q(strip, "provenance-hover-customers")).not.toBeNull();
  } finally { await done(); }
});

test("the revenue reconciliation lists each year with its sources by cell or page and the differences", async () => {
  const { host, done } = await mount(results());
  try {
    const row = q(host, "reconciliation-2025");
    const sources = [...row.querySelectorAll('[data-testid="reconciliation-source"]')].map((e) => e.textContent);
    expect(sources).toEqual(["File report.xlsx · Report!B4:M4 · 1,200 EUR", "File pnl.xlsx · P&L!D4 · 1,300 EUR", "Deck board.pdf · page 7 · 1,500 EUR"]);
    expect(text(row, "reconciliation-gap")).toBe("300 EUR");
    expect([...row.querySelectorAll('[data-testid="reconciliation-also-read"]')].map((e) => e.textContent)).toEqual(["Also read on page 7 · 400 EUR"]);
    expect(row.textContent).toContain("20%");
    expect(row.textContent).toContain("Differs");
  } finally { await done(); }
});

test("a rounded agreement reads Agrees (rounded) in green with its note, and a growth year taken from the deck says so", async () => {
  const rounded = { ...RM.reconciliation[0], period: "2024", status: "agrees_rounded", gap: 34000, gap_pct: 0.03,
    note: "deck figure printed to the nearest hundred thousand" };
  const withDeck = { ...RM.growth_by_year[1], deck_note: "2025 from deck, page 6, unverified" };
  const { host, done } = await mount(results({ role_metrics: { ...RM, reconciliation: [rounded, ...RM.reconciliation], growth_by_year: [RM.growth_by_year[0], withDeck] } }));
  try {
    const row = q(host, "reconciliation-2024");
    expect(text(row, "reconciliation-green")).toBe("Agrees (rounded)");
    expect(text(row, "reconciliation-note")).toBe("deck figure printed to the nearest hundred thousand");
    expect(q(host, "reconciliation-2025").textContent).toContain("Differs");
    expect(q(host, "metric-card-growth_by_year").textContent).toContain("2025 from deck, page 6, unverified");
  } finally { await done(); }
});

test("one reason per missing metric, the same text at the top and in Data gaps", async () => {
  const { host, done } = await mount(results());
  try {
    const top = text(host, "role-missing-reason-sm_share");
    expect(top).toBe("S&M split only in plan years; actual years carry OPEX total only");
    expect(text(host, "role-missing-reason-cash")).toBe("needs a cash row");
    expect(host.querySelectorAll('[data-testid="role-missing-sm_share"]').length).toBe(1);
    const gap = [...host.querySelectorAll('[data-testid="data-gap-why"]')].map((e) => e.textContent).join(" ");
    expect(gap).toContain(top);
  } finally { await done(); }
});

test("a row whose costs are printed as negatives carries the note, and a margin note from the sheet's own row shows", async () => {
  const rm = { ...RM, metrics: [
    metric("gross_margin", "Gross margin", { unit: "rate", value: 0.75, basis: "yearly", detail: "costs shown as negative; the sheet's own gross margin row states 62% against 75% computed (difference 13%)" }),
    metric("sm_share", "S&M share of revenue", { unit: "rate", value: 0.375, basis: "yearly", detail: "costs shown as negative" }),
    metric("yearly_cac_payback", "CAC payback (yearly)", { unit: "months", value: 14, basis: "yearly", detail: "costs shown as negative" })] };
  const { host, done } = await mount(results({ role_metrics: rm }));
  try {
    expect(text(host, "role-detail-sm_share")).toBe("S&M share of revenue: costs shown as negative");
    expect(text(host, "role-detail-gross_margin")).toContain("costs shown as negative");
    expect(text(host, "role-detail-gross_margin")).toContain("62% against 75% computed");
    expect(text(host, "role-detail-yearly_cac_payback")).toContain("costs shown as negative");
  } finally { await done(); }
});
