import React, { act } from "react";
import { createRoot } from "react-dom/client";

import DeckPanel from "./DeckPanel";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({ getDecks: jest.fn(), removeDeck: jest.fn(), updateCandidate: jest.fn(), uploadDeck: jest.fn(), addClaim: jest.fn() }));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn(), message: jest.fn() } }));

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
// ... and by the group of the claim type first: revenue (1), market size (5), Unknown (6).
const CLAIMS = [
  claim("c", "d1", 2, { group: 1 }),
  claim("d", "d2", 3, { group: 1 }),
  claim("b", "d2", 1, { claim_type: "market", label_from: "MARKET SIZE", group: 5, confidence: { level: "High", failed: [], text: "High" } }),
  claim("a", "d1", 1, { claim_type: "unknown", target_date: null, group: 6, confidence: { level: "Low", failed: ["no date", "no heading"], text: "Low – no date, no heading" } }),
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

test("the table has a Confidence column between Period and the claim, in every row", async () => {
  await act(async () => { q("deck-tab-all").click(); });
  await open(6);
  const heads = [...document.body.querySelectorAll("[data-testid='deck-candidates'] thead th")].map((th) => th.textContent);
  expect(heads).toEqual(["Type", "Value", "Period", "Confidence", "Claim in the deck", "Source", "Status", "Action"]);
  const cells = rows().map((tr) => tr.querySelector("[data-testid='candidate-confidence']").textContent);
  expect(cells.sort()).toEqual(["High", "Low – no date, no heading", "Medium – not corroborated", "Medium – not corroborated"].sort());
});

test("All lists the claims in the server's order, group by group; a deck tab keeps that order", async () => {
  await act(async () => { q("deck-tab-all").click(); });
  await open(6);
  expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["c", "d", "b", "a"]);
  await act(async () => { q("deck-tab-d1").click(); });
  expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["c", "a"]);
});

test("Unknown and Other start collapsed under a header with their count; the other groups are open", async () => {
  await act(async () => { q("deck-tab-all").click(); });
  expect(["claim-group-1", "claim-group-5", "claim-group-6"].map((id) => q(id).textContent)).toEqual([
    "Revenue, ARR, MRR and bookings (2)", "Market size (1)", "Unknown – choose type (1)"]);
  expect(q("claim-group-2")).toBeNull();
  expect(q("claim-group-toggle-6").getAttribute("aria-expanded")).toBe("false");
  expect(q("claim-group-toggle-1").getAttribute("aria-expanded")).toBe("true");
  expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["c", "d", "b"]);
  await open(6);
  expect(rows().length).toBe(4);
  await open(6);
  expect(rows().length).toBe(3);
  await open(1);
  expect(rows().map((tr) => /snippet-(\w)/.exec(text(tr))[1])).toEqual(["b"]);
});

test("the Period column reads FY2025 for the year 2025 and no date when the deck gives no period", async () => {
  await act(async () => { q("deck-tab-all").click(); });
  await open(6);
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
  expect(rows()[2].querySelector("[data-testid='candidate-confidence']").textContent).toBe("Medium – no figure");
});

test("an Unknown type says so, cannot be approved before a type is chosen, and Market size is a choice", async () => {
  await act(async () => { q("deck-tab-d1").click(); });
  await open(6);
  const first = rows()[1];
  expect(first.textContent).toContain("Unknown – choose type");
  expect(first.querySelector("[data-testid='candidate-approve']").disabled).toBe(true);
  expect(rows()[0].querySelector("[data-testid='candidate-approve']").disabled).toBe(false);
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

test("the upload help, the Confidence hover are shown word for word", async () => {
  await reload([claim("c", "d1", 2, { group: 1 })]);
  expect(q("deck-upload-help").textContent).toMatch(/^Board deck or growth plan: the company's board decks, investor updates.* Up to 8 documents per audit\./);
  expect(q("candidate-confidence-text").title).toMatch(/^Confidence shows how well this figure was read from the deck, not whether it is true\. High:/);
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

  test("the claims text is the agreed wording and the Approve, Edit and Reject lines are gone", () => {
    expect(q("claims-instructions").textContent).toBe(
      "Claims found in the uploaded documents" +
      "These figures were extracted automatically and inform the growth plan. While errors are possible, you only need to check claims that look incorrect or implausible against their source slides before making your selection.");
    expect(q("deck-scope-message").textContent).toContain("If a number you need sits in a picture, use Add claim and cite the page, or upload the source spreadsheet.");
  });

  test("one row opens with the metric list of the other rows and a dropdown of the uploaded decks", async () => {
    await openRow();
    const typeOptions = [...q("add-claim-type").options].map((o) => o.textContent);
    expect(typeOptions).toContain("Revenue");
    expect(typeOptions).toContain("Market size");
    expect(typeOptions).not.toContain("Unknown – choose type");
    expect([...q("add-claim-deck").options].map((o) => o.textContent).sort()).toEqual(["newer.pdf", "older.pptx"]);
    for (const id of ["add-claim-value", "add-claim-value-high", "add-claim-unit", "add-claim-currency", "add-claim-date", "add-claim-page"]) expect(q(id)).not.toBeNull();
  });

  test("Save stays off until the value and the page are filled; the source document is always one of the decks", async () => {
    await openRow();
    expect(q("add-claim-save").disabled).toBe(true);
    await change(q("add-claim-value"), "5");
    expect(q("add-claim-save").disabled).toBe(true);          // no page yet
    await change(q("add-claim-page"), "3");
    expect(q("add-claim-save").disabled).toBe(false);
    await change(q("add-claim-page"), "");
    expect(q("add-claim-save").disabled).toBe(true);
  });

  test("Save sends the claim with its deck and page, closes the row and reloads the list on that deck", async () => {
    api.addClaim.mockResolvedValue({ id: "n1", deck_id: "d1" });
    await openRow();
    await change(q("add-claim-deck"), "d1");
    await change(q("add-claim-value"), "3600000");
    await change(q("add-claim-currency"), "usd");
    await change(q("add-claim-date"), "2025");
    await change(q("add-claim-page"), "4");
    await act(async () => { q("add-claim-save").click(); });
    expect(api.addClaim).toHaveBeenCalledWith("a1", {
      claim_type: "revenue", deck_id: "d1", page: 4, value: 3600000, value_high: null, unit: null, currency: "USD", target_date: "2025" });
    expect(q("add-claim-row")).toBeNull();
    expect(api.getDecks).toHaveBeenCalledTimes(2);
  });

  test("an analyst-entered claim shows its tag and the confidence Analyst-entered", async () => {
    api.getDecks.mockResolvedValue({ decks: DECKS, candidates: [
      claim("n1", "d1", 4, { group: 1, status: "approved", origin: "analyst", snippet: "Added by analyst", confidence: { level: null, failed: [], text: "Analyst-entered" } })] });
    await act(async () => { q("deck-tab-all").click(); });
    await act(async () => { root.render(<DeckPanel auditId="a1" reloadKey={1} />); });
    const tr = rows()[0];
    expect(tr.querySelector("[data-testid='candidate-confidence']").textContent).toBe("Analyst-entered");
    expect(tr.textContent).toContain("Added by analyst");
  });
});
