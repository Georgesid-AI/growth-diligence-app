// docs/specs/claim-groups.md section 5: an ambiguous total is a card with its candidates, sources and reconciliation hint; nothing is selected for
// the analyst; a figure passed over stays a claim and can be excluded with a reason; a conflict stays listed after a choice, with Undo.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import NeedsAttention from "./NeedsAttention";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getDatasets: jest.fn(), getDecks: jest.fn(), getClaimRegister: jest.fn(), updateCandidate: jest.fn(), decideColumns: jest.fn(),
  answerDefinitionCheck: jest.fn(), answerTurnover: jest.fn(), getBlockers: jest.fn(), runStage: jest.fn(), answerCorrection: jest.fn(),
  chooseGroup: jest.fn(), undoGroupChoice: jest.fn(),
}));
jest.mock("react-router-dom", () => ({ Link: ({ to, children }) => <a href={to}>{children}</a>, useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const candidate = (claimId, value, extra = {}) => ({ claim_id: claimId, claim_ids: [claimId], identity: `id-${claimId}`, value, currency: "EUR", unit: null,
  period: "FY2024", source: "testco_board.pptx slide 3", hint: null, chosen: false, ...extra });
const TOTAL_OPEN = { id: "r1", kind: "total", state: "open", metric: "Revenue", period: "FY2024", reason: "Several annual figures are stated for the same period. Choose the one to use.",
  candidates: [candidate("a1", 1000000, { hint: "quarters sum to €1,000,000, within ±2%" }), candidate("a2", 1250000, { source: "testco_board.pptx slide 8" })] };

const mount = async (register) => {
  api.getDatasets.mockResolvedValue([]);
  api.getDecks.mockResolvedValue({ decks: [], candidates: [], attention: [] });
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

test("an ambiguous total is one card with each candidate, its source and the hint, and no candidate is selected", async () => {
  const { host, done } = await mount({ reviews: [TOTAL_OPEN], conflicts: [TOTAL_OPEN] });
  try {
    expect(all(host, "attention-card").length).toBe(1);
    expect(q(host, "attention-count").textContent).toBe("1 question needs a word from you");
    expect(q(host, "attention-group-title").textContent).toBe("Which annual figure should the audit use? Revenue, FY2024");
    const rows = all(host, "attention-group-candidate");
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain("1,000,000");
    expect(rows[0].textContent).toContain("testco_board.pptx slide 3");
    expect(rows[0].textContent).toContain("quarters sum to €1,000,000, within ±2%");
    expect(rows[1].textContent).toContain("testco_board.pptx slide 8");
    expect(all(host, "attention-group-chosen").length).toBe(0);
    expect(all(host, "attention-group-choose").length).toBe(2);
    expect(q(host, "attention-group-undo")).toBeNull();
    expect(q(host, "attention-group-kept").textContent).toContain("stay as claims");
  } finally { await done(); }
});

test("a click chooses that candidate by its identity and the cards are read again", async () => {
  api.chooseGroup.mockResolvedValue({});
  const { host, done } = await mount({ reviews: [TOTAL_OPEN], conflicts: [TOTAL_OPEN] });
  try {
    await act(async () => { all(host, "attention-group-choose")[1].click(); });
    expect(api.chooseGroup).toHaveBeenCalledWith("a1", "r1", "id-a2");
    expect(api.getClaimRegister.mock.calls.length).toBeGreaterThan(1);
  } finally { await done(); }
});

test("a figure can be excluded only once a reason is picked, with the existing control and the same closed words", async () => {
  api.updateCandidate.mockResolvedValue({});
  const { host, done } = await mount({ reviews: [TOTAL_OPEN], conflicts: [TOTAL_OPEN] });
  try {
    const exclude = all(host, "attention-group-exclude")[1];
    expect(exclude.disabled).toBe(true);
    const select = all(host, "attention-group-reason-select")[1];
    await act(async () => { select.value = "deck_context"; select.dispatchEvent(new Event("change", { bubbles: true })); });
    expect(all(host, "attention-group-exclude")[1].disabled).toBe(false);
    await act(async () => { all(host, "attention-group-exclude")[1].click(); });
    expect(api.updateCandidate).toHaveBeenCalledWith("a1", "a2", { status: "rejected", reason: "deck_context" });
  } finally { await done(); }
});

test("a figure of a table row has no exclude here: excluding it would drop its other periods", async () => {
  const table = { ...TOTAL_OPEN, candidates: [candidate("a1#2", 1000000), candidate("a2", 1250000)] };
  const { host, done } = await mount({ reviews: [table], conflicts: [table] });
  try {
    expect(all(host, "attention-group-exclude").length).toBe(1);
  } finally { await done(); }
});

test("a conflict that stays after a choice is still a card, names the chosen figure and offers Undo", async () => {
  api.undoGroupChoice.mockResolvedValue({});
  const chosen = { ...TOTAL_OPEN, state: "chosen", candidates: [candidate("a1", 1000000, { chosen: true }), candidate("a2", 1250000)] };
  const { host, done } = await mount({ reviews: [], conflicts: [chosen] });
  try {
    expect(all(host, "attention-card").length).toBe(1);
    expect(q(host, "attention-group-chosen").textContent).toBe("Chosen by you");
    expect(all(host, "attention-group-choose").length).toBe(1);
    await act(async () => { q(host, "attention-group-undo").click(); });
    expect(api.undoGroupChoice).toHaveBeenCalledWith("a1", "r1");
  } finally { await done(); }
});

test("a conflict of more than four candidates shows one line and a button to the claims list, and offers no candidate", async () => {
  const many = { ...TOTAL_OPEN, candidates: [1, 2, 3, 4, 5].map((i) => candidate(`a${i}`, 1000000 + i * 100000, { source: `testco_board.pptx slide ${i}` })) };
  const section = document.createElement("section");
  section.id = "claim-register";
  section.scrollIntoView = jest.fn();
  document.body.appendChild(section);
  const { host, done } = await mount({ reviews: [many], conflicts: [many] });
  try {
    expect(all(host, "attention-group-candidate").length).toBe(0);
    expect(all(host, "attention-group-choose").length).toBe(0);
    expect(q(host, "attention-group-too-many").textContent).toBe("5 annual figures are stated for this period; too many to choose from here. Review them in the claims list.");
    await act(async () => { q(host, "attention-group-open-claims").click(); });
    expect(section.scrollIntoView).toHaveBeenCalled();
    expect(api.chooseGroup).not.toHaveBeenCalled();
  } finally { await done(); section.remove(); }
});

test("a conflict of four candidates still lists each of them", async () => {
  const four = { ...TOTAL_OPEN, candidates: [1, 2, 3, 4].map((i) => candidate(`a${i}`, 1000000 + i * 100000)) };
  const { host, done } = await mount({ reviews: [four], conflicts: [four] });
  try {
    expect(all(host, "attention-group-candidate").length).toBe(4);
    expect(q(host, "attention-group-too-many")).toBeNull();
  } finally { await done(); }
});
