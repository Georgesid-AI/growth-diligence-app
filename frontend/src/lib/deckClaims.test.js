import {
  ALL_DECKS, AI_SUGGESTION_LABEL, CLAIM_TYPES, INCONSISTENCY_LABEL, UPLOADED_BEFORE_CONSENT, VERIFIED_LABEL, deckRunLog, REMOVE_DECK_CONFIRM, claimPeriod, conversionHover, claimSections, claimsForDeck, periodLabel, directionText, deckTabs, defaultDeck, CLAIMS_CHOICES, CLAIMS_HEADING, CLAIMS_INTRO, COLUMNS, claimValue, rowEdit, newClaimPayload, sourceRef, statusCounts, typeLabel,
  DECK_SCOPE_CANNOT, DECK_SCOPE_INTRO, DECK_SCOPE_OUTRO, OTHER_TYPE_NOTE, needsType, readingChoices, confidenceText, UNKNOWN_TYPE_LABEL,
} from "./deckClaims";

describe("source reference", () => {
  test("slide, page, notes and table cell", () => {
    expect(sourceRef({ file: "board.pptx", slide: 5, kind: "text" })).toBe("board.pptx · slide 5");
    expect(sourceRef({ file: "board.pptx", slide: 2, kind: "notes" })).toBe("board.pptx · slide 2 · notes");
    expect(sourceRef({ file: "plan.pdf", page: 19, kind: "table", table: 1, row: 4, col: 2 }))
      .toBe("plan.pdf · page 19 · table 1, row 4, col 2");
    expect(sourceRef({ file: "plan.docx", page: 6, kind: "text" })).toBe("plan.docx · page 6");
  });
});

describe("claim value", () => {
  test("keeps the deck's decimals and shows unit or currency", () => {
    expect(claimValue({ value: 3600000, currency: "USD" })).toBe("3,600,000 USD");
    expect(claimValue({ value: 13.72, unit: "%" })).toBe("13.72%");
    expect(claimValue({ value: 4.9, unit: "x" })).toBe("4.9x");
    expect(claimValue({ value: 24, unit: "months" })).toBe("24 months");
    expect(claimValue({ value: 2.5 })).toBe("2.5");
    expect(claimValue({ value: null, target_date: "2021-Q3" })).toBe("—");
    expect(claimValue({ value: 12000000, value_high: 13000000, currency: "USD" })).toBe("12,000,000–13,000,000 USD");
    expect(claimValue({ value: 5, value_high: 10, unit: "%" })).toBe("5–10%");
    // The counted noun is the unit: Buffer slide 5.
    expect(claimValue({ value: 800, unit: "paying users" })).toBe("800 paying users");
    expect(claimValue({ value: 97, unit: "%" })).toBe("97%");
    expect(claimValue({ value: 150000, currency: "USD" })).toBe("150,000 USD");
    expect(claimValue({ value: 1500000, unit: "updates" })).toBe("1,500,000 updates");
  });
});

test("status counts", () => {
  expect(statusCounts([{ status: "pending" }, { status: "approved" }, { status: "pending" }]))
    .toEqual({ pending: 2, approved: 1, rejected: 0, edited: 0 });
});

test("scope message is the spec text", () => {
  expect([DECK_SCOPE_INTRO, "We cannot read:", ...DECK_SCOPE_CANNOT.map((l) => `- ${l}`), DECK_SCOPE_OUTRO].join("\n")).toBe(
    "We read text from PowerPoint, Word and text-based PDF files.\n" +
    "We cannot read:\n" +
    "- Scanned PDFs, images or charts saved as pictures. There is no text in them to read, only pixels.\n" +
    "- Keynote files or Google Slides links. Please export them as PowerPoint or PDF first.\n" +
    "If a number you need sits in a picture, use Add claim and cite the page, or upload the source spreadsheet.",
  );
});

test("type labels", () => {
  expect(typeLabel("user_growth")).toBe("User growth");
  expect(typeLabel("gross_margin")).toBe("Gross margin");
  expect(typeLabel("customers")).toBe("Customers");
  expect(typeLabel("usage")).toBe("Usage");
});

test("every column has a header", () => {
  expect(COLUMNS).toEqual(["Type", "Value", "Period", "Confidence", "Claim in the deck", "Source", "Status", "Action"]);
});

