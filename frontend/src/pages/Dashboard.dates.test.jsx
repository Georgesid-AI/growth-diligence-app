// Release 1, committed before the code: docs/specs/dates-and-periods.md (plan section 3, the regression required in Release 1).
// A revenue file ending June 2019, an as-of month set to 30 Jun 2026, analysed in October 2026: every figure is labelled June
// 2019, and 2026 is printed only as the requested analysis date. failing() becomes test() in the code PR.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import Dashboard from "./Dashboard";
import * as api from "@/lib/api";
import sample from "./fixtures/sample_results.json";

jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), getResults: jest.fn(), readNarrative: jest.fn(), generateNarrative: jest.fn(), getDisclosure: jest.fn(),
  getClaimRegister: jest.fn(), updateClaimInputs: jest.fn(), claimsCsvUrl: () => "x", exportUrl: () => "x", reportUsage: jest.fn(),
  getVerdict: jest.fn(), putIcInputs: jest.fn(), getMemo: jest.fn(), getLlmUsage: jest.fn(), getIntegrity: jest.fn(),
  NARRATIVE_TIMEOUT_MS: 150000, NARRATIVE_EXPECTED_SECONDS: 33,
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({ useParams: () => ({ id: "a1" }), useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));
jest.mock("recharts", () => new Proxy({}, { get: () => ({ children }) => <div>{children}</div> }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const BLOCKS = ["arr", "mrr_series", "revenue_series", "customers_series", "nrr", "gross_churn", "acv_path", "cohort_retention"];

function regressionResults() {
  const data = JSON.parse(JSON.stringify(sample));
  const r = data.results;
  r.as_of_month = "2026-06";
  r.arr.month = "2019-06";
  r.source_period = { month: "2019-06", status: "Complete", complete_by: "as_of", evidence_to: "2019-06" };
  r.metric_periods = Object.fromEntries(BLOCKS.map((b) => [b, { first: "2017-07", last: "2019-06", missing: [] }]));
  data.audit = { ...data.audit, as_of_month: "2026-06-30", analysis_date: "2026-10-15", computed_at: "2026-10-15T09:00:00+00:00" };
  return data;
}

async function mountDashboard(data) {
  api.getAudit.mockResolvedValue(data.audit);
  api.getResults.mockResolvedValue(data);
  api.readNarrative.mockResolvedValue({ narrative_status: "unavailable", reason: "x" });
  api.getDisclosure.mockResolvedValue(null);
  api.getClaimRegister.mockResolvedValue({ claims: [], register: [] });
  api.getVerdict.mockResolvedValue(null);
  api.getLlmUsage.mockResolvedValue({ run_id: "a1", calls: 0, structure_calls: 0, cache_hits: 0, input_tokens: 0, output_tokens: 0,
    estimated_cost_usd: 0, by_step: {} });
  api.getIntegrity.mockResolvedValue(null);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<Dashboard />); });
  await act(async () => { await Promise.resolve(); });
  return { host, done: async () => { await act(async () => { root.unmount(); }); host.remove(); } };
}

test("plan 3 regression: the requested analysis date and the latest valid source period are shown apart, and figures read June 2019", async () => {
  const { host, done } = await mountDashboard(regressionResults());
  try {
    expect(host.querySelector('[data-testid="dates-line"]').textContent)
      .toBe("Requested analysis date: 15 Oct 2026 · Latest valid source period: June 2019 (Complete)");
    expect(host.textContent).toContain("Evidence to June 2019");
    expect(host.textContent).not.toContain("30 Jun 2026");
    expect(host.textContent).not.toContain("2026-06");
    expect(host.textContent).toContain("Jul 2017 – Jun 2019");
    const years = host.textContent.match(/(?:\d{1,2} \w{3} )?2026(?:-\d{2}-\d{2})?/g) || [];
    expect(years.every((y) => y === "15 Oct 2026" || y === "2026-10-15")).toBe(true);
  } finally { await done(); }
});

test("a metric with months missing shows the list of months beside its period", async () => {
  const data = regressionResults();
  data.results.metric_periods.arr = { first: "2017-07", last: "2019-06", missing: ["2018-03", "2018-04"] };
  const { host, done } = await mountDashboard(data);
  try {
    expect(host.textContent).toContain("Months missing: Mar 2018, Apr 2018");
  } finally { await done(); }
});

test("a possibly partial last month says so beside the latest valid source period", async () => {
  const data = regressionResults();
  data.results.source_period = { month: "2019-06", status: "Possibly partial", complete_by: null, evidence_to: "2019-06" };
  const { host, done } = await mountDashboard(data);
  try {
    expect(host.querySelector('[data-testid="dates-line"]').textContent).toContain("Latest valid source period: June 2019 (Possibly partial)");
  } finally { await done(); }
});
