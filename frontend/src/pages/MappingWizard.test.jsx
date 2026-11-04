import React, { act } from "react";
import { createRoot } from "react-dom/client";

import MappingWizard from "./MappingWizard";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), getDatasets: jest.fn(), uploadChatFile: jest.fn(), reportUsage: jest.fn(), removeDeck: jest.fn(),
  getReview: jest.fn(), getDecks: jest.fn(), runStage: jest.fn(), uploadDeck: jest.fn(), getReading: jest.fn(),
  saveFx: jest.fn(), computeAudit: jest.fn(), updateAudit: jest.fn(), putIcInputs: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({ useParams: () => ({ id: "a1" }), useNavigate: () => jest.fn(), useLocation: () => ({ pathname: "/audit/a1/mapping" }) }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ audit, children }) => <div><span data-testid="header-target">{audit ? String(audit.target_arr) : ""}</span>{children}</div> }));
jest.mock("@/components/ReadingScreen", () => ({ __esModule: true, default: ({ reloadKey = 0 }) => <div data-testid="reading-screen" data-reload={reloadKey} /> }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const AUDIT = { id: "a1", company_name: "Target", reporting_currency: "EUR", fiscal_year_end: 12, structure_reading_consent: true, datasets: {} };
// A stored file as the upload and the file list give it: its name and size. No type, no column, no count of answers.
const FILE = (over = {}) => ({ status: "ok", dtype: "file", file: "rev.csv", file_hash: "h1", size_bytes: 2048, ext: "csv", row_count: 1240, sheets: 1, uploaded_at: "t", ...over });

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
const all = (id) => [...document.body.querySelectorAll(`[data-testid="${id}"]`)];
let root, host;

async function mount({ audit = AUDIT, datasets = [] } = {}) {
  api.getAudit.mockResolvedValue(audit);
  api.getDatasets.mockResolvedValue(datasets);
  api.reportUsage.mockResolvedValue({});
  api.getReview.mockResolvedValue({ computed: false });
  api.getDecks.mockResolvedValue({ decks: [], candidates: [] });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<MappingWizard />); });
}
const flush = () => act(async () => { await Promise.resolve(); });
async function pick(files) {
  const input = q("chat-file-input");
  Object.defineProperty(input, "files", { value: files, configurable: true });
  await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
  await flush();
}
const file = (name, size = 10) => new File(["x".repeat(size)], name);
const change = async (el, value) => {
  const proto = el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  });
};
const click = (el) => act(async () => { el.click(); });

beforeEach(() => { jest.clearAllMocks(); });
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });

describe("the page no longer holds the older mapping (read-check-review.md section 12)", () => {
  test("?view=legacy brings nothing back: no mapping block, no type picker, no revenue-row picker, no Confirm all", async () => {
    window.history.pushState({}, "", "/?view=legacy");
    await mount({ datasets: [FILE()] });
    await flush();
    expect(q("reading-screen")).not.toBeNull();
    for (const id of ["revenue-settings", "billing-terms-section", "mapping-table", "type-line", "revenue-row-picker", "confirm-all", "older-mapping-waits"]) expect(q(id)).toBeNull();
    expect(document.body.textContent).not.toMatch(/Older mapping|Lines wait for your decision|Columns wait|Needs your review/);
    window.history.pushState({}, "", "/");
  });
});


describe("the Upload page, top to bottom (docs/design/audit-page-mockup.html)", () => {
  const follows = (a, b) => !!(q(a).compareDocumentPosition(q(b)) & Node.DOCUMENT_POSITION_FOLLOWING);

  test("header, the two cards, the run card, Check results, then More settings; nothing else between the run card and Check results", async () => {
    await mount({ datasets: [FILE()] });
    await flush();
    expect(q("upload-company").textContent).toBe("Company: Target · EUR");
    for (const [a, b] of [["upload-header", "sheet-card"], ["sheet-card", "deck-card"], ["deck-card", "run-audit-panel"], ["run-audit-panel", "reading-screen"], ["reading-screen", "more-settings"]]) {
      expect(follows(a, b)).toBe(true);
    }
    expect(q("upload-page").lastElementChild).toBe(q("run-audit-panel"));          // the processing text stays closed until its link is pressed
    expect(q("upload-page").nextElementSibling).toBe(q("reading-screen"));
    expect(q("setup-consent-checkbox")).toBeNull();
    expect(document.body.querySelectorAll("button[data-testid^='run-audit']")).toHaveLength(1);
  });

  test("a stored file is listed on reload by its name; nothing asks for its type or its columns", async () => {
    await mount({ datasets: [FILE({ file: "rev.csv" })] });
    await flush();
    expect(q("sheet-file").querySelector('[data-testid="file-name"]').textContent).toBe("rev.csv");
    expect(document.body.textContent).not.toMatch(/Which type|Needs your review|Columns wait/);
  });
});

describe("the page follows the background reading", () => {
  test("when background reading finishes the blockers are read again, with no page reload", async () => {
    jest.useFakeTimers();
    const { BLOCKERS_CHANGED } = require("@/components/BlockerBanner");
    const fired = jest.fn();
    window.addEventListener(BLOCKERS_CHANGED, fired);
    api.getAudit.mockResolvedValueOnce({ ...AUDIT, sheet_reads_pending: 1 }).mockResolvedValue(AUDIT);
    await mount();
    expect(fired).not.toHaveBeenCalled();
    await act(async () => { jest.advanceTimersByTime(3100); });
    await act(async () => { await Promise.resolve(); });
    expect(fired).toHaveBeenCalledTimes(1);
    window.removeEventListener(BLOCKERS_CHANGED, fired);
    jest.useRealTimers();
  });
});
