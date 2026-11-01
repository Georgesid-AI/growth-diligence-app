import React, { act } from "react";
import { createRoot } from "react-dom/client";

import MappingWizard from "./MappingWizard";
import * as api from "@/lib/api";
import { S4_DROP_ZONE_LEAD, S4_DROP_ZONE_BOLD, S7_REFUSED, S7B_XLS_REFUSED, S_UPLOAD_RETRY } from "@/lib/chatUpload";

jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), getDatasets: jest.fn(), uploadChatFile: jest.fn(), reportUsage: jest.fn(),
  getReview: jest.fn(), getDecks: jest.fn(), runStage: jest.fn(), uploadDeck: jest.fn(), getReading: jest.fn(),
  saveFx: jest.fn(), computeAudit: jest.fn(), updateAudit: jest.fn(), putIcInputs: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({ useParams: () => ({ id: "a1" }), useNavigate: () => jest.fn(), useLocation: () => ({ pathname: "/audit/a1/mapping" }) }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ audit, children }) => <div><span data-testid="header-target">{audit ? String(audit.target_arr) : ""}</span>{children}</div> }));
jest.mock("@/components/DeckPanel", () => ({ reloadKey = 0 }) => <div data-testid="deck-panel" data-reload={reloadKey} />);
jest.mock("@/components/ReadingScreen", () => ({ __esModule: true, default: () => <div data-testid="reading-screen" />, ReadingTop: ({ host }) => <div data-testid="reading-top">{host}</div> }));

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

describe("the FX settings", () => {
  test("rates save to the audit as they change and need no file", async () => {
    api.saveFx.mockResolvedValue({ fx: { USD: 0.9 } });
    await mount();
    expect(q("fx-settings")).not.toBeNull();
    expect(q("revenue-settings")).toBeNull();           // no revenue file, and the rates are still there to set
    await change(q("fx-ccy-input"), "usd");
    await change(q("fx-rate-input"), "0.9");
    const add = [...q("fx-settings").querySelectorAll("button")].find((b) => b.textContent.includes("Add"));
    await click(add);
    await flush();
    expect(api.saveFx).toHaveBeenCalledWith("a1", { USD: 0.9 });
    expect(q("fx-settings").textContent).toContain("1 USD = 0.9 EUR");
  });

  test("a saved rate makes the deck panel read the claims again; a refused save does not", async () => {
    api.saveFx.mockResolvedValue({ fx: { USD: 0.9 } });
    await mount();
    expect(q("deck-panel").getAttribute("data-reload")).toBe("0");
    await change(q("fx-ccy-input"), "usd");
    await change(q("fx-rate-input"), "0.9");
    await click([...q("fx-settings").querySelectorAll("button")].find((b) => b.textContent.includes("Add")));
    await flush();
    expect(q("deck-panel").getAttribute("data-reload")).toBe("1");
    api.saveFx.mockRejectedValue(new Error("x"));
    await change(q("fx-ccy-input"), "gbp");
    await change(q("fx-rate-input"), "1.14");
    await click([...q("fx-settings").querySelectorAll("button")].find((b) => b.textContent.includes("Add")));
    await flush();
    expect(q("deck-panel").getAttribute("data-reload")).toBe("1");
  });

  test("a rate that cannot be saved is taken back and says so", async () => {
    const { toast } = require("sonner");
    api.saveFx.mockRejectedValue(new Error("x"));
    await mount();
    await change(q("fx-ccy-input"), "gbp");
    await change(q("fx-rate-input"), "1.14");
    await click([...q("fx-settings").querySelectorAll("button")].find((b) => b.textContent.includes("Add")));
    await flush();
    expect(toast.error).toHaveBeenCalledWith("Save failed");
    expect(q("fx-settings").textContent).not.toContain("1 GBP");
  });
});

