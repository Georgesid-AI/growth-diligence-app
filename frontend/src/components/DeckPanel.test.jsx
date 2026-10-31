import React, { act } from "react";
import { createRoot } from "react-dom/client";

import DeckPanel from "./DeckPanel";
import * as api from "@/lib/api";
import { COLUMNS, PROMPT_MISSING_LINE, REVIEW_INTRO } from "@/lib/deckClaims";

jest.mock("@/lib/api", () => ({ getDecks: jest.fn(), removeDeck: jest.fn(), updateCandidate: jest.fn(), uploadDeck: jest.fn(), addClaim: jest.fn(),
  answerTurnover: jest.fn(), answerCorrection: jest.fn() }));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn(), message: jest.fn() } }));
const { toast } = require("sonner");

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
// The server sends them ascending by page across the decks within each group.
// ... and by the group of the claim type first: revenue (1), market size (5), Other (9: a figure with no type).
const CLAIMS = [
  claim("c", "d1", 2, { group: 1 }),
  claim("d", "d2", 3, { group: 1 }),
  claim("b", "d2", 1, { claim_type: "market", label_from: "MARKET SIZE", group: 5, confidence: { level: "High", failed: [], text: "High" } }),
  claim("a", "d1", 1, { claim_type: "unknown", target_date: null, group: 9, confidence: { level: "Low", failed: ["no date", "no heading"], text: "Low – no date, no heading" } }),
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

const rows = () => [...document.body.querySelectorAll("[data-testid='deck-candidates'] tbody tr[data-testid^='candidate-row']")];
const open = async (group) => act(async () => { q(`claim-group-toggle-${group}`).click(); });
const text = (tr) => tr.textContent;

test("the table has an Extraction confidence column between Period and the claim, in every row", async () => {
  await act(async () => { q("deck-tab-all").click(); });
  await open(9);
  const heads = [...document.body.querySelectorAll("[data-testid='deck-candidates'] thead th")].map((th) => th.textContent);
  expect(heads).toEqual(["Type", "Value", "Period", "Claim in the deck", "Source", "Extraction confidence", "Status", "Action"]);
  const cells = rows().map((tr) => tr.querySelector("[data-testid='candidate-confidence-text']").textContent);
  expect(cells.sort()).toEqual(["High", "Low", "Medium", "Medium"].sort());
});

test("All lists the claims in the server's order, group by group; a deck tab keeps that order", async () => {
  await act(async () => { q("deck-tab-all").click(); });
  await open(9);
  expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["c", "d", "b", "a"]);
  await act(async () => { q("deck-tab-d1").click(); });
  expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["c", "a"]);
});

test("Other starts collapsed under its count; the other groups are open", async () => {
  await act(async () => { q("deck-tab-all").click(); });
  expect(["claim-group-toggle-1", "claim-group-toggle-5", "claim-group-toggle-9"].map((id) => q(id).textContent)).toEqual([
    "Revenue, ARR, MRR and bookings (2)", "Market size (1)", "1 other figure"]);
  expect(q("claim-group-2")).toBeNull();
  expect(q("claim-group-toggle-9").getAttribute("aria-expanded")).toBe("false");
  expect(q("claim-group-toggle-1").getAttribute("aria-expanded")).toBe("true");
  expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["c", "d", "b"]);
  await open(9);
  expect(rows().length).toBe(4);
  await open(9);
  expect(rows().length).toBe(3);
  await open(1);
  expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["b"]);
});

test("Use of funds and Pricing start collapsed, listed after Market size and before Other; a pricing claim keeps its type in the editor", async () => {
  await reload([
    claim("m", "d1", 1, { group: 5, claim_type: "market" }),
    claim("p", "d1", 2, { group: 10, claim_type: "pricing", value: 49, unit: null, currency: "EUR" }),
    claim("u", "d1", 3, { group: 8, claim_type: "use_of_funds", value: 40, unit: "%", currency: null }),
    claim("o", "d1", 4, { group: 9, claim_type: "other" }),
  ]);
  const toggles = [...document.querySelectorAll("[data-testid^='claim-group-toggle-']")];
  expect(toggles.map((n) => [n.getAttribute("data-testid").replace("claim-group-toggle-", ""), n.getAttribute("aria-expanded")])).toEqual([
    ["5", "true"], ["10", "false"], ["8", "false"], ["9", "false"]]);
  expect(toggles.map((n) => n.textContent)).toEqual(["Market size (1)", "Pricing (1)", "Use of funds (1)", "1 other figure"]);
  await open(10);
  await act(async () => { q("candidate-row-p").querySelector("[data-testid='candidate-edit']").click(); });
  const select = document.body.querySelector("[data-testid='edit-claim-type']");
  expect(select.selectedOptions[0].textContent).toBe("Pricing");
});

test("the Period column reads FY2025 for the year 2025 and no date when the deck gives no period", async () => {
  await act(async () => { q("deck-tab-all").click(); });
  await open(9);
  expect(rows().map((tr) => tr.querySelectorAll("td")[2].textContent)).toEqual(["FY2025", "FY2025", "FY2025", "no date"]);
});

test("a figure in another currency shows both figures, and a direction with no figure says so", async () => {
  api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [
    claim("f", "d1", 1, { group: 1, currency: "GBP", value: 150000, fx: { rate: 1.14, date: "2026-06-30", currency: "EUR" } }),
    claim("g", "d1", 2, { group: 1, currency: "USD", value: 1000, fx: { rate: null, date: "2026-06-30", currency: "EUR" } }),
    claim("h", "d1", 3, { group: 2, claim_type: "ebitda", value: null, currency: null, claim_direction: "positive", target_date: "2024-Q2",
      confidence: { level: "Medium", failed: ["no figure"], text: "Medium – no figure" } }),
  ] });
  await act(async () => { root.unmount(); });
  host.remove();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<DeckPanel auditId="a1" />); });
  await act(async () => { q("deck-tab-all").click(); });
  expect(rows().map((tr) => tr.querySelectorAll("td")[1].textContent)).toEqual([
    "150,000 GBP (171,000 EUR)", "1,000 USD (USD→EUR rate missing – enter it in FX settings at the top of the page)", "positive (no figure)"]);
  // the rate and its date are on hover, not in the row
  expect(rows()[0].querySelector("[data-testid='candidate-value']").getAttribute("title")).toBe("Rate used: 1 GBP = 1.14 EUR on 30 Jun 2026");
  expect(rows()[0].textContent).not.toMatch(/1\.14|30 Jun 2026/);
  expect(rows()[2].querySelectorAll("td")[2].textContent).toBe("Q2 2024");
  expect(rows()[2].querySelector("[data-testid='candidate-confidence-text']").textContent).toBe("Medium");
});

test("a figure with no type reads Other, has no Keep, and saves only once a claim type is chosen; Market size is a choice", async () => {
  await act(async () => { q("deck-tab-d1").click(); });
  await open(9);
  const first = rows()[1];
  expect(first.querySelector("[data-testid='candidate-type']").textContent).toBe("Other");
  expect(first.querySelector("[data-testid='candidate-keep']")).toBeNull();
  expect(rows()[0].querySelector("[data-testid='candidate-keep']").disabled).toBe(false);          // a claim that waits for an answer can be kept
  await act(async () => { first.querySelector("[data-testid='candidate-edit']").click(); });
  const select = document.body.querySelector("[data-testid='edit-claim-type']");
  expect(select.selectedOptions[0].textContent).toBe("Other");
  const options = [...select.options].map((o) => o.textContent);
  expect(options).toContain("Market size");
  expect(options).not.toContain("Market");
  expect(document.body.querySelector("[data-testid='edit-save']").disabled).toBe(true);
});

test("Label from shows the one heading the server found", async () => {
  await act(async () => { q("deck-tab-d2").click(); });
  expect(q("candidate-label").textContent).toBe("Label from: MARKET SIZE");
});

test("the segment follows the label and share of sits in the reasons column; neither shows when the page printed none", async () => {
  api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [
    claim("s", "d2", 1, { group: 1, label_from: "Revenue", page_segment: "EMEA", page_share_of: "Total revenue" }),
    claim("t", "d2", 2, { group: 1, page_segment: "APAC" }),
    claim("u", "d2", 3, { group: 1 }),
  ] });
  await act(async () => { root.unmount(); });
  root = createRoot(host);
  await act(async () => { root.render(<DeckPanel auditId="a1" />); });
  await act(async () => { q("deck-tab-d2").click(); });
  const [withBoth, segmentOnly, neither] = rows();
  expect(withBoth.querySelector("[data-testid='candidate-label']").textContent).toBe("Label from: Revenue · EMEA");
  expect(withBoth.querySelector("[data-testid='candidate-share-of']").textContent).toBe("Share of: Total revenue");
  expect(withBoth.querySelector("[data-testid='candidate-confidence']").contains(withBoth.querySelector("[data-testid='candidate-share-of']"))).toBe(true);
  expect(segmentOnly.querySelector("[data-testid='candidate-label']").textContent).toBe("Segment: APAC");
  expect(neither.querySelector("[data-testid='candidate-label']")).toBeNull();
  expect(neither.querySelector("[data-testid='candidate-share-of']")).toBeNull();
});

