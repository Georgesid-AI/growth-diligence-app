// The default Upload page never shows the old mapping block, for any file. A file the old path still waits on gets one line linking to ?view=legacy.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import MappingWizard from "./MappingWizard";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), getDatasets: jest.fn(), uploadChatFile: jest.fn(), decideColumns: jest.fn(), decideLines: jest.fn(), decideRecognition: jest.fn(), reportUsage: jest.fn(),
  changeDatasetType: jest.fn(), confirmForecastClaims: jest.fn(), getReview: jest.fn(), getDecks: jest.fn(), runStage: jest.fn(), uploadDeck: jest.fn(),
  saveMapping: jest.fn(), saveFx: jest.fn(), computeAudit: jest.fn(), getRevenueCustomers: jest.fn(), updateAudit: jest.fn(), putIcInputs: jest.fn(),
  getReading: jest.fn(), decideCard: jest.fn(), changeReading: jest.fn(), getCell: jest.fn(), getDeckPage: jest.fn(), downloadReading: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({ useParams: () => ({ id: "a1" }), useNavigate: () => jest.fn(), useLocation: () => ({ pathname: "/audit/a1/mapping" }) }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const AUDIT = { id: "a1", company_name: "Target", reporting_currency: "EUR", fiscal_year_end: 12, structure_reading_consent: true, as_of_month: null, datasets: {} };
const EMPTY = { files: [], tables: { confirmed: [], rejected: [], cannot_check: [] }, counts: { confirmed: 0, rejected: 0, cannot_check: 0 }, cards: [], review: {} };
const col = (name, extra = {}) => ({ column: name, field: null, state: "confirmed", source: "rules", confidence: 90, pending: false, ...extra });
const VIEW = (over = {}) => ({
  status: "ok", dtype: "revenue", file: "rev.csv", size_bytes: 2048, ext: "csv", row_count: 10, months: { count: 24, first: "2023-01", last: "2024-12" },
  pending: 0, missing_required: [], version: 1, ai_reading: { status: "rules" }, fields: [], mapping: {}, fx: {}, billing_terms: {}, uploaded_at: "t", saved: true,
  columns: [col("Customer", { field: "customer_id" }), col("Amount", { field: "amount" })], ...over,
});
const OLD_BLOCK = ["mapping-table-revenue", "chat-system-revenue", "type-label-revenue", "status-revenue"];

async function render(datasets) {
  window.history.pushState({}, "", "/");
  api.getAudit.mockResolvedValue(AUDIT);
  api.getDatasets.mockResolvedValue(datasets);
  api.reportUsage.mockResolvedValue({});
  api.getReview.mockResolvedValue({ computed: false });
  api.getDecks.mockResolvedValue({ decks: [], candidates: [] });
  api.getReading.mockResolvedValue(EMPTY);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<MappingWizard />); });
  await act(async () => { await Promise.resolve(); });
  await act(async () => { await Promise.resolve(); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}
const q = (host, id) => host.querySelector(`[data-testid="${id}"]`);

test("a settled file shows no old mapping block and no waiting line", async () => {
  const { host, done } = await render([VIEW()]);
  OLD_BLOCK.forEach((id) => expect(q(host, id)).toBeNull());
  ["Detected", "Revenue row", "Last actual column", "Sent to the AI", "Confirm all", "Why this step matters", "Supports"].forEach((t) => expect(host.textContent).not.toContain(t));
  expect(q(host, "older-mapping-waits")).toBeNull();
  await done();
});

test("a file with open answers shows only the one waiting line, linking to ?view=legacy", async () => {
  const { host, done } = await render([VIEW({ pending: 2, columns: [col("Amount", { state: "unsure", pending: true }), col("Adj", { state: "needs", pending: true })] })]);
  OLD_BLOCK.forEach((id) => expect(q(host, id)).toBeNull());
  const line = q(host, "older-mapping-waits");
  expect(line.textContent).toBe("Older mapping waits for 2 answers before the engine can run — answer them");
  expect(line.querySelector("a").getAttribute("href")).toBe("?view=legacy");
  expect(host.querySelectorAll('[data-testid="older-mapping-waits"]').length).toBe(1);
  await done();
});
