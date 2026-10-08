import React, { act } from "react";
import { createRoot } from "react-dom/client";

import Dashboard from "./Dashboard";
import * as api from "@/lib/api";
import sample from "./fixtures/sample_results.json";

jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), getResults: jest.fn(), readNarrative: jest.fn(), generateNarrative: jest.fn(), getDisclosure: jest.fn(),
  getClaimRegister: jest.fn(), updateClaimInputs: jest.fn(), claimsCsvUrl: () => "x", exportUrl: () => "x", reportUsage: jest.fn(),
  NARRATIVE_TIMEOUT_MS: 150000, NARRATIVE_EXPECTED_SECONDS: 33,
}));
jest.mock("react-router-dom", () => ({ useParams: () => ({ id: "a1" }), useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));
jest.mock("recharts", () => new Proxy({}, { get: () => ({ children }) => <div>{children}</div> }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Degrade, don't die (CLAUDE.md rule 20): the gateway fails, every computed metric still renders with its citation.
test("when the narrative cannot be generated the metrics render with their sources and S17 says why", async () => {
  api.getAudit.mockResolvedValue(sample.audit);
  api.getResults.mockResolvedValue(sample);
  api.readNarrative.mockResolvedValue({ narrative_status: "unavailable", reason: "The provider did not answer" });
  api.getDisclosure.mockResolvedValue(null);
  api.getClaimRegister.mockResolvedValue({ claims: [], register: [] });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<Dashboard />); });
  await act(async () => { await Promise.resolve(); });
  const notice = host.querySelector('[data-testid="narrative-unavailable"]');
  expect(notice.textContent).toContain("Narrative could not be generated.");
  expect(notice.textContent).toContain("The computed metrics below are unaffected — they come from the calculation engine, not the narrative.");
  expect(host.textContent).toContain("Ending ARR202,125 EUR");
  // Each figure keeps its citation: a source-lineage trigger wraps it (the card shows file, sheet, rows on hover).
  for (const metric of ["arr", "nrr", "gross_churn"]) {
    expect(host.querySelector(`[data-testid="provenance-hover-${metric}"]`)).not.toBeNull();
  }
  expect(sample.results.arr.source.row_numbers.length).toBeGreaterThan(0);
  await act(async () => { root.unmount(); });
  host.remove();
});

const CITED_BLOCKS = ["mrr-by-segment-chart", "cohort-retention", "anomaly-flags", "segment-paths", "new-mrr-by-quarter"];

async function mountDashboard(results) {
  api.getAudit.mockResolvedValue(sample.audit);
  api.getResults.mockResolvedValue(results);
  api.readNarrative.mockResolvedValue({ narrative_status: "unavailable", reason: "x" });
  api.getDisclosure.mockResolvedValue(null);
  api.getClaimRegister.mockResolvedValue({ claims: [], register: [] });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<Dashboard />); });
  await act(async () => { await Promise.resolve(); });
  return { host, unmount: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}

test("segment paths, new MRR, cohort retention, MRR by segment and anomaly flags show their citation like the other blocks", async () => {
  const { host, unmount } = await mountDashboard(sample);
  for (const id of CITED_BLOCKS) {
    expect(host.querySelector(`[data-testid="provenance-hover-${id}"]`)).not.toBeNull();
  }
  await unmount();
});

test("a block stored without its citation shows no source trigger (the contract test refuses such a payload)", async () => {
  const results = JSON.parse(JSON.stringify(sample));
  delete results.results.mrr_series.source;
  const { host, unmount } = await mountDashboard(results);
  expect(host.querySelector('[data-testid="provenance-hover-mrr-by-segment-chart"]')).toBeNull();
  expect(host.querySelector('[data-testid="provenance-hover-cohort-retention"]')).not.toBeNull();
  await unmount();
});
