// docs/specs/claim-types-and-correction.md (plan section 4 and 7.1): the editor, Other figures and Add from deck.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import DeckPanel from "./DeckPanel";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({ getDecks: jest.fn(), removeDeck: jest.fn(), updateCandidate: jest.fn(), uploadDeck: jest.fn(), addClaim: jest.fn(),
  answerTurnover: jest.fn(), approveAll: jest.fn(), getDeckPage: jest.fn(), addFromDeck: jest.fn() }));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn(), message: jest.fn() } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const DECKS = [{ deck_id: "d1", file: "board.pptx", pages: 12, page_unit: "slide", uploaded_at: "2026-10-01" }];
const claim = (id, over = {}) => ({
  id, deck_id: "d1", status: "approved", claim_type: "revenue", value: 200000, value_high: null, unit: null, currency: "EUR",
  target_date: "2024-02", snippet: `snippet-${id}`, label_from: null, date_from: null, inconsistent_dates: [], group: 1,
  sources: [{ file: "board.pptx", slide: 9, kind: "text" }], figure_type: "target", figure_type_set_by: "parser",
  population: null, growth_basis: null, edit_log: [],
  confidence: { level: "High", failed: [], text: "High" }, ...over,
});
const TARGET = claim("t1", { snippet: "Target ARR of €200,000 in Feb 2024" });
const OTHER = claim("o1", { status: "pending", claim_type: "other", value: 15, unit: "months", currency: null, target_date: null,
  snippet: "15 months", group: 9, figure_type: null });
const MISSED = "Signed twelve enterprise pilots last quarter";

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
let root, host;
beforeEach(async () => {
  jest.clearAllMocks();
  api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [TARGET, OTHER] });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<DeckPanel auditId="a1" />); });
});
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });

const setValue = async (el, value) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(el, value);
  el.dispatchEvent(new Event("change", { bubbles: true }));
});

test("plan 4 (1): the editor corrects Target to Actual with a reason, and the save sends both", async () => {
  await act(async () => { q("candidate-row-t1").querySelector("[data-testid='candidate-edit']").click(); });
  const figureType = q("edit-figure-type");
  expect([...figureType.querySelectorAll("option")].map((o) => o.textContent)).toEqual(["Actual", "Target", "Unknown"]);
  expect(figureType.value).toBe("target");
  await setValue(figureType, "actual");
  expect(q("edit-reason").value).toBe("parser_misread");
  api.updateCandidate.mockResolvedValue({ ...TARGET, status: "edited", figure_type: "actual" });
  await act(async () => { q("edit-save").click(); });
  expect(api.updateCandidate).toHaveBeenCalledWith("a1", "t1", expect.objectContaining({ figure_type: "actual", reason: "parser_misread" }));
});

test("plan 4 (2): Other figures sit collapsed under their count, with no Approve and no review count", async () => {
  expect(q("claim-group-toggle-9").textContent).toBe("1 other figure");
  await act(async () => { q("claim-group-toggle-9").click(); });
  const row = q("candidate-row-o1");
  expect(row.querySelector("[data-testid='candidate-approve']")).toBeNull();
  expect(row.querySelector("[data-testid='candidate-edit']")).not.toBeNull();
  expect(document.body.textContent).not.toMatch(/1 to review/);
});

test("plan 4 (3): a line of the deck page is added from the deck and shows its page as source", async () => {
  api.getDeckPage.mockResolvedValue({ deck_id: "d1", file: "board.pptx", page_unit: "slide", page: 4, pages: 12,
    lines: [{ ref: "b1", kind: "text", text: MISSED }, { ref: "b2", kind: "table", text: "Q1 2024" }] });
  const added = claim("n1", { status: "pending", claim_type: "other", value: null, currency: null, target_date: null, snippet: MISSED,
    origin: "deck_analyst", sources: [{ file: "board.pptx", slide: 4, kind: "text" }], group: 9, figure_type: null,
    confidence: { level: "Low", failed: ["no date", "no heading"], text: "Low – no date, no heading" } });
  api.addFromDeck.mockResolvedValue(added);
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(q("deck-page-input"), "4");
    q("deck-page-input").dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => { q("deck-page-show").click(); });
  expect(api.getDeckPage).toHaveBeenCalledWith("a1", "d1", 4);
  await act(async () => { q("deck-page-line-b1").click(); });
  api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [TARGET, OTHER, added] });
  await act(async () => { q("add-from-deck").click(); });
  expect(api.addFromDeck).toHaveBeenCalledWith("a1", "d1", { page: 4, ref: "b1" });
  const row = q("candidate-row-n1");
  expect(row.textContent).toContain("slide 4");
  expect(row.textContent).toContain("Added from deck by analyst");
  expect(row.textContent).toContain(MISSED);
});