describe("the AI reading poll", () => {
  const notFound = Object.assign(new Error("404"), { response: { status: 404 } });
  const reading = { decks: [{ ...DECKS[0], ai_status: "reading" }], candidates: [] };
  const unhandled = jest.fn();
  beforeEach(() => { process.on("unhandledRejection", unhandled); unhandled.mockClear(); });
  afterEach(() => { process.off("unhandledRejection", unhandled); jest.useRealTimers(); });

  const remount = async () => {
    await act(async () => { root.unmount(); });
    host.remove();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    jest.useFakeTimers();
    await act(async () => { root.render(<DeckPanel auditId="a1" />); });
  };

  test("an audit deleted mid-poll: the 404 is caught, the poll stops, nothing is shown or thrown", async () => {
    api.getDecks.mockReset();
    api.getDecks.mockResolvedValueOnce(reading).mockRejectedValue(notFound);
    await remount();
    expect(api.getDecks).toHaveBeenCalledTimes(1);
    await act(async () => { jest.advanceTimersByTime(5000); });
    expect(api.getDecks).toHaveBeenCalledTimes(2);
    await act(async () => { jest.advanceTimersByTime(60000); });
    expect(api.getDecks).toHaveBeenCalledTimes(2);          // stopped
    expect(require("sonner").toast.error).not.toHaveBeenCalled();
    expect(unhandled).not.toHaveBeenCalled();
  });

  test("the claims of a deck whose stored status flips to read are listed by the very poll that sees the flip (George, 2026-10-23)", async () => {
    const read = { decks: [{ ...DECKS[0], ai_status: "read", pages_read: 2, pages_rejected: 0, figure_pages: 2 }], candidates: [claim("n", "d2", 1, { group: 1 })] };
    api.getDecks.mockReset();
    api.getDecks.mockResolvedValueOnce(reading).mockResolvedValue(read);
    await remount();
    expect(document.body.querySelectorAll("[data-testid^='candidate-row']")).toHaveLength(0);
    await act(async () => { jest.advanceTimersByTime(5000); });
    expect(api.getDecks).toHaveBeenCalledTimes(2);
    expect(document.body.querySelectorAll("[data-testid^='candidate-row']")).toHaveLength(1);
    await act(async () => { jest.advanceTimersByTime(60000); });
    expect(api.getDecks).toHaveBeenCalledTimes(2);            // read: the poll stops
  });

  test("leaving the page mid-poll: no further request and no state set after unmount", async () => {
    api.getDecks.mockReset();
    api.getDecks.mockResolvedValue(reading);
    await remount();
    await act(async () => { root.unmount(); });
    await act(async () => { jest.advanceTimersByTime(60000); });
    expect(api.getDecks).toHaveBeenCalledTimes(1);
    expect(unhandled).not.toHaveBeenCalled();
    root = createRoot(host);                                  // afterEach unmounts
  });
});


// --- the task of 2026-10-09: items 4, 6b, 7, 8 and the period of item 5 ---------------------------------------------------
const reload = async (candidates) => {
  await act(async () => { root.unmount(); });
  host.remove();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  api.getDecks.mockResolvedValue({ decks: DECKS, candidates });
  await act(async () => { root.render(<DeckPanel auditId="a1" />); });
  await act(async () => { q("deck-tab-all").click(); });
};
const fig = (value, slide, over = {}) => ({ value, value_high: null, currency: null, unit: "customers", date: "2024", claim_type: "customers",
  source: { file: "older.pptx", slide, kind: "text" }, ...over });

test("the Deck inconsistency tag has its explanation on hover and in the opened row, built from the two figures", async () => {
  await reload([claim("c", "d1", 2, { group: 3, claim_type: "customers", inconsistent_dates: ["2024"],
    inconsistencies: [{ this: fig(5, 1), other: fig(6, 4) }] })]);
  const tag = q("candidate-inconsistency");
  const sentence = "The deck gives different figures for this metric: 5 customers at older.pptx · slide 1 and 6 customers at older.pptx · slide 4.";
  expect(tag.getAttribute("title")).toBe(sentence);
  expect(q("candidate-inconsistency-text")).toBeNull();
  await act(async () => { tag.click(); });
  expect(q("candidate-inconsistency-text").textContent).toBe(sentence);
});

test("a turnover figure and a revenue figure name their deck labels, each at its own page", async () => {
  const money = (label, value, page) => ({ value, value_high: null, currency: "GBP", unit: null, date: "2023", claim_type: "revenue", label,
    source: { file: "d.pdf", page, kind: "text" } });
  await reload([claim("c", "d1", 2, { group: 3, claim_type: "revenue", inconsistent_dates: ["2023"],
    inconsistencies: [{ this: money("Turnover", 550508, 17), other: money("Revenue", 150000, 19) }] })]);
  expect(q("candidate-inconsistency").getAttribute("title")).toBe(
    "The deck gives different figures for this metric: Turnover 550,508 GBP at d.pdf · page 17 and Revenue 150,000 GBP at d.pdf · page 19.");
});

test("a use-of-funds text figure and its chart figure show text and chart with the dropped category, and no Contradicted", async () => {
  const share = (label, value) => ({ value, value_high: null, currency: null, unit: "%", date: null, claim_type: "use_of_funds", label,
    source: { file: "d.pdf", page: 22, kind: "text" } });
  await reload([claim("c", "d1", 22, { group: 8, claim_type: "use_of_funds", value: 40, unit: "%", inconsistent_dates: [],
    inconsistencies: [{ this: share("text", 40), other: share("chart", 42), note: "chart excludes Operational Expenses & Talent Acquisition, rescaled" }] })]);
  await open(8);                                   // Use of funds starts collapsed (George, 2026-10-23)
  expect(q("candidate-inconsistency").getAttribute("title")).toBe(
    "The deck gives different figures for this metric: text 40% at d.pdf · page 22 and chart 42% at d.pdf · page 22; chart excludes Operational Expenses & Talent Acquisition, rescaled.");
  expect(document.body.textContent).not.toMatch(/Contradicted/);
});

test("a percentage on a mixed slide is Other and says so: mixed slide – check", async () => {
  await reload([claim("c", "d1", 22, { group: 9, claim_type: "unknown", value: 60, unit: "%", mixed_slide: true }),
    claim("d", "d1", 22, { group: 9, claim_type: "unknown", value: 40, unit: "%" })]);
  await open(9);
  expect(document.querySelectorAll("[data-testid=candidate-mixed-slide]").length).toBe(1);
  expect(q("candidate-mixed-slide").textContent).toBe("mixed slide – check");
});

test("the edit form of a Use of funds claim shows Use of funds, and correcting the value keeps the type", async () => {
  await reload([claim("c", "d1", 22, { group: 8, claim_type: "use_of_funds", value: 40, unit: "%", inconsistent_dates: [] })]);
  await open(8);
  api.updateCandidate.mockResolvedValue({ id: "c", status: "edited" });
  await act(async () => { q("candidate-row-c").querySelector("[data-testid='candidate-edit']").click(); });
  const select = q("edit-claim-type");
  expect(select.value).toBe("use_of_funds");
  expect(select.selectedOptions[0].textContent).toBe("Use of funds");
  await act(async () => { q("edit-save").click(); });
  expect(api.updateCandidate.mock.calls.at(-1)[2].claim_type).toBe("use_of_funds");
});

test("after the analyst edits a claim its confidence reads Analyst-edited, not a score (issue #146)", async () => {
  const parsed = claim("c", "d1", 22, { group: 8, claim_type: "use_of_funds", value: 40, unit: "%", currency: null,
    confidence: { level: "Low", failed: ["no unit", "not corroborated"], text: "Low – no unit, not corroborated" } });
  await reload([parsed]);
  await open(8);
  expect(q("candidate-row-c").querySelector("[data-testid='candidate-confidence-text']").textContent).toBe("Low");
  api.updateCandidate.mockResolvedValue({ id: "c", status: "edited" });
  api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [{ ...parsed, status: "edited", currency: "EUR",
    confidence: { level: null, failed: [], text: "Analyst-edited" } }] });
  await act(async () => { q("candidate-row-c").querySelector("[data-testid='candidate-edit']").click(); });
  await act(async () => { q("edit-save").click(); });
  const shown = q("candidate-row-c").querySelector("[data-testid='candidate-confidence']");
  expect(shown.querySelector("[data-testid='candidate-confidence-text']").textContent).toBe("Analyst-edited");
  expect(shown.querySelector("[data-testid='candidate-confidence-text']").className).toBe("text-slate-500");
});

