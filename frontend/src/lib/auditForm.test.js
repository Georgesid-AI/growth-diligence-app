import { isIsoDate, asOfInputValue, parseMonthYear, asOfSourceText, asOfDisplay, targetDateError, plainNumber, groupThousands, storedNumberInput, CONSENT_LABEL, VERIFIED_LINE, NEW_AUDIT_TITLE, NEW_AUDIT_PARAGRAPHS,
  requiredFieldError, SETUP_HELP, SETUP_LABELS, AS_OF_PLACEHOLDER, asOfWarning, revenueLastMonth } from "./auditForm";

// The reported case: target 31/12/2027, as-of 30/06/2026, as the date inputs deliver them.
test("target 2027-12-31 after as-of 2026-06-30 passes", () => {
  expect(targetDateError("2027-12-31", "2026-06-30")).toBeNull();
});

test("a year outside 2000 to 2100 is refused for the target date and the as-of date", () => {
  expect(targetDateError("0027-01-01", "")).toBe("Target date year must be between 2000 and 2100");
  expect(targetDateError("2101-01-01", "")).toBe("Target date year must be between 2000 and 2100");
  expect(targetDateError("2027-01-01", "0001-01-01")).toBe("As-of month year must be between 2000 and 2100");
  expect(targetDateError("2027-01-01", "1999-12-31")).toBe("As-of month year must be between 2000 and 2100");
});

test("target before the as-of month is refused", () => {
  expect(targetDateError("2026-03-31", "2026-06-30")).toBe("Target date must be after the as-of month");
});

test("target on the as-of date is refused", () => {
  expect(targetDateError("2026-06-30", "2026-06-30")).toBe("Target date must be after the as-of month");
});

// What a browser without a month picker sent before the fix: free text, compared as a
// string ("2027-12" <= "30/06/2026"), which gave the wrong "must be after" error.
test("a non-ISO as-of is refused as a format problem, not compared", () => {
  expect(targetDateError("2027-12-31", "30/06/2026")).toBe("As-of month must be a full date (YYYY-MM-DD)");
  expect(targetDateError("31/12/2027", "2026-06-30")).toBe("Target date must be a full date (YYYY-MM-DD)");
});

test("ISO check rejects impossible dates", () => {
  expect(isIsoDate("2026-06-30")).toBe(true);
  expect(isIsoDate("2026-02-30")).toBe(false);
  expect(isIsoDate("2026-06")).toBe(false);
});

test("a stored YYYY-MM as-of opens as its month end", () => {
  expect(asOfInputValue("2026-06")).toBe("2026-06-30");
  expect(asOfInputValue("2024-02")).toBe("2024-02-29");
  expect(asOfInputValue("2026-06-30")).toBe("2026-06-30");
  expect(asOfInputValue(null)).toBe("");
});

test("Target ARR shows 6,000,000 and stays a plain number", () => {
  expect(groupThousands("6000000")).toBe("6,000,000");
  expect(plainNumber("6,000,000")).toBe("6000000");
  expect(parseFloat(plainNumber("6,000,000"))).toBe(6000000);
  expect(groupThousands(plainNumber("1,234.5.6"))).toBe("1,234.56");
  expect(groupThousands("")).toBe("");
});

test("Target ARR never keeps a leading zero; a stored 0 or an empty value shows an empty box", () => {
  expect(plainNumber("05")).toBe("5");
  expect(plainNumber("0,005")).toBe("5");
  expect(plainNumber("0.5")).toBe("0.5");
  expect(plainNumber("0")).toBe("0");
  expect(groupThousands(plainNumber("0012345"))).toBe("12,345");
  expect(plainNumber("")).toBe("");
  expect(storedNumberInput(0)).toBe("");
  expect(storedNumberInput(null)).toBe("");
  expect(storedNumberInput(undefined)).toBe("");
  expect(storedNumberInput(40000000)).toBe("40000000");
});

// docs/specs/chat-upload.md section 23, word for word.
test("the consent label, the verification line and the dialog text are the spec's words", () => {
  expect(CONSENT_LABEL).toBe("Use AI to read spreadsheets and deck pages. Before anything is sent, names, contact details and ID numbers are removed, and client and company names are replaced by codes that exist only in this audit. Figures and labels are sent as they are. Deck pages are also sent as an image of the page, which is not masked. Untick if the client requires code-based extraction only; this may find fewer figures. Narratives use AI on computed results either way.");
  expect(VERIFIED_LINE).toBe("Every extracted number is checked by code against its source cell. Numbers that don't match are marked unverified for review.");
  expect(NEW_AUDIT_TITLE).toBe("Create a new audit");
  expect(NEW_AUDIT_PARAGRAPHS).toEqual([
    "Start by entering your project or company name.",
    "Once you upload your files, the app identifies file types, matches data columns to the fields used in the audit, and uses AI to read tables and charts in your decks. You'll review any column matches that need confirmation before calculations begin.",
    "Before content is sent to the AI model, the app replaces email addresses, phone numbers, personal names and customer names found in your uploaded data files.",
    "On the next screen, you can add your files and review the upload requirements.",
  ]);
});

