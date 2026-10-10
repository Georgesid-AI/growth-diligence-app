import React, { act } from "react";
import { createRoot } from "react-dom/client";

import MappingWizard from "./MappingWizard";
import * as api from "@/lib/api";
import { toast } from "sonner";
import { SETUP_HELP } from "@/lib/auditForm";
import {
  S1_TEXT_REPLY, S2_EXPLAINER_CONSENT, S3_EXPLAINER_NO_CONSENT, S4_DROP_ZONE, S7_REFUSED, S7B_XLS_REFUSED, S12_MODEL_FAILED, S_UPLOAD_RETRY, S21_NOTE_REFUSED, REASONS,
  S5_head, S9_confidence, mappedBy, sortColumns, S25_PARAGRAPHS,
} from "@/lib/chatUpload";

jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), getDatasets: jest.fn(), uploadChatFile: jest.fn(), decideColumns: jest.fn(), reportUsage: jest.fn(),
  saveMapping: jest.fn(), saveFx: jest.fn(), computeAudit: jest.fn(), getRevenueCustomers: jest.fn(), updateAudit: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({ useParams: () => ({ id: "a1" }), useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ audit, children }) => <div><span data-testid="header-target">{audit ? String(audit.target_arr) : ""}</span>{children}</div> }));
jest.mock("@/components/DeckPanel", () => ({ reloadKey = 0 }) => <div data-testid="deck-panel" data-reload={reloadKey} />);

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const AUDIT = { id: "a1", company_name: "Target", reporting_currency: "EUR", fiscal_year_end: 12, structure_reading_consent: true, datasets: {} };
const FIELDS = { required: ["customer_id", "invoice_date", "amount", "currency"], optional: ["segment", "revenue_type"] };

const row = (column, over = {}) => ({
  column, field: null, source: "rules", state: "auto", confidence: 100, fit_note: null, decision: null, reason: null, pending: false,
  position: 1, ...over,
});
const VIEW = (over = {}) => ({
  status: "ok", dtype: "revenue", file: "rev.csv", size_bytes: 2048, ext: "csv", row_count: 1240, months: { count: 24, first: "2023-01", last: "2024-12" },
  pending: 0, missing_required: [], version: 1, ai_reading: { status: "rules" }, fields: FIELDS, mapping: {}, fx: {}, billing_terms: {},
  uploaded_at: "t", saved: true,
  columns: [row("Customer", { field: "customer_id" }), row("Invoice Date", { field: "invoice_date" }), row("Amount", { field: "amount" }),
            row("Currency", { field: "currency" }), row("Memo", { state: "unused", source: null, confidence: null })],
  ...over,
});
const PENDING_VIEW = () => VIEW({
  pending: 2, months: null,
  columns: [
    row("Customer", { field: "customer_id" }),
    row("Amount", { field: "amount", state: "unsure", confidence: 30, pending: true, source: "rules" }),
    row("Adj", { field: "revenue_type", state: "ai", confidence: null, source: "ai", pending: true }),
    row("Notes", { state: "needs", source: "needs", confidence: null, pending: true }),
  ],
});

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
const all = (id) => [...document.body.querySelectorAll(`[data-testid="${id}"]`)];
let root, host;