describe("a turnover claim asks Revenue or Volume in its own row (05-zero2hero.pdf, claim-matching.md section 11 point 8)", () => {
  // As GET /decks sends p17's three bars, all to review: the revenue file starts in 2023, p19's pending table gives
  // Revenue 130,550 (FY2022) and 150,000 (FY2023).
  const view = (id, period, over = {}) => [{ claim_id: id, period, turnover_state: "ask", turnover_note: "Revenue or volume? Confirm below",
    turnover_set_by: "python", turnover_reason: null, turnover_suggested: null, deck_revenue_note: null, implied_take_rate: null,
    implied_take_rate_source: null, file_note: null, ...over }];
  const bar = (id, value, year, turnover) => claim(id, "d2", 17, { group: 1, value, currency: "GBP", target_date: year,
    snippet: value.toLocaleString("en-US"), label_from: "Turnover(£/year)", turnover });
  const ZERO2HERO = [
    bar("t21", 278085, "2021", view("t21", "2021", { file_note: "Revenue file does not cover this period" })),
    bar("t22", 415107, "2022", view("t22", "2022", { turnover_suggested: "volume", file_note: "Revenue file does not cover this period",
      deck_revenue_note: "Deck revenue for the same period: 130,550 GBP (page 19); implied take rate 31%, derived, not verified" })),
    bar("t23", 550508, "2023", view("t23", "2023", { turnover_suggested: "volume",
      deck_revenue_note: "Deck revenue for the same period: 150,000 GBP (page 19); implied take rate 27%, derived, not verified" })),
  ];
  const cell = (id, testid) => q(`candidate-row-${id}`).querySelector(`[data-testid='${testid}']`);

  test("the metric cell reads Turnover – confirm: with Revenue and Volume, never Revenue, and the row is Unverified", async () => {
    await reload(ZERO2HERO);
    for (const id of ["t21", "t22", "t23"]) {
      expect(cell(id, "turnover-confirm").textContent).toBe("Turnover – confirm:");
      expect(cell(id, "candidate-type").textContent).not.toMatch(/^Revenue/);
      expect(cell(id, "register-turnover-revenue").textContent).toBe("Revenue");
      expect(cell(id, "register-turnover-volume").textContent).toBe("Volume");
      expect(cell(id, "candidate-turnover-label").textContent).toBe("Unverified");
      expect(q(`candidate-row-${id}`).textContent).toContain("Needs your attention");
    }
  });

  test("deck revenue below turnover pre-selects Volume and shows the deck revenue and the implied take rate", async () => {
    await reload(ZERO2HERO);
    expect(cell("t23", "register-turnover-volume").getAttribute("aria-pressed")).toBe("true");
    expect(cell("t23", "register-turnover-revenue").getAttribute("aria-pressed")).toBeNull();
    expect(cell("t23", "register-deck-revenue").textContent).toBe(
      "Deck revenue for the same period: 150,000 GBP (page 19); implied take rate 27%, derived, not verified");
    expect(cell("t21", "register-turnover-volume").getAttribute("aria-pressed")).toBeNull();
  });

  test("a period the revenue file does not cover says so in the row", async () => {
    await reload(ZERO2HERO);
    expect(cell("t21", "turnover-file-note").textContent).toBe("Revenue file does not cover this period");
    expect(cell("t22", "turnover-file-note").textContent).toBe("Revenue file does not cover this period");
    expect(cell("t23", "turnover-file-note")).toBeNull();
  });

  test("Volume, with a reason, is saved for the pending claim and the list is read again", async () => {
    await reload(ZERO2HERO);
    api.answerTurnover.mockResolvedValue({ register: [] });
    const select = cell("t23", "register-turnover-reason");
    expect(cell("t23", "register-turnover-volume").disabled).toBe(true);
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, "deck_says_processed_volume");
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const reads = api.getDecks.mock.calls.length;
    await act(async () => { cell("t23", "register-turnover-volume").click(); });
    expect(api.answerTurnover).toHaveBeenCalledWith("a1", "t23", { as: "volume", reason: "deck_says_processed_volume" });
    expect(api.getDecks.mock.calls.length).toBe(reads + 1);
  });

  test("once the analyst confirms, the row shows the answer and is no longer Unverified", async () => {
    await reload([bar("t23", 550508, "2023", view("t23", "2023", { turnover_state: "volume", turnover_note: "Transaction volume",
      turnover_set_by: "analyst", turnover_reason: "deck_says_processed_volume" }))]);
    expect(cell("t23", "turnover-confirm")).toBeNull();
    expect(cell("t23", "register-turnover-note").textContent).toBe("Transaction volume · set by you");
    expect(cell("t23", "candidate-turnover-label")).toBeNull();
  });

  test("a value of a turnover table row names its period", async () => {
    await reload([claim("r", "d2", 19, { group: 1, currency: "GBP", by_period: [{ value: 1, target_date: "2022" }, { value: 2, target_date: "2023" }],
      turnover: [...view("r#1", "Y/E 22"), ...view("r#2", "Y/E 23")] })]);
    expect([...q("candidate-row-r").querySelectorAll("[data-testid='turnover-confirm']")].map((n) => n.textContent)).toEqual([
      "Y/E 22 · Turnover – confirm:", "Y/E 23 · Turnover – confirm:"]);
  });

  describe("the edit form opens on the stored answer (task of 2026-10-09, items 8 and 9)", () => {
    const answered = (kind, reason = "deck_says_processed_volume", over = {}) => bar("t23", 550508, "2023", view("t23", "2023", {
      turnover_state: kind, turnover_note: kind === "volume" ? "Transaction volume" : "Gross revenue (turnover)", turnover_set_by: "analyst",
      turnover_reason: reason, ...over }));
    const openEdit = async (id) => { await act(async () => { cell(id, "candidate-edit").click(); }); };
    const setSelect = async (el, value) => act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(el, value);
      el.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const options = () => [...q("edit-claim-type").querySelectorAll("option")].map((o) => o.textContent);

    test("a Transaction volume claim opens with Transaction volume selected, not the first item, and saves unchanged without a new answer", async () => {
      await reload([answered("volume")]);
      api.updateCandidate.mockResolvedValue({ id: "t23", status: "edited" });
      await openEdit("t23");
      const select = q("edit-claim-type");
      expect(select.value).toBe("transaction_volume");
      expect(select.selectedOptions[0].textContent).toBe("Transaction volume");
      expect(options()[0]).not.toBe("Transaction volume");
      expect(options()).toContain("Revenue");
      expect(q("edit-turnover-reason")).toBeNull();                      // nothing changed: no reason asked
      expect(q("edit-save").disabled).toBe(false);
      expect(q("edit-value").value).toBe("550508");                      // every other field is prefilled from the stored claim
      expect(q("edit-target-date").value).toBe("2023");
      await act(async () => { q("edit-save").click(); });
      expect(api.updateCandidate).toHaveBeenCalledTimes(1);
      expect(api.updateCandidate.mock.calls[0][2].claim_type).toBe("revenue");
      expect(api.answerTurnover).not.toHaveBeenCalled();                 // the answer is untouched
      await openEdit("t23");
      expect(q("edit-claim-type").value).toBe("transaction_volume");     // still Transaction volume
    });

    test("a claim answered Revenue opens on Revenue; a claim not yet answered opens on 'Turnover – choose', never on Revenue", async () => {
      await reload([answered("revenue", "deck_says_gross_revenue")]);
      await openEdit("t23");
      expect(q("edit-claim-type").value).toBe("revenue");
      await reload(ZERO2HERO);
      await openEdit("t21");
      expect(q("edit-claim-type").value).toBe("turnover_ask");
      expect(q("edit-claim-type").selectedOptions[0].textContent).toBe("Turnover – choose");
      expect(q("edit-save").disabled).toBe(false);                       // a figure can still be corrected without answering
    });

    test("changing a Transaction volume claim to Revenue asks for a reason; Save and approve waits for it, then records it as the button does", async () => {
      await reload([answered("volume")]);
      api.updateCandidate.mockResolvedValue({ id: "t23", status: "edited" });
      api.answerTurnover.mockResolvedValue({ register: [] });
      await openEdit("t23");
      await setSelect(q("edit-claim-type"), "revenue");
      expect(q("edit-turnover-reason")).not.toBeNull();
      expect([...q("edit-turnover-reason").querySelectorAll("option")].map((o) => o.textContent)).toEqual(
        ["Reason…", "Deck says gross revenue", "Deck says processed volume", "Revenue file confirms"]);
      expect(q("edit-save").disabled).toBe(true);
      await setSelect(q("edit-turnover-reason"), "deck_says_processed_volume");       // contradicts Revenue: the server refuses it
      expect(q("edit-save").disabled).toBe(true);
      await setSelect(q("edit-turnover-reason"), "deck_says_gross_revenue");
      expect(q("edit-save").disabled).toBe(false);
      await act(async () => { q("edit-save").click(); });
      expect(api.answerTurnover).toHaveBeenCalledWith("a1", "t23", { as: "revenue", reason: "deck_says_gross_revenue" });
    });

    test("changing a Revenue claim to Transaction volume uses the Volume path", async () => {
      await reload([answered("revenue", "deck_says_gross_revenue")]);
      api.updateCandidate.mockResolvedValue({ id: "t23", status: "edited" });
      api.answerTurnover.mockResolvedValue({ register: [] });
      await openEdit("t23");
      await setSelect(q("edit-claim-type"), "transaction_volume");
      expect(q("edit-save").disabled).toBe(true);
      await setSelect(q("edit-turnover-reason"), "deck_says_processed_volume");
      await act(async () => { q("edit-save").click(); });
      expect(api.answerTurnover).toHaveBeenCalledWith("a1", "t23", { as: "volume", reason: "deck_says_processed_volume" });
    });

    test("the edit form offers the same three reasons, and hides 'Revenue file confirms' when no revenue-file period exists", async () => {
      await reload([answered("volume", "deck_says_processed_volume", { file_note: "Revenue file does not cover this period" })]);
      await openEdit("t23");
      await setSelect(q("edit-claim-type"), "revenue");
      expect([...q("edit-turnover-reason").querySelectorAll("option")].map((o) => o.textContent)).toEqual(
        ["Reason…", "Deck says gross revenue", "Deck says processed volume"]);
    });

    test("a claim that is not a turnover claim has no Transaction volume entry and asks for no reason", async () => {
      await reload([claim("c", "d1", 2, { group: 1 })]);
      await openEdit("c");
      expect(options()).not.toContain("Transaction volume");
      expect(q("edit-claim-type").value).toBe("revenue");
      await setSelect(q("edit-claim-type"), "customers");
      expect(q("edit-turnover-reason")).toBeNull();
    });
  });
});

test("Needs your attention is a status label, not a control: plain text with no border, chip or button around it (George, 2026-10-09)", async () => {
  await reload([claim("c", "d1", 2, { group: 1 }), claim("e", "d1", 3, { group: 1, status: "approved" })]);
  for (const [id, label] of [["c", "Needs your attention"], ["e", "In the register"]]) {
    const status = q(`candidate-row-${id}`).querySelector("[data-testid='candidate-status']");
    expect(status.textContent).toBe(label);
    expect(status.tagName).toBe("SPAN");
    expect(status.className.split(/\s+/).filter((c) => /^(border|rounded|px-|py-|bg-)/.test(c))).toEqual([]);
    expect(status.closest("button, a, [role='button']")).toBeNull();
  }
});

