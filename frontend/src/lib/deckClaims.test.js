import { claimValue, sourceRef, statusCounts, DECK_SCOPE_CANNOT, DECK_SCOPE_INTRO, DECK_SCOPE_OUTRO } from "./deckClaims";

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
