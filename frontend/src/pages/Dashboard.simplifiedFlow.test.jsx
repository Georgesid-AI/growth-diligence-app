// docs/design/simplified-flow.md, "The Audit page" and "Evidence labels": the order of the page, the assumptions strip, the five
// selected claims, the label definitions and what sits under Supporting detail. Presentation only: no figure is computed here.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import Dashboard from "./Dashboard";
import * as api from "@/lib/api";
import sample from "./fixtures/sample_results.json";
import labels from "@/lib/evidence_labels.json";

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

const LINE = "Top-5 claim contradicted: revenue 200,000 EUR vs 150,000 EUR observed (board.pptx, slide 4).";
const ROW = (n, label, extra = {}) => ({
  claim_id: `c${n}`, rank: n, claim_type: "revenue", claimed_value: 200000, unit: null, currency: "EUR", period: "Feb 2024", period_note: null,
  segment: "Whole company", segment_set_by: "python", metric: "ARR", observed_value: 150000, observed_at: "2024-02",
  observed_source: { file: "revenue.csv", sheet: "CSV", rows: "rows 2–71", rule: "ARR" }, observed_citation: "(mrr_series.data.total, CSV, rows 2–71, Feb 2024)",
  gap: 50000, gap_normalised: 0.25, gap_kind: "miss", gloss: "€50,000 lower", evidence_label: label, reason: "outside ±5%: a miss", overlaps_with: [],
  value_at_stake_arr: 50000, deck_reading: "parser", page_ref: "slide 4", gate_sentence: null, ...extra,
});
const FIVE = [ROW(1, "Contradicted"), ROW(2, "Verified"), ROW(3, "Unverified"), ROW(4, "Unsupported"), ROW(5, "Inconclusive")];
const VERDICT = {
  verdict: {
    heading: "Claim-review conclusion — assessment of the five selected claims", scope_sentence: "This assesses the five claims the analyst selected. It is not an investment recommendation.",
    status: "ok", outcome: "Selected claims not supported", outcome_code: "not_supported", rule: "1 selected claim is Contradicted.", message: null, blocked: [],
    five: FIVE.map((r) => ({ claim_id: r.claim_id, rank: r.rank, claim: `Claim ${r.rank}`, evidence_label: r.evidence_label, reason: r.reason })),
    reasons: ["#1 Claim 1: Contradicted."], other_contradictions: [], other_contradictions_text: "None found among tested claims.",
    top5: { proposed: FIVE.map((r) => r.claim_id), confirmed: true, void: false, claim_ids: FIVE.map((r) => r.claim_id), set_at: "2026-10-15", in_force: FIVE.map((r) => r.claim_id) },
  },
  data_gaps: [], top_gaps: [], key_gates: { note: null, ok: true, all_key: true, saved: 0, sentences: [] }, gates_still_needed: 0, deal_terms: "Deal terms: n/a",
  candidates: FIVE.map((r) => ({ claim_id: r.claim_id, rank: r.rank, claim: `Claim ${r.rank}`, evidence_label: r.evidence_label, reason: r.reason })),
  ic_inputs: { first_quarterly_review: null, ratings: null, thesis: null }, ratings_for: {}, thesis_labels: {}, judgment_labels: {},
};
const DECKS = { decks: [], candidates: [{ id: "k1", claim_type: "revenue", status: "pending", value: 100, unit: "EUR", sources: [{ page: 3 }], flags: [] }] };

