// PR 3 (docs/design/read-check-review.md section 11, docs/design/audit-page-mockup.html): the default Upload page is the reading screen. Run WITHOUT
// ?view=legacy: no "Why this step matters", no long explainer, no deck panel; the one-sentence explainer, the AI-reading tick, Run audit at the right.
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
jest.mock("@/components/DeckPanel", () => () => <div data-testid="deck-panel" />);
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const AUDIT = { id: "a1", company_name: "Target", reporting_currency: "EUR", fiscal_year_end: 12, structure_reading_consent: true, as_of_month: null, datasets: {} };
const EMPTY = { files: [], tables: { confirmed: [], rejected: [], cannot_check: [] }, counts: { confirmed: 0, rejected: 0, cannot_check: 0 }, cards: [], review: {} };

test("the default Upload page is the reading screen: one sentence, the tick, Run audit at the right, no Why this step matters, no deck panel", async () => {
  api.getAudit.mockResolvedValue(AUDIT);
  api.getDatasets.mockResolvedValue([]);
  api.reportUsage.mockResolvedValue({});
  api.getReview.mockResolvedValue({ computed: false });
  api.getDecks.mockResolvedValue({ decks: [], candidates: [] });
  api.getReading.mockResolvedValue(EMPTY);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<MappingWizard />); });
  await act(async () => { await Promise.resolve(); });
  const q = (id) => host.querySelector(`[data-testid="${id}"]`);
  expect(q("reading-explainer").textContent).toMatch(/^The model reads each file in full\./);
  expect(q("setup-consent-checkbox").checked).toBe(true);
  expect(q("reading-screen")).not.toBeNull();
  expect(q("run-audit-top-host")).not.toBeNull();
  expect(q("reading-top").contains(q("run-audit-top-host"))).toBe(true);
  expect(host.textContent).not.toContain("Why this step matters");
  expect(q("deck-panel")).toBeNull();
  expect(q("consent-block")).toBeNull();
  expect(q("heading-confirmed").textContent).toBe("Confirmed · 0");
  expect(q("more-settings").open).toBe(false);
  await act(async () => { root.unmount(); });
  host.remove();
});