test("the upload help, the Extraction confidence hover are shown word for word", async () => {
  await reload([claim("c", "d1", 2, { group: 1 })]);
  expect(q("deck-upload-help").textContent).toMatch(/^Board deck or growth plan: the company's board decks, investor updates.* Up to 8 documents per audit\./);
  expect(q("candidate-confidence-text").title).toBe("How confidently the app extracted and linked the figure to its source. This does not verify the company’s claim.");
});

test("a tag never shows without its explanation", async () => {
  await reload([claim("c", "d1", 2, { group: 1, inconsistent_dates: ["2024"], inconsistencies: [] })]);
  expect(q("candidate-inconsistency")).toBeNull();
});

test("a claim in another currency with no rate names the pair and links to the FX settings", async () => {
  await reload([claim("u", "d1", 2, { group: 5, claim_type: "market", currency: "USD", value: 5e9,
    fx: { rate: null, date: "2026-06-30", currency: "EUR" } })]);
  expect(rows()[0].textContent).toContain("(USD→EUR rate missing – enter it in FX settings at the top of the page)");
  const link = q("fx-settings-link");
  expect(link.getAttribute("href")).toBe("#fx-settings");
  expect(link.textContent).toBe("FX settings");
});

test("a claim with its rate shows no FX link", async () => {
  await reload([claim("u", "d1", 2, { group: 1, currency: "USD", fx: { rate: 0.9, date: "2026-06-30", currency: "EUR" } })]);
  expect(q("fx-settings-link")).toBeNull();
});

test("the unit list offers count, with what it counts", async () => {
  await act(async () => { q("deck-tab-all").click(); });
  await act(async () => { q("candidate-row-c").querySelector("[data-testid='candidate-edit']").click(); });
  const option = [...document.body.querySelectorAll("#claim-units option")].find((o) => o.value === "count");
  expect(option).toBeDefined();
  expect(option.getAttribute("label")).toBe("customers, headcount, deals");
});

test("a period read from the label's brackets shows beside the date, or alone when the deck gives no year", async () => {
  await reload([claim("p", "d1", 2, { group: 1, target_date: null, period_basis: "per year", currency: "GBP" }),
    claim("q", "d1", 3, { group: 1, target_date: "2024", period_basis: "per month" })]);
  expect(rows().map((tr) => tr.querySelectorAll("td")[2].textContent)).toEqual(["per year", "FY2024 · per month"]);
  await reload([claim("p", "d1", 2, { group: 1, target_date: "2023", period_basis: "per year", currency: "GBP" })]);
  expect(rows().map((tr) => tr.querySelectorAll("td")[2].textContent)).toEqual(["FY2023"]);
});

describe("an approved claim that moves to another category (item 8)", () => {
  const moved = (over = {}) => [claim("c", "d1", 2, { group: 3, claim_type: "customers", status: "edited", ...over })];
  const edit = async (type) => {
    await act(async () => { q("candidate-row-c").querySelector("[data-testid='candidate-edit']").click(); });
    const select = q("edit-claim-type");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, type);
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => { q("edit-save").click(); });
    await act(async () => { await Promise.resolve(); });
  };

  test("a toast names the new category with Undo for 4 seconds, and the row is highlighted for the same time", async () => {
    jest.useFakeTimers();
    try {
      await reload([claim("c", "d1", 2, { group: 1, status: "approved" })]);
      api.updateCandidate.mockResolvedValue({ id: "c", status: "edited", claim_type: "customers" });
      api.getDecks.mockResolvedValue({ decks: DECKS, candidates: moved() });
      await edit("customers");
      const [message, options] = require("sonner").toast.message.mock.calls[0];
      expect(message).toBe("Claim moved to Customers, users, usage, retention and sales");
      expect(options.duration).toBe(4000);
      expect(options.action.label).toBe("Undo");
      expect(q("candidate-row-c").getAttribute("data-highlight")).toBe("true");
      await act(async () => { jest.advanceTimersByTime(3900); });
      expect(q("candidate-row-c").getAttribute("data-highlight")).toBe("true");
      await act(async () => { jest.advanceTimersByTime(200); });
      expect(q("candidate-row-c").getAttribute("data-highlight")).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  test("Undo puts the claim back in its category and shows no second notice", async () => {
    await reload([claim("c", "d1", 2, { group: 1, status: "approved" })]);
    api.updateCandidate.mockResolvedValue({ id: "c", status: "edited", claim_type: "customers" });
    api.getDecks.mockResolvedValue({ decks: DECKS, candidates: moved() });
    await edit("customers");
    const { action } = require("sonner").toast.message.mock.calls[0][1];
    api.updateCandidate.mockClear();
    api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [claim("c", "d1", 2, { group: 1, status: "edited" })] });
    await act(async () => { action.onClick(); });
    await act(async () => { await Promise.resolve(); });
    expect(api.updateCandidate).toHaveBeenCalledWith("a1", "c", { claim_type: "revenue" });
    expect(require("sonner").toast.message).toHaveBeenCalledTimes(1);
    expect(q("candidate-row-c").getAttribute("data-highlight")).toBeNull();
  });

  test("a change inside the same category, or a claim not yet approved, shows no toast", async () => {
    await reload([claim("c", "d1", 2, { group: 1, status: "approved" })]);
    api.updateCandidate.mockResolvedValue({ id: "c", status: "edited", claim_type: "revenue_growth" });
    api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [claim("c", "d1", 2, { group: 1, claim_type: "revenue_growth", status: "edited" })] });
    await edit("revenue_growth");
    expect(require("sonner").toast.message).not.toHaveBeenCalled();
  });
});

test("a rate saved on the page reloads the claims, so the converted figures replace the missing-rate note with the tab kept", async () => {
  await act(async () => { q("deck-tab-d1").click(); });
  api.getDecks.mockClear();
  api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [claim("u", "d1", 2, { group: 5, claim_type: "market", currency: "USD", value: 5e9,
    fx: { rate: 0.9, date: "2026-06-30", currency: "EUR" } })] });
  await act(async () => { root.render(<DeckPanel auditId="a1" reloadKey={1} />); });
  expect(api.getDecks).toHaveBeenCalledTimes(1);
  expect(rows()[0].textContent).toContain("5,000,000,000 USD (4,500,000,000 EUR)");
  expect(rows()[0].textContent).not.toMatch(/rate missing|0\.9|30 Jun 2026/);
});

test("a market-size row: the value, the converted value, FY2028 from the deck, and no rate date anywhere on the row", async () => {
  api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [
    claim("m", "d1", 5, { group: 5, claim_type: "market", currency: "USD", value: 2.5e9, target_date: "2028", period_text: "FY2028",
      fx: { rate: 0.9, date: "2026-06-30", currency: "EUR" } }),
    claim("n", "d1", 6, { group: 5, claim_type: "market", currency: "USD", value: 1e9, target_date: null,
      fx: { rate: 0.9, date: "2026-06-30", currency: "EUR" } }),
  ] });
  await act(async () => { root.unmount(); });
  host.remove();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<DeckPanel auditId="a1" />); });
  await act(async () => { q("deck-tab-all").click(); });
  const [dated, undated] = rows();
  const cells = (tr) => [...tr.querySelectorAll("td")].slice(1, 3).map((td) => td.textContent);
  expect(cells(dated)).toEqual(["2,500,000,000 USD (2,250,000,000 EUR)", "FY2028"]);
  expect(cells(undated)).toEqual(["1,000,000,000 USD (900,000,000 EUR)", "no date"]);
  for (const tr of [dated, undated]) expect(tr.textContent).not.toMatch(/30 Jun 2026|0\.9|Jun/);
  expect(dated.querySelector("[data-testid='candidate-value']").getAttribute("title")).toBe("Rate used: 1 USD = 0.9 EUR on 30 Jun 2026");
});

describe("a claim changed to a count type (Users), and a refused save", () => {
  const toastError = () => require("sonner").toast.error;
  let started = false;
  beforeEach(() => { started = false; });
  const choose = async (type) => {
    if (!started) {
      started = true;
      await act(async () => { q("deck-tab-all").click(); });
      await act(async () => { q("candidate-row-c").querySelector("[data-testid='candidate-edit']").click(); });
    }
    const select = q("edit-claim-type");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, type);
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
  };

  test("choosing a count type clears the currency and sets the unit to count; the save sends exactly that", async () => {
    await choose("revenue");                                           // revenue stays: currency EUR, no unit
    expect([q("edit-currency").value, q("edit-unit").value]).toEqual(["EUR", ""]);
    await choose("users");
    expect([q("edit-currency").value, q("edit-unit").value]).toEqual(["", "count"]);
    api.updateCandidate.mockResolvedValue({ id: "c", status: "edited" });
    await act(async () => { q("edit-save").click(); });
    expect(api.updateCandidate).toHaveBeenCalledWith("a1", "c", expect.objectContaining({ claim_type: "users", unit: "count", currency: null }));
  });

  test("a type that is not a count leaves the currency and the unit alone; a count type already chosen keeps the noun typed", async () => {
    await choose("costs");
    expect([q("edit-currency").value, q("edit-unit").value]).toEqual(["EUR", ""]);
    await choose("customers");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(q("edit-unit"), "paying users");
      q("edit-unit").dispatchEvent(new Event("input", { bubbles: true }));
    });
    await choose("users");                                             // count to count: nothing is reset
    expect(q("edit-unit").value).toBe("paying users");
  });

  test("a refused save says which field was rejected and why, never only that it could not be saved", async () => {
    api.updateCandidate.mockRejectedValue({ response: { status: 422, statusText: "Unprocessable Entity",
      data: { detail: [{ loc: ["body", "unit"], msg: "String should have at least 1 character", type: "string_too_short" }] } } });
    await choose("users");
    await act(async () => { q("edit-save").click(); });
    expect(toastError()).toHaveBeenLastCalledWith("HTTP 422 Unprocessable Entity — unit: String should have at least 1 character");
    api.updateCandidate.mockRejectedValue({ response: { status: 400, statusText: "", data: { detail: "claim_type: choose a claim type for this item before approving it" } } });
    await act(async () => { q("edit-save").click(); });
    expect(toastError()).toHaveBeenLastCalledWith("HTTP 400 — claim_type: choose a claim type for this item before approving it");
    for (const [message] of toastError().mock.calls) expect(message).not.toMatch(/^Could not save$/i);
  });
});

