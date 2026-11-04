import React, { act } from "react";
import { createRoot } from "react-dom/client";

import UploadSection from "./UploadSection";
import * as api from "@/lib/api";

/**
 * The top of the Upload page (docs/design/audit-page-mockup.html; docs/specs/chat-upload.md section 5): header, the two file cards, the run card.
 * Run with --no-cache (rule 25).
 */
jest.mock("@/lib/api", () => ({
  getDatasets: jest.fn(), getDecks: jest.fn(), getReview: jest.fn(), uploadChatFile: jest.fn(), uploadDeck: jest.fn(), removeDeck: jest.fn(),
  removeDataset: jest.fn(), rereadDataset: jest.fn(), rereadDeck: jest.fn(),
  runStage: jest.fn(), reportUsage: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({ useNavigate: () => jest.fn() }), { virtual: true });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const AUDIT = { id: "a1", company_name: "Tc", reporting_currency: "EUR", structure_reading_consent: true };
const SHEET = (over = {}) => ({ dtype: "file", file: "Testco_Revenue.xlsx", file_hash: "h1", size_bytes: 100, ext: "xlsx", read_state: "done", read_stage: null,
  read_elapsed: 107, read_checking_elapsed: 2, read_checked: 30, read_total: 30, read_matched: 28, read_items: 30, ...over });
const DECK = (over = {}) => ({ deck_id: "d1", file: "Board_deck_Q3.pdf", pages: 24, page_unit: "page", figure_pages: 17, skipped_pages: [1, 2, 3, 4, 5, 6, 7],
  ai_status: "read", read_elapsed: 72, ...over });

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
const all = (id) => [...document.body.querySelectorAll(`[data-testid="${id}"]`)];
let root, host;

async function mount({ sheets = [], decks = [], audit = AUDIT } = {}) {
  api.getDatasets.mockResolvedValue(sheets);
  api.getDecks.mockResolvedValue({ decks, candidates: [] });
  api.getReview.mockResolvedValue({ computed: false });
  api.reportUsage.mockResolvedValue({});
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<UploadSection audit={audit} onChanged={() => {}} onRunning={() => {}} />); });
  await act(async () => { await Promise.resolve(); });
}
const pickFiles = async (id, files) => {
  const input = q(id);
  Object.defineProperty(input, "files", { value: files, configurable: true });
  await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => { await Promise.resolve(); });
};
const follows = (a, b) => !!(q(a).compareDocumentPosition(q(b)) & Node.DOCUMENT_POSITION_FOLLOWING);

beforeEach(() => { jest.resetAllMocks(); });
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); jest.useRealTimers(); });

describe("the header and the explainer", () => {
  test("Company: <name> · <currency>, with no 'target not set'", async () => {
    await mount();
    expect(q("upload-company").textContent).toBe("Company: Tc · EUR");
    expect(document.body.textContent).not.toMatch(/target not set/i);
  });

  test("the explainer sentence is the mockup's, followed by the link that opens the full text", async () => {
    await mount();
    expect(q("reading-explainer").textContent).toBe(
      "Files are processed automatically using Anthropic's AI API and are not used for model training. Some identifying information is removed or replaced with codes, but names in free text and information visible in PDF deck images are sent unchanged. Processing starts on upload. By uploading, you consent to the processing described here. How your files are processed");
    expect(q("processing-text")).toBeNull();
    await act(async () => { q("processing-link").click(); });
    expect(q("processing-text").querySelector("h2").textContent).toBe("How your files are processed");
    expect(q("processing-text").querySelectorAll("p")).toHaveLength(4);
    expect([...q("processing-text").querySelectorAll("p b")].map((b) => b.textContent)).toEqual(
      ["Privacy protections and their limits:", "What is sent to the AI:", "Accuracy checks:", "Processing and storage:"]);
    expect(follows("upload-header", "processing-text")).toBe(true);
    expect(follows("processing-text", "sheet-card")).toBe(true);        // opens under the link, above the Financial data card
    await act(async () => { q("processing-link").click(); });
    expect(q("processing-text")).toBeNull();
  });

  test.each([[true, true], [false, false]])("the zero-data-retention sentence shows only when provider_zdr is true (%s)", async (zdr, shown) => {
    await mount({ audit: { ...AUDIT, provider_zdr: zdr } });
    await act(async () => { q("processing-link").click(); });
    const text = q("processing-text").textContent;
    expect(text.includes("Deck pages are processed by Anthropic under a zero-data-retention arrangement. Nothing is retained after the reply and nothing is used for training.")).toBe(shown);
    expect(q("processing-text").querySelector("p").textContent.endsWith("Nothing is retained after the reply and nothing is used for training.")).toBe(shown);   // appended to the first paragraph
    expect(text).not.toContain("Deck pages are sent to Anthropic's API for reading");
    expect(text).toContain("Processing starts automatically when you upload, without a separate confirmation step.");
  });
});

