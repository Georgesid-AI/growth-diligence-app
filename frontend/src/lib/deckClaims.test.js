import {
  ALL_DECKS, AI_SUGGESTION_LABEL, CLAIM_TYPES, INCONSISTENCY_LABEL, VERIFIED_LABEL, badgeText, deckRunLog, deckReadLine, aiReadStatus, REMOVE_DECK_CONFIRM, claimPeriod, conversionHover, claimSections, claimsForDeck, periodLabel, directionText, deckTabs, defaultDeck, CLAIMS_CHOICES, CLAIMS_HEADING, CLAIMS_INTRO, COLUMNS, claimValue, rowEdit, newClaimPayload, sourceRef, statusCounts, typeLabel,
  countLine, statusText, STATUS_LABELS, DECK_SCOPE_CANNOT, DECK_SCOPE_CANNOT_LEAD, DECK_SCOPE_INTRO, isDeckFile, DECK_SCOPE_OUTRO, EDIT_TYPES, isOther, readingChoices, confidenceText, otherFiguresTitle,
  claimFields, editLogText, CONSENT_OFF_LINE,
  CLAIMS_VIEW, REVIEW_VIEW, VIEW_LABELS, REVIEW_INTRO, claimsForView, isFlagged, flagsText, INFORMATIONAL_FLAGS,
  CLAIM_GROUPS, COLLAPSED_BY_DEFAULT, SCENARIO_GROUP, PROMPT_MISSING_LINE, scenarioText, isCase,
} from "./deckClaims";