describe("Add claim", () => {
  const change = async (el, value) => {
    const proto = el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    await act(async () => {
      Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
      el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
    });
  };
  const openRow = async () => act(async () => { q("add-claim").click(); });

  test("the claims text is the agreed wording, with the Keep, Edit and Reject lines below it", () => {
    const lines = [...q("claims-instructions").querySelectorAll("h4, p")].map((n) => n.textContent);
    expect(lines[0]).toBe("Claims found in the uploaded documents");
    expect(lines[1]).toBe("These figures were read from the uploaded documents and tested against the data automatically. Errors are possible: check only the claims that look incorrect or implausible against their source slides, or that wait for your answer.");
    expect(lines.slice(2).map((l) => l.split(":")[0])).toEqual(["✓ Keep", "✎ Edit", "✕ Reject"]);
    expect(q("deck-scope-message").textContent).toContain("If a number you need sits in a picture, use Add claim and cite the page, or upload the source spreadsheet.");
  });

  test("one row opens with the metric list of the other rows and a dropdown of the uploaded decks", async () => {
    await openRow();
    const typeOptions = [...q("add-claim-type").options].map((o) => o.textContent);
    expect(typeOptions).toContain("Revenue");
    expect(typeOptions).toContain("Market size");
    expect(typeOptions).not.toContain("Other");
    expect([...q("add-claim-deck").options].map((o) => o.textContent).sort()).toEqual(["newer.pdf", "older.pptx"]);
    for (const id of ["add-claim-value", "add-claim-value-high", "add-claim-unit", "add-claim-currency", "add-claim-date", "add-claim-page"]) expect(q(id)).not.toBeNull();
  });

  test("the metric has no default and lists only metrics in the claim's unit; Save stays off until value, metric and page are filled", async () => {
    await openRow();
    expect(q("add-claim-metric").value).toBe("");
    expect([...q("add-claim-metric").options].map((o) => o.value)).not.toContain("none");
    await change(q("add-claim-currency"), "EUR");
    expect([...q("add-claim-metric").options].map((o) => o.value)).toEqual(expect.arrayContaining(["ARR", "MRR", "Revenue"]));
    expect([...q("add-claim-metric").options].map((o) => o.value)).not.toContain("Win rate");
    expect(q("add-claim-save").disabled).toBe(true);
    await change(q("add-claim-value"), "5");
    await change(q("add-claim-page"), "3");
    expect(q("add-claim-save").disabled).toBe(true);          // no metric yet
    await change(q("add-claim-metric"), "ARR");
    expect(q("add-claim-save").disabled).toBe(false);
    await change(q("add-claim-currency"), "");               // ARR no longer fits: the choice is dropped, not sent
    expect(q("add-claim-metric").value).toBe("");
    expect(q("add-claim-save").disabled).toBe(true);
    await change(q("add-claim-currency"), "EUR");
    await change(q("add-claim-metric"), "ARR");
    await change(q("add-claim-page"), "");
    expect(q("add-claim-save").disabled).toBe(true);
  });

  test("Save sends the claim with its deck and page, closes the row and reloads the list on that deck", async () => {
    api.addClaim.mockResolvedValue({ id: "n1", deck_id: "d1" });
    await openRow();
    await change(q("add-claim-deck"), "d1");
    await change(q("add-claim-value"), "3600000");
    await change(q("add-claim-currency"), "usd");
    await change(q("add-claim-metric"), "ARR");
    await change(q("add-claim-date"), "2025");
    await change(q("add-claim-page"), "4");
    await act(async () => { q("add-claim-save").click(); });
    expect(api.addClaim).toHaveBeenCalledWith("a1", {
      claim_type: "revenue", metric: "ARR", deck_id: "d1", page: 4, value: 3600000, value_high: null, unit: null, currency: "USD", target_date: "2025" });
    expect(q("add-claim-row")).toBeNull();
    expect(api.getDecks).toHaveBeenCalledTimes(2);
  });

  test("Acquisition channels is in the Type list of Add claim, asks for the platform and no metric, and sends a count with no currency", async () => {
    api.addClaim.mockResolvedValue({ id: "n2", deck_id: "d1" });
    await openRow();
    expect([...q("add-claim-type").options].map((o) => o.textContent)).toContain("Acquisition channels");
    await change(q("add-claim-type"), "acquisition_channels");
    expect(q("add-claim-metric")).toBeNull();
    expect(q("add-claim-unit").value).toBe("count");
    await change(q("add-claim-deck"), "d1");
    await change(q("add-claim-value"), "30000");
    await change(q("add-claim-page"), "17");
    expect(q("add-claim-save").disabled).toBe(true);                       // the platform is required
    await change(q("add-claim-platform"), " Telegram ");
    await act(async () => { q("add-claim-save").click(); });
    expect(api.addClaim).toHaveBeenCalledWith("a1", {
      claim_type: "acquisition_channels", label: "Telegram", unit: "count", deck_id: "d1", page: 17, value: 30000, value_high: null, currency: null, target_date: null });
  });

  test("an analyst-entered claim shows its tag and the confidence Analyst-entered", async () => {
    api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [
      claim("n1", "d1", 4, { group: 1, status: "approved", origin: "analyst", snippet: "Added by analyst", confidence: { level: null, failed: [], text: "Analyst-entered" } })] });
    await act(async () => { q("deck-tab-all").click(); });
    await act(async () => { root.render(<DeckPanel auditId="a1" reloadKey={1} />); });
    const tr = rows()[0];
    expect(tr.querySelector("[data-testid='candidate-confidence-text']").textContent).toBe("Analyst-entered");
    expect(tr.textContent).toContain("Added by analyst");
  });
});


describe("the category sections (docs/specs/chat-upload.md section 17; the claim approval is gone, docs/design/simplified-flow.md)", () => {
  const pending = (id, group, over = {}) => claim(id, "d1", 1, { group, ...over });
  const LIST = [
    pending("r1", 1), pending("r2", 1), pending("r3", 1, { status: "approved" }),
    pending("a1", 7, { claim_type: "acquisition_channels", value: 30000, unit: "count", currency: null, channel: "Telegram", target_date: null }),
    pending("f1", 8, { claim_type: "use_of_funds", value: 40, unit: "%", currency: null, target_date: null }),
    claim("n1", "d2", 2, { group: 1 }),
  ];

  test("no section has an Approve all, at its top or at its bottom, and the API has no call for it", async () => {
    await reload(LIST.concat([pending("o1", 9, { claim_type: "other" })]));
    await open(8);
    await open(9);
    expect(document.body.querySelector("[data-testid^='approve-all-']")).toBeNull();
    expect(document.body.querySelector("[data-testid^='claim-group-end-']")).toBeNull();
  });

  test("a claim that waits for an answer has Keep, Edit and Reject; a claim in the register has Edit and Reject only", async () => {
    await reload([pending("w", 1), pending("e", 1, { status: "approved" })]);
    const wait = rows().find((tr) => text(tr).includes("snippet-w")), done = rows().find((tr) => text(tr).includes("snippet-e"));
    expect(wait.querySelector("[data-testid='candidate-keep']")).not.toBeNull();
    expect(done.querySelector("[data-testid='candidate-keep']")).toBeNull();
    for (const row of [wait, done]) {
      expect(row.querySelector("[data-testid='candidate-edit']")).not.toBeNull();
      expect(row.querySelector("[data-testid='candidate-reject']")).not.toBeNull();
      expect(row.querySelector("[data-testid='candidate-approve']")).toBeNull();
    }
    api.updateCandidate.mockResolvedValue({ id: "w", status: "approved" });
    await act(async () => { wait.querySelector("[data-testid='candidate-keep']").click(); });
    expect(api.updateCandidate).toHaveBeenCalledWith("a1", "w", { status: "approved" });
  });

  test("Acquisition channels and Use of funds are sections of their own, in that order, directly above Other", async () => {
    await reload(LIST.concat([pending("o1", 9, { claim_type: "other" })]));
    const titles = [...document.body.querySelectorAll("[data-testid^='claim-group-toggle-']")].map((b) => b.textContent.replace(/\s*\(\d+\)$/, ""));
    expect(titles.slice(-3)).toEqual(["Acquisition channels", "Use of funds", "1 other figure"]);
    expect(q("claim-group-7").textContent).toContain("(1)");
    expect(q("candidate-row-a1").querySelector("[data-testid='candidate-type']").textContent).toContain("Acquisition channels");
    expect(q("candidate-row-a1").querySelector("[data-testid='candidate-channel']").textContent).toBe("Telegram");
    expect(q("candidate-row-a1").querySelector("[data-testid='candidate-value']").textContent).toBe("30,000 count");
  });

  test("the edit form's Type list holds Acquisition channels, and choosing it makes the figure a count with no currency", async () => {
    await reload([pending("r1", 1)]);
    await act(async () => { q("candidate-row-r1").querySelector("[data-testid='candidate-edit']").click(); });
    const select = q("edit-claim-type");
    expect([...select.options].map((o) => o.textContent)).toContain("Acquisition channels");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, "acquisition_channels");
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(q("edit-unit").value).toBe("count");
    expect(q("edit-currency").value).toBe("");
  });

  test("a light divider and a gap of about twice the old one sit between sections, and not above the first", async () => {
    await reload(LIST);
    expect(q("claim-group-gap-1")).toBeNull();
    for (const group of [7, 8]) {
      const gap = q(`claim-group-gap-${group}`);
      expect(gap.getAttribute("aria-hidden")).toBe("true");
      expect(gap.querySelector("td").className).toContain("py-3.5");                // 2 x 14 px of the old 8 + 6 px
      expect(gap.querySelector("td > div").className).toContain("border-t");
      expect(gap.nextElementSibling).toBe(q(`claim-group-${group}`));
    }
  });
});

