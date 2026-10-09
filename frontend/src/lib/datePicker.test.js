import {
  MAX_YEAR, MIN_YEAR, YEAR_ERROR, dateRangeError, displayDate, openingView, parseIso, parseTyped, parseYear, pickSide, CALENDAR_HEIGHT, shiftMonth, shiftYear, toIso, weeks,
} from "./datePicker";

test("the years run from 2000 to 2100 and a year outside is rejected", () => {
  expect([MIN_YEAR, MAX_YEAR]).toEqual([2000, 2100]);
  expect(YEAR_ERROR).toBe("Year must be between 2000 and 2100");
  expect(["2000", "2026", "2100"].map(parseYear)).toEqual([2000, 2026, 2100]);
  expect(["1999", "2101", "0001", "27", "20267", "", "abcd", "20.5"].map(parseYear)).toEqual(Array(8).fill(null));
});

test("a date outside the range or not real shows as nothing, never as year 0001", () => {
  expect(displayDate("2026-06-30")).toBe("30 Jun 2026");
  expect(["0001-01-01", "0027-01-01", "1999-12-31", "2101-01-01", "2026-02-30", "30/06/2026", "", null].map(displayDate)).toEqual(Array(8).fill(""));
  expect(parseIso("2000-01-01")).toEqual({ year: 2000, month: 0, day: 1 });
  expect(parseIso("2100-12-31")).toEqual({ year: 2100, month: 11, day: 31 });
  expect(parseIso("2024-02-29")).not.toBeNull();
  expect(parseIso("2023-02-29")).toBeNull();
});

test("the month and year arrows stop at the ends of the range", () => {
  expect(shiftMonth({ year: 2026, month: 0 }, -1)).toEqual({ year: 2025, month: 11 });
  expect(shiftMonth({ year: 2026, month: 11 }, 1)).toEqual({ year: 2027, month: 0 });
  expect(shiftMonth({ year: 2000, month: 0 }, -1)).toBeNull();
  expect(shiftMonth({ year: 2100, month: 11 }, 1)).toBeNull();
  expect(shiftYear({ year: 2026, month: 5 }, 1)).toEqual({ year: 2027, month: 5 });
  expect(shiftYear({ year: 2000, month: 5 }, -1)).toBeNull();
  expect(shiftYear({ year: 2100, month: 5 }, 1)).toBeNull();
});

test("the calendar opens at the value's month, else today's, inside the range", () => {
  expect(openingView("2027-12-31")).toEqual({ year: 2027, month: 11 });
  expect(openingView("", new Date(2026, 9, 8))).toEqual({ year: 2026, month: 9 });
  expect(openingView("0001-01-01", new Date(2026, 9, 8))).toEqual({ year: 2026, month: 9 });
  expect(openingView("", new Date(1990, 3, 1))).toEqual({ year: 2000, month: 0 });
  expect(openingView("", new Date(2150, 3, 1))).toEqual({ year: 2100, month: 0 });
});

test("weeks start on Monday and hold every day once", () => {
  const june = weeks({ year: 2026, month: 5 });               // 1 June 2026 is a Monday
  expect(june[0][0]).toBe(1);
  expect(june.flat().filter(Boolean)).toEqual(Array.from({ length: 30 }, (_, i) => i + 1));
  expect(june.every((w) => w.length === 7)).toBe(true);
  expect(weeks({ year: 2026, month: 2 })[0].indexOf(1)).toBe(6);   // 1 March 2026 is a Sunday
  expect(toIso(2026, 5, 7)).toBe("2026-06-07");
});

test("every date field refuses a year outside 2000 to 2100 and a date that is not real", () => {
  expect(dateRangeError("Gate date", "")).toBeNull();
  expect(dateRangeError("Gate date", "2026-06-30")).toBeNull();
  expect(dateRangeError("Gate date", "0001-01-01")).toBe("Gate date year must be between 2000 and 2100");
  expect(dateRangeError("Gate date", "2101-01-01")).toBe("Gate date year must be between 2000 and 2100");
  expect(dateRangeError("Gate date", "2026-02-30")).toBe("Gate date must be a real date");
  expect(dateRangeError("Gate date", "30/06/2026")).toBe("Gate date must be a full date (YYYY-MM-DD)");
});

test("a typed date is read as year-month-day with dashes or day.month.year with dots, and nothing else", () => {
  expect(["2026-06-30", "30.06.2026", "1.2.2028", "2028-2-1", " 30.06.2026 "].map(parseTyped))
    .toEqual(["2026-06-30", "2026-06-30", "2028-02-01", "2028-02-01", "2026-06-30"]);
  expect(["06/07/2026", "30-06-2026", "2026.06.30", "2026-02-30", "31.04.2026", "30.06.1999", "2101-01-01", "30.06.26", "", null, "2026-06"]
    .map(parseTyped)).toEqual(Array(11).fill(null));
});

test("the calendar goes below the field when it fits and above when it does not", () => {
  expect(pickSide({ bottom: 200 }, 900)).toBe("bottom");
  expect(pickSide({ bottom: 900 - CALENDAR_HEIGHT }, 900)).toBe("bottom");
  expect(pickSide({ bottom: 900 - CALENDAR_HEIGHT + 1 }, 900)).toBe("top");
  expect(pickSide({ bottom: 880 }, 900)).toBe("top");
});
