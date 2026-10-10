import React, { act } from "react";
import { createRoot } from "react-dom/client";

import DeckPanel from "./DeckPanel";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({ getDecks: jest.fn(), removeDeck: jest.fn(), updateCandidate: jest.fn(), uploadDeck: jest.fn(), addClaim: jest.fn(),
  answerTurnover: jest.fn() }));
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

test("a use-of-funds text figure and its chart figure show text and chart with the dropped category, and no Contradicted", async () => {
  const share = (label, value) => ({ value, value_high: null, currency: null, unit: "%", date: null, claim_type: "use_of_funds", label,
    source: { file: "d.pdf", page: 22, kind: "text" } });
  await reload([claim("c", "d1", 22, { group: 7, claim_type: "use_of_funds", value: 40, unit: "%", inconsistent_dates: [],
    inconsistencies: [{ this: share("text", 40), other: share("chart", 42), note: "chart excludes Operational Expenses & Talent Acquisition, rescaled" }] })]);
  await open(7);                                   // Other holds Use of funds and starts collapsed
  expect(q("candidate-inconsistency").getAttribute("title")).toBe(
    "The deck gives different figures for this metric: text 40% at d.pdf · page 22 and chart 42% at d.pdf · page 22; chart excludes Operational Expenses & Talent Acquisition, rescaled.");
  expect(document.body.textContent).not.toMatch(/Contradicted/);
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
    bar("t21", 278085, "2021", view("t21", "2021", { file_note: "No revenue-file period to compare" })),
    bar("t22", 415107, "2022", view("t22", "2022", { turnover_suggested: "volume", file_note: "No revenue-file period to compare",
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
      expect(q(`candidate-row-${id}`).textContent).toContain("To review");
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
    expect(cell("t21", "turnover-file-note").textContent).toBe("No revenue-file period to compare");
    expect(cell("t22", "turnover-file-note").textContent).toBe("No revenue-file period to compare");
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
      await reload([answered("volume", "deck_says_processed_volume", { file_note: "No revenue-file period to compare" })]);
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

test("To review is a status label, not a control: plain text with no border, chip or button around it (George, 2026-10-09)", async () => {
  await reload([claim("c", "d1", 2, { group: 1 }), claim("e", "d1", 3, { group: 1, status: "approved" })]);
  for (const [id, label] of [["c", "To review"], ["e", "Approved"]]) {
    const status = q(`candidate-row-${id}`).querySelector("[data-testid='candidate-status']");
    expect(status.textContent).toBe(label);
    expect(status.tagName).toBe("SPAN");
    expect(status.className.split(/\s+/).filter((c) => /^(border|rounded|px-|py-|bg-)/.test(c))).toEqual([]);
    expect(status.closest("button, a, [role='button']")).toBeNull();
  }
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

  test("the claims text is the agreed wording, with the Approve, Edit and Reject lines below it", () => {
    const lines = [...q("claims-instructions").querySelectorAll("h4, p")].map((n) => n.textContent);
    expect(lines[0]).toBe("Claims found in the uploaded documents");
    expect(lines[1]).toBe("These figures were extracted automatically and inform the growth plan. While errors are possible, you only need to check claims that look incorrect or implausible against their source slides before making your selection.");
    expect(lines.slice(2).map((l) => l.split(":")[0])).toEqual(["✓ Approve", "✎ Edit", "✕ Reject"]);
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