describe("upload box", () => {
  const pick = async (name) => {
    const input = q("deck-upload-input");
    const file = new File(["x"], name);
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
  };

  test("the box holds the agreed text word for word and the picker, inside the deck section", () => {
    const box = q("deck-upload-box");
    expect(q("deck-panel").contains(box)).toBe(true);
    expect(box.contains(q("deck-upload-input"))).toBe(true);
    const lines = [...q("deck-scope-message").querySelectorAll("p, li")].map((n) => (n.tagName === "LI" ? "- " : "") + n.textContent);
    expect(lines.join("\n")).toBe(
      "Upload PowerPoint, Word and text-based PDF files.\n" +
      "The app cannot read:\n" +
      "- Scanned PDFs, images or charts saved as pictures. There is no text in them to read, only pixels.\n" +
      "- Keynote files or Google Slides links. Please export them as PowerPoint or PDF first.\n" +
      "If a number you need sits in a picture, use Add claim and cite the page, or upload the source spreadsheet.");
    expect(q("deck-upload-input").getAttribute("accept")).toBe(".pptx,.pdf,.docx");
  });

  test("a file of another type is refused with the accepted types named, and nothing is uploaded", async () => {
    await pick("slides.key");
    expect(api.uploadDeck).not.toHaveBeenCalled();
    expect(lineTexts()).toEqual(["slides.key: refused – Only .pptx, .docx and .pdf files can be uploaded here."]);
  });

  const lineTexts = () => [...document.querySelectorAll('[data-testid="deck-upload-line"]')].map((n) => n.textContent);

  const drop = async (...names) => {
    const box = q("deck-upload-box");
    const files = names.map((n) => new File(["x"], n));
    const over = new Event("dragover", { bubbles: true, cancelable: true });
    await act(async () => { box.dispatchEvent(over); });
    const ev = new Event("drop", { bubbles: true, cancelable: true });
    ev.dataTransfer = { files };
    await act(async () => { box.dispatchEvent(ev); });
    return { over, ev };
  };

  test("the box is a drop zone: a dropped file of an accepted type goes to the existing upload, and the browser does not open it", async () => {
    api.uploadDeck.mockResolvedValue({ file: "plan.pptx", pages: 3, page_unit: "slide", candidates: 2, deck_id: "d1" });
    const { over, ev } = await drop("plan.pptx");
    expect(over.defaultPrevented && ev.defaultPrevented).toBe(true);
    expect(api.uploadDeck).toHaveBeenCalledWith("a1", expect.objectContaining({ name: "plan.pptx" }));
    expect(lineTexts().every((t) => t.includes(": done"))).toBe(true);
  });

  test("a dropped file of another type is refused with the same message, and nothing is uploaded", async () => {
    await drop("slides.key");
    expect(api.uploadDeck).not.toHaveBeenCalled();
    expect(lineTexts()).toEqual(["slides.key: refused – Only .pptx, .docx and .pdf files can be uploaded here."]);
  });

  test("several files dropped at once are uploaded one after another with a status line each, and a refused type stops no other", async () => {
    let release;
    api.uploadDeck.mockImplementation((id, file) => (file.name === "a.pptx"
      ? new Promise((resolve) => { release = () => resolve({ file: "a.pptx", pages: 3, page_unit: "slide", candidates: 2, deck_id: "d1" }); })
      : Promise.resolve({ file: file.name, pages: 5, page_unit: "page", candidates: 4, deck_id: "d2" })));
    await drop("a.pptx", "slides.key", "b.pdf");
    expect(api.uploadDeck).toHaveBeenCalledTimes(1);          // one after another: b.pdf waits for a.pptx
    expect(lineTexts()).toEqual(["a.pptx: uploading…", "slides.key: refused – Only .pptx, .docx and .pdf files can be uploaded here.",
      "b.pdf: waiting"]);
    await act(async () => { release(); });
    expect(api.uploadDeck.mock.calls.map(([, f]) => f.name)).toEqual(["a.pptx", "b.pdf"]);
    expect(lineTexts()).toEqual(["a.pptx: done · 3 slides parsed · 2 candidate claims", "slides.key: refused – Only .pptx, .docx and .pdf files can be uploaded here.",
      "b.pdf: done · 5 pages parsed · 4 candidate claims"]);
  });

  test("a deck read by the page read says pages parsed, pages with figures and the AI read status, never pages read", async () => {
    api.uploadDeck.mockResolvedValueOnce({ file: "a.pdf", pages: 24, page_unit: "page", figure_pages: 9, candidates: 0, ai_status: "waiting", deck_id: "d1" })
      .mockResolvedValueOnce({ file: "b.pdf", pages: 3, page_unit: "page", figure_pages: 2, candidates: 0, ai_status: "reading", deck_id: "d2" });
    await drop("a.pdf", "b.pdf");
    expect(lineTexts()).toEqual(["a.pdf: done · 24 pages parsed · 9 with figures · AI read: waiting for revenue file",
      "b.pdf: done · 3 pages parsed · 2 with figures · AI read: queued"]);
    expect(lineTexts().join(" ")).not.toMatch(/pages read/);
  });

  test("the upload row reads the same stored status as the panel: queued at upload, done after the poll shows the read finished", async () => {
    const stored = { deck_id: "d3", file: "c.pdf", pages: 3, page_unit: "page", figure_pages: 2, uploaded_at: "2026-10-03" };
    api.uploadDeck.mockResolvedValueOnce({ file: "c.pdf", pages: 3, page_unit: "page", figure_pages: 2, candidates: 0, ai_status: "reading", deck_id: "d3" });
    api.getDecks.mockResolvedValue({ decks: [...DECKS, { ...stored, ai_status: "reading" }], candidates: CLAIMS });
    jest.useFakeTimers();
    try {
      await drop("c.pdf");
      expect(lineTexts()).toEqual(["c.pdf: done · 3 pages parsed · 2 with figures · AI read: queued"]);
      api.getDecks.mockResolvedValue({ decks: [...DECKS, { ...stored, ai_status: "read", pages_read: 2, pages_rejected: 0 }], candidates: CLAIMS });
      await act(async () => { jest.advanceTimersByTime(5000); });
      expect(lineTexts()).toEqual(["c.pdf: done · 3 pages parsed · 2 with figures · AI read: done, 2 read, 0 rejected"]);
    } finally { jest.useRealTimers(); }
  });

  test("a failed upload shows its line and the next file still goes", async () => {
    api.uploadDeck.mockRejectedValueOnce({ response: { data: { detail: "Could not read the deck" } } })
      .mockResolvedValueOnce({ file: "b.pdf", pages: 5, page_unit: "page", candidates: 4, deck_id: "d2" });
    await drop("a.pptx", "b.pdf");
    expect(lineTexts()).toEqual(["a.pptx: failed – Could not read the deck", "b.pdf: done · 5 pages parsed · 4 candidate claims"]);
  });

  test("an accepted type goes to the existing upload", async () => {
    api.uploadDeck.mockResolvedValue({ file: "plan.docx", pages: 3, page_unit: "page", candidates: 2, deck_id: "d1" });
    await pick("plan.docx");
    expect(api.uploadDeck).toHaveBeenCalledWith("a1", expect.objectContaining({ name: "plan.docx" }));
    expect(lineTexts().every((t) => t.includes(": done"))).toBe(true);
  });
});

test("the deck-list shows the AI badge only when it says something the confidence cell does not: AI suggestion, not matched; Matched to page repeats it (George, 2026-10-27)", async () => {
  api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [
    claim("m", "d1", 1, { group: 1, origin: "ai", ai_label: "Verified" }),
    claim("n", "d1", 2, { group: 1, origin: "ai", ai_label: "AI suggestion, not verified" }),
  ] });
  await act(async () => { root.render(<DeckPanel auditId="a2" />); });
  await act(async () => { q("deck-tab-all").click(); });
  const badges = [...document.body.querySelectorAll("[data-testid='candidate-ai-label']")].map((b) => b.textContent);
  expect(badges).toEqual(["AI suggestion, not matched"]);
});

test("a period Python read from 'in 2021' shows its note under the period in the deck list, as the register does; a row with no note or no period shows none (PR 152 follow-up)", async () => {
  const note = "period read as Dec 2021 from 'in 2021'";
  api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [
    claim("n1", "d1", 1, { group: 1, target_date: "2021-12", period_read_note: note }),
    claim("n2", "d1", 2, { group: 1, period_read_note: null }),
    claim("n3", "d1", 3, { group: 1, target_date: null, period_read_note: note }),
  ] });
  await act(async () => { root.unmount(); });
  root = createRoot(host);
  await act(async () => { root.render(<DeckPanel auditId="a1" />); });
  await act(async () => { q("deck-tab-all").click(); });
  const notes = [...document.body.querySelectorAll("[data-testid='candidate-period-note']")].map((n) => n.textContent);
  expect(notes).toEqual([note]);
  const row = rows().find((tr) => text(tr).includes("snippet-n1"));
  expect(row.querySelector("[data-testid='candidate-period-note']")).not.toBeNull();
});

