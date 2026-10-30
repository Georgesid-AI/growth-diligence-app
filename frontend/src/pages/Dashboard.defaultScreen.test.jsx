// PR 3 (docs/design/read-check-review.md section 11): the questions ("Needs your attention"), the claims list and the five-claims conclusion stay in the
// code and leave the default screen. This file runs WITHOUT ?view=legacy; the files that test them set it.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import Dashboard from "./Dashboard";
import * as api from "@/lib/api";
import sample from "./fixtures/sample_results.json";

jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), getResults: jest.fn(), readNarrative: jest.fn(), generateNarrative: jest.fn(), getDisclosure: jest.fn(),
  getClaimRegister: jest.fn(), getBlockers: jest.fn(), updateClaimInputs: jest.fn(), claimsCsvUrl: () => "x", exportUrl: () => "x", reportUsage: jest.fn(),
  getVerdict: jest.fn(), putIcInputs: jest.fn(), getMemo: jest.fn(), getIntegrity: jest.fn(), getDatasets: jest.fn(), getDecks: jest.fn(),
  NARRATIVE_TIMEOUT_MS: 150000, NARRATIVE_EXPECTED_SECONDS: 33,
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({ useParams: () => ({ id: "a1" }), useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));
jest.mock("@/components/NeedsAttention", () => () => <div data-testid="needs-attention" />);
jest.mock("@/components/FiveClaims", () => () => <div data-testid="verdict-five" />);
jest.mock("@/components/ClaimRegister", () => () => <div data-testid="claim-register" />);
jest.mock("@/components/Verdict", () => ({ Conclusion: () => <div data-testid="verdict" />, VerdictDetail: () => null, ReportDownload: () => null }));
jest.mock("recharts", () => new Proxy({}, { get: () => ({ children }) => <div>{children}</div> }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

test("the default Audit page has no conclusion of five claims, no Needs your attention and no claims list", async () => {
  api.getBlockers.mockResolvedValue([]);
  api.getAudit.mockResolvedValue({ ...sample.audit, target_arr: 1000000, target_date: "2026-12-31", as_of_month: null, reporting_currency: "EUR",
    datasets: { revenue: { months: { first: "2023-01", last: "2024-02" } } } });
  api.getResults.mockResolvedValue(sample);
  api.readNarrative.mockResolvedValue({ narrative_status: "unavailable", reason: "x" });
  api.getDisclosure.mockResolvedValue(null);
  api.getClaimRegister.mockResolvedValue({ claims: [], register: [] });
  api.getVerdict.mockResolvedValue(null);
  api.getIntegrity.mockResolvedValue(null);
  api.getDatasets.mockResolvedValue([]);
  api.getDecks.mockResolvedValue({ decks: [], candidates: [] });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<Dashboard />); });
  await act(async () => { await Promise.resolve(); });
  await act(async () => { await Promise.resolve(); });
  const has = (id) => host.querySelector(`[data-testid="${id}"]`);
  expect(has("assumptions-strip")).not.toBeNull();
  for (const id of ["verdict", "verdict-five", "needs-attention", "claim-register"]) expect(has(id)).toBeNull();
  await act(async () => { root.unmount(); });
  host.remove();
});
