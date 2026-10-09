import React, { act } from "react";
import { createRoot } from "react-dom/client";

import { Layout } from "./Layout";
import { BLOCKERS_CHANGED } from "./BlockerBanner";
import * as api from "@/lib/api";
import { REVENUE_REQUIRED_NOTE, setCalculatePressed } from "@/lib/chatUpload";

jest.mock("@/lib/api", () => ({ getBlockers: jest.fn() }));
jest.mock("react-router-dom", () => ({
  useNavigate: () => jest.fn(),
  useLocation: () => ({ pathname: "/audit/a1/mapping" }),
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a>,
}), { virtual: true });

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const BLOCKERS = [
  { kind: "revenue_file_missing", text: "Revenue file missing: upload and map it to compute metrics." },
  { kind: "claim_contradicted", text: "Top-5 claim contradicted: revenue 100 EUR vs 80 EUR observed (board.pptx, slide 4)." },
  { kind: "revenue_reconciliation", text: "Revenue file and P&L differ by 10% over 2024-01–2024-12 (13,200 EUR vs 12,000 EUR).", link: "/audit/a1/diagnostics" },
];
const AUDIT = { id: "a1", company_name: "Target", reporting_currency: "EUR", target_arr: 1000000 };
const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
let root, host;

async function mount(audit) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Layout audit={audit}><div data-testid="page" /></Layout>); });
}
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); jest.clearAllMocks(); window.sessionStorage.clear(); });

test("an audit view shows the blockers the server returns, in the header, with the evidence link", async () => {
  setCalculatePressed("a1");
  api.getBlockers.mockResolvedValue(BLOCKERS);
  await mount(AUDIT);
  const banner = q("blocker-banner");
  expect(banner).not.toBeNull();
  expect(banner.closest("header")).not.toBeNull();
  expect(["blocker-revenue_file_missing", "blocker-claim_contradicted", "blocker-revenue_reconciliation"].map((id) => q(id).textContent.startsWith(BLOCKERS.find((b) => `blocker-${b.kind}` === id).text))).toEqual([true, true, true]);
  expect(q("blocker-link").getAttribute("href")).toBe("/audit/a1/diagnostics");
  expect(banner.querySelectorAll("li").length).toBe(3);
  expect(api.getBlockers).toHaveBeenCalledWith("a1");
});

test("the revenue file blocker is not shown when the screen opens; the other two are", async () => {
  api.getBlockers.mockResolvedValue(BLOCKERS);
  await mount(AUDIT);
  expect(q("blocker-revenue_file_missing")).toBeNull();
  expect(q("blocker-claim_contradicted")).not.toBeNull();
  expect(q("blocker-banner").querySelectorAll("li").length).toBe(2);
});

test("only the revenue file missing: no banner until Calculate is pressed, then the banner with the one-line reason under it", async () => {
  api.getBlockers.mockResolvedValue(BLOCKERS.slice(0, 1));
  await mount(AUDIT);
  expect(q("blocker-banner")).toBeNull();
  setCalculatePressed("a1");
  await act(async () => { window.dispatchEvent(new Event(BLOCKERS_CHANGED)); });
  expect(q("blocker-revenue_file_missing").textContent).toContain("Revenue file missing: upload and map it to compute metrics.");
  expect(q("blocker-revenue-note").textContent).toBe(REVENUE_REQUIRED_NOTE);
  expect(REVENUE_REQUIRED_NOTE).toBe("The revenue file is the only required file. Every metric in the audit (ARR, NRR, churn, CAC payback) is computed from it; without it nothing can be calculated or verified.");
});

test("a revenue file that is uploaded and not confirmed shows its own wording, with no required-file line", async () => {
  setCalculatePressed("a1");
  api.getBlockers.mockResolvedValue([{ kind: "revenue_file_missing", text: "Revenue file uploaded – confirm the mapping to compute metrics." }]);
  await mount(AUDIT);
  expect(q("blocker-revenue_file_missing")).not.toBeNull();
  expect(q("blocker-revenue-note")).toBeNull();
});

test("no blocker, no banner; and it clears when the server stops returning one", async () => {
  setCalculatePressed("a1");
  api.getBlockers.mockResolvedValue(BLOCKERS.slice(0, 1));
  await mount(AUDIT);
  expect(q("blocker-revenue_file_missing")).not.toBeNull();
  api.getBlockers.mockResolvedValue([]);
  await act(async () => { window.dispatchEvent(new Event(BLOCKERS_CHANGED)); });
  expect(q("blocker-banner")).toBeNull();
});

test("the audit list has no banner and asks for none", async () => {
  await mount(undefined);
  expect(q("blocker-banner")).toBeNull();
  expect(api.getBlockers).not.toHaveBeenCalled();
});

test("an audit deleted while its banner is up: the 404 is caught, the banner clears, and later events ask nothing", async () => {
  setCalculatePressed("a1");
  api.getBlockers.mockResolvedValue(BLOCKERS.slice(0, 1));
  await mount(AUDIT);
  expect(q("blocker-revenue_file_missing")).not.toBeNull();
  api.getBlockers.mockRejectedValue(Object.assign(new Error("404"), { response: { status: 404 } }));
  await act(async () => { window.dispatchEvent(new Event(BLOCKERS_CHANGED)); });
  expect(q("blocker-banner")).toBeNull();
  const calls = api.getBlockers.mock.calls.length;
  await act(async () => { window.dispatchEvent(new Event(BLOCKERS_CHANGED)); });
  expect(api.getBlockers.mock.calls.length).toBe(calls);
});