test("the company name is the only required field; a client name is not asked for", () => {
  expect(requiredFieldError({ company_name: "Acme" })).toBeNull();
  expect(requiredFieldError({ company_name: " " })).toBe("Company name is required");
  expect(requiredFieldError({ company_name: "Acme", client_name: " " })).toBeNull();
});

// docs/specs/chat-upload.md section 30 (George, 2026-10-24): the as-of month defaults to the revenue file's last month.
describe("the as-of month default and its warning line", () => {
  test("the help says what the as-of month is; the field takes a typed month and year", () => {
    expect(SETUP_HELP.as_of_month).toBe("Last month of actual figures. Months after it are read as plan.");
    expect(AS_OF_PLACEHOLDER).toBe("e.g. Jun 2021");
  });

  test("a typed month and year becomes the stored last day of that month; anything else is refused", () => {
    expect(parseMonthYear("Jun 2021")).toBe("2021-06-30");
    expect(parseMonthYear("june 2021")).toBe("2021-06-30");
    expect(parseMonthYear("2020-02")).toBe("2020-02-29");
    expect(parseMonthYear("06/2021")).toBe("2021-06-30");
    for (const bad of ["", "2021", "Foo 2021", "13/2021", "Jun 1999", "2021-06-15"]) expect(parseMonthYear(bad)).toBeNull();
  });

  test("the field says where its month came from", () => {
    expect(asOfSourceText({ as_of_month: "2021-06-30", as_of_by: "detected", as_of_file: "revenue.csv" })).toBe("(detected from revenue.csv)");
    // a file stored by recognition alone (a monthly report with no months and no mapping) names itself the same way (PR 196 review)
    expect(asOfSourceText({ as_of_month: "2025-06-30", as_of_by: "detected", as_of_file: "monthly_report.csv" }))
      .toBe("(detected from monthly_report.csv)");
    expect(asOfSourceText({ as_of_month: "2021-12-31", as_of_by: "detected", as_of_file: "pnl.xlsx", as_of_cue: "Forecast" }))
      .toBe("(detected from pnl.xlsx, cue: 'Forecast')");
    expect(asOfSourceText({ as_of_month: "2021-06-30", as_of_by: "analyst", as_of_file: "revenue.csv", as_of_cue: "Forecast" })).toBe("(set by analyst)");
    expect(asOfSourceText({ as_of_month: null })).toBe("");
    expect(asOfDisplay("2021-06-30")).toBe("Jun 2021");
  });

  test("no completeness tick is left in the labels or the help", () => {
    expect(JSON.stringify([SETUP_LABELS, SETUP_HELP])).not.toMatch(/last month is\s+complete|partial/i);
  });

  test("the revenue file's last month comes from the results, else from the mapped file, else none", () => {
    const mapped = { datasets: { revenue: { months: { first: "2017-07", last: "2019-06" } } } };
    expect(revenueLastMonth(mapped)).toBe("2019-06");
    expect(revenueLastMonth({ ...mapped, results: { source_period: { month: "2019-05" } } })).toBe("2019-05");
    expect(revenueLastMonth({ datasets: { revenue: { months: null } } })).toBeNull();
    expect(revenueLastMonth({ datasets: {} })).toBeNull();
    expect(revenueLastMonth(null)).toBeNull();
  });

  test("a warning line only when the as-of month is later than the revenue file's last month", () => {
    expect(asOfWarning("2026-06-30", "2019-06")).toBe("The as-of month, June 2026, is later than the last month of the revenue file, "
      + "June 2019. The figures stop at June 2019; the months after it hold no revenue.");
    expect(asOfWarning("2019-07-31", "2019-06")).toMatch(/July 2019/);
    expect(asOfWarning("2019-06-30", "2019-06")).toBeNull();
    expect(asOfWarning("2019-06-01", "2019-06")).toBeNull();
    expect(asOfWarning("2019-03-31", "2019-06")).toBeNull();
    expect(asOfWarning("2019-06", "2019-05")).toMatch(/June 2019/);
    expect(asOfWarning("", "2019-06")).toBeNull();
    expect(asOfWarning(null, "2019-06")).toBeNull();
    expect(asOfWarning("2026-06-30", null)).toBeNull();
  });
});
