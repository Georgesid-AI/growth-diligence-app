import React, { act } from "react";
import { createRoot } from "react-dom/client";

import RunAudit from "./RunAudit";
import * as api from "@/lib/api";

const mockNavigate = jest.fn();
jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), updateAudit: jest.fn(), reportUsage: jest.fn(), getBlockers: jest.fn(),
  uploadChatFile: jest.fn(), uploadDeck: jest.fn(), runStage: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({
  useParams: () => ({ id: "a1" }), useNavigate: () => mockNavigate, useLocation: () => ({ pathname: "/audit/a1/run" }),
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a>,
}), { virtual: true });
jest.mock("@/components/AuditSetup", () => ({ __esModule: true, default: () => <div data-testid="audit-setup" /> }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const AUDIT = { id: "a1", company_name: "TestCo", reporting_currency: "EUR", target_arr: 1000000, as_of_month: null };
const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
let root, host;

beforeEach(() => {
  jest.resetAllMocks();
  mockNavigate.mockClear();
  api.getAudit.mockResolvedValue(AUDIT);
  api.getBlockers.mockResolvedValue([]);
  api.reportUsage.mockResolvedValue(null);
  api.uploadChatFile.mockResolvedValue({ status: "ok", dtype: "revenue" });
  api.uploadDeck.mockResolvedValue({});
});
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });

async function mount() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<RunAudit />); });
  await act(async () => { await Promise.resolve(); });
}
const attach = async (...names) => {
  const files = names.map((n) => new File(["x"], n));
  await act(async () => {
    const input = q("run-file-input");
    Object.defineProperty(input, "files", { value: files, configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
};

test("one Run audit button; the stages are listed in order with their state", async () => {
  await mount();
  expect(document.body.querySelectorAll('[data-testid="run-audit"]')).toHaveLength(1);
  expect(q("run-audit").textContent).toBe("Run audit");
  expect([...q("run-stages").querySelectorAll("li")].map((li) => li.getAttribute("data-testid"))).toEqual(["stage-mapping", "stage-engine", "stage-claims"]);
  expect(q("stage-mapping").textContent).toContain("File mapping");
  expect(q("stage-engine").textContent).toContain("Engine calculations");
  expect(q("stage-claims").textContent).toContain("Claim extraction from decks");
});

test("one press runs the files and the three stages in order and opens the review screen", async () => {
  const order = [];
  api.uploadChatFile.mockImplementation(async (id, f) => { order.push(`upload:${f.name}`); return { status: "ok" }; });
  api.uploadDeck.mockImplementation(async (id, f) => { order.push(`deck:${f.name}`); return {}; });
  api.runStage.mockImplementation(async (id, key) => { order.push(`stage:${key}`); return { stage: key, status: "done" }; });
  await mount();
  await attach("revenue.csv", "board.pptx");
  expect(q("run-file-list").textContent).toContain("revenue.csv");
  await act(async () => { q("run-audit").click(); });
  await act(async () => { await Promise.resolve(); });
  expect(order).toEqual(["upload:revenue.csv", "stage:mapping", "stage:engine", "deck:board.pptx", "stage:claims"]);
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/review");
});

test("a stage that needs the analyst sends them to the review screen", async () => {
  api.runStage.mockResolvedValue({ stage: "mapping", status: "needs_review", open: 1 });
  await mount();
  await attach("revenue.csv");
  await act(async () => { q("run-audit").click(); });
  await act(async () => { await Promise.resolve(); });
  expect(api.runStage).toHaveBeenCalledTimes(1);
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/review");
});

test("a failed stage says what to do in plain English and Retry stage carries on from it without sending the files again", async () => {
  let fail = true;
  api.runStage.mockImplementation(async (id, key) => (key === "engine" && fail
    ? { stage: key, status: "failed", message: "The calculations could not be completed. Check the mapping on the review screen, then retry this stage." }
    : { stage: key, status: "done" }));
  await mount();
  await attach("revenue.csv");
  await act(async () => { q("run-audit").click(); });
  await act(async () => { await Promise.resolve(); });
  expect(q("stage-mapping").getAttribute("data-status")).toBe("done");
  expect(q("stage-engine").getAttribute("data-status")).toBe("failed");
  expect(q("stage-engine-message").textContent).toContain("could not be completed");
  expect(q("stage-claims").getAttribute("data-status")).toBe("idle");
  expect(mockNavigate).not.toHaveBeenCalled();
  fail = false;
  api.uploadChatFile.mockClear();
  await act(async () => { q("retry-engine").click(); });
  await act(async () => { await Promise.resolve(); });
  expect(api.uploadChatFile).not.toHaveBeenCalled();
  expect(q("stage-engine").getAttribute("data-status")).toBe("done");
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/review");
});

test("under React.StrictMode the stage updates still land (alive ref is re-armed on the second mount)", async () => {
  api.runStage.mockResolvedValue({ stage: "mapping", status: "needs_review", open: 1 });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<React.StrictMode><RunAudit /></React.StrictMode>); });
  await act(async () => { await Promise.resolve(); });
  await attach("revenue.csv");
  await act(async () => { q("run-audit").click(); });
  await act(async () => { await Promise.resolve(); });
  expect(q("stage-mapping").getAttribute("data-status")).toBe("needs_review");
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/review");
});