async function mount({ audit = AUDIT, datasets = [] } = {}) {
  api.getAudit.mockResolvedValue(audit);
  api.getDatasets.mockResolvedValue(datasets);
  api.reportUsage.mockResolvedValue({});
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
// Dropping or picking a file only attaches it; nothing is read until Map is pressed.
async function pickAndMap(files) {
  await pick(files);
  await act(async () => { q("chat-map").click(); });
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

describe("the screen", () => {
  test("keeps the header bar, the chat panel and the deck panel below it", async () => {
    await mount();
    expect(q("fiscal-year-end-select")).not.toBeNull();
    expect(q("asof-month-input")).not.toBeNull();
    expect(q("compute-button")).not.toBeNull();
    const chat = q("upload-chat");
    expect(chat.compareDocumentPosition(q("deck-panel")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(q("chat-drop-zone").textContent).toBe(S4_DROP_ZONE);
    expect(S4_DROP_ZONE).toBe("Drop files here or use the paperclip. Required: revenue by customer (monthly, 24–36 months). Also useful: CRM export, P&L. Board decks go to the Deck panel. .xlsx or .csv only.");
    expect(q("chat-paperclip")).not.toBeNull();
    expect(q("chat-file-input").multiple).toBe(true);
  });

  test("the set-up fields are at the top, above the chat, each with its one line of help", async () => {
    await mount({ audit: { ...AUDIT, target_arr: 40000000, target_date: "2028-12-31", as_of_month: "2026-06" } });
    const setup = q("audit-setup");
    expect(setup.compareDocumentPosition(q("upload-chat")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(setup.compareDocumentPosition(q("fx-settings")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(q("fx-settings").compareDocumentPosition(q("upload-chat")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(SETUP_HELP).toEqual({
      reporting_currency: "All figures are converted to this currency. Use the company's home currency; the verdict and memo use it.",
      target_arr: "The plan figure the audit tests. Every claim's VaS (see glossary) is measured against it.",
      target_date: "When the plan says Target ARR (see glossary) is reached. Sets the forecast horizon.",
      as_of_month: "Last month of actual data. Metrics are computed up to this month. Defaults to the last P&L month.",
      fiscal_year_end: "Maps FY labels in the deck to months. A wrong setting shifts every FY claim.",
    });
    for (const [field, text] of Object.entries(SETUP_HELP)) expect(q(`setup-help-${field}`).textContent).toBe(text);
    expect(setup.contains(q("setup-currency-select")) && setup.contains(q("setup-target-arr-input")) && setup.contains(q("fiscal-year-end-select"))).toBe(true);
    expect(q("setup-target-arr-input").value).toBe("40,000,000");
    expect(q("setup-target-date-input").value).toBe("31 Dec 2028");
    expect(q("asof-month-input").value).toBe("30 Jun 2026");
  });

  test("each set-up field saves as it changes; a refused save names the field and the reason", async () => {
    api.updateAudit.mockResolvedValue({});
    await mount();
    await act(async () => { q("setup-target-arr-input").focus(); });
    await change(q("setup-target-arr-input"), "12500000");
    await act(async () => { q("setup-target-arr-input").blur(); });
    expect(api.updateAudit).toHaveBeenLastCalledWith("a1", { target_arr: 12500000 });
    // a typed target date, 30.06.2028
    await act(async () => { q("setup-target-date-input").focus(); });
    await change(q("setup-target-date-input"), "30.06.2028");
    await act(async () => { q("setup-target-date-input").blur(); });
    expect(api.updateAudit).toHaveBeenLastCalledWith("a1", { target_date: "2028-06-30" });
    // clearing the as-of month sends an explicit null: back to the default
    await act(async () => { q("asof-month-input").focus(); });
    await change(q("asof-month-input"), "2026-06-15");
    await act(async () => { q("asof-month-input").blur(); });
    expect(api.updateAudit).toHaveBeenLastCalledWith("a1", { as_of_month: "2026-06-15" });
    await act(async () => { q("asof-month-input").focus(); });
    await change(q("asof-month-input"), "");
    await act(async () => { q("asof-month-input").blur(); });
    expect(api.updateAudit).toHaveBeenLastCalledWith("a1", { as_of_month: null });
    // a target date not after the as-of month is refused before anything is sent
    api.updateAudit.mockClear();
    await act(async () => { q("asof-month-input").focus(); });
    await change(q("asof-month-input"), "2028-06-15");
    await act(async () => { q("asof-month-input").blur(); });
    expect(api.updateAudit).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenLastCalledWith("Target date must be after the as-of month");
    // a server refusal names the field
    api.updateAudit.mockRejectedValue({ response: { status: 422, statusText: "", data: { detail: [{ loc: ["body", "target_arr"], msg: "Input should be a valid number" }] } } });
    await act(async () => { q("setup-target-arr-input").focus(); });
    await change(q("setup-target-arr-input"), "7");
    await act(async () => { q("setup-target-arr-input").blur(); });
    expect(toast.error).toHaveBeenLastCalledWith("Target ARR could not be saved: HTTP 422 — target_arr: Input should be a valid number");
  });

  test("Target ARR: a stored 0 shows an empty box, a digit replaces it, clearing leaves it empty", async () => {
    api.updateAudit.mockResolvedValue({});
    await mount({ audit: { ...AUDIT, target_arr: 0 } });
    expect(q("setup-target-arr-input").value).toBe("");
    await change(q("setup-target-arr-input"), "05");
    expect(q("setup-target-arr-input").value).toBe("5");
    await change(q("setup-target-arr-input"), "");
    expect(q("setup-target-arr-input").value).toBe("");
  });

  test("the header target follows a saved Target ARR without a reload", async () => {
    api.updateAudit.mockResolvedValue({ target_arr: 12500000 });
    await mount({ audit: { ...AUDIT, target_arr: 0 } });
    await act(async () => { q("setup-target-arr-input").focus(); });
    await change(q("setup-target-arr-input"), "12500000");
    api.getAudit.mockResolvedValue({ ...AUDIT, target_arr: 12500000 });
    await act(async () => { q("setup-target-arr-input").blur(); });
    await flush();
    expect(q("header-target").textContent).toBe("12500000");
    expect(api.getAudit).toHaveBeenCalledTimes(2);        // the page's own load, then the refetch after the save
  });

  test("a 502 or 503 on a set-up save reads 'Server is restarting', not the proxy's page", async () => {
    await mount();
    for (const status of [502, 503]) {
      api.updateAudit.mockRejectedValue({ response: { status, statusText: "Bad Gateway", data: "<html><body>Cloudflare Error 502</body></html>" } });
      await act(async () => { q("setup-target-arr-input").focus(); });
      await change(q("setup-target-arr-input"), String(status));
      await act(async () => { q("setup-target-arr-input").blur(); });
      expect(toast.error).toHaveBeenLastCalledWith("Target ARR could not be saved: Server is restarting – try again in a few seconds");
    }
  });

  test("the explainer follows the audit's consent: S2 when ticked, S3 when not", async () => {
    await mount();
    expect(q("chat-explainer").textContent).toBe(S2_EXPLAINER_CONSENT);
    await act(async () => { root.unmount(); }); host.remove();
    await mount({ audit: { ...AUDIT, structure_reading_consent: false } });
    expect(q("chat-explainer").textContent).toBe(S3_EXPLAINER_NO_CONSENT);
  });

  test("the chat has Map and Calculate, the header has Calculate; the Calculate buttons look the same and share one tooltip", async () => {
    await mount();
    const header = q("compute-button"), chat = q("chat-calculate");
    expect(q("chat-map").textContent).toBe("Map");
    expect(header.textContent).toBe("Calculate");
    expect(chat.textContent).toBe("Calculate");
    expect(chat.title).toBe(header.title);
    expect(header.className).toBe(chat.className);
    expect(q("chat-map").className).toBe(chat.className);
  });

  test("with no file attached and none loaded, Map is off with its tooltip and Calculate is off with its own", async () => {
    await mount();
    expect(q("chat-map").disabled).toBe(true);
    expect(q("chat-map").title).toBe("Attach the revenue file first. It is the only required file.");
    expect(q("chat-map-wrap").title).toBe(q("chat-map").title);
    expect(q("compute-button").disabled).toBe(true);
    expect(q("chat-calculate").disabled).toBe(true);
    expect(q("compute-button").title).toBe("Map the revenue file and confirm every column that waits for you first.");
    expect(q("compute-button-wrap").title).toBe(q("compute-button").title);
    expect(q("chat-calculate-wrap").title).toBe(q("compute-button").title);
  });

  test("Map is on with a file attached; Calculate stays off until the mapping is saved, in the header and the chat alike", async () => {
    api.uploadChatFile.mockResolvedValue(PENDING_VIEW());
    api.decideColumns.mockResolvedValue(VIEW());
    await mount();
    await pick([file("rev.csv")]);
    expect(q("chat-map").disabled).toBe(false);
    expect([q("compute-button").disabled, q("chat-calculate").disabled]).toEqual([true, true]);
    await act(async () => { q("chat-map").click(); });
    await flush();
    expect(q("chat-map").disabled).toBe(false);                 // a file is loaded
    expect([q("compute-button").disabled, q("chat-calculate").disabled]).toEqual([true, true]);      // two columns still wait
    await click(q("confirm-Amount"));
    await flush();
    expect([q("compute-button").disabled, q("chat-calculate").disabled]).toEqual([false, false]);    // mapping saved
    expect(q("compute-button").title).toBe("Computes the metrics from the mapped files.");
    expect(q("chat-calculate").title).toBe(q("compute-button").title);
  });

  test("a file removed from the chat switches Map off again; a loaded file keeps it on", async () => {
    await mount();
    await pick([file("rev.csv")]);
    expect(q("chat-map").disabled).toBe(false);
    await click(q("unstage-rev.csv"));
    expect(q("chat-map").disabled).toBe(true);
    await act(async () => { root.unmount(); }); host.remove();
    await mount({ datasets: [VIEW()] });
    expect(q("chat-map").disabled).toBe(false);
    expect([q("compute-button").disabled, q("chat-calculate").disabled]).toEqual([false, false]);     // stored mapping is complete
  });

  test("Send is greyed out while the text box is empty and carries its tooltip", async () => {
    await mount();
    const send = q("chat-send");
    expect(send.disabled).toBe(true);
    expect(send.title).toBe("Send a message (for answering the chat's questions)");
    expect(q("chat-send-wrap").title).toBe(send.title);          // a disabled button shows no tooltip of its own
    await change(q("chat-text-input"), "   ");
    expect(send.disabled).toBe(true);
    await change(q("chat-text-input"), "hello");
    expect(send.disabled).toBe(false);
  });

  test("the mapping panel has no scroll of its own: the page scrolls as one", async () => {
    await mount();
    expect(q("chat-messages").className).not.toMatch(/overflow|max-h/);
  });

  test("typed text gets the system reply and causes no API call", async () => {
    await mount();
    const calls = Object.values(api).flatMap((f) => (f.mock ? f.mock.calls.length : 0)).reduce((a, b) => a + b, 0);
    await change(q("chat-text-input"), "hello, map my columns");
    await act(async () => { q("chat-send").click(); });
    expect(q("chat-text-analyst").textContent).toBe("hello, map my columns");
    expect(q("chat-text-system").textContent).toBe(S1_TEXT_REPLY);
    expect(q("chat-text-input").value).toBe("");
    const after = Object.values(api).flatMap((f) => (f.mock ? f.mock.calls.length : 0)).reduce((a, b) => a + b, 0);
    expect(after).toBe(calls);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
  });

  test("reload rebuilds one analyst bubble and one system bubble per stored file", async () => {
    await mount({ datasets: [VIEW(), VIEW({ dtype: "pnl", file: "pnl.xlsx", ext: "xlsx" })] });
    await flush();
    expect(all("chat-analyst-bubble").length).toBe(2);
    expect(q("chat-system-revenue")).not.toBeNull();
    expect(q("chat-system-pnl")).not.toBeNull();
    expect(q("type-icon-csv")).not.toBeNull();
    expect(q("type-icon-xlsx")).not.toBeNull();
  });
});

describe("a file", () => {
  test("gets an analyst bubble (name, size, icon) and a system bubble with the detected type, the months and the table", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW());
    await mount();
    await pickAndMap([file("rev.csv", 2048)]);
    expect(api.uploadChatFile).toHaveBeenCalledWith("a1", expect.any(File), {});
    const analyst = q("chat-analyst-bubble");
    expect(analyst.textContent).toContain("rev.csv");
    expect(analyst.textContent).toContain("2.0 KB");
    expect(q("bubble-head").textContent).toBe("Detected: Revenue lines · 1,240 rows · 24 months (Jan 2023 – Dec 2024)");
    const table = q("mapping-table-revenue");
    expect([...table.querySelectorAll("thead th")].map((th) => th.textContent)).toEqual(["In your file", "Means", "Confidence", "Mapped by", ""]);
    expect(table.textContent).not.toContain("Your decision");
    expect(q("source-Customer").textContent).toBe("Rules");
    expect(q("confidence-Customer").textContent).toBe("100");
    expect(q("column-row-Memo")).toBeNull();
    expect(q("unused-toggle-revenue").textContent).toContain("Not used (1)");
    await click(q("unused-toggle-revenue"));
    expect(q("column-row-Memo")).not.toBeNull();
    expect(q("correct-Memo")).not.toBeNull();
    expect(q("status-revenue").textContent).toBe("Ready for calculation");
    expect(q("revenue-settings")).not.toBeNull();
  });

  test("files are sent one at a time, in drop order", async () => {
    const order = [];
    let release;
    api.uploadChatFile.mockImplementationOnce((id, f) => { order.push(f.name); return new Promise((r) => { release = () => r(VIEW()); }); });
    api.uploadChatFile.mockImplementationOnce((id, f) => { order.push(f.name); return Promise.resolve(VIEW({ dtype: "crm", file: "crm.csv" })); });
    await mount();
    await pickAndMap([file("first.csv"), file("second.csv")]);
    expect(order).toEqual(["first.csv"]);
    await act(async () => { release(); });
    await flush();
    expect(order).toEqual(["first.csv", "second.csv"]);
  });

  test("a read that gets no answer puts the file back as attached; Map sends it again", async () => {
    const timeout = Object.assign(new Error("timeout of 120000ms exceeded"), { code: "ECONNABORTED" });   // what axios raises; no response
    api.uploadChatFile.mockImplementation(async (id, f) => VIEW({ dtype: f.name.split(".")[0] === "rev" ? "revenue" : f.name.split(".")[0], file: f.name }));
    api.uploadChatFile.mockImplementationOnce(async (id, f) => VIEW({ dtype: "crm", file: f.name }));
    api.uploadChatFile.mockImplementationOnce(() => Promise.reject(timeout));          // the second file hangs, then times out
    await mount();
    await pickAndMap([file("crm.csv"), file("pnl.csv"), file("rev.csv")]);
    expect(api.uploadChatFile.mock.calls.map((c) => c[1].name)).toEqual(["crm.csv", "pnl.csv", "rev.csv"]);    // the loop went on
    expect(q("chat-text-system").textContent).toBe(S_UPLOAD_RETRY);
    expect(q("unstage-pnl.csv")).not.toBeNull();                                      // back with its "x"
    expect(all("attachment-note").length).toBe(1);
    expect(document.body.querySelectorAll('[data-testid="chat-analyst-bubble"] .animate-spin').length).toBe(0);
    expect(q("chat-map").disabled).toBe(false);
    await act(async () => { q("chat-map").click(); });
    await flush();
    expect(api.uploadChatFile.mock.calls.map((c) => c[1].name)).toEqual(["crm.csv", "pnl.csv", "rev.csv", "pnl.csv"]);
    expect(all("attachment-note").length).toBe(0);
    expect(q("mapping-table-pnl")).not.toBeNull();
  });

  test("anything but xlsx or csv is refused in the browser with S7 and counted by extension", async () => {
    await mount();
    await pickAndMap([file("board.pptx")]);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
    expect(q("chat-text-system").textContent).toBe(S7_REFUSED);
    expect(api.reportUsage).toHaveBeenCalledWith("a1", { rejected_extension: "pptx" });
  });

  test("an old .xls file is refused with 'Save as .xlsx or .csv and upload again.' and counted", async () => {
    await mount();
    await pickAndMap([file("old.xls")]);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
    expect(S7B_XLS_REFUSED).toBe("Save as .xlsx or .csv and upload again.");
    expect(q("chat-text-system").textContent).toBe(S7B_XLS_REFUSED);
    expect(api.reportUsage).toHaveBeenCalledWith("a1", { rejected_extension: "xls" });
    expect(q("chat-file-input").getAttribute("accept")).toBe(".xlsx,.csv");
  });

  test("an unknown type asks for it and sends the same file again with the type picked", async () => {
    api.uploadChatFile.mockResolvedValueOnce({ status: "unknown_type", file: "mystery.csv", size_bytes: 5, ext: "csv" });
    api.uploadChatFile.mockResolvedValueOnce(VIEW({ dtype: "crm", file: "mystery.csv" }));
    await mount();
    const f = file("mystery.csv");
    await pickAndMap([f]);
    expect(q("chat-unknown").textContent).toContain("Could not tell what this file holds. Pick its type:");
    expect(["Revenue lines", "CRM deals", "P&L (monthly)"].every((t) => q("chat-unknown").textContent.includes(t))).toBe(true);
    await click(q("pick-type-crm"));
    await flush();
    expect(api.uploadChatFile).toHaveBeenLastCalledWith("a1", f, { dtype: "crm" });
    expect(q("chat-unknown")).toBeNull();
    expect(q("chat-system-crm")).not.toBeNull();
  });

  test("a loaded type with other bytes asks S8: Replace sends replace=true, Keep current drops the file", async () => {
    const conflict = { response: { status: 409, data: { detail: { code: "type_loaded", dtype: "revenue", file: "old.csv" } } } };
    api.uploadChatFile.mockRejectedValueOnce(conflict);
    api.uploadChatFile.mockResolvedValueOnce(VIEW());
    await mount();
    const f = file("new.csv");
    await pickAndMap([f]);
    expect(q("chat-replace").textContent).toContain("A revenue file is already loaded (old.csv). Replace it?");
    await click(q("replace-yes"));
    await flush();
    expect(api.uploadChatFile).toHaveBeenLastCalledWith("a1", f, { dtype: "revenue", replace: true });
    api.uploadChatFile.mockRejectedValueOnce(conflict);
    await pickAndMap([file("again.csv")]);
    await click(q("replace-no"));
    expect(q("chat-replace")).toBeNull();
    expect(api.uploadChatFile).toHaveBeenCalledTimes(3);      // Keep current sent nothing more
  });

  test("the same file again says S14", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW({ status: "same_file", version: 3 }));
    await mount();
    await pickAndMap([file("rev.csv")]);
    expect(q("bubble-same").textContent).toBe("Same file as before: saved mapping v3 applied.");
  });
});

describe("the FX settings", () => {
  test("rates save to the audit as they change, need no file, and never carry the mapping", async () => {
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
    expect(api.saveMapping).not.toHaveBeenCalled();
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

describe("Map and Calculate", () => {
  test("a dropped file is only attached: nothing is read, the box stays usable, and Map reads the files in drop order without computing", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW());
    api.getDatasets.mockResolvedValue([VIEW()]);
    await mount();
    await pick([file("a.csv")]);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
    expect(q("attachment-note").textContent).toBe("attached – not read yet");
    expect(q("chat-system-revenue")).toBeNull();
    expect(q("chat-drop-zone")).not.toBeNull();             // the upload box stays after a drop
    await pick([file("b.csv")]);
    expect(all("chat-analyst-bubble").length).toBe(2);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
    expect(api.computeAudit).not.toHaveBeenCalled();
    await act(async () => { q("chat-map").click(); });
    await flush();
    expect(api.uploadChatFile.mock.calls.map((c) => c[1].name)).toEqual(["a.csv", "b.csv"]);
    for (let i = 0; i < 5; i += 1) await flush();
    expect(api.computeAudit).not.toHaveBeenCalled();         // Map never computes
  });

  test("an attachment can be taken off before Map", async () => {
    await mount();
    await pick([file("a.csv")]);
    await click(q("unstage-a.csv"));
    expect(all("chat-analyst-bubble").length).toBe(0);
    expect(q("chat-map").disabled).toBe(true);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
  });

  test("with a revenue file whose columns all have a decision, Calculate computes the metrics, from the chat and from the header", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW());
    api.updateAudit.mockResolvedValue({});
    api.computeAudit.mockResolvedValue({});
    await mount();
    await pickAndMap([file("rev.csv")]);
    for (let i = 0; i < 5; i += 1) await flush();
    expect(api.computeAudit).not.toHaveBeenCalled();
    await act(async () => { q("chat-calculate").click(); });
    for (let i = 0; i < 5; i += 1) await flush();
    expect(api.computeAudit).toHaveBeenCalledTimes(1);
    expect(api.computeAudit).toHaveBeenCalledWith("a1");
    await act(async () => { q("compute-button").click(); });
    for (let i = 0; i < 5; i += 1) await flush();
    expect(api.computeAudit).toHaveBeenCalledTimes(2);
  });

  test("with a column still waiting, Map reads the file and Calculate stays off", async () => {
    api.uploadChatFile.mockResolvedValue(PENDING_VIEW());
    await mount();
    await pickAndMap([file("rev.csv")]);
    expect(q("chat-calculate").disabled).toBe(true);
    await act(async () => { q("chat-calculate").click(); q("compute-button").click(); });
    expect(api.computeAudit).not.toHaveBeenCalled();
  });

  test("Map with no revenue file loaded computes nothing and releases the revenue banner; before the press it is held back", async () => {
    const { calculatePressed } = require("@/lib/chatUpload");
    window.sessionStorage.clear();
    const seen = jest.fn();
    window.addEventListener("blockers:changed", seen);
    await mount({ datasets: [VIEW({ dtype: "crm", file: "crm.csv" })] });      // a file is loaded, but not the revenue file
    expect(calculatePressed("a1")).toBe(false);
    expect(q("chat-map").disabled).toBe(false);
    expect(q("chat-calculate").disabled).toBe(true);           // no revenue file: nothing to calculate
    await act(async () => { q("chat-map").click(); });
    await flush();
    window.removeEventListener("blockers:changed", seen);
    expect(calculatePressed("a1")).toBe(true);
    expect(seen).toHaveBeenCalled();
    expect(api.computeAudit).not.toHaveBeenCalled();
    window.sessionStorage.clear();
  });
});

describe("the mapping table", () => {
  const dash = /^[\s—–-]*$/;
  const mountPending = async () => {
    api.uploadChatFile.mockResolvedValue(PENDING_VIEW());
    await mount();
    await pickAndMap([file("rev.csv")]);
  };

  test("AI, unsure and undecided rows wait for a click; the status says how many and Calculate stays off", async () => {
    await mountPending();
    expect(q("status-revenue").textContent).toBe("2 columns wait for your decision");
    expect([q("compute-button").disabled, q("chat-calculate").disabled]).toEqual([true, true]);
    expect(api.computeAudit).not.toHaveBeenCalled();
    expect(q("bubble-head").textContent).toBe("Detected: Revenue lines · 1,240 rows");
    expect(q("bubble-head").textContent).not.toContain("confirmed");
    expect(q("source-Adj").textContent).toBe("AI suggestion – confirm");
    expect(q("confidence-Adj").textContent).toBe("needs confirmation");
    expect(q("confidence-Amount").textContent).toBe("30");
    expect(q("source-Amount").textContent).toBe("Rules");
    expect(q("source-Notes").textContent).toBe("You – choose");
    expect(q("confidence-Notes").textContent).toBe("needs confirmation");
    expect(q("needs-field-Notes").value).toBe("");
    expect(q("needs-field-Notes").selectedOptions[0].textContent).toBe("Not used");
    expect(q("confirm-Amount")).not.toBeNull();
    expect(q("correct-Customer")).not.toBeNull();
    expect(q("confirm-Customer")).toBeNull();
  });

  test("rows that need a click come first, then ascending confidence, the auto-accepted 100s last", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW({
      pending: 3, months: null,
      columns: [
        row("Auto100a", { field: "customer_id" }),
        row("Auto90", { field: "invoice_date", confidence: 90 }),
        row("Needs", { state: "needs", source: "needs", confidence: null, pending: true }),
        row("Unsure50", { field: "amount", state: "unsure", confidence: 50, pending: true }),
        row("Auto100b", { field: "currency" }),
        row("Ai", { field: "segment", state: "ai", source: "ai", confidence: null, pending: true }),
        row("Unsure20", { field: "revenue_type", state: "unsure", confidence: 20, pending: true }),
        row("Done", { field: "service_start", state: "corrected", source: "ai", confidence: null, decision: "correct" }),
      ],
    }));
    await mount();
    await pickAndMap([file("rev.csv")]);
    const order = [...q("mapping-table-revenue").querySelectorAll("tbody tr[data-testid^='column-row-']")]
      .map((tr) => tr.getAttribute("data-testid").replace("column-row-", ""));
    expect(order).toEqual(["Needs", "Ai", "Unsure20", "Unsure50", "Done", "Auto90", "Auto100a", "Auto100b"]);
    expect(sortColumns([row("b", { confidence: 100 }), row("a", { confidence: 100 })]).map((c) => c.column)).toEqual(["b", "a"]);
  });

  test("the confidence cell is never a dash: the number, needs confirmation, or reused", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW({
      pending: 2, columns: [
        row("Rule", { field: "customer_id" }),
        row("Ai", { field: "segment", state: "ai", source: "ai", confidence: null, pending: true }),
        row("Saved", { field: "amount", source: "saved", confidence: 100 }),
        row("SavedLow", { field: "currency", source: "saved", state: "unsure", confidence: 60, pending: true }),
        row("Needs", { state: "needs", source: "needs", confidence: null, pending: true }),
        row("Chosen", { field: "revenue_type", state: "confirmed", source: "decision", confidence: null, decision: "confirm" }),
        row("Memo", { state: "unused", source: null, confidence: null }),
      ],
    }));
    await mount();
    await pickAndMap([file("rev.csv")]);
    await click(q("unused-toggle-revenue"));
    const cells = Object.fromEntries(["Rule", "Ai", "Saved", "SavedLow", "Needs", "Chosen", "Memo"].map((c) => [c, q(`confidence-${c}`).textContent]));
    expect(cells).toEqual({ Rule: "100", Ai: "needs confirmation", Saved: "reused", SavedLow: "reused", Needs: "needs confirmation",
                            Chosen: "confirmed", Memo: "0" });
    Object.values(cells).forEach((text) => expect(text).not.toMatch(dash));
    const by = Object.fromEntries(["Rule", "Ai", "Saved", "Needs", "Chosen"].map((c) => [c, q(`source-${c}`).textContent]));
    expect(by).toEqual({ Rule: "Rules", Ai: "AI suggestion – confirm", Saved: "Saved from earlier upload", Needs: "You – choose", Chosen: "You" });
  });

  test("a rule row the analyst confirmed or corrected is now the analyst's", () => {
    expect(mappedBy(row("a", { state: "confirmed", decision: "confirm" }))).toBe("You");
    expect(mappedBy(row("a", { state: "corrected", decision: "correct", source: "ai" }))).toBe("You");
    expect(S9_confidence(row("a", { state: "confirmed", decision: "confirm", confidence: 30 }))).toBe("30");
  });

  test("the month range shows once the date column is confirmed, and no text stands in for it before", () => {
    expect(S5_head(VIEW())).toBe("Detected: Revenue lines · 1,240 rows · 24 months (Jan 2023 – Dec 2024)");
    expect(S5_head(VIEW({ months: null }))).toBe("Detected: Revenue lines · 1,240 rows");
  });

  test("a collapsible box 'Why this step matters' sits above the mapping table, open, with the agreed text", async () => {
    api.uploadChatFile.mockResolvedValueOnce(VIEW()).mockResolvedValueOnce(VIEW({ dtype: "pnl", file: "pnl.csv" }));
    await mount();
    await pickAndMap([file("rev.csv"), file("pnl.csv")]);
    const box = q("why-this-matters");
    expect(all("why-this-matters").length).toBe(1);
    expect(box.tagName).toBe("DETAILS");
    expect(box.open).toBe(true);
    expect(q("why-this-matters-title").textContent).toBe("Why this step matters");
    expect(box.compareDocumentPosition(q("mapping-table-revenue")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(box.contains(q("mapping-table-revenue"))).toBe(false);
    expect([...box.querySelectorAll("p")].map((p) => p.textContent)).toEqual([
      "Every figure in this audit depends on how the columns are interpreted. If a column is mapped incorrectly—for example, bookings are treated as revenue, or an invoice date as a service date—the resulting calculations may look correct but be wrong.",
      "The app suggests a mapping for each column and indicates its confidence level. High-confidence mappings are accepted automatically, but you can change them. Low-confidence mappings appear at the top of the table and require your review.",
      "No calculations begin until all required columns are confirmed.",
      "Your choices are saved with the audit and automatically reused if you upload the same file again.",
    ]);
    expect(S25_PARAGRAPHS).toHaveLength(4);
    await act(async () => { box.open = false; });
    expect(box.open).toBe(false);
  });

  test("a confidence lowered by the values says why (S9)", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW({ columns: [row("Amount", { field: "amount", state: "unsure", confidence: 0, fit_note: "0 of 20 values are numbers", pending: true })], pending: 1 }));
    await mount();
    await pickAndMap([file("rev.csv")]);
    expect(q("confidence-Amount").textContent).toBe("0 · 0 of 20 values are numbers");
  });

  test("Confirm sends one decision and the new state replaces the bubble; Calculate enables once nothing waits", async () => {
    await mountPending();
    api.decideColumns.mockResolvedValue(VIEW());
    await click(q("confirm-Amount"));
    await flush();
    expect(api.decideColumns).toHaveBeenCalledWith("a1", "revenue", [{ column: "Amount", action: "confirm", field: "amount" }]);
    expect(q("status-revenue").textContent).toBe("Ready for calculation");
    expect(q("compute-button").disabled).toBe(false);
  });

  test("an amount column named turnover or volume asks once, revenue or volume, and sends the closed answer", async () => {
    const asking = VIEW({ pending: 1, saved: false, columns: [
      row("Customer", { field: "customer_id" }),
      row("Total Turnover", { field: "amount", pending: true, money_ask: true }),
    ] });
    api.uploadChatFile.mockResolvedValue(asking);
    await mount();
    await pickAndMap([file("rev.csv")]);
    expect(q("money-ask-Total Turnover").textContent).toContain("Is this money the company earned (revenue) or the value of transactions processed (volume)?");
    expect(q("confirm-Total Turnover")).toBeNull();
    api.decideColumns.mockResolvedValue(VIEW());
    await click(q("money-volume-Total Turnover"));
    await flush();
    expect(api.decideColumns).toHaveBeenCalledWith("a1", "revenue", [{ column: "Total Turnover", action: "confirm", money_kind: "volume" }]);
  });

  test("a row that needs a decision sends the field chosen, or Not used", async () => {
    await mountPending();
    api.decideColumns.mockResolvedValue(PENDING_VIEW());
    await change(q("needs-field-Notes"), "segment");
    await click(q("confirm-Notes"));
    expect(api.decideColumns).toHaveBeenLastCalledWith("a1", "revenue", [{ column: "Notes", action: "confirm", field: "segment" }]);
    await click(q("confirm-Notes"));
    await change(q("needs-field-Notes"), "");
    await click(q("confirm-Notes"));
    expect(api.decideColumns).toHaveBeenLastCalledWith("a1", "revenue", [{ column: "Notes", action: "confirm", field: null }]);
  });

  test("Correct offers the fields (a held one disabled, naming its column) and the S11 reasons", async () => {
    await mountPending();
    await click(q("correct-Adj"));
    const field = q("correct-field-Adj");
    const held = [...field.options].find((o) => o.value === "customer_id");
    expect(held.disabled).toBe(true);
    expect(held.textContent).toContain("held by Customer");
    expect([...field.options].find((o) => o.value === "segment").disabled).toBe(false);
    expect([...q("correct-reason-Adj").options].map((o) => o.textContent)).toEqual(REASONS.map((r) => r.label));
    expect(q("correct-note-Adj")).toBeNull();
  });

  test("the reason stays selected for the next correction; an Other note clears after each one", async () => {
    await mountPending();
    api.decideColumns.mockResolvedValue(PENDING_VIEW());
    await click(q("correct-Adj"));
    await change(q("correct-reason-Adj"), "other");
    expect(q("correct-note-Adj").placeholder).toBe("Why? Up to 60 characters; no file names, figures or names.");
    expect(q("correct-note-Adj").maxLength).toBe(60);
    await change(q("correct-note-Adj"), "Adj is not it");
    await change(q("correct-field-Adj"), "segment");
    await click(q("correct-apply-Adj"));
    await flush();
    expect(api.decideColumns).toHaveBeenLastCalledWith("a1", "revenue", [
      { column: "Adj", action: "correct", field: "segment", reason: "other", note: "Adj is not it" }]);
    await click(q("correct-Amount"));
    expect(q("correct-reason-Amount").value).toBe("other");
    await click(q("correct-Adj"));
    expect(q("correct-reason-Adj").value).toBe("other");
    expect(q("correct-note-Adj").value).toBe("", "the note cleared");
  });

  test("a refused note shows S21, keeps the reason and clears the note", async () => {
    await mountPending();
    api.decideColumns.mockRejectedValue({ response: { status: 400, data: { detail: S21_NOTE_REFUSED } } });
    await click(q("correct-Adj"));
    await change(q("correct-reason-Adj"), "other");
    await change(q("correct-note-Adj"), "year 2024");
    await click(q("correct-apply-Adj"));
    await flush();
    expect(q("correct-error-Adj").textContent).toBe(S21_NOTE_REFUSED);
    expect(q("correct-reason-Adj").value).toBe("other");
    expect(q("correct-note-Adj").value).toBe("");
  });

  test("when the model failed the bubble says S12", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW({ ai_reading: { status: "timeout" } }));
    await mount();
    await pickAndMap([file("rev.csv")]);
    expect(q("bubble-ai-failed").textContent).toBe(S12_MODEL_FAILED);
  });

  test("a required field that is not mapped is named in the status line", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW({ missing_required: ["currency"] }));
    await mount();
    await pickAndMap([file("rev.csv")]);
    expect(q("status-revenue").textContent).toBe("Required field not mapped: currency");
    expect([q("compute-button").disabled, q("chat-calculate").disabled]).toEqual([true, true]);
    expect(api.computeAudit).not.toHaveBeenCalled();
  });
});

