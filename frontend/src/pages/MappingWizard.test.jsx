import React, { act } from "react";
import { createRoot } from "react-dom/client";

import MappingWizard from "./MappingWizard";
import * as api from "@/lib/api";
import {
  S1_TEXT_REPLY, S2_EXPLAINER_CONSENT, S3_EXPLAINER_NO_CONSENT, S4_DROP_ZONE, S7_REFUSED, S12_MODEL_FAILED, S21_NOTE_REFUSED, REASONS,
} from "@/lib/chatUpload";

jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), getDatasets: jest.fn(), uploadChatFile: jest.fn(), decideColumns: jest.fn(), reportUsage: jest.fn(),
  saveMapping: jest.fn(), computeAudit: jest.fn(), getRevenueCustomers: jest.fn(), updateAudit: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({ useParams: () => ({ id: "a1" }), useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));
jest.mock("@/components/DeckPanel", () => () => <div data-testid="deck-panel" />);

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
    expect(q("chat-paperclip")).not.toBeNull();
    expect(q("chat-file-input").multiple).toBe(true);
  });

  test("the explainer follows the audit's consent: S2 when ticked, S3 when not", async () => {
    await mount();
    expect(q("chat-explainer").textContent).toBe(S2_EXPLAINER_CONSENT);
    await act(async () => { root.unmount(); }); host.remove();
    await mount({ audit: { ...AUDIT, structure_reading_consent: false } });
    expect(q("chat-explainer").textContent).toBe(S3_EXPLAINER_NO_CONSENT);
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
    await pick([file("rev.csv", 2048)]);
    expect(api.uploadChatFile).toHaveBeenCalledWith("a1", expect.any(File), {});
    const analyst = q("chat-analyst-bubble");
    expect(analyst.textContent).toContain("rev.csv");
    expect(analyst.textContent).toContain("2.0 KB");
    expect(q("bubble-head").textContent).toBe("Detected: Revenue lines · 1,240 rows · 24 months (Jan 2023 – Dec 2024)");
    const table = q("mapping-table-revenue");
    expect([...table.querySelectorAll("thead th")].map((th) => th.textContent)).toEqual(["Column", "Field", "Confidence", "Source", ""]);
    expect(q("source-Customer").textContent).toBe("Rules");
    expect(q("confidence-Customer").textContent).toBe("100");
    expect(q("column-row-Memo")).toBeNull();
    expect(q("unused-toggle-revenue").textContent).toContain("Not used (1)");
    await click(q("unused-toggle-revenue"));
    expect(q("column-row-Memo")).not.toBeNull();
    expect(q("correct-Memo")).not.toBeNull();
    expect(q("status-revenue").textContent).toBe("Ready for compute");
    expect(q("revenue-settings")).not.toBeNull();
  });

  test("files are sent one at a time, in drop order", async () => {
    const order = [];
    let release;
    api.uploadChatFile.mockImplementationOnce((id, f) => { order.push(f.name); return new Promise((r) => { release = () => r(VIEW()); }); });
    api.uploadChatFile.mockImplementationOnce((id, f) => { order.push(f.name); return Promise.resolve(VIEW({ dtype: "crm", file: "crm.csv" })); });
    await mount();
    await pick([file("first.csv"), file("second.csv")]);
    expect(order).toEqual(["first.csv"]);
    await act(async () => { release(); });
    await flush();
    expect(order).toEqual(["first.csv", "second.csv"]);
  });

  test("anything but xlsx or csv is refused in the browser with S7 and counted by extension", async () => {
    await mount();
    await pick([file("board.pptx")]);
    expect(api.uploadChatFile).not.toHaveBeenCalled();
    expect(q("chat-text-system").textContent).toBe(S7_REFUSED);
    expect(api.reportUsage).toHaveBeenCalledWith("a1", { rejected_extension: "pptx" });
  });

  test("an unknown type asks for it and sends the same file again with the type picked", async () => {
    api.uploadChatFile.mockResolvedValueOnce({ status: "unknown_type", file: "mystery.csv", size_bytes: 5, ext: "csv" });
    api.uploadChatFile.mockResolvedValueOnce(VIEW({ dtype: "crm", file: "mystery.csv" }));
    await mount();
    const f = file("mystery.csv");
    await pick([f]);
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
    await pick([f]);
    expect(q("chat-replace").textContent).toContain("A revenue file is already loaded (old.csv). Replace it?");
    await click(q("replace-yes"));
    await flush();
    expect(api.uploadChatFile).toHaveBeenLastCalledWith("a1", f, { dtype: "revenue", replace: true });
    api.uploadChatFile.mockRejectedValueOnce(conflict);
    await pick([file("again.csv")]);
    await click(q("replace-no"));
    expect(q("chat-replace")).toBeNull();
    expect(api.uploadChatFile).toHaveBeenCalledTimes(3);      // Keep current sent nothing more
  });

  test("the same file again says S14", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW({ status: "same_file", version: 3 }));
    await mount();
    await pick([file("rev.csv")]);
    expect(q("bubble-same").textContent).toBe("Same file as before: saved mapping v3 applied.");
  });
});

