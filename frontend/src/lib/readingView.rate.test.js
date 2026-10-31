import { valueText } from "./readingView";

test("a rate is a fraction whatever its size: the reader's unit decides, no scale is guessed from the number", () => {
  expect(valueText(0.045, "rate")).toBe("4.5%");
  expect(valueText(1.2, "rate")).toBe("120%");        // a churn of 1.2 % is written 0.012 by the reader; 1.2 is 120 %
  expect(valueText(0.012, "rate")).toBe("1.2%");
  expect(valueText(4.5, "rate")).toBe("450%");        // no 1.5 threshold: a larger number is not turned into "points"
  expect(valueText(null, "rate")).toBe("—");
});