describe("the header Calculate button is the chat's Calculate (always the same state)", () => {
  test("with a revenue file loaded and a new one attached, Calculate waits for Map, then computes on the new file", async () => {
    const order = [];
    api.uploadChatFile.mockImplementation(async () => { order.push("read"); return VIEW({ file: "new.csv" }); });
    api.updateAudit.mockResolvedValue({});
    api.computeAudit.mockImplementation(async () => { order.push("compute"); return {}; });
    await mount({ datasets: [VIEW({ file: "old.csv" })] });
    await flush();
    expect(q("compute-button").disabled).toBe(false);          // ready on the old file
    await pick([file("new.csv")]);
    expect([q("compute-button").disabled, q("chat-calculate").disabled]).toEqual([true, true]);    // an unread file: map it first
    await act(async () => { q("chat-map").click(); });
    for (let i = 0; i < 5; i += 1) await flush();
    expect([q("compute-button").disabled, q("chat-calculate").disabled]).toEqual([false, false]);
    await act(async () => { q("compute-button").click(); });
    for (let i = 0; i < 5; i += 1) await flush();
    expect(order).toEqual(["read", "compute"]);
  });

  test("the two Calculate buttons never differ, and Map is only on with a file attached or loaded", async () => {
    await mount();
    expect([q("chat-map").disabled, q("compute-button").disabled, q("chat-calculate").disabled]).toEqual([true, true, true]);
    await pick([file("rev.csv")]);
    expect([q("chat-map").disabled, q("compute-button").disabled, q("chat-calculate").disabled]).toEqual([false, true, true]);
  });
});

