// George, 2026-10-27: the undated figures of one page are one card (one date for all, or Keep undated); a slice larger than the company total is
// one card that asks what the figure is and offers nothing to choose.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import NeedsAttention from "./NeedsAttention";
import * as api from "@/lib/api";
import { labelLine } from "@/lib/deckClaims";

jest.mock("@/lib/api", () => ({
  getDatasets: jest.fn(), getDecks: jest.fn(), getClaimRegister: jest.fn(), updateCandidate: jest.fn(), decideColumns: jest.fn(),
  answerDefinitionCheck: jest.fn(), answerTurnover: jest.fn(), getBlockers: jest.fn(), runStage: jest.fn(), answerCorrection: jest.fn(),
  chooseGroup: jest.fn(), undoGroupChoice: jest.fn(), keepUndated: jest.fn(),
}));
jest.mock("react-router-dom", () => ({ Link: ({ to, children }) => <a href={to}>{children}</a>, useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const claim = (id, extra = {}) => ({ id, status: "approved", claim_type: "revenue", value: 200000, currency: "EUR", target_date: null, period_text: null,
  snippet: `ARR ${id}`, label_from: null, flags: [], sources: [{ file: "deck.pptx", page: 3 }], ...extra });
const IDS = ["u1", "u2", "u3", "u4", "u5", "u6"];
const UNDATED = { key: "k1", page: "page 3", n: 6 };

const mount = async ({ candidates = [], attention = [], register = {} }) => {
  api.getDatasets.mockResolvedValue([]);
  api.getDecks.mockResolvedValue({ decks: [], candidates, attention });
  api.getClaimRegister.mockResolvedValue({ register: [], groups: [], reviews: [], conflicts: [], ...register });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<NeedsAttention auditId="a1" onChanged={jest.fn()} />); });
  await act(async () => { await Promise.resolve(); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
};
const q = (host, id) => host.querySelector(`[data-testid="${id}"]`);
const all = (host, id) => [...host.querySelectorAll(`[data-testid="${id}"]`)];
const six = () => ({ candidates: IDS.map((id) => claim(id)), attention: IDS.map((id) => ({ id, in_top5: false, set: "Period not read – set it in the claim row", undated: UNDATED })) });

test("six undated figures of one page are one card with a date field and Keep undated", async () => {
  const { host, done } = await mount(six());
  try {
    expect(all(host, "attention-card").length).toBe(1);
    expect(q(host, "attention-count").textContent).toBe("1 question needs a word from you");
    expect(q(host, "attention-undated-title").textContent).toBe("Set the period for 6 figures on page 3");
    expect(q(host, "attention-undated-date")).not.toBeNull();
    expect(q(host, "attention-undated-keep").textContent).toBe("Keep undated");
  } finally { await done(); }
});

test("Keep undated sends every figure of the card once", async () => {
  api.keepUndated.mockResolvedValue({ kept: 6 });
  const { host, done } = await mount(six());
  try {
    await act(async () => { q(host, "attention-undated-keep").click(); });
    expect(api.keepUndated).toHaveBeenCalledWith("a1", IDS);
  } finally { await done(); }
});

test("one date typed once is applied to every figure of the card", async () => {
  api.updateCandidate.mockResolvedValue({});
  const { host, done } = await mount(six());
  try {
    const input = q(host, "attention-undated-date");
    expect(q(host, "attention-undated-set").disabled).toBe(true);
    await act(async () => { input.focus(); });
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      set.call(input, "2024-06-30");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    await act(async () => { q(host, "attention-undated-set").click(); });
    expect(api.updateCandidate.mock.calls.map((c) => [c[1], c[2]])).toEqual(IDS.map((id) => [id, { target_date: "2024-06-30" }]));
  } finally { await done(); }
});

test("a lone undated figure keeps its own card", async () => {
  const { host, done } = await mount({ candidates: [claim("u1")], attention: [{ id: "u1", in_top5: false, set: "Period not read – set it in the claim row" }] });
  try {
    expect(q(host, "attention-undated")).toBeNull();
    expect(q(host, "attention-set")).not.toBeNull();
  } finally { await done(); }
});

test("a slice larger than the company total is one card with its figures and nothing to choose", async () => {
  const card = { id: "s1", kind: "segment_size", state: "open", metric: "Revenue", period: "FY2024", reason: "Segment larger than the company total; check what this figure is",
    candidates: [{ claim_id: "c2", claim_ids: ["c2"], identity: "i2", value: 1300000, currency: "EUR", unit: null, period: "FY2024", source: "deck.pptx slide 4", hint: "Direct", chosen: false },
      { claim_id: "c3", claim_ids: ["c3"], identity: "i3", value: 200000, currency: "EUR", unit: null, period: "FY2024", source: "deck.pptx slide 4", hint: "Partners", chosen: false }] };
  const { host, done } = await mount({ register: { reviews: [card] } });
  try {
    expect(all(host, "attention-card").length).toBe(1);
    expect(q(host, "attention-group-reason").textContent).toBe("Segment larger than the company total; check what this figure is");
    const rows = all(host, "attention-group-candidate");
    expect(rows.map((r) => r.textContent.includes("Direct") || r.textContent.includes("Partners"))).toEqual([true, true]);
    expect(all(host, "attention-group-choose").length).toBe(0);
    expect(all(host, "attention-group-exclude").length).toBe(0);
    expect(q(host, "attention-group-open-claims")).not.toBeNull();
  } finally { await done(); }
});

test("a figure whose only label was a title reads (no label read), never the title", () => {
  expect(labelLine({ label_from: null, flags: ["no label read"] })).toBe("Label from: (no label read)");
  expect(labelLine({ label_from: null, flags: ["no label read"], page_segment: "EMEA" })).toBe("Label from: (no label read) · EMEA");
  expect(labelLine({ label_from: "Paying users", flags: [] })).toBe("Label from: Paying users");
  expect(labelLine({ label_from: null, flags: [] })).toBeNull();
});
