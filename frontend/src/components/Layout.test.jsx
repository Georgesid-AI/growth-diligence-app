import React, { act } from "react";
import { createRoot } from "react-dom/client";

import { Layout } from "./Layout";
import { BLOCKERS_CHANGED } from "./BlockerBanner";
import * as api from "@/lib/api";
import { REVENUE_REQUIRED_NOTE, setCalculatePressed } from "@/lib/chatUpload";

jest.mock("@/lib/api", () => ({ getBlockers: jest.fn(), getAllowance: jest.fn() }));
const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
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
});

test("the one-line reason under S16a is the sentence the spec gives (chat-upload.md)", () => {
  const spec = require("fs").readFileSync(require("path").join(__dirname, "../../../docs/specs/chat-upload.md"), "utf8").replace(/\s+/g, " ");
  expect(spec).toContain(REVENUE_REQUIRED_NOTE);
});

test("a revenue file that is uploaded and not confirmed shows its own wording in a fresh tab, with no required-file line", async () => {
  window.sessionStorage.clear();                  // another tab, another analyst, the next day: Calculate was never pressed here
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

test.each([0, null, undefined])("the header reads 'target not set' when Target ARR is %p, and the figure once it is set", async (value) => {
  api.getBlockers.mockResolvedValue([]);
  await mount({ ...AUDIT, target_arr: value });
  expect(q("header-target-line").textContent).toBe("EUR · target not set");
  await act(async () => { root.unmount(); }); host.remove();
  await mount(AUDIT);
  expect(q("header-target-line").textContent).toMatch(/^EUR · target .*1,?000,?000.* ARR$/);
});

test("an open audit has four tabs in this order, no Details menu and no Run audit tab", async () => {
  api.getBlockers.mockResolvedValue([]);
  await mount(AUDIT);
  expect(["nav-tab-mapping-wizard", "nav-tab-review", "nav-tab-audit", "nav-tab-missing-data"].map((id) => q(id).textContent))
    .toEqual(["Upload & Mapping", "Review", "Audit", "Diagnostics"]);
  expect([...q("nav-tab-review").parentElement.children].map((b) => b.textContent)).toEqual(["Upload & Mapping", "Review", "Audit", "Diagnostics"]);
  expect(q("nav-details")).toBeNull();
  expect(q("details-menu")).toBeNull();
  expect(q("nav-tab-run-audit")).toBeNull();
  expect(document.body.textContent).not.toMatch(/Details|Run audit|Growth Dashboard/);
});

test.each([
  ["nav-tab-mapping-wizard", "/audit/a1/mapping"],
  ["nav-tab-review", "/audit/a1/review"],
  ["nav-tab-audit", "/audit/a1/dashboard"],
  ["nav-tab-missing-data", "/audit/a1/diagnostics"],
])("the %s tab navigates to %s", async (testid, path) => {
  api.getBlockers.mockResolvedValue([]);
  mockNavigate.mockClear();
  await mount(AUDIT);
  await act(async () => { q(testid).click(); });
  expect(mockNavigate).toHaveBeenCalledWith(path);
});

test("an audit page has an All audits button next to the app name, and both open the Audit Hub", async () => {
  api.getBlockers.mockResolvedValue([]);
  mockNavigate.mockClear();
  await mount(AUDIT);
  expect(q("nav-all-audits").textContent.trim()).toBe("All audits");
  expect(q("nav-all-audits").parentElement).toBe(q("nav-tab-audit-list").parentElement);
  await act(async () => { q("nav-all-audits").click(); });
  await act(async () => { q("nav-tab-audit-list").click(); });
  expect(mockNavigate.mock.calls).toEqual([["/"], ["/"]]);
});

test("the Audit Hub itself has no All audits button and no tabs", async () => {
  await mount(undefined);
  expect(q("nav-all-audits")).toBeNull();
  expect(q("nav-tab-review")).toBeNull();
  expect(q("nav-tab-audit-list")).not.toBeNull();
});

test("the header has no Heuristics badge", async () => {
  api.getBlockers.mockResolvedValue([]);
  api.getAllowance.mockResolvedValue({ state: "ok", percent: 0 });
  await mount(AUDIT);
  expect(document.body.textContent.toLowerCase()).not.toContain("heuristics");
  expect(q("header-target-line")).not.toBeNull();
});

test("the allowance line sits under the header on an audit screen and the blockers stay apart from it", async () => {
  api.getBlockers.mockResolvedValue(BLOCKERS.slice(1, 2));
  api.getAllowance.mockResolvedValue({ state: "warn", percent: 85 });
  await mount(AUDIT);
  expect(q("allowance-warn").closest("header")).toBeNull();
  expect(q("blocker-banner").contains(q("allowance-warn"))).toBe(false);
  expect(q("blocker-banner").querySelectorAll("li").length).toBe(1);
});