describe("the two cards", () => {
  test("Financial data and Board deck or growth plan carry the mockup's texts, a one-word Upload button and a dashed drop zone", async () => {
    await mount();
    expect(q("sheet-card").querySelector("h2").textContent).toBe("Financial data");
    expect(q("sheet-card").textContent).toContain("Required: a monthly revenue or ARR report. A P&L, revenue by customer or CRM export add more metrics. .xlsx or .csv");
    expect(q("sheet-upload").textContent).toBe("Upload");
    expect(q("sheet-drop").textContent).toBe("Drop files here");
    expect(q("deck-card").querySelector("h2").textContent).toBe("Board deck or growth plan");
    expect(q("deck-card").textContent).toContain("Board decks, investor updates, growth model or business plan. .pdf, .pptx or .docx · up to 8 documents");
    expect(q("deck-card").textContent).toContain("Page images work for PDF only – export PowerPoint or Word to PDF for the best read. Cannot read: scanned PDFs, images, Keynote or Google Slides links.");
    expect(q("deck-upload").textContent).toBe("Upload");
    expect(q("deck-drop").textContent).toBe("Drop documents here");
    expect(q("deck-note").textContent).toBe("Page images are sent without masking.");
    expect(follows("sheet-card", "deck-card")).toBe(true);
    expect(follows("deck-card", "run-audit-panel")).toBe(true);
    expect(q("sheet-drop").closest(".panel")).toBe(q("sheet-card"));
  });

  test("there is no AI reading tick box, no Map button, no paperclip and no chat bubbles", async () => {
    await mount({ sheets: [SHEET()] });
    expect(document.body.querySelector('input[type="checkbox"]')).toBeNull();
    for (const id of ["setup-consent-checkbox", "chat-map", "chat-paperclip", "chat-messages", "chat-analyst-bubble", "chat-drop-zone"]) expect(q(id)).toBeNull();
    expect(document.body.textContent).not.toContain("This window takes");
  });
});

