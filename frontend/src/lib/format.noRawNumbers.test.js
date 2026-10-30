/**
 * One number formatter for every number on any page, in the memo and in the exports (docs/design/read-check-review.md section 11.5, PR 3):
 * whole numbers; one decimal only for a single-digit multiple (3.3x), a single-digit number (1.2) or a single-digit percent (4.5 %); stored
 * values never rounded. Only lib/format.js turns a number into text: this test fails on any other file of src that rounds or groups a number
 * itself (toFixed, toLocaleString, Intl.NumberFormat, toPrecision, toExponential).
 */
import fs from "fs";
import path from "path";
import { displayNumber, fmtCount, fmtCurrency, fmtMonths, fmtPct, fmtRatio } from "./format";

const SRC = path.resolve(__dirname, "..");
const files = (dir) => fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
  const p = path.join(dir, e.name);
  if (e.isDirectory()) return files(p);
  return /\.(js|jsx)$/.test(e.name) && !/\.test\.jsx?$/.test(e.name) ? [p] : [];
});
const FORBIDDEN = /\.toFixed\(|\.toLocaleString\(|Intl\.NumberFormat|\.toPrecision\(|\.toExponential\(/;

test("no component or helper formats a number without lib/format.js", () => {
  const all = files(SRC);
  expect(all.length).toBeGreaterThan(50);
  const offenders = all.filter((f) => path.basename(f) !== "format.js" && FORBIDDEN.test(fs.readFileSync(f, "utf8"))).map((f) => path.relative(SRC, f));
  expect(offenders).toEqual([]);
});

test("the rule: whole numbers, one decimal only below ten, a multiple, a number and a percent alike; the .0 is dropped", () => {
  expect(fmtRatio(3.28)).toBe("3.3x");
  expect(fmtRatio(12.4)).toBe("12x");
  expect(displayNumber(1.2)).toBe("1.2");
  expect(displayNumber(7)).toBe("7");
  expect(fmtPct(0.045)).toBe("4.5 %");
  expect(fmtPct(1.0641)).toBe("106 %");
  expect(fmtMonths(5.67)).toBe("5.7 months");
  expect(fmtCount(1234567.89)).toBe("1,234,568");
  expect(fmtCurrency(2.54, "EUR")).toBe("2.5 EUR");
  expect(displayNumber(9.96)).toBe("10");
  expect(displayNumber(-0.04)).toBe("0");
});
