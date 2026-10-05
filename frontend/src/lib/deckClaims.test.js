import {
  ALL_DECKS, CLAIM_TYPES, INCONSISTENCY_LABEL, REMOVE_DECK_CONFIRM, claimDate, claimsForDeck, deckTabs, defaultDeck, CLAIMS_CHOICES, CLAIMS_HEADING, CLAIMS_INTRO, COLUMNS, claimValue, rowEdit, sourceRef, statusCounts, typeLabel,
  DECK_SCOPE_CANNOT, DECK_SCOPE_INTRO, DECK_SCOPE_OUTRO,
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
    "If a number you need sits in a picture, add it as text or send the source spreadsheet.",
  );
});

test("type labels", () => {
  expect(typeLabel("user_growth")).toBe("User growth");
  expect(typeLabel("gross_margin")).toBe("Gross margin");
  expect(typeLabel("customers")).toBe("Customers");
  expect(typeLabel("usage")).toBe("Usage");
});

test("every column has a header", () => {
  expect(COLUMNS).toEqual(["Type", "Value", "Date", "Claim in the deck", "Source", "Status", "Action"]);
});

test("instruction text is word for word", () => {
  expect([CLAIMS_HEADING, CLAIMS_INTRO, ...CLAIMS_CHOICES.map(([a, b]) => `${a} ${b}`)].join("\n")).toBe(
    "Claims found in the deck\n" +
    "These figures may inform the growth plan. They were identified automatically and may contain errors. Check each claim against its source slide, then choose:\n" +
    "✓ Approve: Confirm this is a claim the company makes. It will be added to the claim register and tested against the data.\n" +
    "✎ Edit: Correct the figure, type, unit or date, then approve the claim. It will be added to the claim register and tested against the data.\n" +
    "✕ Reject: Exclude items that are not company claims, such as another company's figures, funds raised or chart axis labels. Rejected items remain in the record but are not used.",
  );
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
    "user_growth", "gross_margin", "gross_profit", "costs", "ebitda", "net_profit", "people", "product", "market"]);
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
    expect(claimValue(row)).toBe("200 (Y/E 22) · 5,000 (Y/E 23) · 20,000 (Y/E 24)");
    expect(claimValue({ currency: "GBP", by_period: [{ value: 42638, period: "Y/E 22" }, { value: 50000, period: "Y/E 23" }] }))
      .toBe("42,638 GBP (Y/E 22) · 50,000 GBP (Y/E 23)");
    expect(claimDate(row)).toBe("2022–2024");
    expect(claimDate({ target_date: "2024-Q2" })).toBe("2024-Q2");
    expect(claimDate({ target_date: null })).toBe("—");
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
