import vectors from "./format_vectors.json";
import { fmt, bandRangeLabel } from "./format";

test.each(vectors)("shared vector %#", (v) => {
  expect(fmt(v.kind, v.in, v.ccy)).toBe(v.out);
});

test("band range label uses raw thresholds", () => {
  expect(bandRangeLabel(100, 1000, "EUR")).toBe("100–1,000 EUR");
  expect(bandRangeLabel(100000, null, "EUR")).toBe("100,000 EUR+");
  expect(bandRangeLabel(0, 100, "EUR")).toBe("<100 EUR");
});
