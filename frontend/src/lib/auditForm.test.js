import { isIsoDate, asOfInputValue, targetDateError, plainNumber, groupThousands, CONSENT_EXPLAINER, CONSENT_LABEL,
  requiredFieldError } from "./auditForm";

// The reported case: target 31/12/2027, as-of 30/06/2026, as the date inputs deliver them.
test("target 2027-12-31 after as-of 2026-06-30 passes", () => {
  expect(targetDateError("2027-12-31", "2026-06-30")).toBeNull();
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

// docs/specs/llm-structure-reading.md section 4, word for word.
test("the consent explainer and label are the spec's words", () => {
  expect(CONSENT_EXPLAINER).toBe("This app reads tables and charts in the uploaded decks with an AI model. Every number is checked by code against its source cell; anything that does not match is marked as unverified. Emails, phone numbers, personal names and the customers named in the uploaded data files are replaced before anything is sent.");
  expect(CONSENT_LABEL).toBe("AI-assisted reading enabled per engagement terms. Uncheck if the client requires code-based extraction only; this may identify fewer findings.");
});

test("a client name and an engagement reference are required", () => {
  const form = { company_name: "Acme", client_name: "Northbridge Capital", engagement_reference: "ENG-1" };
  expect(requiredFieldError(form)).toBeNull();
  expect(requiredFieldError({ ...form, client_name: " " })).toBe("Client name is required");
  expect(requiredFieldError({ ...form, engagement_reference: "" })).toBe("Engagement reference is required");
  expect(requiredFieldError({ ...form, company_name: "" })).toBe("Company name is required");
});