describe("one line per file, with its stage tag", () => {
  test("Removing personal data: the first stage, with the elapsed time and no second line", async () => {
    await mount({ sheets: [SHEET({ read_state: "reading", read_stage: "removing_personal_data", read_elapsed: 3 })] });
    const row = q("sheet-file");
    expect(row.querySelector('[data-testid="file-tag"]').textContent).toBe("Removing personal data");
    expect(row.querySelector('[data-testid="file-time"]').textContent).toBe("Elapsed 0:03");
    expect(row.querySelector('[data-testid="file-sub"]')).toBeNull();
    expect(row.querySelector('[data-testid="file-name"]').textContent).toBe("Testco_Revenue.xlsx");
    expect(row.querySelector('[data-testid="file-remove"]').textContent).toBe("Remove");     // a stored spreadsheet is removed like a deck
  });

  test("Reading the sheet: the muted line says usually 1–3 minutes", async () => {
    await mount({ sheets: [SHEET({ read_state: "reading", read_stage: "reading_the_sheet", read_elapsed: 38 })] });
    expect(q("sheet-file").querySelector('[data-testid="file-tag"]').textContent).toBe("Reading the sheet");
    expect(q("sheet-file").querySelector('[data-testid="file-sub"]').textContent).toBe("usually 1–3 minutes");
    expect(q("sheet-file").querySelector('[data-testid="file-time"]').textContent).toBe("Elapsed 0:38");
  });

  test("Checking cells: the muted line says n of m figures checked", async () => {
    await mount({ sheets: [SHEET({ read_state: "reading", read_stage: "checking_cells", read_elapsed: 90, read_checked: 112, read_total: 185 })] });
    expect(q("sheet-file").querySelector('[data-testid="file-tag"]').textContent).toBe("Checking cells");
    expect(q("sheet-file").querySelector('[data-testid="file-sub"]').textContent).toBe("112 of 185 figures checked");
  });

  test("Processed: a finished line shows the frozen time only, without the label", async () => {
    await mount({ sheets: [SHEET()] });
    const row = q("sheet-file");
    expect(row.querySelector('[data-testid="file-tag"]').textContent).toBe("Processed");
    expect(row.querySelector('[data-testid="file-tag"]').className).toContain("done");
    expect(row.querySelector('[data-testid="file-time"]').textContent).toBe("1:47");
    expect(row.querySelector('[data-testid="file-sub"]')).toBeNull();
  });

  test("a file the reader could not read says so and is not called Processed", async () => {
    await mount({ sheets: [SHEET({ read_state: "failed", read_elapsed: 12 })] });
    expect(q("sheet-file").querySelector('[data-testid="file-tag"]').textContent).toBe("Not processed");
    expect(q("sheet-file").querySelector('[data-testid="file-sub"]').textContent).toBe("The file is stored but could not be read.");
  });

  test("a stored file from before the stage was kept reads as Processed with no time", async () => {
    const { read_state: _a, read_stage: _b, read_elapsed: _c, ...old } = SHEET();
    await mount({ sheets: [old] });
    expect(q("sheet-file").querySelector('[data-testid="file-tag"]').textContent).toBe("Processed");
    expect(q("sheet-file").querySelector('[data-testid="file-time"]').textContent).toBe("");
  });

  test("the elapsed time counts up each second from the server's count", async () => {
    jest.useFakeTimers();
    await mount({ sheets: [SHEET({ read_state: "reading", read_stage: "reading_the_sheet", read_elapsed: 38 })] });
    expect(q("sheet-file").querySelector('[data-testid="file-time"]').textContent).toBe("Elapsed 0:38");
    await act(async () => { jest.advanceTimersByTime(2000); });
    expect(q("sheet-file").querySelector('[data-testid="file-time"]').textContent).toBe("Elapsed 0:40");
  });

  test("a deck keeps one summary line, shown once, with the frozen time", async () => {
    await mount({ decks: [DECK()] });
    const row = q("deck-file");
    expect(row.querySelector('[data-testid="file-tag"]').textContent).toBe("Processed");
    expect(row.querySelector('[data-testid="file-time"]').textContent).toBe("1:12");
    expect(row.querySelector('[data-testid="file-summary"]').textContent).toBe("24 pages · 17 with figures processed · 7 skipped (no numbers)");
    expect(document.body.textContent.split("17 with figures processed")).toHaveLength(2);
  });

  test("a deck that is being read shows its page progress and the running time", async () => {
    await mount({ decks: [DECK({ ai_status: "reading", read_progress: { done: 2, total: 24 }, read_elapsed: 20 })] });
    expect(q("deck-file").querySelector('[data-testid="file-tag"]').textContent).toBe("Reading the pages");
    expect(q("deck-file").querySelector('[data-testid="file-summary"]').textContent).toBe("page 3 of 24");
    expect(q("deck-file").querySelector('[data-testid="file-time"]').textContent).toBe("Elapsed 0:20");
  });

  const CONFIRM = "Remove – deletes this file and all its claims, including reviewed ones · Cancel";
  const click = async (el) => { await act(async () => { el.click(); }); };

  test.each([["deck", "deck-file", () => DECK(), "removeDeck", "d1"], ["data file", "sheet-file", () => SHEET(), "removeDataset", "h1"]])(
    "Remove on a %s turns the same link, in place, into the confirmation; Remove there deletes", async (_, rowId, make, call, id) => {
      api[call].mockResolvedValue({});
      await mount(rowId === "deck-file" ? { decks: [make()] } : { sheets: [make()] });
      const row = q(rowId);
      const before = row.querySelectorAll("a").length;
      await click(row.querySelector('[data-testid="file-remove"]'));
      expect(api[call]).not.toHaveBeenCalled();
      expect(row.querySelector('[data-testid="file-remove"]')).toBeNull();                       // the link is replaced, not kept beside it
      expect(row.querySelector('[data-testid="file-remove-confirm"]').textContent).toBe(CONFIRM);
      expect(row.querySelectorAll("li, p, button").length).toBe(0);                              // no second line, no second button
      expect(row.querySelectorAll("a").length).toBe(before + 1);                                 // Remove and Cancel stand where the one link stood
      if (rowId === "deck-file") api.getDecks.mockResolvedValue({ decks: [], candidates: [] }); else api.getDatasets.mockResolvedValue([]);
      await click(row.querySelector('[data-testid="file-remove-yes"]'));
      await act(async () => { await Promise.resolve(); });
      expect(api[call]).toHaveBeenCalledWith("a1", id);
      expect(q(rowId)).toBeNull();
    });

  test.each([["deck-file", { decks: [DECK()] }], ["sheet-file", { sheets: [SHEET()] }]])("Cancel in the confirmation of %s restores the link and removes nothing", async (rowId, files) => {
    await mount(files);
    const row = q(rowId);
    await click(row.querySelector('[data-testid="file-remove"]'));
    await click(row.querySelector('[data-testid="file-remove-cancel"]'));
    expect(row.querySelector('[data-testid="file-remove"]').textContent).toBe("Remove");
    expect(row.querySelector('[data-testid="file-remove-confirm"]')).toBeNull();
    expect(api.removeDeck).not.toHaveBeenCalled();
    expect(api.removeDataset).not.toHaveBeenCalled();
  });
});