test("instruction text is word for word", () => {
  expect([CLAIMS_HEADING, CLAIMS_INTRO, ...CLAIMS_CHOICES.map(([a, b]) => `${a} ${b}`)].join("\n")).toBe(
    "Claims found in the uploaded documents\n" +
    "These figures were extracted automatically and inform the growth plan. While errors are possible, you only need to check claims that look incorrect or implausible against their source slides before making your selection.\n" +
    "✓ Approve: Confirm this is a claim the company makes. It will be added to the claim register and tested against the data.\n" +
    "✎ Edit: Correct the figure, type, unit or date, then approve the claim. It will be added to the claim register and tested against the data.\n" +
    "✕ Reject: Exclude items that are not company claims, such as another company's figures, funds raised or chart axis labels. Rejected items remain in the record but are not used.",
  );
});

describe("Add claim form", () => {
  const draft = { claim_type: "revenue", value: "3600000", value_high: "", unit: "", currency: "usd", target_date: "2025", deck_id: "d1", page: "4", metric: "ARR" };
  test("source document and page are required, and so is the value", () => {
    expect(newClaimPayload(draft)).toEqual({ claim_type: "revenue", metric: "ARR", deck_id: "d1", page: 4, value: 3600000, value_high: null, unit: null, currency: "USD", target_date: "2025" });
    expect(newClaimPayload({ ...draft, page: "" })).toBeNull();
    expect(newClaimPayload({ ...draft, page: "0" })).toBeNull();
    expect(newClaimPayload({ ...draft, page: "1.5" })).toBeNull();
    expect(newClaimPayload({ ...draft, deck_id: "" })).toBeNull();
    expect(newClaimPayload({ ...draft, value: "" })).toBeNull();
    expect(newClaimPayload({ ...draft, metric: "" })).toBeNull();
  });
  test("a range keeps both ends", () => {
    expect(newClaimPayload({ ...draft, value: "2", value_high: "3" })).toMatchObject({ value: 2, value_high: 3 });
  });
});

describe("deck selector", () => {
  const decks = [
    { deck_id: "a", file: "older.pdf", uploaded_at: "2026-10-04T10:00:00.000001+00:00" },
    { deck_id: "b", file: "newer.pptx", uploaded_at: "2026-10-04T11:00:00.000001+00:00" },
  ];
  const candidates = [{ id: 1, deck_id: "b" }, { id: 2, deck_id: "a" }, { id: 3, deck_id: "a" }];

  test("defaults to the most recently uploaded deck", () => {
    expect(defaultDeck(decks)).toBe("b");
    expect(defaultDeck([])).toBe(ALL_DECKS);
  });

  test("one tab per deck plus All, each with its claim count, most recent deck first", () => {
    expect(deckTabs(decks, candidates)).toEqual([
      { id: ALL_DECKS, label: "All", count: 3 },
      { id: "b", label: "newer.pptx", count: 1 },
      { id: "a", label: "older.pdf", count: 2 },
    ]);
  });

  test("a tab shows its deck's claims in server order; All shows every claim", () => {
    expect(claimsForDeck(candidates, "a").map((c) => c.id)).toEqual([2, 3]);
    expect(claimsForDeck(candidates, ALL_DECKS).map((c) => c.id)).toEqual([1, 2, 3]);
  });

  test("remove confirmation text", () => {
    expect(REMOVE_DECK_CONFIRM).toBe("This deletes the deck and all its claims, including reviewed ones.");
  });
});

test("the analyst chooses among plan claim types only; old usage claims keep their label", () => {
  expect(CLAIM_TYPES).toEqual(["revenue", "revenue_growth", "growth", "retention", "sales", "customers", "users",
    "user_growth", "gross_margin", "gross_profit", "costs", "ebitda", "net_profit", "people", "product", "market",
    "cash", "burn", "runway", "ltv", "cac", "customer_lifetime", "ltv_cac", "trials_per_day", "months_to_profitability"]);
  // Issue #45 (deck-parser.md section 2): the new claim types and their labels.
  expect(["cash", "burn", "runway", "ltv", "cac", "customer_lifetime", "ltv_cac", "trials_per_day",
    "months_to_profitability"].map(typeLabel)).toEqual(["Cash", "Burn", "Runway", "LTV", "CAC", "Customer lifetime",
    "LTV/CAC", "Trials per day", "Months to profitability"]);
  expect([typeLabel("gross_profit"), typeLabel("costs"), typeLabel("ebitda"), typeLabel("net_profit")])
    .toEqual(["Gross profit", "Costs", "EBITDA", "Net profit"]);
  expect(typeLabel("usage")).toBe("Usage");
});