describe("source reference", () => {
  test("slide, page, notes and table cell", () => {
    expect(sourceRef({ file: "board.pptx", slide: 5, kind: "text" })).toBe("board.pptx · slide 5");
    expect(sourceRef({ file: "board.pptx", slide: 2, kind: "notes" })).toBe("board.pptx · slide 2 · notes");
    expect(sourceRef({ file: "plan.pdf", page: 19, kind: "table", table: 1, row: 4, col: 2 }))
      .toBe("plan.pdf · page 19 · table 1, row 4, col 2");
    expect(sourceRef({ file: "plan.docx", page: 6, kind: "text" })).toBe("plan.docx · page 6");
    // a forecast table's cell (chat-upload.md section 20): the file, then sheet!cell, never "page undefined"
    expect(sourceRef({ file: "plan.csv", sheet: "Plan", cell: "E5", kind: "sheet" })).toBe("plan.csv · Plan!E5");
    expect(sourceRef({ file: "plan.csv", sheet: "Plan", cell: "H5:S5", kind: "sheet" })).toBe("plan.csv · Plan!H5:S5");
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
    .toEqual({ pending: 2, approved: 1, rejected: 0, edited: 0, auto: 0 });
});

test("scope message is the spec text", () => {
  expect([DECK_SCOPE_INTRO, DECK_SCOPE_CANNOT_LEAD, ...DECK_SCOPE_CANNOT.map((l) => `- ${l}`), DECK_SCOPE_OUTRO].join("\n")).toBe(
    "Upload PowerPoint, Word and text-based PDF files.\n" +
    "The app cannot read:\n" +
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
  // George, 2026-10-20: unit economics per account or user, and the pipeline columns of a deck table.
  expect(["arpa", "arpu", "pipeline"].map(typeLabel)).toEqual(["ARPA", "ARPU", "Pipeline"]);
});

test("every column has a header", () => {
  expect(COLUMNS).toEqual(["Type", "Value", "Period", "Claim in the deck", "Source", "Extraction confidence", "Status", "Action"]);
});

test("instruction text is word for word", () => {
  expect([CLAIMS_HEADING, CLAIMS_INTRO, ...CLAIMS_CHOICES.map(([a, b]) => `${a} ${b}`)].join("\n")).toBe(
    "Claims found in the uploaded documents\n" +
    "These figures were read from the uploaded documents and tested against the data automatically. Errors are possible: check only the claims that look incorrect or implausible against their source slides, or that wait for your answer.\n" +
    "✓ Keep: Shown on a claim a check asks about: confirm this is a claim the company makes. It is then tested against the data and enters the claim register.\n" +
    "✎ Edit: Correct the figure, type, unit or date. The claim is tested again against the data.\n" +
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
  test("acquisition channels need the platform, send a count with no currency and no metric", () => {
    const channel = { ...draft, claim_type: "acquisition_channels", value: "30000", unit: "", currency: "usd", metric: "", target_date: "", label: " Telegram " };
    expect(newClaimPayload(channel)).toEqual({ claim_type: "acquisition_channels", label: "Telegram", unit: "count", deck_id: "d1", page: 4,
      value: 30000, value_high: null, currency: null, target_date: null });
    expect(newClaimPayload({ ...channel, label: "  " })).toBeNull();
    expect(newClaimPayload({ ...draft, label: "Telegram" })).toMatchObject({ metric: "ARR" });
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

  test("one tab per deck plus All, each with its claim count, in upload order: the new deck on the right", () => {
    expect(deckTabs(decks, candidates)).toEqual([
      { id: ALL_DECKS, label: "All", count: 3 },
      { id: "a", label: "older.pdf", count: 2 },
      { id: "b", label: "newer.pptx", count: 1 },
    ]);
    // The server sends the most recent deck first; a deck uploaded later is never moved ahead of an earlier one, whatever order they arrive in.
    const third = { deck_id: "c", file: "third.pdf", uploaded_at: "2026-10-04T12:00:00.000001+00:00" };
    expect(deckTabs([third, decks[1], decks[0]], []).map((t) => t.id)).toEqual([ALL_DECKS, "a", "b", "c"]);
    expect(deckTabs([decks[0], third, decks[1]], []).map((t) => t.id)).toEqual([ALL_DECKS, "a", "b", "c"]);
  });

  test("a tab shows its deck's claims in server order; All shows every claim", () => {
    expect(claimsForDeck(candidates, "a").map((c) => c.id)).toEqual([2, 3]);
    expect(claimsForDeck(candidates, ALL_DECKS).map((c) => c.id)).toEqual([1, 2, 3]);
  });

  test("remove confirmation text", () => {
    expect(REMOVE_DECK_CONFIRM).toBe("This deletes the deck and all its claims, including reviewed ones.");
  });
});

test("ARR, MRR, Churn, NRR and CAC payback are types of their own, in the Type column and in the edit dropdown (engine contract 8)", () => {
  expect(["arr", "mrr", "churn", "nrr", "cac_payback"].map(typeLabel)).toEqual(["ARR", "MRR", "Churn", "NRR", "CAC payback"]);
  expect(EDIT_TYPES).toEqual(expect.arrayContaining(["arr", "mrr", "churn", "nrr", "cac_payback"]));
  expect(typeLabel("revenue")).toBe("Revenue");
  expect(typeLabel("retention")).toBe("Retention");
  const group = (g) => CLAIM_GROUPS.find(([n]) => n === g)[1];
  expect(group(1)).toBe("Revenue, ARR, MRR and bookings");
  expect(group(3)).toBe("Customers, users, usage, retention and sales");
});

test("the analyst chooses among plan claim types only; old usage claims keep their label", () => {
  expect(CLAIM_TYPES).toEqual(["revenue", "arr", "mrr", "revenue_growth", "growth", "retention", "churn", "nrr", "sales", "customers", "users",
    "user_growth", "gross_margin", "gross_profit", "costs", "ebitda", "net_profit", "people", "product", "market",
    "cash", "burn", "runway", "ltv", "cac", "cac_payback", "customer_lifetime", "ltv_cac", "trials_per_day", "months_to_profitability",
    "arpa", "arpu", "pipeline", "acquisition_channels"]);
  expect(typeLabel("acquisition_channels")).toBe("Acquisition channels");
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
    expect(badgeText(VERIFIED_LABEL)).toBe("Matched to page");
    expect(badgeText(AI_SUGGESTION_LABEL)).toBe("AI suggestion, not matched");
    expect(typeLabel("use_of_funds")).toBe("Use of funds");
    expect(CLAIM_TYPES).not.toContain("use_of_funds");
  });

  test("the deck panel shows the status and the slides sent, never a cost", () => {
    expect(deckRunLog({ ai_status: "waiting" })).toEqual(["AI reading: waiting for revenue file"]);
    expect(deckRunLog({ ai_status: "read", page_unit: "slide", sent_pages: [4, 7, 12], ai_cost_usd: 0.0123 }))
      .toEqual(["AI reading: read", "Sent to the model: slides 4, 7, 12"]);
    expect(deckRunLog({ ai_status: "stopped", ai_message: "AI reading stopped: this audit reached its 400,000-token limit. The remaining structures were read by Python only." }))
      .toEqual(["AI reading: not read", "AI reading stopped: this audit reached its 400,000-token limit. The remaining structures were read by Python only."]);
    expect(deckRunLog({})).toEqual([]);
  });

  test("the deck line reads 'N pages parsed · M with figures · AI read: <status>' with each status (George, 2026-10-23)", () => {
    const deck = { pages: 24, page_unit: "page", figure_pages: 9 };
    const line = (extra) => deckReadLine({ ...deck, ...extra });
    expect(line({ ai_status: "waiting" })).toBe("24 pages parsed · 9 with figures · AI read: waiting for revenue file");
    expect(line({ ai_status: "reading" })).toBe("24 pages parsed · 9 with figures · AI read: queued");
    expect(line({ ai_status: "reading", read_progress: { done: 0, total: 9 } })).toBe("24 pages parsed · 9 with figures · AI read: page 1 of 9");
    expect(line({ ai_status: "reading", read_progress: { done: 5, total: 9 } })).toBe("24 pages parsed · 9 with figures · AI read: page 6 of 9");
    expect(line({ ai_status: "reading", read_progress: { done: 9, total: 9 } })).toBe("24 pages parsed · 9 with figures · AI read: page 9 of 9");
    expect(line({ ai_status: "read", pages_read: 7, pages_rejected: 2 })).toBe("24 pages parsed · 9 with figures · AI read: done, 7 read, 2 rejected");
    expect(line({ ai_status: "not_read", pages_read: 0, pages_rejected: 9 })).toBe("24 pages parsed · 9 with figures · AI read: done, 0 read, 9 rejected");
    expect(line({ ai_status: "read" })).toBe("24 pages parsed · 9 with figures · AI read: done, 0 read, 0 rejected");
    expect(line({ ai_status: "python_only" })).toContain("AI read: not run");
    expect(aiReadStatus({ ai_status: "reading", read_progress: { done: 0, total: 0 } })).toBe("queued");
    expect(deckReadLine({ pages: 3, page_unit: "slide", figure_pages: 0, ai_status: "read", pages_read: 0, pages_rejected: 0 })).toMatch(/^3 slides parsed · 0 with figures/);
    for (const status of ["waiting", "reading", "read", "not_read"]) expect(line({ ai_status: status })).not.toMatch(/pages read/);
  });

  test("the run log's first line is the deck line when the page read stored the pages with figures, else the former line", () => {
    expect(deckRunLog({ ai_status: "read", pages: 5, page_unit: "page", figure_pages: 3, pages_read: 3, pages_rejected: 0, sent_pages: [2, 3, 4] }))
      .toEqual(["5 pages parsed · 3 with figures · AI read: done, 3 read, 0 rejected", "Sent to the model: pages 2, 3, 4"]);
    expect(deckRunLog({ ai_status: "waiting", pages: 5, page_unit: "page", figure_pages: 3 })).toEqual(["5 pages parsed · 3 with figures · AI read: waiting for revenue file"]);
    expect(deckRunLog({ ai_status: "waiting", pages: 5 })).toEqual(["AI reading: waiting for revenue file"]);
  });

  test("a deck restarted after 10 minutes reads 'restarted' until its first page is read", () => {
    const deck = { ai_status: "reading", ai_message: "restarted", pages: 24, page_unit: "page", figure_pages: 9 };
    expect(deckRunLog(deck)).toEqual(["24 pages parsed · 9 with figures · AI read: restarted"]);
    expect(deckRunLog({ ...deck, read_progress: { done: 0, total: 9 } })).toEqual(["24 pages parsed · 9 with figures · AI read: page 1 of 9"]);
    expect(deckRunLog({ ...deck, ai_message: null })).toEqual(["24 pages parsed · 9 with figures · AI read: queued"]);
    expect(deckRunLog({ ai_status: "reading", ai_message: "restarted" })).toEqual(["AI reading: restarted"]);
  });

  test("the run log names the skipped pages and each page not read, after the deck line (the status wording is the deck line's)", () => {
    expect(deckRunLog({ ai_status: "read", pages: 24, page_unit: "page", figure_pages: 11, pages_read: 9, pages_rejected: 2, skipped_pages: [3, 7, 20], unread_pages: [5, 9] }))
      .toEqual(["24 pages parsed · 11 with figures · AI read: done, 9 read, 2 rejected",
        "Skipped pages 3, 7, 20: no numbers in the page text.", "page 5 not read", "page 9 not read"]);
    expect(deckRunLog({ ai_status: "read", pages: 5, page_unit: "page", figure_pages: 5, pages_read: 5, pages_rejected: 0, skipped_pages: [], unread_pages: [] }))
      .toEqual(["5 pages parsed · 5 with figures · AI read: done, 5 read, 0 rejected"]);
    // the last run's unread pages are not shown while a new one reads
    expect(deckRunLog({ ai_status: "reading", pages: 5, page_unit: "page", figure_pages: 5, read_progress: { done: 1, total: 4 }, unread_pages: [4] }))
      .toEqual(["5 pages parsed · 5 with figures · AI read: page 2 of 4"]);
  });

  test("the run log counts the periods Python corrected from the header cells", () => {
    expect(deckRunLog({ ai_status: "read", periods_corrected: 2 }))
      .toEqual(["AI reading: read", "Periods corrected from the header cells: 2"]);
    expect(deckRunLog({ ai_status: "read", periods_corrected: 0 })).toEqual(["AI reading: read"]);
  });

  test("a deck not read because AI reading is off says so in one line (George, 2026-10-22), and no line asks for a re-upload (it is read when reading is ticked)", () => {
    expect(deckRunLog({ ai_status: "python_only", ai_message: CONSENT_OFF_LINE })).toEqual([CONSENT_OFF_LINE]);
    // the former path (DECK_PIPELINE=rules) still lists claims at upload: the server sends no message, and the old line stands
    expect(deckRunLog({ ai_status: "python_only", ai_message: null })).toEqual(["AI reading: not read (AI-assisted reading is off for this audit)"]);
    expect(CONSENT_OFF_LINE).toBe("Deck not read. AI-assisted reading is off for this audit, so no claims were extracted. Tick consent on the Upload page to read it, or use Add claim.");
    expect(deckRunLog({ ai_status: "python_only", ai_message: CONSENT_OFF_LINE, sent_pages: [3] })).toEqual([CONSENT_OFF_LINE]);
    expect(deckRunLog({ ai_status: "python_only", ai_message: CONSENT_OFF_LINE, uploaded_before_consent: true }).join(" ")).not.toContain("re-upload");
    expect(deckRunLog({})).toEqual([]);
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

  test("an item labelled other and a figure with no type are both Other; the editor may type a claim Other (claim-types-and-correction.md 4)", () => {
    expect(typeLabel("other")).toBe("Other");
    expect(typeLabel("unknown")).toBe("Other");
    expect(CLAIM_TYPES).not.toContain("other");
    expect(CLAIM_TYPES).not.toContain("unknown");
    expect(EDIT_TYPES).toContain("other");
    expect([isOther({ claim_type: "other" }), isOther({ claim_type: "unknown" }), isOther({ claim_type: "product" })]).toEqual([true, true, false]);
  });

  test("an Other figure is not a claim that waits for an answer: it is not counted", () => {
    const claims = [{ id: 1, status: "pending", claim_type: "revenue" }, { id: 2, status: "pending", claim_type: "unknown" },
      { id: 3, status: "pending", claim_type: "other" }];
    expect(statusCounts(claims).pending).toBe(1);
    expect([otherFiguresTitle(1), otherFiguresTitle(3)]).toEqual(["1 other figure", "3 other figures"]);
  });

  test("the editor opens on the stored field, else the one the register reads, else Unknown; the Status hover lists the edit log", () => {
    expect(claimFields({ figure_type: "target", claim_fields: { figure_type: "actual" } }).figure_type).toBe("target");
    expect(claimFields({ claim_fields: { figure_type: "actual", population: "paying", growth_basis: "yoy" } }))
      .toEqual({ figure_type: "actual", population: "paying", growth_basis: "yoy" });
    expect(claimFields({})).toEqual({ figure_type: "unknown", population: "", growth_basis: "unknown" });
    expect(editLogText({ edit_log: [{ field: "figure_type", previous: "target", value: "actual", by: "analyst", at: "2026-10-15T09:00:00+00:00",
      reason: "parser_misread" }] })).toBe("Figure type: Target → Actual · analyst · 15 Oct 2026 · Parser misread the deck");
    expect(editLogText({})).toBe("");
  });

  test("'Market size' is in the type list the analyst chooses from", () => {
    expect(CLAIM_TYPES).toContain("market");
    expect(typeLabel("market")).toBe("Market size");
    expect(CLAIM_TYPES.map(typeLabel)).toContain("Market size");
  });

  test("the confidence column shows the level once; the reasons are on their own lines (George, 2026-10-27)", () => {
    expect(confidenceText({ confidence: { level: "Low", failed: ["no date", "no heading"], text: "Low – no date, no heading" } })).toBe("Low");
    expect(confidenceText({ confidence: { level: "High", failed: [], text: "High" } })).toBe("High");
    expect(confidenceText({ confidence: { level: null, failed: [], text: "Analyst-edited" } })).toBe("Analyst-edited");
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

  test("the groups, in order; Other is collapsed under its count; an empty group is not listed", () => {
    const claims = ["c", "a", "b"].map((id, i) => ({ id, group: [5, 1, 9][i] }));
    expect(claimSections(claims).map((s) => [s.group, s.title, s.claims.map((c) => c.id), s.collapsed])).toEqual([
      [1, "Revenue, ARR, MRR and bookings", ["a"], false], [5, "Market size", ["c"], false], [9, "1 other figure", ["b"], true]]);
    expect(claimSections([{ id: "z" }])[0]).toMatchObject({ group: 9, title: "1 other figure", collapsed: true });
    expect(claimSections([7, 9, 8].map((group) => ({ id: `g${group}`, group }))).map((s) => [s.group, s.title, s.collapsed])).toEqual([
      [7, "Acquisition channels", false], [8, "Use of funds", true], [9, "1 other figure", true]]);
    expect(claimSections([10, 5].map((group) => ({ id: `g${group}`, group }))).map((s) => [s.group, s.title, s.collapsed])).toEqual([
      [5, "Market size", false], [10, "Pricing", true]]);   // George, 2026-10-23: Pricing and Use of funds start collapsed, after Market size and before Other
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


describe("the status of a claim once Python enters it (docs/design/simplified-flow.md section 2)", () => {
  test("the labels: needs your attention, in the register, rejected, edited; no claim 'to review' and none 'approved'", () => {
    expect(STATUS_LABELS).toEqual({ pending: "Needs your attention", approved: "In the register", rejected: "Rejected", edited: "Edited" });
  });
  test("the count line names what waits and how many Python entered on its own", () => {
    expect(countLine({ pending: 1, approved: 3, auto: 2, edited: 1, rejected: 0 })).toBe("1 needs your attention · 3 in the register (2 auto) · 1 edited · 0 rejected");
    expect(countLine({ pending: 2, approved: 3, auto: 0, edited: 0, rejected: 1 })).toBe("2 need your attention · 3 in the register · 0 edited · 1 rejected");
  });
  test("a claim Python entered reads Entered by the app; a re-opened claim carries its note", () => {
    expect(statusText({ status: "approved", auto_approval: "auto" })).toBe("Entered by the app");
    expect(statusText({ status: "approved", auto_approval: null })).toBe("In the register");
    expect(statusText({ status: "pending", auto_note: "Re-opened – a check now asks about it" })).toBe("Re-opened – a check now asks about it");
    expect(statusText({ status: "pending" })).toBe("Needs your attention");
  });
});

describe("installed units (chat-upload.md section 20)", () => {
  test("a claim read from a forecast table shows its type, which no type list offers", () => {
    expect(typeLabel("installed_units")).toBe("Installed units");
    expect(CLAIM_TYPES).not.toContain("installed_units");
    expect(EDIT_TYPES).not.toContain("installed_units");
  });
});

describe("stale results (George, 2026-10-20)", () => {
  test("a conversion date that would come from stale results reads Stale – re-run audit", () => {
    const fx = { rate: 1.14, date: null, date_stale: true, currency: "EUR" };
    expect(conversionHover({ currency: "GBP", fx })).toBe("Rate used: 1 GBP = 1.14 EUR on Stale – re-run audit");
  });
});

test("only .pptx, .docx and .pdf files are deck files, whatever the case", () => {
  expect(["a.pptx", "B.DOCX", "c.d.pdf"].map(isDeckFile)).toEqual([true, true, true]);
  expect(["a.key", "b.xlsx", "c.png", "pdf", "d.pdf.exe"].map(isDeckFile)).toEqual([false, false, false, false, false]);
});

describe("the Claims and Review views (George, 2026-10-22, docs/design/ai-reads-rules-check.md)", () => {
  const plain = { id: "p", flags: [] };
  const none = { id: "n" };
  const flagged = { id: "f", flags: ["currency assumed", "scenario label not on page"] };
  test("an informational flag (cell corrected) keeps the claim in the main list, its note shown on the row; any other flag sends it to Review", () => {
    const corrected = { id: "c", flags: ["cell corrected"] };
    const both = { id: "b", flags: ["cell corrected", "sign not on page"] };
    expect(INFORMATIONAL_FLAGS).toEqual(["cell corrected", "currency assumed", "unit assumed", "period from page heading", "period from another cell"]);
    expect(isFlagged({ id: "u", flags: ["currency assumed"] })).toBe(false);
    expect(isFlagged(corrected)).toBe(false);
    expect(isFlagged(both)).toBe(true);
    expect(claimsForView([corrected, both], CLAIMS_VIEW).map((c) => c.id)).toEqual(["c"]);
    expect(claimsForView([corrected, both], REVIEW_VIEW).map((c) => c.id)).toEqual(["b"]);
    expect(flagsText(corrected)).toBe("The figure was found in a different cell than the one cited");
  });
  test("George, 2026-10-23: the year label hint is informational (the claim stays in the main list, the note on its row), in the Review page and the panel alike", () => {
    const hinted = { id: "y", flags: ["year label below: 2022"] };
    const hintedAndCurrency = { id: "yc", flags: ["currency assumed", "year label below: 2024"] };
    const hintedAndSign = { id: "ys", flags: ["year label below: 2022", "sign not on page"] };
    const lookalike = { id: "l", flags: ["year label below: Q3 2022"] };
    expect([hinted, hintedAndCurrency].map(isFlagged)).toEqual([false, false]);
    expect([hintedAndSign, lookalike].map(isFlagged)).toEqual([true, true]);
    expect(claimsForView([hinted, hintedAndCurrency, hintedAndSign], CLAIMS_VIEW).map((c) => c.id)).toEqual(["y", "yc"]);
    expect(claimsForView([hinted, hintedAndCurrency, hintedAndSign], REVIEW_VIEW).map((c) => c.id)).toEqual(["ys"]);
    expect(flagsText(hinted)).toBe("The year label printed below the figure is 2022");
  });
  test("a claim with a flag is listed under Review and nowhere else; a claim without one under Claims", () => {
    expect(claimsForView([plain, flagged, none], CLAIMS_VIEW).map((c) => c.id)).toEqual(["p", "n"]);
    expect(claimsForView([plain, flagged, none], REVIEW_VIEW).map((c) => c.id)).toEqual(["f"]);
    expect(isFlagged(flagged)).toBe(true);
    expect(isFlagged(plain)).toBe(false);
    expect(isFlagged(none)).toBe(false);
  });
  test("the flags read as their plain texts, joined; the labels are Claims and Review", () => {
    expect(flagsText(flagged)).toBe("The app assigned a currency without an explicit currency label for this figure. Check the assumption. · The scenario (best, realistic, worst) is not written near the figure");
    expect(flagsText(plain)).toBe("");
    expect(VIEW_LABELS).toEqual({ claims: "Claims", review: "Review" });
    expect(REVIEW_INTRO).toBe("Flagged by the checks: the figure, its unit, its label or its page could not be confirmed on the slide. Each flag names what to check.");
  });
});

describe("the page reader's seven new metrics (George, 2026-10-23)", () => {
  test("Pricing is a type with a label and a group of its own, offered by the editor only on a claim that already has it", () => {
    expect(typeLabel("pricing")).toBe("Pricing");
    expect(CLAIM_TYPES).not.toContain("pricing");
    expect(CLAIM_GROUPS.find(([g]) => g === 10)[1]).toBe("Pricing");
    expect(CLAIM_GROUPS.map(([g]) => g).slice(4, 6)).toEqual([5, 10]);
    expect(COLLAPSED_BY_DEFAULT).toEqual([8, 9, 10]);
  });
});

describe("review of PR #164 (George, 2026-10-23)", () => {
  test("Scenarios is a section above Other and below Use of funds; only a best or worst case belongs there", () => {
    expect(SCENARIO_GROUP).toBe(6);
    expect(CLAIM_GROUPS.map(([g]) => g)).toEqual([1, 2, 3, 4, 5, 10, 7, 8, 6, 9]);
    expect(CLAIM_GROUPS.find(([g]) => g === 6)[1]).toBe("Scenarios");
    expect(isCase({ scenario: "best" })).toBe(true);
    expect(isCase({ scenario: "worst" })).toBe(true);
    expect(isCase({ scenario: "realistic" })).toBe(false);
    expect(isCase({ scenario: "none" })).toBe(false);
    expect(isCase({})).toBe(false);
  });
  test("the case a claim names is shown as a word, none for a claim with no scenario", () => {
    expect(scenarioText({ scenario: "best" })).toBe("Best case");
    expect(scenarioText({ scenario: "realistic" })).toBe("Realistic case");
    expect(scenarioText({ scenario: "worst" })).toBe("Worst case");
    expect(scenarioText({ scenario: "none" })).toBe("");
    expect(scenarioText({})).toBe("");
  });
  test("a deck whose prompt is missing reads one line, word for word", () => {
    expect(PROMPT_MISSING_LINE).toBe("AI reading not run – deck_reading prompt missing in prompt store");
    expect(deckRunLog({ ai_status: "prompt_missing", ai_message: PROMPT_MISSING_LINE })).toEqual([PROMPT_MISSING_LINE]);
  });
});