describe("recovering a failed file without deleting the audit", () => {
  const FAILED = (over = {}) => SHEET({ read_state: "failed", file: "bad.xlsx", file_hash: "hb", ...over });
  const click = async (el) => { await act(async () => { el.click(); }); await act(async () => { await Promise.resolve(); }); };

  test("a failed data file has Re-read, which reads the stored file again; a processed file has none", async () => {
    api.rereadDataset.mockResolvedValue({});
    await mount({ sheets: [FAILED(), SHEET()] });
    const rows = all("sheet-file");
    expect(rows[0].querySelector('[data-testid="file-reread"]').textContent).toBe("Re-read");
    expect(rows[1].querySelector('[data-testid="file-reread"]')).toBeNull();
    await click(rows[0].querySelector('[data-testid="file-reread"]'));
    expect(api.rereadDataset).toHaveBeenCalledWith("a1", "hb");
    expect(api.uploadChatFile).not.toHaveBeenCalled();
  });

  test("a failed deck has Re-read too", async () => {
    api.rereadDeck.mockResolvedValue({});
    await mount({ decks: [DECK({ ai_status: "not_read" })] });
    await click(q("deck-file").querySelector('[data-testid="file-reread"]'));
    expect(api.rereadDeck).toHaveBeenCalledWith("a1", "d1");
  });

  test("Re-read failed files shows from two failed files, above the lists, and re-reads each", async () => {
    api.rereadDataset.mockResolvedValue({});
    api.rereadDeck.mockResolvedValue({});
    await mount({ sheets: [FAILED()], decks: [DECK({ ai_status: "not_read" })] });
    expect(q("reread-failed-link").textContent).toBe("Re-read failed files");
    expect(follows("reread-failed-link", "sheet-card")).toBe(true);
    await click(q("reread-failed-link"));
    expect(api.rereadDataset).toHaveBeenCalledWith("a1", "hb");
    expect(api.rereadDeck).toHaveBeenCalledWith("a1", "d1");
  });

  test("with one failed file there is no Re-read failed files button", async () => {
    await mount({ sheets: [FAILED(), SHEET()] });
    expect(q("reread-failed")).toBeNull();
  });

  test("a file with a stored name asks one line before it replaces it; Replace uploads with replace, Cancel uploads nothing", async () => {
    api.uploadChatFile.mockResolvedValue({ status: "ok" });
    await mount({ sheets: [SHEET()] });
    await pickFiles("sheet-file-input", [new File(["x"], "Testco_Revenue.xlsx")]);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
    expect(q("replace-confirm").textContent).toBe("A file named Testco_Revenue.xlsx is already stored. Replace it? Replace · Cancel");
    await click(q("replace-cancel"));
    expect(q("replace-confirm")).toBeNull();
    expect(api.uploadChatFile).not.toHaveBeenCalled();
    await pickFiles("sheet-file-input", [new File(["x"], "Testco_Revenue.xlsx")]);
    await click(q("replace-yes"));
    expect(api.uploadChatFile).toHaveBeenCalledTimes(1);
    expect(api.uploadChatFile.mock.calls[0][2]).toEqual({ replace: true });
  });

  test("a new name uploads at once, with no question", async () => {
    api.uploadChatFile.mockResolvedValue({ status: "ok" });
    await mount({ sheets: [SHEET()] });
    await pickFiles("sheet-file-input", [new File(["x"], "other.xlsx")]);
    expect(q("replace-confirm")).toBeNull();
    expect(api.uploadChatFile.mock.calls[0][2]).toEqual({ replace: false });
  });
});