describe("a table row is one claim with its values by period (zero2hero page 19)", () => {
  const row = {
    claim_type: "users", value: null, target_date: null,
    by_period: [
      { value: 200, value_high: null, target_date: "2022", period: "Y/E 22" },
      { value: 5000, value_high: null, target_date: "2023", period: "Y/E 23" },
      { value: 20000, value_high: null, target_date: "2024", period: "Y/E 24" },
    ],
  };

  test("value and date columns", () => {
    expect(claimValue(row)).toBe("200 (FY2022) · 5,000 (FY2023) · 20,000 (FY2024)");
    expect(claimValue({ currency: "GBP", by_period: [{ value: 42638, target_date: "2022", period: "Y/E 22" }, { value: 50000, target_date: "2023" }] }))
      .toBe("42,638 GBP (FY2022) · 50,000 GBP (FY2023)");
    expect(claimPeriod(row)).toBe("FY2022–FY2024");
    expect(claimPeriod({ target_date: "2024-Q2" })).toBe("Q2 2024");
    expect(claimPeriod({ target_date: null })).toBe("no date");
    // The deck's own wording ("FY25", "Y/E 22") stays in the claim; the column has one format.
    expect(claimPeriod({ target_date: "2025", period_text: "FY25" })).toBe("FY2025");
    expect(claimPeriod({ by_period: [{ target_date: "2022", period_text: "Y/E 22" }, { target_date: "2023", period_text: "Y/E 23" }] }))
      .toBe("FY2022–FY2023");
  });

  test("editing one value sends every period, the others unchanged", () => {
    expect(rowEdit(row, ["200", "6000", "20000"])).toEqual([
      { value: 200, value_high: null, target_date: "2022" },
      { value: 6000, value_high: null, target_date: "2023" },
      { value: 20000, value_high: null, target_date: "2024" },
    ]);
  });

  test("inconsistency label", () => {
    expect(INCONSISTENCY_LABEL).toBe("Deck inconsistency");
  });
});

describe("model readings in the approval list (docs/specs/llm-structure-reading.md)", () => {
  test("a reading cites its structure and cell", () => {
    expect(sourceRef({ file: "plan.pdf", page: 19, kind: "structure", structure: "table", table: 1, cell: "r4c3" }))
      .toBe("plan.pdf · page 19 · table 1, cell r4c3");
    expect(sourceRef({ file: "plan.pdf", page: 19, kind: "structure", structure: "kpi_panel", cell: "r2c1" }))
      .toBe("plan.pdf · page 19 · KPI panel, cell r2c1");
  });

  test("every row is labelled Verified or AI suggestion, not verified", () => {
    expect(VERIFIED_LABEL).toBe("Verified");
    expect(AI_SUGGESTION_LABEL).toBe("AI suggestion, not verified");
    expect(typeLabel("use_of_funds")).toBe("Use of funds");
    expect(CLAIM_TYPES).not.toContain("use_of_funds");
  });

  test("the deck panel shows the status, the slides sent and the cost", () => {
    expect(deckRunLog({ ai_status: "waiting" })).toEqual(["AI reading: waiting for revenue file"]);
    expect(deckRunLog({ ai_status: "read", page_unit: "slide", sent_pages: [4, 7, 12], ai_cost_usd: 0.0123 }))
      .toEqual(["AI reading: read", "Sent to the model: slides 4, 7, 12", "Cost: $0.01"]);
    expect(deckRunLog({ ai_status: "stopped", ai_message: "AI reading stopped: this audit reached its 400,000-token limit. The remaining structures were read by Python only." }))
      .toEqual(["AI reading: not read", "AI reading stopped: this audit reached its 400,000-token limit. The remaining structures were read by Python only."]);
    expect(deckRunLog({})).toEqual([]);
  });

  test("the run log counts the periods Python corrected from the header cells", () => {
    expect(deckRunLog({ ai_status: "read", periods_corrected: 2 }))
      .toEqual(["AI reading: read", "Periods corrected from the header cells: 2"]);
    expect(deckRunLog({ ai_status: "read", periods_corrected: 0 })).toEqual(["AI reading: read"]);
  });

  test("a deck uploaded while AI reading was off says to re-upload it once reading is on", () => {
    const line = "Uploaded before AI reading was enabled; re-upload to read.";
    expect(UPLOADED_BEFORE_CONSENT).toBe(line);
    expect(deckRunLog({ ai_status: "python_only", uploaded_before_consent: true })).toEqual(["AI reading: not read", line]);
    expect(deckRunLog({ uploaded_before_consent: true })).toEqual(["AI reading: not read", line]);
    expect(deckRunLog({ ai_status: "python_only", uploaded_before_consent: false }))
      .toEqual(["AI reading: not read (AI-assisted reading is off for this audit)"]);
  });
});