describe("the revenue settings", () => {
  test("FX rates save as they change and never carry the mapping, so a click is the only way to confirm a column", async () => {
    jest.useFakeTimers();
    try {
      api.uploadChatFile.mockResolvedValue(PENDING_VIEW());
      api.saveMapping.mockResolvedValue({ ok: true });
      await mount();
      await pick([file("rev.csv")]);
      expect(q("revenue-settings")).not.toBeNull();
      await change(q("fx-ccy-input"), "usd");
      await change(q("fx-rate-input"), "0.9");
      await act(async () => { q("revenue-settings").querySelector("button svg")?.closest("button"); });
      const add = [...q("revenue-settings").querySelectorAll("button")].find((b) => b.textContent.includes("Add"));
      await click(add);
      await act(async () => { jest.advanceTimersByTime(700); });
      expect(api.saveMapping).toHaveBeenCalledTimes(1);
      const [, dtype, payload] = api.saveMapping.mock.calls[0];
      expect(dtype).toBe("revenue");
      expect(payload).toEqual({ fx: { USD: 0.9 }, billing_terms: {} });
      expect("mapping" in payload).toBe(false);
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("the mapping table", () => {
  const mountPending = async () => {
    api.uploadChatFile.mockResolvedValue(PENDING_VIEW());
    await mount();
    await pick([file("rev.csv")]);
  };

  test("AI, unsure and undecided rows wait for a click; Compute is disabled and the status says how many", async () => {
    await mountPending();
    expect(q("status-revenue").textContent).toBe("2 columns wait for your decision");
    expect(q("compute-button").disabled).toBe(true);
    expect(q("bubble-head").textContent).toContain("months: after the date column is confirmed");
    expect(q("source-Adj").textContent).toBe("AI suggestion, not verified");
    expect(q("confidence-Amount").textContent).toBe("30");
    expect(q("source-Notes").textContent).toBe("Needs your decision");
    expect(q("needs-field-Notes").value).toBe("");
    expect(q("needs-field-Notes").selectedOptions[0].textContent).toBe("Not used");
    expect(q("confirm-Amount")).not.toBeNull();
    expect(q("correct-Customer")).not.toBeNull();
    expect(q("confirm-Customer")).toBeNull();
  });

  test("a confidence lowered by the values says why (S9)", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW({ columns: [row("Amount", { field: "amount", state: "unsure", confidence: 0, fit_note: "0 of 20 values are numbers", pending: true })], pending: 1 }));
    await mount();
    await pick([file("rev.csv")]);
    expect(q("confidence-Amount").textContent).toBe("0 · 0 of 20 values are numbers");
  });

  test("Confirm sends one decision and the new state replaces the bubble; Compute enables once nothing waits", async () => {
    await mountPending();
    api.decideColumns.mockResolvedValue(VIEW());
    await click(q("confirm-Amount"));
    await flush();
    expect(api.decideColumns).toHaveBeenCalledWith("a1", "revenue", [{ column: "Amount", action: "confirm", field: "amount" }]);
    expect(q("status-revenue").textContent).toBe("Ready for compute");
    expect(q("compute-button").disabled).toBe(false);
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
    await pick([file("rev.csv")]);
    expect(q("bubble-ai-failed").textContent).toBe(S12_MODEL_FAILED);
  });

  test("a required field that is not mapped is named in the status line", async () => {
    api.uploadChatFile.mockResolvedValue(VIEW({ missing_required: ["currency"] }));
    await mount();
    await pick([file("rev.csv")]);
    expect(q("status-revenue").textContent).toBe("Required field not mapped: currency");
    expect(q("compute-button").disabled).toBe(true);
  });
});