describe("the upload list (read-check-review.md section 11.1)", () => {
  test("a dropped file is only attached: nothing is sent, the box stays usable, and Map sends the files in drop order without computing", async () => {
    api.uploadChatFile.mockImplementation(async (id, f) => FILE({ file: f.name }));
    api.getDatasets.mockResolvedValue([FILE({ file: "a.csv" }), FILE({ file: "b.csv", file_hash: "h2" })]);
    await mount();
    await pick([file("a.csv")]);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
    expect(q("attachment-note").textContent).toBe("attached – not read yet");
    expect(q("chat-drop-zone")).not.toBeNull();             // the upload box stays after a drop
    expect(q("chat-drop-zone").textContent).toContain(S4_DROP_ZONE_BOLD);
    expect(q("chat-drop-zone").textContent).toContain(S4_DROP_ZONE_LEAD.slice(0, 40));
    await pick([file("b.csv")]);
    expect(all("chat-analyst-bubble").length).toBe(2);
    await act(async () => { q("chat-map").click(); });
    await flush();
    expect(api.uploadChatFile.mock.calls.map((c) => c[1].name)).toEqual(["a.csv", "b.csv"]);
    expect(api.uploadChatFile.mock.calls.every((c) => c.length === 2)).toBe(true);        // the file and nothing else: no type, no replace
    for (let i = 0; i < 5; i += 1) await flush();
    expect(api.computeAudit).not.toHaveBeenCalled();         // Map never computes
    expect(all("attachment-note").length).toBe(0);
  });

  test("an attachment can be taken off before Map", async () => {
    await mount();
    await pick([file("a.csv")]);
    await click(q("unstage-a.csv"));
    expect(all("chat-analyst-bubble").length).toBe(0);
    expect(q("chat-map").disabled).toBe(true);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
  });

  test("Map is only on with a file attached or loaded", async () => {
    await mount();
    expect(q("chat-map").disabled).toBe(true);
    await pick([file("a.csv")]);
    expect(q("chat-map").disabled).toBe(false);
  });

  test("a stored file is listed on reload by its name; nothing asks for its type or its columns", async () => {
    await mount({ datasets: [FILE()] });
    await flush();
    expect(all("chat-analyst-bubble").length).toBe(1);
    expect(q("chat-analyst-bubble").textContent).toContain("rev.csv");
    for (const id of ["chat-system-revenue", "chat-unknown", "chat-replace", "status-revenue", "mapping-table", "type-line", "confirm-all"]) expect(q(id)).toBeNull();
    expect(document.body.textContent).not.toMatch(/Confirm all|Confidence|wait for your decision|Older mapping/);
  });

  test("anything but xlsx or csv is refused in the browser and counted by extension; an old .xls says how to save it", async () => {
    await mount();
    await pick([file("deck.pptx")]);
    expect(document.body.textContent).toContain(S7_REFUSED);
    expect(api.reportUsage).toHaveBeenCalledWith("a1", { rejected_extension: "pptx" });
    await pick([file("old.xls")]);
    expect(document.body.textContent).toContain(S7B_XLS_REFUSED);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
  });

  test("a read that gets no answer puts the file back as attached; Map sends it again", async () => {
    api.uploadChatFile.mockRejectedValueOnce(new Error("timeout")).mockResolvedValue(FILE({ file: "a.csv" }));
    await mount();
    await pick([file("a.csv")]);
    await act(async () => { q("chat-map").click(); });
    for (let i = 0; i < 5; i += 1) await flush();
    expect(document.body.textContent).toContain(S_UPLOAD_RETRY);
    expect(q("attachment-note")).not.toBeNull();
    await act(async () => { q("chat-map").click(); });
    for (let i = 0; i < 5; i += 1) await flush();
    expect(api.uploadChatFile).toHaveBeenCalledTimes(2);
    expect(q("attachment-note")).toBeNull();
  });

  test("a refusal from the server shows its words", async () => {
    api.uploadChatFile.mockRejectedValue({ response: { status: 413, data: { detail: "This file is too large to keep." } } });
    await mount();
    await pick([file("a.csv")]);
    await act(async () => { q("chat-map").click(); });
    for (let i = 0; i < 5; i += 1) await flush();
    expect(document.body.textContent).toContain("This file is too large to keep.");
  });

  test("Map sets the flag that releases the banner, and refreshes it once after the last file", async () => {
    const { calculatePressed } = require("@/lib/chatUpload");
    window.sessionStorage.clear();
    api.uploadChatFile.mockImplementation(async (id, f) => FILE({ file: f.name }));
    const seen = jest.fn();
    window.addEventListener("blockers:changed", seen);
    await mount();
    expect(calculatePressed("a1")).toBe(false);
    await pick([file("a.csv"), file("b.csv")]);
    await act(async () => { q("chat-map").click(); });
    for (let i = 0; i < 6; i += 1) await flush();
    window.removeEventListener("blockers:changed", seen);
    expect(calculatePressed("a1")).toBe(true);
    expect(seen).toHaveBeenCalledTimes(1);
    window.sessionStorage.clear();
  });

  test("while files are being sent Map is off and nothing is sent twice", async () => {
    let release;
    api.uploadChatFile.mockImplementation((id, f) => new Promise((resolve) => { release = () => resolve(FILE({ file: f.name })); }));
    await mount();
    await pick([file("a.csv")]);
    await act(async () => { q("chat-map").click(); });
    await act(async () => { q("chat-map").click(); });
    expect(api.uploadChatFile).toHaveBeenCalledTimes(1);
    await act(async () => { release(); });
    for (let i = 0; i < 4; i += 1) await flush();
    expect(api.uploadChatFile).toHaveBeenCalledTimes(1);
  });
});

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