describe("structure labelling in the approval list (docs/specs/structure-labelling.md)", () => {
  const hours = {
    value: 2500, unit: "hours",
    readings: [{ value: 2500, dot_reading: "thousands", bracket_reading: null },
      { value: 2.5, dot_reading: "decimal", bracket_reading: null }],
  };

  test("an ambiguous figure shows both readings, Python's default first and pre-selected", () => {
    expect(readingChoices(hours)).toEqual([
      { value: 2500, label: "2,500 hours (thousands)", selected: true },
      { value: 2.5, label: "2.5 hours (decimal)", selected: false },
    ]);
    const loss = { value: -1200, currency: "GBP", readings: [{ value: -1200, dot_reading: null, bracket_reading: "negative" },
      { value: 1200, dot_reading: null, bracket_reading: "positive" }] };
    expect(readingChoices(loss).map((r) => r.label)).toEqual(["-1,200 GBP (negative)", "1,200 GBP (positive)"]);
  });

  test("a figure with one reading offers no choice", () => {
    expect(readingChoices({ value: 5000, readings: [] })).toEqual([]);
    expect(readingChoices({ value: 5000 })).toEqual([]);
    expect(readingChoices({ value: 5000, readings: [{ value: 5000, dot_reading: null, bracket_reading: null }] })).toEqual([]);
  });

  test("an item labelled other is listed as type Other and needs a type before it can be approved", () => {
    expect(typeLabel("other")).toBe("Other");
    expect(CLAIM_TYPES).not.toContain("other");
    expect(needsType({ claim_type: "other" })).toBe(true);
    expect(needsType({ claim_type: "product" })).toBe(false);
    expect(OTHER_TYPE_NOTE).toBe("Choose a claim type, then approve.");
  });

  test("a figure no heading names a type for is listed as 'Unknown – choose type' and needs a type before approval", () => {
    expect(UNKNOWN_TYPE_LABEL).toBe("Unknown – choose type");
    expect(typeLabel("unknown")).toBe("Unknown – choose type");
    expect(CLAIM_TYPES).not.toContain("unknown");
    expect(needsType({ claim_type: "unknown" })).toBe(true);
  });

  test("'Market size' is in the type list the analyst chooses from", () => {
    expect(CLAIM_TYPES).toContain("market");
    expect(typeLabel("market")).toBe("Market size");
    expect(CLAIM_TYPES.map(typeLabel)).toContain("Market size");
  });

  test("the confidence column shows the server's text: the level and the failed checks", () => {
    expect(confidenceText({ confidence: { level: "Low", failed: ["no date", "no heading"], text: "Low – no date, no heading" } })).toBe("Low – no date, no heading");
    expect(confidenceText({ confidence: { level: "High", failed: [], text: "High" } })).toBe("High");
    expect(confidenceText({})).toBe("—");
  });
});