describe("the Review view (George, 2026-10-22, docs/design/ai-reads-rules-check.md)", () => {
  const flagged = claim("f", "d2", 4, { group: 1, flags: ["currency assumed", "scenario label not on page"], ai_label: "AI suggestion, not matched", basis: "scenario", scenario: "best" });
  test("a flagged claim is not in the main list; Review lists it with its flags; the counts follow the view", async () => {
    await reload([...CLAIMS, flagged]);
    expect(q("claims-view-claims").textContent).toBe("Claims (4)");
    expect(q("claims-view-review").textContent).toBe("Review (1)");
    await open(9);
    expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["c", "d", "b", "a"]);
    expect(q("candidate-flags")).toBeNull();
    expect(q("review-intro")).toBeNull();
    await act(async () => { q("claims-view-review").click(); });
    expect(q("claims-view-review").getAttribute("aria-selected")).toBe("true");
    expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["f"]);
    expect([...q("candidate-flags").children].map((d) => d.textContent)).toEqual([
      "The app assigned a currency without an explicit currency label for this figure. Check the assumption.",
      "The scenario (best, realistic, worst) is not written near the figure"]);
    expect(q("candidate-ai-label").textContent).toBe("AI suggestion, not matched");
    expect(q("review-intro").textContent).toBe(REVIEW_INTRO);
    expect(q("candidate-keep")).not.toBeNull();                          // a flagged claim waits for an answer: keep, edit or reject
    expect(document.body.querySelector("[data-testid^='approve-all-']")).toBeNull();     // there is no Approve all
    await act(async () => { q("claims-view-claims").click(); });
    expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["c", "d", "b", "a"]);     // Other stays opened
  });
  test("a deck tab keeps the view: the Review count is that deck's", async () => {
    await reload([...CLAIMS, flagged]);
    await act(async () => { q("deck-tab-d1").click(); });
    expect(q("claims-view-review").textContent).toBe("Review (0)");
    await act(async () => { q("deck-tab-d2").click(); });
    expect(q("claims-view-review").textContent).toBe("Review (1)");
  });
});

describe("review of PR #164 (George, 2026-10-23)", () => {
  const best = claim("s", "d1", 6, { group: 6, flags: [], basis: "scenario", scenario: "best", snippet: "snippet-s" });
  const real = claim("r", "d1", 6, { group: 1, flags: [], basis: "scenario", scenario: "realistic", snippet: "snippet-r" });

  test("H2: best and worst cases are a Scenarios section above Other; a realistic case stays a plan claim and names its case", async () => {
    await reload([...CLAIMS, best, real]);
    const order = [...document.body.querySelectorAll("[data-testid^='claim-group-toggle-']")].map((b) => b.textContent);
    expect(order).toEqual(["Revenue, ARR, MRR and bookings (3)", "Market size (1)", "Scenarios (1)", "1 other figure"]);
    const row = rows().find((tr) => text(tr).includes("snippet-s"));
    expect(row.querySelector("[data-testid='candidate-scenario']").textContent).toBe("Best case");
    const plan = rows().find((tr) => text(tr).includes("snippet-r"));
    expect(plan.querySelector("[data-testid='candidate-scenario']").textContent).toBe("Realistic case");
    expect(rows().find((tr) => text(tr).includes("snippet-c")).querySelector("[data-testid='candidate-scenario']")).toBeNull();
  });

  test("M6: a deck whose prompt is missing says so in its run log", async () => {
    api.getDecks.mockResolvedValue({ decks: [{ ...DECKS[0], ai_status: "prompt_missing", ai_message: PROMPT_MISSING_LINE }], candidates: [] });
    await act(async () => { root.unmount(); });
    host.remove();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => { root.render(<DeckPanel auditId="a1" />); });
    expect(q("deck-run-log").textContent).toBe(PROMPT_MISSING_LINE);
  });
});


describe("corrections and Undo on a rejected row (George, 2026-10-26)", () => {
  const applied = { field: "period", reason: "year under bar differs", original: "2023", corrected: "2022", state: "applied" };

  test("a corrected row reads 'Corrected: period 2023 → 2022' with Undo, and Undo asks the server to undo that correction", async () => {
    api.answerCorrection.mockResolvedValue({});
    await reload([claim("k", "d1", 1, { group: 1, status: "approved", corrections: [applied], flags: [] })]);
    const row = q("candidate-row-k");
    expect(row.querySelector("[data-testid='candidate-correction']").textContent).toContain("Corrected: period 2023 → 2022");
    await act(async () => { row.querySelector("[data-testid='candidate-correction-undo']").click(); });
    expect(api.answerCorrection).toHaveBeenCalledWith("a1", "k", { index: 0, action: "undo" });
  });

  test("an undone correction shows no note", async () => {
    await reload([claim("k", "d1", 1, { group: 1, status: "approved", corrections: [{ ...applied, state: "undone" }] })]);
    expect(q("candidate-row-k").querySelector("[data-testid='candidate-correction']")).toBeNull();
  });

  test("a section with nothing waiting for a yes has no Accept all", async () => {
    await reload([claim("ok", "d1", 2, { group: 1, status: "approved" })]);
    expect(q("claim-group-accept-all-top-1")).toBeNull();
    expect(q("claim-group-accept-all-bottom-1")).toBeNull();
  });
  test("a rejected row shows Undo, which restores the previous status; other rows have none", async () => {
    api.updateCandidate.mockResolvedValue({});
    await reload([claim("r", "d1", 1, { group: 1, status: "rejected" }), claim("p", "d1", 2, { group: 1, status: "pending" })]);
    expect(q("candidate-row-p").querySelector("[data-testid='candidate-undo-reject']")).toBeNull();
    await act(async () => { q("candidate-row-r").querySelector("[data-testid='candidate-undo-reject']").click(); });
    expect(api.updateCandidate).toHaveBeenCalledWith("a1", "r", { undo: true });
  });
});

describe("column headings and confidence reasons", () => {
  const heads = () => [...document.body.querySelectorAll("[data-testid='deck-candidates'] thead th")];
  test("hover and tap open the heading's pop-up; the confidence cell carries its reason line", async () => {
    await act(async () => { q("deck-tab-all").click(); });
    await open(9);
    const th = heads().find((h) => h.textContent.startsWith("Source"));
    expect(th.querySelector("[role='tooltip']")).toBeNull();
    await act(async () => { th.querySelector("button").click(); });
    expect(th.querySelector("[role='tooltip']").textContent).toMatch(/slide|page/i);
    await act(async () => { th.querySelector("button").click(); });
    expect(th.querySelector("[role='tooltip']")).toBeNull();
    await act(async () => { th.querySelector("button").dispatchEvent(new MouseEvent("mouseover", { bubbles: true })); });
    expect(th.querySelector("[role='tooltip']")).not.toBeNull();
    const reason = rows()[0].querySelector("[data-testid='candidate-confidence-reason']");
    expect(reason.textContent.length).toBeGreaterThan(10);
  });
  test("the type cell shows the segment and the part-of line", async () => {
    api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [claim("s", "d1", 1, { group: 1, made_of: { segment: "Platform Subscriptions", part_of: "part of ARR 2025 total" } })] });
    await act(async () => { root.render(<DeckPanel auditId="a2" />); });
    await act(async () => { q("deck-tab-all").click(); });
    const cell = document.body.querySelector("[data-testid='candidate-type']");
    expect(cell.textContent).toContain("Revenue · Platform Subscriptions");
    expect(cell.querySelector("[data-testid='candidate-part-of']").textContent).toBe("part of ARR 2025 total");
  });
});

