// docs/design/simplified-flow.md, The Audit page, item 5: the questions that wait for the analyst, as cards: at most three, "n more" for the rest;
// the claim questions in the server's ranking, the questions of the five selected claims first.
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
const mount = async (candidates, views = [], props = {}, attention = []) => {
  api.getDatasets.mockResolvedValue(views);
  api.getDecks.mockResolvedValue({ decks: [], candidates, attention });
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

test("Keep and Not a company claim answer in place, the cards are read again and the page is told; nothing is deleted", async () => {
  api.updateCandidate.mockResolvedValue({});
  const { host, onChanged, done } = await mount([claim("k1")]);
  try {
    api.getDecks.mockResolvedValue({ decks: [], candidates: [claim("k1", { status: "approved" })] });
    await act(async () => { q(host, "attention-keep").click(); });
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

const ids = (host) => [...host.querySelectorAll('[data-testid="attention-claim"]')].map((n) => /k\d/.exec(n.textContent)?.[0]);

test("the claim questions follow the server's ranking and the questions of the five come first, before the columns", async () => {
  const view = { dtype: "revenue", file: "revenue.csv", pending: 1, missing_required: [], fields: { required: ["amount"], optional: [] },
    columns: [{ column: "Amt", field: "amount", state: "matched", pending: true, confidence: 70, decision: null }] };
  const cs = [1, 2, 3, 4].map((n) => claim(`k${n}`, { snippet: `k${n}` }));
  const attention = [{ id: "k3", in_top5: true }, { id: "k1", in_top5: true }, { id: "k4", in_top5: false }, { id: "k2", in_top5: false }];
  const { host, done } = await mount(cs, [view], {}, attention);
  try {
    await act(async () => { q(host, "attention-more").click(); });
    const order = [...host.querySelectorAll('[data-testid="attention-card"]')].map((card) => (card.querySelector('[data-testid="attention-mapping"]') ? "column" : "claim"));
    expect(order).toEqual(["claim", "claim", "column", "claim", "claim"]);
    expect(q(host, "attention-count").textContent).toBe("5 questions need a word from you");
  } finally { await done(); }
});

test("without a ranking the claims keep the server's list order and the columns stay first", async () => {
  const view = { dtype: "revenue", file: "revenue.csv", pending: 1, missing_required: [], fields: { required: ["amount"], optional: [] },
    columns: [{ column: "Amt", field: "amount", state: "matched", pending: true, confidence: 70, decision: null }] };
  const { host, done } = await mount([claim("k2", { value: 222 }), claim("k1", { value: 111 })], [view]);
  try {
    const cards = [...host.querySelectorAll('[data-testid="attention-card"]')];
    expect(cards.map((card) => (card.querySelector('[data-testid="attention-mapping"]') ? "column" : "claim"))).toEqual(["column", "claim", "claim"]);
    expect(cards[1].textContent).toContain("222");
    expect(cards[2].textContent).toContain("111");
  } finally { await done(); }
});

test("a card for a claim says Keep and Not a company claim; the old Approve and Reject words are gone", async () => {
  const { host, done } = await mount([claim("k1")]);
  try {
    expect(q(host, "attention-keep").textContent).toBe("Keep");
    expect(q(host, "attention-reject").textContent).toBe("Not a company claim");
    expect(host.textContent).not.toMatch(/Approve/);
  } finally { await done(); }
});

test("an untested row whose reason asks the analyst to set something is a card with the claims list's editor and counts as a question", async () => {
  const REASON = "Period not read – set it in the claim row";
  const set = claim("s1", { status: "approved", target_date: null, snippet: "ARR of 200,000" });
  const fine = claim("f1", { status: "approved" });
  const { host, done } = await mount([set, fine], [], {}, [{ id: "s1", in_top5: true, set: REASON }]);
  try {
    expect(host.querySelectorAll('[data-testid="attention-card"]').length).toBe(1);
    expect(q(host, "attention-count").textContent).toBe("1 question needs a word from you");
    expect(q(host, "attention-set-reason").textContent).toBe(REASON);
    expect(q(host, "candidate-row-s1")).not.toBeNull();
    await act(async () => { q(host, "candidate-edit").click(); });
    api.getDecks.mockResolvedValue({ decks: [], candidates: [{ ...set, target_date: "2024-02" }, fine], attention: [] });
    api.updateCandidate.mockResolvedValue({});
    await act(async () => { q(host, "edit-target-date").focus(); });
    const input = q(host, "edit-target-date");
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    await act(async () => { setter.call(input, "2024-02"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => { q(host, "edit-save").click(); });
    expect(api.updateCandidate).toHaveBeenCalledWith("a1", "s1", expect.objectContaining({ target_date: "2024-02" }));
    expect(q(host, "needs-attention")).toBeNull();
  } finally { await done(); }
});
