// docs/specs/forecast-and-payback.md section 5: one list of four columns and one forecast note, shared by the register, the five and the memo.
import claimColumns from "./claim_columns.json";
import { FORECAST_NOTE, REGISTER_COLUMNS, REGISTER_COLUMN_WIDTHS, claimName, hasForecast, isForecastRow } from "./claimRegister";
import { candidateText } from "./verdict";

test("the register's columns are the shared four, and their widths fill the table", () => {
  expect(REGISTER_COLUMNS).toEqual(claimColumns.columns);
  expect(REGISTER_COLUMNS).toEqual(["Claim and period", "Evidence / calculation", "Result", "Source"]);
  expect(REGISTER_COLUMN_WIDTHS.length).toBe(4);
  expect(REGISTER_COLUMN_WIDTHS.reduce((a, b) => a + b, 0)).toBe(100);
  expect(FORECAST_NOTE).toBe("Forecast calculations describe assumptions; future outcomes are unverified.");
});

test("a forecast is a target-classified claim for a period after the as-of month, and only that", () => {
  const row = { figure_type: "target", period_end: "2026-12-31", as_of_month: "2024-12" };
  expect(isForecastRow(row)).toBe(true);
  expect(isForecastRow({ ...row, figure_type: "actual" })).toBe(false);          // a later period alone is missing coverage
  expect(isForecastRow({ ...row, period_end: "2024-06-30" })).toBe(false);       // a plan for a period that has passed is shown, not a forecast
  expect(isForecastRow({ ...row, as_of_month: null })).toBe(false);
  expect(hasForecast([{ ...row, figure_type: "actual" }])).toBe(false);
  expect(hasForecast([{ ...row, figure_type: "actual" }, row])).toBe(true);
  expect(hasForecast([])).toBe(false);
  expect(hasForecast(undefined)).toBe(false);
});

test("a claim is named by its words and period, never by a rank", () => {
  expect(claimName({ metric: "ARR", period: "Feb 2024", segment: "Whole company" })).toBe("ARR, Feb 2024");
  expect(claimName({ metric: "Revenue", period: "FY2023", segment: "Enterprise" })).toBe("Revenue · Enterprise, FY2023");
  expect(claimName({ claim_type: "revenue", period: null })).toBe("Revenue");
  expect(candidateText({ rank: 3, claim: "Win rate" })).toBe("Win rate");
});