describe("files go up the moment they are picked", () => {
  test("a picked spreadsheet is uploaded at once, shows Removing personal data while it goes, and is listed from the server after", async () => {
    let done;
    api.uploadChatFile.mockImplementation(() => new Promise((resolve) => { done = () => resolve({ status: "ok" }); }));
    await mount();
    await pickFiles("sheet-file-input", [new File(["x"], "rev.xlsx")]);
    expect(api.uploadChatFile).toHaveBeenCalledTimes(1);
    expect(q("sheet-file").querySelector('[data-testid="file-tag"]').textContent).toBe("Removing personal data");
    expect(q("sheet-file").querySelector('[data-testid="file-time"]').textContent).toBe("Elapsed 0:00");
    api.getDatasets.mockResolvedValue([SHEET({ file: "rev.xlsx", read_state: "reading", read_stage: "reading_the_sheet", read_elapsed: 1 })]);
    await act(async () => { done(); });
    await act(async () => { await Promise.resolve(); });
    expect(all("sheet-file")).toHaveLength(1);
    expect(q("sheet-file").querySelector('[data-testid="file-tag"]').textContent).toBe("Reading the sheet");
  });

  test("a picked deck is uploaded at once", async () => {
    api.uploadDeck.mockResolvedValue({ deck_id: "d1" });
    await mount();
    await pickFiles("deck-file-input", [new File(["x"], "board.pdf")]);
    expect(api.uploadDeck).toHaveBeenCalledTimes(1);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
  });

  test("a file of the wrong type is refused once in its card and counted by extension; an old .xls says how to save it", async () => {
    await mount();
    await pickFiles("sheet-file-input", [new File(["x"], "notes.docx")]);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
    expect(q("sheet-refusal").textContent).toBe("notes.docx: Only .xlsx and .csv files go here.");
    expect(api.reportUsage).toHaveBeenCalledWith("a1", { rejected_extension: "docx" });
    await pickFiles("sheet-file-input", [new File(["x"], "old.xls")]);
    expect(q("sheet-refusal").textContent).toBe("Save as .xlsx or .csv and upload again.");
    await pickFiles("deck-file-input", [new File(["x"], "data.csv")]);
    expect(q("deck-refusal").textContent).toBe("data.csv: Only .pdf, .pptx and .docx files go here.");
  });

  test("an upload the server refuses shows its words on the file's line, and Remove takes the line off", async () => {
    api.uploadChatFile.mockRejectedValue({ response: { data: { detail: "This file could not be read as a sheet" } } });
    await mount();
    await pickFiles("sheet-file-input", [new File(["x"], "bad.xlsx")]);
    const row = q("sheet-file");
    expect(row.querySelector('[data-testid="file-tag"]').textContent).toBe("Not processed");
    expect(row.querySelector('[data-testid="file-sub"]').textContent).toBe("This file could not be read as a sheet");
    await act(async () => { row.querySelector('[data-testid="file-remove"]').click(); });
    expect(q("sheet-file")).toBeNull();
  });
});

