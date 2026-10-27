import texts from "./claims_list_texts.json";
import evidenceLabels from "./evidence_labels.json";
import { COLUMNS, columnText, confidenceReasons, flagsText, typeCellLines } from "./deckClaims";

const FLAGS = ["value not on page", "currency assumed", "unit assumed", "scenario label not on page", "period not on page", "page out of range",
  "use-of-funds share", "acquisition channel", "turnover not revenue", "year under bar differs", "pipeline column", "axis tick", "not a plan line",
  "matches analyst claim", "basis and scenario disagree", "basis conflicts with period", "cell corrected", "sign not on page", "period from page heading",
  "period from another cell", "period is a range", "growth dated to start year", "label mismatch", "sources disagree", "source ambiguous",
  "source not associated", "extraction incomplete"];

describe("claims list texts", () => {
  test("the columns are in the agreed order: confidence after Source, before Status", () => {
    expect(COLUMNS).toEqual(["Type", "Value", "Period", "Claim in the deck", "Source", "Extraction confidence", "Status", "Action"]);
  });
  test("every heading has a pop-up text in the one shared file", () => {
    COLUMNS.forEach((c) => { expect(texts.columns[c]).toBeTruthy(); expect(columnText(c)).toBe(texts.columns[c]); });
    expect(Object.keys(texts.columns).sort()).toEqual([...COLUMNS].sort());
  });
  test("the confidence pop-up starts with the pinned explainer", () => {
    expect(texts.columns["Extraction confidence"].startsWith(evidenceLabels.explainers.extraction_confidence)).toBe(true);
  });
  test("a plain explanation for every flag word and check word the server can name", () => {
    [...FLAGS, "not matched", "no date", "no figure", "no unit", "no heading", "not corroborated"].forEach((w) => expect(texts.reasons[w]).toBeTruthy());
  });
  const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
  test("the confidence reason lines follow the server's failed checks, one line each, and never repeat the level (George, 2026-10-27)", () => {
    expect(confidenceReasons({ confidence: { level: "Medium", failed: ["period from another cell"], text: "Medium – period from another cell" } }))
      .toEqual([cap(texts.reasons["period from another cell"])]);
    expect(confidenceReasons({ confidence: { level: "Low", failed: ["no date", "no heading"], text: "Low – no date, no heading" } }))
      .toEqual([cap(texts.reasons["no date"]), cap(texts.reasons["no heading"])]);
    expect(confidenceReasons({ confidence: { level: "High", failed: [], text: "High" } })).toEqual([cap(texts.reasons.High.replace("High – ", ""))]);
    expect(confidenceReasons({ confidence: { level: null, failed: [], text: "Analyst-entered" } })).toEqual([cap(texts.reasons["Analyst-entered"].replace("Analyst-entered – ", ""))]);
    expect(confidenceReasons({ confidence: { level: "Medium", failed: ["year label below: 2022"], text: "x" } })[0]).toContain("2022");
    expect(confidenceReasons({})).toEqual([]);
    ["High", "Medium", "Low", "Analyst-entered", "Analyst-edited"].forEach((level) => {
      const lines = confidenceReasons({ confidence: { level: level.startsWith("Analyst") ? null : level, failed: [], text: level.startsWith("Analyst") ? level : level } });
      lines.forEach((line) => expect(line.startsWith(level)).toBe(false));
    });
  });
  test("two checks that share a text give it once", () => {
    expect(confidenceReasons({ confidence: { level: "Low", failed: ["not matched", "value not on page"], text: "Low" } })).toEqual([cap(texts.reasons["not matched"])]);
  });
  test("a label mismatch reads as the question on screen, never as the closed word", () => {
    expect(flagsText({ flags: ["label mismatch"] })).toBe("The app could not confidently link this figure to its label. Which label describes it?");
    expect(flagsText({ flags: ["currency assumed", "label mismatch"] })).toBe(`${texts.reasons["currency assumed"]} · The app could not confidently link this figure to its label. Which label describes it?`);
  });
  test("two flags that map to the same text show it once", () => {
    expect(flagsText({ flags: ["value not on page", "label mismatch", "value not on page"] })).toBe(`${texts.reasons["value not on page"]} · ${texts.label_mismatch_question}`);
  });
  test("the type cell: segment after the type, a part-of line for a part of a group", () => {
    expect(typeCellLines({ claim_type: "revenue" })).toEqual({ title: "Revenue", partOf: null });
    expect(typeCellLines({ claim_type: "revenue", made_of: { segment: "Platform Subscriptions", part_of: "part of ARR 2025 total" } }))
      .toEqual({ title: "Revenue · Platform Subscriptions", partOf: "part of ARR 2025 total" });
  });
});