describe("the revenue banner timing (decision D)", () => {
  const { calculatePressed } = require("@/lib/chatUpload");
  const counted = async (run) => {
    const seen = jest.fn();
    window.addEventListener("blockers:changed", seen);
    await run();
    window.removeEventListener("blockers:changed", seen);
    return seen.mock.calls.length;
  };
  beforeEach(() => window.sessionStorage.clear());

  test("computing does not reset the flag that Map set", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW());
    api.updateAudit.mockResolvedValue({});
    api.computeAudit.mockResolvedValue({});
    await mount();
    await pickAndMap([file("rev.csv")]);
    await act(async () => { q("chat-calculate").click(); });
    for (let i = 0; i < 5; i += 1) await flush();
    expect(api.computeAudit).toHaveBeenCalled();
    expect(calculatePressed("a1")).toBe(true);
  });

  test("the banner is refreshed once after the last file, not after each", async () => {
    api.uploadChatFile.mockResolvedValueOnce(VIEW({ dtype: "pnl", file: "pnl.csv" })).mockResolvedValueOnce(VIEW());
    await mount();
    const n = await counted(async () => {
      await pick([file("pnl.csv"), file("rev.csv")]);
      await act(async () => { q("chat-map").click(); });
      for (let i = 0; i < 5; i += 1) await flush();
    });
    expect(api.uploadChatFile).toHaveBeenCalledTimes(2);
    expect(n).toBe(1);
  });

  test("a file that waits for its type neither refreshes the banner nor releases 'Revenue file missing'", async () => {
    api.uploadChatFile.mockResolvedValueOnce({ status: "unknown_type", file: "mystery.csv", size_bytes: 5, ext: "csv" });
    await mount();
    const n = await counted(async () => { await pickAndMap([file("mystery.csv")]); });
    expect(q("chat-unknown")).not.toBeNull();
    expect(n).toBe(0);
    expect(calculatePressed("a1")).toBe(false);
    expect(api.computeAudit).not.toHaveBeenCalled();
    // once its type is picked the file is read and the banner refreshes
    api.uploadChatFile.mockResolvedValueOnce(VIEW({ dtype: "crm", file: "mystery.csv" }));
    const after = await counted(async () => { await click(q("pick-type-crm")); await flush(); });
    expect(after).toBe(1);
    expect(calculatePressed("a1")).toBe(true);        // set on the answer path: "Revenue file missing" shows without a second press
  });

  test("a file that waits for a replace answer does the same", async () => {
    api.uploadChatFile.mockRejectedValueOnce({ response: { status: 409, data: { detail: { code: "type_loaded", dtype: "revenue", file: "old.csv" } } } });
    await mount();
    const n = await counted(async () => { await pickAndMap([file("new.csv")]); });
    expect(q("chat-replace")).not.toBeNull();
    expect([n, calculatePressed("a1")]).toEqual([0, false]);
    api.uploadChatFile.mockResolvedValueOnce(VIEW({ dtype: "crm", file: "new.csv" }));
    await click(q("replace-yes"));
    await flush();
    expect(calculatePressed("a1")).toBe(true);
  });
});

