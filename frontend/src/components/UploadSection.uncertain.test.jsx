import React, { act } from "react";
import { createRoot } from "react-dom/client";

import UploadSection from "./UploadSection";
import * as api from "@/lib/api";
import { READINGS_CHANGED } from "@/lib/uploadView";

/**
 * Item 12 of the brief of George, 2026-11-05: above Run audit, when readings await confirmation, one line says so and links to the Uncertain list; Run audit
 * stays enabled. Item 11: the reading step says how many. Run with --no-cache (rule 25).
 */
jest.mock("@/lib/api", () => ({
  getDatasets: jest.fn(), getDecks: jest.fn(), getReview: jest.fn(), getReading: jest.fn(), uploadChatFile: jest.fn(), uploadDeck: jest.fn(), removeDeck: jest.fn(),
  removeDataset: jest.fn(), rereadDataset: jest.fn(), rereadDeck: jest.fn(), runStage: jest.fn(), reportUsage: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({ useNavigate: () => jest.fn() }), { virtual: true });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const AUDIT = { id: "a1", company_name: "Tc", reporting_currency: "EUR", structure_reading_consent: true };
const SHEET = { dtype: "file", file: "Testco_Revenue.xlsx", file_hash: "h1", size_bytes: 100, ext: "xlsx", read_state: "done", read_stage: null,
  read_elapsed: 107, read_checking_elapsed: 2, read_checked: 30, read_total: 30, read_matched: 28, read_items: 30, rows_mapped: 5 };
const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
let root, host;

const item = (rows) => ({ kind: "row", key: `k${rows[0]}`, sheet: "S", row: rows[0], rows, fields: ["role"], first: {}, second: {} });
const reading = (uncertain, figures = []) => ({ files: [{ kind: "sheet", file_hash: "h1", consistency: { uncertain } }, { kind: "deck", figures }], tables: {}, counts: {}, cards: [], review: {} });

async function mount(read) {
  api.getDatasets.mockResolvedValue([SHEET]);
  api.getDecks.mockResolvedValue({ decks: [], candidates: [] });
  api.getReview.mockResolvedValue({ computed: false });
  api.reportUsage.mockResolvedValue({});
  if (read === "fails") api.getReading.mockRejectedValue(new Error("no")); else api.getReading.mockResolvedValue(read);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<UploadSection audit={AUDIT} onChanged={() => {}} onRunning={() => {}} />); });
  await act(async () => { await Promise.resolve(); });
  await act(async () => { await Promise.resolve(); });
}
beforeEach(() => { jest.resetAllMocks(); });
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });

test("uncertain readings: the reading step names them, the notice sits above Run audit with a link, and Run audit stays enabled", async () => {
  await mount(reading([item([6, 7]), item([9])], [{ uncertain: true, id: "c1", reading: { index: 0, options: ["a", "b"], details: [{ value: "1" }, { value: "2" }] } }, { uncertain: false }]));
  expect(q("step-reading-second").textContent).toMatch(/1 file processed · 3 uncertain readings$/);
  const notice = q("uncertain-notice");
  expect(notice.textContent).toBe("3 uncertain readings await confirmation. Ratings exclude them until you confirm. Review →");
  expect(notice.querySelector("a").getAttribute("href")).toBe("#uncertain-list");
  expect(notice.querySelector("a").textContent).toBe("Review →");
  expect(q("run-audit").disabled).toBe(false);
  expect(q("run-audit").compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();     // the notice sits above the button
});

test("nothing uncertain, or a reading that cannot be fetched: no notice and the step reads as before", async () => {
  await mount(reading([]));
  expect(q("uncertain-notice")).toBeNull();
  expect(q("step-reading-second").textContent).toMatch(/1 file processed$/);
  await act(async () => { root.unmount(); });
  host.remove();
  await mount("fails");
  expect(q("uncertain-notice")).toBeNull();
  expect(q("run-audit").disabled).toBe(false);
});

// Combined fixes, 2026-11-05, items 6 and 7: the count is the items not yet picked; it follows every pick without a reload and goes at zero.
const many = (n) => Array.from({ length: n }, (_, i) => item([i + 1]));
const settle = async (read) => {
  api.getReading.mockResolvedValue(read);
  await act(async () => { window.dispatchEvent(new Event(READINGS_CHANGED)); });
  await act(async () => { await Promise.resolve(); });
  await act(async () => { await Promise.resolve(); });
};

test("twelve uncertain readings: a pick makes it eleven in the notice and the step; picking them all removes the line", async () => {
  await mount(reading(many(12)));
  expect(q("uncertain-notice").textContent).toBe("12 uncertain readings await confirmation. Ratings exclude them until you confirm. Review →");
  expect(q("step-reading-second").textContent).toMatch(/12 uncertain readings$/);
  await settle(reading(many(11)));
  expect(q("uncertain-notice").textContent).toBe("11 uncertain readings await confirmation. Ratings exclude them until you confirm. Review →");
  expect(q("step-reading-second").textContent).toMatch(/11 uncertain readings$/);
  await settle(reading(many(1)));
  expect(q("uncertain-notice").textContent).toBe("1 uncertain reading awaits confirmation. Ratings exclude them until you confirm. Review →");
  await settle(reading([]));
  expect(q("uncertain-notice")).toBeNull();
  expect(q("step-reading-second").textContent).not.toMatch(/uncertain/);
});