describe("the run card", () => {
  const reading = SHEET({ file: "Testco_PnL.xlsx", file_hash: "h2", read_state: "reading", read_stage: "reading_the_sheet", read_elapsed: 38, read_checking_elapsed: null });

  test("Run audit is off while a file is being read, and the line beside it names the file and counts what is ready", async () => {
    await mount({ sheets: [SHEET(), reading], decks: [DECK()] });
    expect(q("run-audit").disabled).toBe(true);
    expect(q("run-audit").textContent).toBe("Run audit");
    expect(q("run-readiness").textContent).toBe("Run audit is off while Testco_PnL.xlsx is being read. 1 of 2 data files and 1 deck ready.");
  });

  test("with every file processed the button is on and the line says Ready", async () => {
    await mount({ sheets: [SHEET(), SHEET({ file: "Testco_PnL.xlsx", file_hash: "h2" })], decks: [DECK()] });
    expect(q("run-audit").disabled).toBe(false);
    expect(q("run-readiness").textContent).toBe("Ready: 2 data files and 1 deck processed.");
  });

  test("every file stored but none read: the step fails in red and Run audit is disabled with that message", async () => {
    await mount({ sheets: [SHEET({ read_state: "failed", rows_mapped: 0 })], decks: [DECK({ ai_status: "not_read", pages_read: 0, pages_rejected: 3 })] });
    expect(q("run-audit").disabled).toBe(true);
    expect(q("run-readiness").textContent).toBe("Failed – no file could be read");
    expect(q("step-reading").getAttribute("data-tone")).toBe("bad");
    expect(q("step-reading-second").textContent).toBe("Failed – no file could be read");
  });

  test("the same provider error on every file is shown once, at the top of the step", async () => {
    const credit = "Anthropic API: insufficient credit – add credit and re-run";
    await mount({ sheets: [SHEET({ read_state: "failed", rows_mapped: 0, read_error: credit })], decks: [DECK({ ai_status: "not_read", pages_read: 0, read_error: credit })] });
    expect(all("step-reading-error").map((e) => e.textContent)).toEqual([credit]);
    expect(all("file-sub").map((e) => e.textContent).filter((t) => /could not be read/.test(t))).toEqual([]);
  });

  test("a deck still being read holds the button too", async () => {
    await mount({ sheets: [SHEET()], decks: [DECK({ ai_status: "reading", read_progress: { done: 1, total: 24 } })] });
    expect(q("run-audit").disabled).toBe(true);
    expect(q("run-readiness").textContent).toBe("Run audit is off while Board_deck_Q3.pdf is being read. 1 of 1 data file and 0 decks ready.");
  });

  test("the button comes on by itself when the polled files are all processed", async () => {
    jest.useFakeTimers();
    await mount({ sheets: [SHEET(), reading] });
    expect(q("run-audit").disabled).toBe(true);
    api.getDatasets.mockResolvedValue([SHEET(), { ...reading, read_state: "done", read_stage: null, read_elapsed: 95 }]);
    await act(async () => { jest.advanceTimersByTime(3100); });
    await act(async () => { await Promise.resolve(); });
    expect(q("run-audit").disabled).toBe(false);
    expect(q("run-readiness").textContent).toBe("Ready: 2 data files and 0 decks processed.");
  });

  test("two steps, in the mockup's states and second lines: reading and checking runs, calculating has not started", async () => {
    await mount({ sheets: [SHEET(), reading], decks: [DECK()] });
    expect(all("run-steps").length).toBe(1);
    expect(["reading", "calculating"].map((k) => q(`step-${k}`).querySelector("b").textContent)).toEqual(["Reading and checking files", "Calculating results"]);
    expect(["reading", "calculating"].map((k) => q(`step-${k}`).getAttribute("data-tone"))).toEqual(["run", "wait"]);
    expect(q("step-reading-second").textContent).toBe("Elapsed 0:38 · 2 of 3 files read");
    expect(q("step-calculating-second").textContent).toBe("not started");
    expect(q("step-checking")).toBeNull();
    expect(document.body.textContent).not.toContain("Checking figures");
  });

  test("when every file is processed reading shows its time and the file count; with no upload seen it is the longest file time", async () => {
    await mount({ sheets: [SHEET(), SHEET({ file_hash: "h2", file: "b.xlsx", read_elapsed: 123 })], decks: [DECK(), DECK({ deck_id: "d2" })] });
    expect(q("step-reading").getAttribute("data-tone")).toBe("done");
    expect(q("step-reading-second").textContent).toBe("2:03 · 4 files processed");
    await act(async () => { root.unmount(); }); host.remove();
    await mount({ sheets: [SHEET()] });
    expect(q("step-reading-second").textContent).toBe("1:47 · 1 file processed");
  });

  test("with no file every step has not started", async () => {
    await mount();
    expect(["reading", "calculating"].map((k) => q(`step-${k}-second`).textContent)).toEqual(["not started", "not started"]);
    expect(q("run-readiness").textContent).toBe("The audit cannot run yet. Missing: a file.");
  });
});