describe("one press at a time", () => {
  test("while files are being read Map and both Calculate buttons are off and nothing is read twice; Calculate then computes once", async () => {
    let release;
    api.uploadChatFile.mockImplementation(() => new Promise((resolve) => { release = () => resolve(VIEW()); }));
    api.updateAudit.mockResolvedValue({});
    api.computeAudit.mockResolvedValue({});
    await mount({ datasets: [VIEW()] });
    await flush();
    await pick([file("rev.csv")]);
    expect(q("chat-map").disabled).toBe(false);
    await act(async () => { q("chat-map").click(); });
    expect([q("chat-map").disabled, q("compute-button").disabled, q("chat-calculate").disabled]).toEqual([true, true, true]);
    await act(async () => { q("chat-map").click(); q("compute-button").click(); q("chat-calculate").click(); });     // second presses do nothing
    await act(async () => { release(); });
    for (let i = 0; i < 6; i += 1) await flush();
    expect(api.uploadChatFile).toHaveBeenCalledTimes(1);
    expect(api.computeAudit).not.toHaveBeenCalled();
    await act(async () => { q("compute-button").click(); q("chat-calculate").click(); });
    for (let i = 0; i < 6; i += 1) await flush();
    expect(api.computeAudit).toHaveBeenCalledTimes(1);
  });
});
