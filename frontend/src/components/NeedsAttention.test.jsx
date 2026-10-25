// docs/design/simplified-flow.md, The Audit page, item 5: the questions Review listed, as cards: at most three, "n more" for the rest.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import NeedsAttention from "./NeedsAttention";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getDatasets: jest.fn(), getDecks: jest.fn(), updateCandidate: jest.fn(), decideColumns: jest.fn(), answerDefinitionCheck: jest.fn(), answerTurnover: jest.fn(),
  getBlockers: jest.fn(), runStage: jest.fn(),
}));
jest.mock("react-router-dom", () => ({ Link: ({ to, children }) => <a href={to}>{children}</a>, useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const claim = (id, extra = {}) => ({ id, claim_type: "revenue", status: "pending", value: 100, unit: "EUR", currency: "EUR", sources: [{ file: "deck.pptx", page: 3 }], group: 1, ...extra });
const mount = async (candidates, views = [], props = {}) => {
  api.getDatasets.mockResolvedValue(views);
  api.getDecks.mockResolvedValue({ decks: [], candidates });
  const onChanged = jest.fn();
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<NeedsAttention auditId="a1" onChanged={onChanged} {...props} />); });
  await act(async () => { await Promise.resolve(); });
  return { host, onChanged, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
};
const q = (host, id) => host.querySelector(`[data-testid="${id}"]`);

test("no open question: the card is not on the page", async () => {
  const { host, done } = await mount([claim("k1", { status: "approved" }), claim("k2", { status: "rejected" })]);
  try { expect(q(host, "needs-attention")).toBeNull(); } finally { await done(); }
});

test("three questions are shown in full and there is no n more link", async () => {
  const { host, done } = await mount([claim("k1"), claim("k2"), claim("k3")]);
  try {
    expect(host.querySelectorAll('[data-testid="attention-card"]').length).toBe(3);
    expect(q(host, "attention-more")).toBeNull();
    expect(q(host, "attention-count").textContent).toBe("3 questions need a word from you");
  } finally { await done(); }
});

test("five questions: three cards, an '2 more' link that opens the rest and closes again", async () => {
  const { host, done } = await mount([1, 2, 3, 4, 5].map((n) => claim(`k${n}`)));
  try {
    expect(host.querySelectorAll('[data-testid="attention-card"]').length).toBe(3);
    expect(q(host, "attention-more").textContent).toBe("2 more");
    await act(async () => { q(host, "attention-more").click(); });
    expect(host.querySelectorAll('[data-testid="attention-card"]').length).toBe(5);
    await act(async () => { q(host, "attention-more").click(); });
    expect(host.querySelectorAll('[data-testid="attention-card"]').length).toBe(3);
  } finally { await done(); }
});

test("Approve and Reject answer in place, the cards are read again and the page is told; nothing is deleted", async () => {
  api.updateCandidate.mockResolvedValue({});
  const { host, onChanged, done } = await mount([claim("k1")]);
  try {
    api.getDecks.mockResolvedValue({ decks: [], candidates: [claim("k1", { status: "approved" })] });
    await act(async () => { q(host, "attention-approve").click(); });
    expect(api.updateCandidate).toHaveBeenCalledWith("a1", "k1", { status: "approved" });
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(q(host, "needs-attention")).toBeNull();
    expect(api.updateCandidate).not.toHaveBeenCalledWith("a1", "k1", expect.objectContaining({ status: "rejected" }));
  } finally { await done(); }
});

test("an Other figure is never a question; an open Definition check asks Yes / No in place", async () => {
  api.answerDefinitionCheck.mockResolvedValue({});
  const open = claim("k2", { status: "approved", definition: [{ claim_id: "r2", definition_check: "ask", definition_question: "Observed 26, claimed 1. Same metric and period?", period: "FY2024" }] });
  const { host, done } = await mount([claim("k1", { claim_type: "other" }), open]);
  try {
    expect(host.querySelectorAll('[data-testid="attention-card"]').length).toBe(1);
    await act(async () => { q(host, "definition-yes").click(); });
    expect(api.answerDefinitionCheck).toHaveBeenCalledWith("a1", "r2", "yes");
  } finally { await done(); }
});

test("a column that waits is a card; mapping questions come before claims", async () => {
  const view = { dtype: "revenue", file: "revenue.csv", pending: 1, missing_required: [], fields: { required: ["amount"], optional: [] },
    columns: [{ column: "Amt", field: "amount", state: "matched", pending: true, confidence: 70, decision: null }] };
  const { host, done } = await mount([claim("k1")], [view]);
  try {
    const cards = host.querySelectorAll('[data-testid="attention-card"]');
    expect(cards.length).toBe(2);
    expect(cards[0].querySelector('[data-testid="attention-mapping"]')).not.toBeNull();
    expect(cards[1].querySelector('[data-testid="attention-claim"]')).not.toBeNull();
  } finally { await done(); }
});