describe("2026-10-08: the Period column, groups, a direction with no figure and a claim in another currency", () => {
  test.each([
    [{ target_date: "2023" }, "FY2023"], [{ target_date: "2024-Q2" }, "Q2 2024"], [{ target_date: "2024-H1" }, "H1 2024"],
    [{ target_date: "2024-06" }, "Jun 2024"], [{ target_date: "2024-06-30" }, "30 Jun 2024"],
    [{ target_date: "FY2025-04", period_start: "2024-04-01" }, "Apr 2024"],
  ])("%j reads %s", (claim, label) => expect(claimPeriod(claim)).toBe(label));

  test("a year label found under a bar replaces \"per year\"; it stays only when no label is found", () => {
    expect(claimPeriod({ target_date: "2023", period_basis: "per year" })).toBe("FY2023");
    expect(claimPeriod({ target_date: null, period_basis: "per year" })).toBe("per year");
    expect(claimPeriod({ target_date: "2024", period_basis: "per month" })).toBe("FY2024 · per month");
    expect(claimPeriod({ by_period: [{ target_date: "2023" }, { target_date: "2025" }], period_basis: "per year" })).toBe("FY2023–FY2025");
  });

  test("\"no date\" only when the deck gives no period", () => {
    expect(claimPeriod({ target_date: null })).toBe("no date");
    expect(claimPeriod({})).toBe("no date");
    expect(periodLabel({ target_date: "0001-01-01" })).toBe("", "a date outside the range is never shown");
  });

  test("the groups, in order; Unknown and Other are collapsed; an empty group is not listed", () => {
    const claims = ["c", "a", "b"].map((id, i) => ({ id, group: [5, 1, 6][i] }));
    expect(claimSections(claims).map((s) => [s.group, s.title, s.claims.map((c) => c.id), s.collapsed])).toEqual([
      [1, "Revenue, ARR, MRR and bookings", ["a"], false], [5, "Market size", ["c"], false], [6, "Unknown – choose type", ["b"], true]]);
    expect(claimSections([{ id: "z" }])[0]).toMatchObject({ group: 7, title: "Other", collapsed: true });
    expect(claimSections([{ id: "p", group: 4 }])[0]).toMatchObject({ title: "Hiring and roadmap", collapsed: false });
    expect(claimSections([{ id: "p", group: 3 }])[0].title).toBe("Customers, users, usage, retention and sales");
    expect(claimSections([]).length).toBe(0);
  });

  test("a direction with no figure reads positive (no figure); a figure typed over it reads as a figure", () => {
    expect(directionText("negative")).toBe("negative (no figure)");
    expect(claimValue({ value: null, claim_direction: "positive" })).toBe("positive (no figure)");
    expect(claimValue({ value: 3, unit: "%", claim_direction: null })).toBe("3%");
    expect(claimValue({ value: null })).toBe("—");
  });

  test("both figures for another currency; no saved rate says so; the audit's own currency is unchanged", () => {
    const fx = { rate: 1.14, date: "2026-06-30", currency: "EUR" };
    // Whole units, no rate and no rate date in the text: they are on hover.
    expect(claimValue({ value: 150000, currency: "GBP", fx })).toBe("150,000 GBP (171,000 EUR)");
    expect(claimValue({ value: 550508, currency: "GBP", fx: { ...fx, rate: 1.15 } })).toBe("550,508 GBP (633,084 EUR)");
    expect(claimValue({ value: 100, currency: "GBP", fx: { ...fx, rate: 1.1349 } })).toBe("100 GBP (113 EUR)");
    expect(claimValue({ value: 150000, value_high: 160000, currency: "GBP", fx })).toBe("150,000–160,000 GBP (171,000–182,400 EUR)");
    expect(conversionHover({ currency: "GBP", fx })).toBe("Rate used: 1 GBP = 1.14 EUR on 30 Jun 2026");
    expect(conversionHover({ currency: "GBP", fx: { ...fx, rate: null } })).toBeNull();
    expect(conversionHover({ currency: "EUR", fx: null })).toBeNull();
    expect(claimValue({ value: 150000, currency: "BRL", fx: { ...fx, rate: null } }))
      .toBe("150,000 BRL (BRL→EUR rate missing – enter it in FX settings at the top of the page)");
    expect(claimValue({ value: 150000, currency: "EUR", fx: null })).toBe("150,000 EUR");
    expect(claimValue({ value: 15, unit: "%", currency: null, fx: null })).toBe("15%");
  });
});
