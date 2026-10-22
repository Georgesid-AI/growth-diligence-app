/* Issue #155 (George, 2026-10-22): a claim Run audit approved on its own reads "Auto-approved – matches revenue file (Δ x.x%)" in the
 * deck list with the figure's citation, the deck list's count line reads "x to review · y approved (z auto) · …", and the register
 * shows the row as "auto". Synthetic claims only (CLAUDE.md rule 15). */
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import DeckPanel from "./DeckPanel";
import ClaimRegister from "./ClaimRegister";
import * as api from "@/lib/api";
import { countLine, statusCounts, statusText } from "@/lib/deckClaims";

jest.mock("@/lib/api", () => ({
  getDecks: jest.fn(), removeDeck: jest.fn(), updateCandidate: jest.fn(), uploadDeck: jest.fn(), addClaim: jest.fn(), answerTurnover: jest.fn(),
  approveAll: jest.fn(), getClaimRegister: jest.fn(), getBlockers: jest.fn(), updateClaimInputs: jest.fn(), answerDefinitionCheck: jest.fn(),
  saveAllGatesCall: jest.fn(), claimsCsvUrl: (id) => `http://api/api/audits/${id}/claims.csv`,
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn(), message: jest.fn() } }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TEXT = "Auto-approved – matches revenue file (Δ 1.1%)";
const CITATION = "(mrr_series.data.total, CSV, rows 2–71, Feb 2024)";
const claim = (id, over = {}) => ({
  id, deck_id: "d1", status: "pending", claim_type: "revenue", value: 200000, value_high: null, unit: null, currency: "EUR", target_date: "2024-02",
  snippet: `snippet-${id}`, label_from: null, date_from: null, inconsistent_dates: [], group: 1, sources: [{ file: "d1", slide: 2, kind: "text" }],
  confidence: { level: "High", failed: [], text: "High" }, ...over,
});
const CANDIDATES = [
  claim("a", { status: "approved", auto_accepted: true, auto_approval: TEXT, auto_citation: CITATION }),
  claim("b", { status: "approved" }),
  claim("c"),
  claim("d", { status: "approved", auto_accepted: true, auto_approval: TEXT, auto_citation: CITATION }),
  claim("e", { status: "edited" }),
];
const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);

test("the count line reads x to review · y approved (z auto) · e edited · r rejected, and the status text names the match", () => {
  expect(statusCounts(CANDIDATES)).toEqual({ pending: 1, approved: 3, rejected: 0, edited: 1, auto: 2 });
  expect(countLine(statusCounts(CANDIDATES))).toBe("1 to review · 3 approved (2 auto) · 1 edited · 0 rejected");
  expect(statusText(CANDIDATES[0])).toBe(TEXT);
  expect(statusText(CANDIDATES[1])).toBe("Approved");
});

test("the deck list shows the status text with the citation on hover for an auto-approved claim and 'Approved' for the others", async () => {
  api.getDecks.mockResolvedValue({ decks: [{ deck_id: "d1", file: "d1.pptx", pages: 5, page_unit: "slide", uploaded_at: "2026-10-01" }], candidates: CANDIDATES });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<DeckPanel auditId="a1" />); });
  const status = (id) => q(`candidate-row-${id}`).querySelector("[data-testid='candidate-status']");
  expect(status("a").textContent).toBe(TEXT);
  expect(status("a").getAttribute("title")).toContain(CITATION);
  expect(status("b").textContent).toBe("Approved");
  expect(host.textContent).toContain("1 to review · 3 approved (2 auto) · 1 edited · 0 rejected");
  await act(async () => { root.unmount(); });
  host.remove();
});

test("the register shows an auto-approved row with the label 'auto' and the status text; the others show neither", async () => {
  const ROW = {
    claim_id: "c01", claim_type: "revenue", claimed_value: 200000, claimed_high: null, unit: null, currency: "EUR", period: "Feb 2024", period_note: null,
    segment: "Whole company", segment_set_by: "python", metric: "ARR", metric_set_by: "python", direction: "higher", observed_value: 202125.48,
    observed_at: "2024-02", observed_source: { file: "revenue.csv", sheet: "CSV", rows: "rows 2–71", rule: "ARR" }, observed_citation: CITATION,
    gap: -2125.48, gap_normalised: -0.010627, gap_kind: "beat", gloss: "€2,125 better than claimed", evidence_label: "Verified",
    reason: "within ±5% of the claim", tolerance: "±5%", rank: 1, value_at_stake_arr: null, shortfall: null, overlaps_with: [],
    evidence_analysis: "Monthly MRR by Segment", evidence_source_key: "mrr_series.data.total", gate_sentence: null, gate_threshold: null,
    gate_budget_decision: null, gate_metric_name: null, gate_direction: null, key_gate: false, gate_needed: false, gate_date: null, gate_saved: false,
    deck_reading: "parser", page_ref: "slide 4", auto_approval: TEXT,
  };
  api.getBlockers.mockResolvedValue([]);
  api.getClaimRegister.mockResolvedValue({ claims: [], register: [ROW, { ...ROW, claim_id: "c02", rank: 2, auto_approval: null }] });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<ClaimRegister auditId="a1" results={{ reporting_currency: "EUR", mrr_series: { segments: [] } }} />); });
  const rows = [...document.body.querySelectorAll("[data-testid='claim-register-row']")];
  expect(rows[0].querySelector("[data-testid='register-auto']").textContent).toBe("auto");
  expect(rows[0].querySelector("[data-testid='register-auto-approval']").textContent).toBe(TEXT);
  expect(rows[0].querySelector("[data-testid='register-observed-citation']").textContent).toBe(CITATION);
  expect(rows[1].querySelector("[data-testid='register-auto']")).toBeNull();
  expect(rows[1].querySelector("[data-testid='register-auto-approval']")).toBeNull();
  await act(async () => { root.unmount(); });
  host.remove();
});
