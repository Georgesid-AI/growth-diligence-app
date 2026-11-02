import vectors from "./format_vectors.json";
import { fmt, bandRangeLabel, fmtElapsed } from "./format";

test.each(vectors)("shared vector %#", (v) => {
  expect(fmt(v.kind, v.in, v.ccy)).toBe(v.out);
});

test("band range label uses raw thresholds", () => {
  expect(bandRangeLabel(100, 1000, "EUR")).toBe("100–1,000 EUR");
  expect(bandRangeLabel(100000, null, "EUR")).toBe("100,000 EUR+");
  expect(bandRangeLabel(0, 100, "EUR")).toBe("<100 EUR");
});

test("a running or finished time is m:ss, whole seconds, minutes grouped by the one rule", () => {
  expect(fmtElapsed(0)).toBe("0:00");
  expect(fmtElapsed(38)).toBe("0:38");
  expect(fmtElapsed(107.9)).toBe("1:47");
  expect(fmtElapsed(3605)).toBe("60:05");
  expect(fmtElapsed(-3)).toBe("0:00");
  expect(fmtElapsed(null)).toBe("—");
});