async function mount({ audit = { ...sample.audit, target_arr: 1000000, target_date: "2026-12-31", fiscal_year_end: 3, as_of_month: null, reporting_currency: "EUR",
  datasets: { revenue: { months: { first: "2023-01", last: "2024-02" } } } }, decks = { decks: [], candidates: [] } } = {}) {
  api.getBlockers.mockResolvedValue([{ kind: "claim_contradicted", text: LINE }]);
  api.getAudit.mockResolvedValue(audit);
  api.getResults.mockResolvedValue(sample);
  api.readNarrative.mockResolvedValue({ narrative_status: "unavailable", reason: "x" });
  api.getDisclosure.mockResolvedValue(null);
  api.getClaimRegister.mockResolvedValue({ claims: [], register: FIVE });
  api.getVerdict.mockResolvedValue(VERDICT);
  api.getIntegrity.mockResolvedValue(null);
  api.getDatasets.mockResolvedValue([]);
  api.getDecks.mockResolvedValue(decks);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<Dashboard />); });
  await act(async () => { await Promise.resolve(); });
  await act(async () => { await Promise.resolve(); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}
const q = (host, id) => host.querySelector(`[data-testid="${id}"]`);
const before = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

test("the page runs: assumptions strip, conclusion with the contradiction lines under it, the five claims, the questions, the report, then Supporting detail", async () => {
  const { host, done } = await mount({ decks: DECKS });
  try {
    const order = ["assumptions-strip", "verdict", "verdict-five", "needs-attention", "report-download", "supporting-detail"].map((id) => q(host, id));
    expect(order.every(Boolean)).toBe(true);
    order.slice(1).forEach((el, i) => expect(before(order[i], el)).toBe(true));
    const verdict = q(host, "verdict");
    expect(before(q(verdict, "verdict-rule"), q(verdict, "contradiction-banner"))).toBe(true);
    expect(before(q(verdict, "conclusion-scope"), q(verdict, "contradiction-banner"))).toBe(true);
    expect(q(verdict, "contradiction-banner").textContent).toBe(LINE);
  } finally { await done(); }
});

test("everything else is under Supporting detail, in the order metric cards · register · data gaps · verdict detail · glossary", async () => {
  const { host, done } = await mount();
  try {
    const detail = q(host, "supporting-detail");
    expect(detail.tagName).toBe("DETAILS");
    expect(detail.open).toBe(false);
    const parts = ["provenance-hover-arr", "claim-register", "data-gaps", "verdict-detail", "glossary"].map((id) => q(detail, id));
    expect(parts.every(Boolean)).toBe(true);
    parts.slice(1).forEach((el, i) => expect(before(parts[i], el)).toBe(true));
    // nothing of the register, the gaps or the verdict detail is outside it
    ["claim-register", "data-gaps", "verdict-detail", "glossary", "mrr-by-segment-chart"].forEach((id) => expect(q(host, id).closest("details")).toBe(detail));
    expect(q(host, "needs-attention")).toBeNull();                                     // at 0 questions the card is hidden
  } finally { await done(); }
});

test("the assumptions strip is read-only: currency, reporting period, target ARR, target date, as-of month (default marked), FY end, one Change link", async () => {
  const { host, done } = await mount();
  try {
    const strip = q(host, "assumptions-strip");
    expect(strip.querySelectorAll("input, select, textarea").length).toBe(0);
    expect(["currency", "period", "target-arr", "target-date", "as-of", "fy-end"].map((k) => q(strip, `assumption-${k}`).textContent)).toEqual([
      "Currency EUR", "Reporting period Jan 2023 – Feb 2024", "Target ARR 1,000,000 EUR",
      "Target date 2026-12-31", "As-of month February 2024 (default)", "FY end March"]);
    expect(strip.querySelectorAll("button").length).toBe(1);
    await act(async () => { q(strip, "assumptions-change").click(); });
    expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/mapping");
  } finally { await done(); }
});

test("a set as-of month is not marked default", async () => {
  const { host, done } = await mount({ audit: { ...sample.audit, as_of_month: "2024-01-31", datasets: {} } });
  try { expect(q(host, "assumption-as-of").textContent).toBe("As-of month January 2024"); } finally { await done(); }
});

test("the five selected claims read Plan assumes · Evidence shows · Result, each with a source link and a Details toggle", async () => {
  const { host, done } = await mount();
  try {
    const five = q(host, "verdict-five");
    expect(five.textContent).toContain("Plan assumes");
    expect(five.textContent).toContain("Evidence shows");
    expect(five.textContent).toContain("Result");
    const rows = five.querySelectorAll('[data-testid="verdict-five-row"]');
    expect(rows.length).toBe(5);
    const first = rows[0];
    expect(q(first, "five-plan").textContent).toContain("200,000 EUR");
    expect(q(first, "five-plan").textContent).toContain("Feb 2024");
    expect(q(first, "five-evidence").textContent).toContain("150,000");
    expect(q(first, "five-evidence").textContent).toContain("2024-02");
    expect(q(first, "five-result").textContent).toContain("Contradicted");
    expect(q(first, "five-source")).toBeNull();
    await act(async () => { q(first, "five-source-link").click(); });
    expect(q(first, "five-source").textContent).toBe("(mrr_series.data.total, CSV, rows 2–71, Feb 2024) · slide 4");
    expect(q(first, "five-details")).toBeNull();
    await act(async () => { q(first, "five-details-toggle").click(); });
    expect(q(first, "five-details").textContent).toContain("outside ±5%: a miss");
    expect(q(first, "five-details").textContent).toContain("VaS");
  } finally { await done(); }
});

test("every label shows its definition on hover; the five definitions are printed in full once, under the five findings, in the note's order", async () => {
  const { host, done } = await mount();
  try {
    const five = q(host, "verdict-five");
    five.querySelectorAll('[data-testid="verdict-five-row"]').forEach((row) => {
      const chip = q(row, "five-result").querySelector("span[title]");
      expect(chip.getAttribute("title")).toBe(`${chip.textContent}: ${labels.definitions[chip.textContent]}`);
    });
    const defs = q(five, "label-definitions");
    expect([...defs.querySelectorAll("dt")].map((d) => d.textContent)).toEqual(["Verified", "Unverified", "Unsupported", "Contradicted", "Inconclusive"]);
    expect([...defs.querySelectorAll("dd")].map((d) => d.textContent)).toEqual(
      ["Verified", "Unverified", "Unsupported", "Contradicted", "Inconclusive"].map((l) => `— ${labels.definitions[l]}`));
    expect(host.querySelectorAll('[data-testid="label-definitions"]').length).toBe(1);
    expect(before(q(five, "verdict-five-row"), defs)).toBe(true);
    // the register's Result column carries the same hover
    const reg = [...host.querySelectorAll('[data-testid="register-evidence"]')];
    expect(reg.length).toBe(5);
    reg.forEach((chip) => expect(chip.getAttribute("title")).toBe(`${chip.textContent}: ${labels.definitions[chip.textContent]}`));
  } finally { await done(); }
});

test("an unconfirmed top 5 shows its proposed five as the findings", async () => {
  api.getVerdict.mockResolvedValue({ ...VERDICT, verdict: { ...VERDICT.verdict, status: "unconfirmed", outcome: null, five: [], top5: { ...VERDICT.verdict.top5, confirmed: false } } });
  const { host, done } = await mount();
  try { expect(q(host, "verdict-five").querySelectorAll('[data-testid="verdict-five-row"]').length).toBe(5); } finally { await done(); }
});
