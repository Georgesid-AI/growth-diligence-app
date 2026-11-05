import { differsText, readingsText, uncertainEntries, whereText } from "./readingView";

/** Combined fixes, 2026-11-05, items 8-10: what the Uncertain list shows for a deck figure, a sheet row and a series difference. */

const deckFile = (fig) => ({ kind: "deck", file: "Board.pdf", deck_id: "d1", figures: [fig] });
const fig = (over = {}) => ({ id: "c1", metric: "revenue", value: 170044, unit: "money", currency: "EUR", period: "2019", page: 11, cell: "r4c2", uncertain: true,
  reading: { index: 0, options: ["a", "b"], details: [{ metric: "revenue", value: "170,044", period: "2019" }, { metric: "revenue", value: "170,044", period: "2019" }] }, ...over });

describe("item 8: a deck figure shows its value and period beside the page and cell, whatever field differs", () => {
  test.each([["metric", { metric: "revenue" }, { metric: "arr" }], ["value", { value: "1" }, { value: "2" }], ["period", { period: "2019" }, { period: "2020" }]])(
    "differing %s", (_f, one, two) => {
      const [entry] = uncertainEntries([deckFile(fig({ reading: { index: 0, options: ["a", "b"], details: [one, two] } }))]);
      expect(entry.where).toBe("170,044 EUR, 2019 · page 11, cell r4c2");
    });
  test("a figure with no currency, no period or no cell says only what it has", () => {
    expect(uncertainEntries([deckFile(fig({ currency: null, unit: "%", value: 62, period: null }))])[0].where).toBe("62% · page 11, cell r4c2");
    expect(uncertainEntries([deckFile(fig({ currency: null, unit: "count", value: 800, cell: null }))])[0].where).toBe("800, 2019 · page 11");
  });
});

describe("item 9: a sheet item shows the row's label text beside the row number", () => {
  const sheet = (item, lines) => ({ kind: "sheet", file: "rev.xlsx", file_hash: "h1", lines: [{ sheet: "Sales", lines }], consistency: { uncertain: [item] } });
  const row = (rows, over = {}) => ({ key: "k", kind: "row", sheet: "Sales", row: rows[0], rows, fields: ["role"], first: {}, second: {}, ...over });
  test("one row", () => {
    const [e] = uncertainEntries([sheet(row([31]), [{ row: 30, label: "Costs" }, { row: 31, label: "Net revenue" }])]);
    expect(e.where).toBe("Sales, row 31 · Net revenue");
  });
  test("a run of rows names the labels in row order, three at most", () => {
    const lines = [6, 7, 8, 9].map((n) => ({ row: n, label: `Line ${n}` }));
    expect(uncertainEntries([sheet(row([6, 7, 8, 9]), lines)])[0].where).toBe("Sales, rows 6–9 · Line 6; Line 7; Line 8; …");
  });
  test("a row whose label the screen does not hold shows the row number alone", () => {
    expect(uncertainEntries([sheet(row([31]), [])])[0].where).toBe("Sales, row 31");
    expect(whereText(row([31]))).toBe("Sales, row 31");
  });
});

describe("item 10: a series or plan series difference never shows the bare period count", () => {
  const d = (over = {}) => ({ period: "2021-03", first: 12000, second: 12500, differing: 3, total: 16, ...over });
  const both = { kind: "row", sheet: "S", row: 31, rows: [31], fields: ["series", "plan_series"], first: { periods: 16 }, second: { periods: 16 },
    series_diff: { series: d(), plan_series: d({ period: "2022-01", first: 5, second: 7, differing: 1, total: 4 }) } };
  test("the series and the plan series each name the first differing period with both values and the count", () => {
    expect(differsText(both)).toBe("series (2021-03: 12,000 / 12,500 · 3 of 16 periods differ), plan series (2022-01: 5 / 7 · 1 of 4 periods differ)");
    expect(readingsText(both, "first")).toBe("series 2021-03: 12,000 · plan series 2022-01: 5");
    expect(readingsText(both, "second")).toBe("series 2021-03: 12,500 · plan series 2022-01: 7");
  });
  test("an item served without the difference of a field says the values differ, never '16 periods'", () => {
    const partly = { ...both, series_diff: { series: d() } };
    expect(readingsText(partly, "first")).toBe("series 2021-03: 12,000 · plan series different values");
    const none = { ...both, series_diff: undefined };
    for (const side of ["first", "second"]) expect(readingsText(none, side)).not.toMatch(/\d+ periods?/);
    expect(readingsText(none, "first")).toBe("series different values · plan series different values");
  });
});
