import React, { act } from "react";
import { createRoot } from "react-dom/client";

import DeckPanel from "./DeckPanel";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({ getDecks: jest.fn(), removeDeck: jest.fn(), updateCandidate: jest.fn(), uploadDeck: jest.fn() }));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const DECKS = [
  { deck_id: "d2", file: "newer.pdf", pages: 9, page_unit: "page", uploaded_at: "2026-10-02" },
  { deck_id: "d1", file: "older.pptx", pages: 9, page_unit: "slide", uploaded_at: "2026-10-01" },
];
const claim = (id, deck_id, page, over = {}) => ({
  id, deck_id, status: "pending", claim_type: "revenue", value: 100, value_high: null, unit: null, currency: "EUR", target_date: "2025",
  snippet: `snippet-${id}`, label_from: null, date_from: null, inconsistent_dates: [],
  sources: [{ file: deck_id, [deck_id === "d1" ? "slide" : "page"]: page, kind: "text" }],
  confidence: { level: "Medium", failed: ["not corroborated"], text: "Medium – not corroborated" }, ...over,
});
// The server sends them ascending by page across the decks.
const CLAIMS = [
  claim("a", "d1", 1, { claim_type: "unknown", target_date: null, confidence: { level: "Low", failed: ["no date", "no heading"], text: "Low – no date, no heading" } }),
  claim("b", "d2", 1, { claim_type: "market", label_from: "MARKET SIZE", confidence: { level: "High", failed: [], text: "High" } }),
  claim("c", "d1", 2),
  claim("d", "d2", 3),
];

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
let root, host;
beforeEach(async () => {
  jest.clearAllMocks();
  api.getDecks.mockResolvedValue({ decks: DECKS, candidates: CLAIMS });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<DeckPanel auditId="a1" />); });
});
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });

const rows = () => [...document.body.querySelectorAll("[data-testid='deck-candidates'] tbody tr")];
const text = (tr) => tr.textContent;

test("the table has a Confidence column between Date and the claim, in every row", async () => {
  await act(async () => { q("deck-tab-all").click(); });
  const heads = [...document.body.querySelectorAll("[data-testid='deck-candidates'] thead th")].map((th) => th.textContent);
  expect(heads).toEqual(["Type", "Value", "Date", "Confidence", "Claim in the deck", "Source", "Status", "Action"]);
  const cells = rows().map((tr) => tr.querySelector("[data-testid='candidate-confidence']").textContent);
  expect(cells.sort()).toEqual(["High", "Low – no date, no heading", "Medium – not corroborated", "Medium – not corroborated"].sort());
});

test("All lists the claims in the server's page order across the decks; a deck tab keeps that order", async () => {
  await act(async () => { q("deck-tab-all").click(); });
  expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["a", "b", "c", "d"]);
  await act(async () => { q("deck-tab-d1").click(); });
  expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["a", "c"]);
});

test("an Unknown type says so, cannot be approved before a type is chosen, and Market size is a choice", async () => {
  await act(async () => { q("deck-tab-d1").click(); });
  const first = rows()[0];
  expect(first.textContent).toContain("Unknown – choose type");
  expect(first.querySelector("[data-testid='candidate-approve']").disabled).toBe(true);
  expect(rows()[1].querySelector("[data-testid='candidate-approve']").disabled).toBe(false);
  await act(async () => { first.querySelector("[data-testid='candidate-edit']").click(); });
  const options = [...document.body.querySelectorAll("[data-testid='edit-claim-type'] option")].map((o) => o.textContent);
  expect(options[0]).toBe("Unknown – choose type");
  expect(options).toContain("Market size");
  expect(options).not.toContain("Market");
  expect(document.body.querySelector("[data-testid='edit-save']").disabled).toBe(true);
});

test("Label from shows the one heading the server found", async () => {
  await act(async () => { q("deck-tab-d2").click(); });
  expect(q("candidate-label").textContent).toBe("Label from: MARKET SIZE");
});