describe("column widths, pop-ups, the confidence and status cells (George, 2026-10-27)", () => {
  const widths = () => Object.fromEntries([...document.body.querySelectorAll("[data-testid='claims-table'] col")].map((c) => [c.getAttribute("data-testid").slice(4), parseFloat(c.style.width)]));
  const rect = (left, top, width, height) => ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top });

  test("Claim in the deck and Type are narrow, Extraction confidence and Status are the widest, and the columns fill the table", async () => {
    await act(async () => { q("deck-tab-all").click(); });
    const w = widths();
    expect(Object.keys(w)).toEqual(COLUMNS);
    expect(Object.values(w).reduce((a, b) => a + b, 0)).toBe(100);
    expect(w["Extraction confidence"]).toBeGreaterThan(Math.max(w.Type, w["Claim in the deck"], w.Value, w.Period, w.Source));
    expect(w.Status).toBeGreaterThan(Math.max(w.Type, w["Claim in the deck"], w.Value, w.Period, w.Source));
    expect(w.Type).toBeLessThanOrEqual(10);
    expect(w["Claim in the deck"]).toBeLessThanOrEqual(15);
    expect(document.body.querySelector("[data-testid='claims-table']").className).toContain("table-fixed");
  });

  describe("a heading's pop-up stays inside the window", () => {
    let spy;
    beforeEach(() => {
      window.innerWidth = 1440; window.innerHeight = 800;
    });
    afterEach(() => spy.mockRestore());
    const at = (anchors) => {
      spy = jest.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function rectOf() {
        if (this.getAttribute("role") === "tooltip") return rect(0, 0, 288, 120);
        const th = this.closest && this.closest("th");
        return th && anchors[th.getAttribute("data-testid")] ? anchors[th.getAttribute("data-testid")] : rect(0, 0, 0, 0);
      });
    };
    const show = async (name) => { await act(async () => { q(`column-${name}`).querySelector("button").click(); }); return q(`column-tip-${name}`); };
    const within = (tip) => {
      const left = parseFloat(tip.style.left); const top = parseFloat(tip.style.top);
      expect(left).toBeGreaterThanOrEqual(0); expect(top).toBeGreaterThanOrEqual(0);
      expect(left + 288).toBeLessThanOrEqual(window.innerWidth); expect(top + 120).toBeLessThanOrEqual(window.innerHeight);
    };

    test("the rightmost column (Action) flips left, so its right edge sits on the heading's", async () => {
      at({ "column-Action": rect(1380, 300, 50, 16) });
      const tip = await show("Action");
      expect(tip.style.position).toBe("fixed");
      expect(parseFloat(tip.style.left)).toBe(1430 - 288);
      within(tip);
    });
    test("Status flips left near the right edge", async () => {
      at({ "column-Status": rect(1250, 300, 50, 16) });
      const tip = await show("Status");
      expect(parseFloat(tip.style.left)).toBe(1300 - 288);
      within(tip);
    });
    test("a heading with room keeps the pop-up under it, starting at its left edge", async () => {
      at({ "column-Type": rect(100, 300, 40, 16) });
      const tip = await show("Type");
      expect([parseFloat(tip.style.left), parseFloat(tip.style.top)]).toEqual([100, 320]);
    });
    test("near the bottom edge the pop-up flips up", async () => {
      at({ "column-Source": rect(500, 780, 60, 16) });
      const tip = await show("Source");
      expect(parseFloat(tip.style.top)).toBe(780 - 4 - 120);
      within(tip);
    });
  });

  test("the confidence cell shows the level once and the reason under it without the level", async () => {
    await reload([claim("m", "d1", 1, { group: 1, confidence: { level: "Medium", failed: ["period from another cell"], text: "Medium – period from another cell" } })]);
    const cell = q("candidate-row-m").querySelector("[data-testid='candidate-confidence']");
    expect(cell.querySelector("[data-testid='candidate-confidence-text']").textContent).toBe("Medium");
    const reason = cell.querySelector("[data-testid='candidate-confidence-reason']").textContent;
    expect(reason).toMatch(/^The period comes from another cell of the page/);
    expect(reason).not.toMatch(/Medium/);
    expect(cell.textContent.match(/Medium/g)).toHaveLength(1);
  });

  test("the status cell shows the status only: no Matched to page, no flag that the confidence reason already says; a flag it does not say stays", async () => {
    await reload([claim("v", "d1", 1, { group: 1, origin: "ai", ai_label: "Verified", flags: ["period from another cell"],
      confidence: { level: "Medium", failed: ["period from another cell"], text: "Medium – period from another cell" } })]);
    const cell = q("candidate-row-v").querySelector("[data-testid='candidate-status']").parentElement;
    expect(cell.textContent).toBe("Needs your attention");
    expect(cell.querySelector("[data-testid='candidate-ai-label']")).toBeNull();
    expect(cell.querySelector("[data-testid='candidate-flags']")).toBeNull();
    await reload([claim("w", "d1", 1, { group: 1, origin: "ai", ai_label: "AI suggestion, not verified", flags: ["axis tick", "period from another cell"],
      confidence: { level: "Medium", failed: ["period from another cell"], text: "Medium – period from another cell" } })]);
    await act(async () => { q("claims-view-review").click(); });
    const kept = q("candidate-row-w").querySelector("[data-testid='candidate-status']").parentElement;
    expect([...kept.querySelector("[data-testid='candidate-flags']").children].map((d) => d.textContent)).toEqual(["The figure looks like a mark on a chart axis, not a claim"]);
    expect(kept.querySelector("[data-testid='candidate-ai-label']").textContent).toBe("AI suggestion, not matched");
  });

  test("an AI suggestion that the confidence reason already calls unmatched shows no second badge", async () => {
    await reload([claim("u", "d1", 1, { group: 1, origin: "ai", ai_label: "AI suggestion, not verified", flags: [],
      confidence: { level: "Low", failed: ["not matched"], text: "Low – not matched" } })]);
    expect(q("candidate-row-u").querySelector("[data-testid='candidate-ai-label']")).toBeNull();
  });
});

describe("Accept all (George, 2026-10-27)", () => {
  const readings = [{ value: 2500, dot_reading: "2.500 as 2,500" }, { value: 2.5, dot_reading: "2.500 as 2.5" }];
  const choose = { field: "segment", reason: "label mismatch", original: null, state: "choose", options: [{ value: "Platform" }, { value: "Services" }] };
  const mixed = () => [
    claim("a", "d1", 1, { group: 1 }),
    claim("b", "d1", 2, { group: 1 }),
    claim("rd", "d1", 3, { group: 1, readings }),
    claim("lg", "d1", 4, { group: 1, corrections: [choose] }),
    claim("tu", "d1", 5, { group: 1, turnover: [{ claim_id: "tu", turnover_state: "ask", turnover_set_by: "app" }] }),
    claim("pp", "d1", 6, { group: 1, claim_type: "customers", unit: "customers", currency: null }),
    claim("lm", "d1", 7, { group: 1, flags: ["label mismatch"] }),
    claim("ok", "d1", 8, { group: 1, status: "approved" }),
  ];
  const click = async (id) => act(async () => { q(id).click(); });

  test("a button at the top and at the bottom of the category counts the rows that wait for a plain yes and says how many need a choice", async () => {
    await reload(mixed());
    expect(q("claim-group-accept-all-top-1").textContent).toBe("Accept all (2)");
    expect(q("claim-group-accept-all-bottom-1").textContent).toBe("Accept all (2)");
    expect(q("claim-group-need-choice-top-1").textContent).toBe("4 need a choice");
    expect(q("claim-group-need-choice-bottom-1").textContent).toBe("4 need a choice");
    await click("claims-view-review");      // the label-mismatch row is a flagged one: Review lists it, and it asks which label
    expect(q("claim-group-accept-all-top-1")).toBeNull();
    expect(q("claim-group-need-choice-top-1").textContent).toBe("1 needs a choice");
    await click("claims-view-claims");
    expect(q("claim-group-footer-1").compareDocumentPosition(q("candidate-row-ok")) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  });

  test("it accepts exactly the plain rows, from the top or the bottom, and leaves the choice rows and the other categories alone", async () => {
    await reload([...mixed(), claim("m1", "d1", 9, { group: 5, claim_type: "market" })]);
    api.updateCandidate.mockResolvedValue({});
    await click("claim-group-accept-all-bottom-1");
    expect(api.updateCandidate.mock.calls.map((c) => [c[1], c[2]])).toEqual([["a", { status: "approved" }], ["b", { status: "approved" }]]);
    expect(q("claim-group-accept-all-top-5").textContent).toBe("Accept all (1)");
    expect(q("claim-group-need-choice-top-5")).toBeNull();
  });

  test("a category whose rows all need a choice shows the note and no button; a deck whose Sales question is open needs a choice on its Sales rows", async () => {
    api.getDecks.mockResolvedValue({ decks: DECKS, sales_questions: [{ deck_id: "d1", file: "older.pptx", claims: 1 }], candidates: [
      claim("s", "d1", 1, { group: 1, label_from: "Sales" }), claim("s2", "d2", 1, { group: 1, label_from: "Sales" })] });
    await reload([]);
    api.getDecks.mockResolvedValue({ decks: DECKS, sales_questions: [{ deck_id: "d1", file: "older.pptx", claims: 1 }], candidates: [
      claim("s", "d1", 1, { group: 1, label_from: "Sales" }), claim("s2", "d2", 1, { group: 1, label_from: "Sales" })] });
    await act(async () => { root.render(<DeckPanel auditId="a1" key="again" />); });
    await act(async () => { q("deck-tab-all").click(); });
    expect(q("claim-group-accept-all-top-1").textContent).toBe("Accept all (1)");
    expect(q("claim-group-need-choice-top-1").textContent).toBe("1 needs a choice");
  });

  test("each accepted row keeps its own Undo, one Undo accept all stands, and both go at the next action", async () => {
    const plain = [claim("a", "d1", 1, { group: 1 }), claim("b", "d1", 2, { group: 1 }), claim("c", "d1", 3, { group: 1 })];
    await reload(plain);
    api.updateCandidate.mockResolvedValue({});
    api.getDecks.mockResolvedValue({ decks: DECKS, candidates: plain.map((c) => ({ ...c, status: "approved" })) });
    await click("claim-group-accept-all-top-1");
    expect(q("claim-group-undo-accept-all-1").textContent).toBe("Undo accept all");
    expect(document.body.querySelectorAll("[data-testid='claim-group-undo-accept-all-1']")).toHaveLength(1);
    expect(document.body.querySelectorAll("[data-testid='candidate-undo-accept']")).toHaveLength(3);
    expect(q("claim-group-accept-all-top-1")).toBeNull();
    api.updateCandidate.mockClear();
    api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [{ ...plain[0], status: "pending" }, ...plain.slice(1).map((c) => ({ ...c, status: "approved" }))] });
    await act(async () => { q("candidate-row-a").querySelector("[data-testid='candidate-undo-accept']").click(); });
    expect(api.updateCandidate.mock.calls.map((c) => [c[1], c[2]])).toEqual([["a", { undo: true }]]);
    expect(document.body.querySelectorAll("[data-testid='candidate-undo-accept']")).toHaveLength(2);
    api.updateCandidate.mockClear();
    api.getDecks.mockResolvedValue({ decks: DECKS, candidates: plain.map((c) => ({ ...c, status: "pending" })) });
    await click("claim-group-undo-accept-all-1");
    expect(api.updateCandidate.mock.calls.map((c) => [c[1], c[2]])).toEqual([["b", { undo: true }], ["c", { undo: true }]]);
    expect(q("claim-group-undo-accept-all-1")).toBeNull();
  });

  test("Undo accept all goes at the next action: rejecting a row, or opening another tab", async () => {
    const plain = [claim("a", "d1", 1, { group: 1 }), claim("b", "d1", 2, { group: 1 })];
    await reload(plain);
    api.updateCandidate.mockResolvedValue({});
    api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [{ ...plain[0], status: "approved" }, plain[1]] });
    await click("claim-group-accept-all-top-1");
    expect(q("claim-group-undo-accept-all-1")).not.toBeNull();
    await act(async () => { q("candidate-row-b").querySelector("[data-testid='candidate-reject']").click(); });
    expect(q("claim-group-undo-accept-all-1")).toBeNull();
    expect(document.body.querySelector("[data-testid='candidate-undo-accept']")).toBeNull();
  });
});
