import React, { act } from "react";
import { createRoot } from "react-dom/client";

import Diagnostics from "./Diagnostics";
import * as api from "@/lib/api";
import { S22_RECONCILIATION } from "@/lib/chatUpload";

jest.mock("@/lib/api", () => ({ getAudit: jest.fn(), getResults: jest.fn(), reportUsage: jest.fn() }));
jest.mock("react-router-dom", () => ({ useParams: () => ({ id: "a1" }), useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const src = (file, rows) => ({ file, sheet: "CSV", rows, row_numbers: [2] });
const month = (m, file, pnl) => ({ month: m, revenue_file: file, pnl, gap: file - pnl, gap_pct: pnl ? Math.round(((file - pnl) / pnl) * 10000) / 10000 : null,
  source: { revenue_file: src("rev.csv", "row 2"), pnl: src("pnl.csv", "row 2") } });
const REC = { available: true, first: "2024-01", last: "2024-02", file_total: 2000, pnl_total: 2000, gap: 0, gap_pct: 0, blocker: false,
  by_month: [month("2024-01", 1100, 1000), month("2024-02", 900, 1000)] };
const RESULTS = (rec) => ({ audit: {}, results: { reporting_currency: "EUR", missing_data: [], anomalies: null, revenue_reconciliation: rec } });
const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
let root, host;

async function mount(rec) {
  api.getAudit.mockResolvedValue({ id: "a1" });
  api.getResults.mockResolvedValue(RESULTS(rec));
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Diagnostics />); });
}
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); jest.clearAllMocks(); });

test("the reconciliation section lists each month and ends with the window total", async () => {
  await mount(REC);
  const section = q("reconciliation");
  expect(section.querySelector("h3").textContent).toBe(S22_RECONCILIATION);
  expect([...section.querySelectorAll("thead th")].map((th) => th.textContent)).toEqual(["Month", "Revenue file", "P&L", "Gap", "Gap %"]);
  const rows = [...section.querySelectorAll('[data-testid="reconciliation-row"]')];
  expect(rows.map((r) => r.children[0].textContent)).toEqual(["2024-01", "2024-02"]);
  expect(rows[0].children[4].textContent).toBe("10%");
  expect(rows[1].children[4].textContent).toBe("-10%");
  expect(rows[0].getAttribute("title")).toContain("rev.csv");
  const total = q("reconciliation-total");
  expect(total.children[0].textContent).toBe("Window total");
  expect(total.previousElementSibling).toBe(rows[1]);
  expect(total.nextElementSibling).toBeNull();
});

test("a month above 2% with a window total under 2% shows in the table and raises no alert here", async () => {
  await mount(REC);
  expect(q("reconciliation-row")).not.toBeNull();
  expect(document.body.querySelector('[role="alert"]')).toBeNull();
});

test("a gap % of a month whose P&L figure is 0 reads as a dash", async () => {
  await mount({ ...REC, by_month: [month("2024-01", 100, 0)] });
  expect(q("reconciliation-row").children[4].textContent).toBe("—");
});

test("without a P&L the section is hidden", async () => {
  await mount(null);
  expect(q("reconciliation")).toBeNull();
  expect(document.body.textContent).toContain("Forensic Diagnostics");
});
