import { differsText, readingsText } from "./readingView";

const diff = { period: "2021-03", first: 12000, second: 12500, differing: 3, total: 30 };
const item = { kind: "row", sheet: "Sales", row: 4, rows: [4], fields: ["series"], series_diff: { series: diff },
  first: { periods: 30 }, second: { periods: 30 } };

test("a series item names the first differing period with both values and how many periods differ, never the period count alone", () => {
  expect(differsText(item)).toBe("series (2021-03: 12,000 / 12,500 · 3 of 30 periods differ)");
  expect(readingsText(item, "first")).toBe("series 2021-03: 12,000");
  expect(readingsText(item, "second")).toBe("series 2021-03: 12,500");
});

test("a period one read lacks shows none; the plan series is worded alike", () => {
  const lacking = { ...item, fields: ["plan_series"], series_diff: { plan_series: { period: "2022-01", first: 5, second: null, differing: 1, total: 12 } } };
  expect(differsText(lacking)).toBe("plan series (2022-01: 5 / none · 1 of 12 periods differ)");
  expect(readingsText(lacking, "second")).toBe("plan series 2022-01: none");
});
