import { figureWhere, sourceParts, ACTION_LABELS } from "./readingView";

/** Board-pack layout fixes, items 2, 6 and 7: how a source is written on the mapping page. */

describe("item 6: a deck figure on a text-style page shows the line it sits in", () => {
  const text = { id: "c1", metric: "arr", value: 1774628, unit: "money", currency: "EUR", period: null, page: 1, cell: "r2c1", line: "ARR: 1 774 628 EUR - 93% of the plan!" };
  test("the page number and the line, never the rNcM anchor", () => {
    expect(figureWhere(text)).toBe("1,774,628 EUR · p1: ARR: 1 774 628 EUR - 93% of the plan!");
    expect(figureWhere(text)).not.toContain("r2c1");
  });
  test("the source of a table figure keeps the cell and gets its row label", () => {
    expect(figureWhere({ ...text, line: null, label: "ARR", period: "2024" })).toBe("1,774,628 EUR, 2024 · page 1, cell r2c1 · ARR");
    expect(figureWhere({ ...text, line: null })).toBe("1,774,628 EUR · page 1, cell r2c1");
  });
  test("a deck row's source is p1: and the line", () => {
    expect(sourceParts({ file: "deck.pdf", deck_id: "d1", page: 1, line: text.line })).toEqual({ first: "p1: ARR: 1 774 628 EUR - 93% of the plan!", rest: "deck.pdf" });
    expect(sourceParts({ file: "deck.pdf", deck_id: "d1", page: 12 })).toEqual({ first: "p12", rest: "deck.pdf" });
  });
});

describe("item 2: a hidden sheet is named so", () => {
  test("a cell of a hidden sheet", () => {
    expect(sourceParts({ file: "pack.xlsx", sheet: "data_for_graphs", cell: "B4", hidden: true })).toEqual({ first: "B4", rest: "data_for_graphs (hidden) · pack.xlsx" });
    expect(sourceParts({ file: "pack.xlsx", sheet: "PNL", cell: "B4" })).toEqual({ first: "B4", rest: "PNL · pack.xlsx" });
  });
});

describe("item 7: the words of a card's actions", () => {
  test("the correction has its own label and use the reader is kept as read on a reviewer's card", () => {
    expect(ACTION_LABELS.apply_fix).toBe("Apply the correction");
    expect(ACTION_LABELS.keep_as_read).toBe("Keep as read");
  });
});
