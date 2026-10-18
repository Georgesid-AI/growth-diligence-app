import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";

import MappingWizard from "./MappingWizard";
import { RunToMapping } from "@/App";
import * as api from "@/lib/api";

// Run audit on the Upload & Mapping page (docs/specs/chat-upload.md section 24): the button and its stages sit below the set-up
// section and above the mapping; Map and Calculate stay.
const mockNavigate = jest.fn();
jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), updateAudit: jest.fn(), reportUsage: jest.fn(), getBlockers: jest.fn(),
  uploadChatFile: jest.fn(), uploadDeck: jest.fn(), runStage: jest.fn(), decideColumns: jest.fn(), changeDatasetType: jest.fn(),
  confirmForecastClaims: jest.fn(), saveMapping: jest.fn(), saveFx: jest.fn(), computeAudit: jest.fn(), getRevenueCustomers: jest.fn(),
  getDatasets: jest.fn(), getReview: jest.fn(), getDecks: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({
  useParams: () => ({ id: "a1" }), useNavigate: () => mockNavigate, useLocation: () => ({ pathname: "/audit/a1/mapping" }),
  Navigate: ({ to }) => <span data-testid="redirect" data-to={to} />,
  BrowserRouter: ({ children }) => <div>{children}</div>, Routes: ({ children }) => <div>{children}</div>, Route: () => null,
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a>,
}), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));
jest.mock("@/components/AuditSetup", () => ({ __esModule: true, default: () => <div data-testid="audit-setup" /> }));
jest.mock("@/components/DeckPanel", () => () => <div data-testid="deck-panel" />);

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const AUDIT = { id: "a1", company_name: "TestCo", reporting_currency: "EUR", target_arr: 1000000, as_of_month: null, structure_reading_consent: true };
const VIEW = (dtype, over = {}) => ({
  status: "ok", dtype, file: `${dtype}.csv`, size_bytes: 10, ext: "csv", row_count: 3, months: null, pending: 0, missing_required: [], version: 1,
  ai_reading: { status: "rules" }, fields: { required: [], optional: [] }, mapping: {}, fx: {}, billing_terms: {}, saved: true,
  uploaded_at: "2026-10-01T09:30:00+00:00", columns: [], ...over });
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
  api.getDatasets.mockResolvedValue([]);
  api.getReview.mockResolvedValue({ computed: false });
  api.getDecks.mockResolvedValue({ decks: [], candidates: [] });
});
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });

async function mount(strict = false) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(strict ? <React.StrictMode><MappingWizard /></React.StrictMode> : <MappingWizard />); });
  await act(async () => { await Promise.resolve(); });
}
const attach = async (...names) => {
  const files = names.map((n) => new File(["x"], n));
  await act(async () => {
    const input = q("chat-file-input");
    Object.defineProperty(input, "files", { value: files, configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
};
const press = async (id) => { await act(async () => { q(id).click(); }); await act(async () => { await Promise.resolve(); }); };
const follows = (a, b) => !!(q(a).compareDocumentPosition(q(b)) & Node.DOCUMENT_POSITION_FOLLOWING);

test("Run audit and its stages sit below the set-up section and above the mapping; Map and Calculate stay", async () => {
  await mount();
  expect(document.body.querySelectorAll('[data-testid="run-audit"]')).toHaveLength(1);
  expect(q("run-audit").textContent).toBe("Run audit");
  expect(follows("audit-setup", "run-audit-panel")).toBe(true);
  expect(follows("run-audit-panel", "fx-settings")).toBe(true);
  expect(follows("run-audit-panel", "upload-chat")).toBe(true);
  expect(follows("run-audit-panel", "deck-panel")).toBe(true);
  expect(q("chat-map")).not.toBeNull();
  expect(q("chat-calculate")).not.toBeNull();
  expect(q("compute-button")).not.toBeNull();
  expect(q("upload-chat").textContent).not.toMatch(/Files already uploaded/);
  expect([...q("run-stages").querySelectorAll("li")].map((li) => li.getAttribute("data-testid"))).toEqual(["stage-mapping", "stage-engine", "stage-claims"]);
  expect(q("stage-mapping").textContent).toContain("File mapping");
  expect(q("stage-engine").textContent).toContain("Engine calculations");
  expect(q("stage-claims").textContent).toContain("Claim extraction from decks");
});

test("the old /audit/:id/run link redirects to Upload & Mapping", () => {
  const html = renderToStaticMarkup(<RunToMapping />);
  expect(html).toContain('data-to="/audit/a1/mapping"');
});

test("one press sends the attached spreadsheets, runs the three stages in order and opens the review screen", async () => {
  const order = [];
  api.uploadChatFile.mockImplementation(async (id, f) => { order.push(`upload:${f.name}`); return { status: "ok" }; });
  api.runStage.mockImplementation(async (id, key) => { order.push(`stage:${key}`); return { stage: key, status: "done" }; });
  await mount();
  await attach("revenue.csv");
  expect(q("chat-messages").textContent).toContain("revenue.csv");
  await press("run-audit");
  expect(order).toEqual(["upload:revenue.csv", "stage:mapping", "stage:engine", "stage:claims"]);
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/review");
});

test("a stage that needs the analyst sends them to the review screen", async () => {
  api.runStage.mockResolvedValue({ stage: "mapping", status: "needs_review", open: 1 });
  await mount();
  await attach("revenue.csv");
  await press("run-audit");
  expect(api.runStage).toHaveBeenCalledTimes(1);
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/review");
});

test("a failed stage says what to do and Retry stage carries on from it without sending the files again", async () => {
  let fail = true;
  api.runStage.mockImplementation(async (id, key) => (key === "engine" && fail
    ? { stage: key, status: "failed", message: "The calculations could not be completed. Check the mapping on the review screen, then retry this stage." }
    : { stage: key, status: "done" }));
  await mount();
  await attach("revenue.csv");
  await press("run-audit");
  expect(q("stage-mapping").getAttribute("data-status")).toBe("done");
  expect(q("stage-engine").getAttribute("data-status")).toBe("failed");
  expect(q("stage-engine-message").textContent).toContain("could not be completed");
  expect(q("stage-claims").getAttribute("data-status")).toBe("idle");
  expect(mockNavigate).not.toHaveBeenCalled();
  fail = false;
  api.uploadChatFile.mockClear();
  await press("retry-engine");
  expect(api.uploadChatFile).not.toHaveBeenCalled();
  expect(q("stage-engine").getAttribute("data-status")).toBe("done");
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/review");
});

test("a file the run sent is no longer attached: the box reads the stored files again", async () => {
  api.runStage.mockImplementation(async (id, key) => (key === "engine" ? { stage: key, status: "failed", message: "x" } : { stage: key, status: "done" }));
  await mount();
  await attach("revenue.csv");
  expect(q("unstage-revenue.csv")).not.toBeNull();
  api.getDatasets.mockResolvedValue([VIEW("revenue")]);
  await press("run-audit");
  expect(q("unstage-revenue.csv")).toBeNull();
  expect(q("upload-chat").textContent).toContain("revenue.csv");
});

test("under React.StrictMode the stage updates still land (alive ref is re-armed on the second mount)", async () => {
  api.runStage.mockResolvedValue({ stage: "mapping", status: "needs_review", open: 1 });
  await mount(true);
  await attach("revenue.csv");
  await press("run-audit");
  expect(q("stage-mapping").getAttribute("data-status")).toBe("needs_review");
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/review");
});

const DECK = { deck_id: "d1", file: "board.pptx", pages: 12, page_unit: "slide", uploaded_at: "2026-10-02T08:00:00+00:00" };
const stageOf = () => ["mapping", "engine", "claims"].map((k) => q(`stage-${k}`).getAttribute("data-status"));

test("a new audit shows every stage as not started", async () => {
  await mount();
  expect(stageOf()).toEqual(["idle", "idle", "idle"]);
  expect(q("stage-mapping-status").textContent).toBe("Not started");
});

test("a finished audit shows each stage done on load, never Not started", async () => {
  api.getDatasets.mockResolvedValue([VIEW("revenue")]);
  api.getReview.mockResolvedValue({ computed: true });
  api.getDecks.mockResolvedValue({ decks: [DECK], candidates: [{ id: "c1", status: "approved" }] });
  await mount();
  expect(stageOf()).toEqual(["done", "done", "done"]);
  expect(q("stage-claims-status").textContent).toBe("Done");
});

test("columns or claims still waiting for the analyst show as needing review; the stage not reached stays not started", async () => {
  api.getDatasets.mockResolvedValue([VIEW("revenue", { pending: 2 })]);
  api.getDecks.mockResolvedValue({ decks: [DECK], candidates: [{ id: "c1", status: "pending" }] });
  await mount();
  expect(stageOf()).toEqual(["needs_review", "idle", "needs_review"]);
  expect(q("stage-mapping-status").textContent).toBe("Needs your review");
});

test("a deck is not attached in the box (the deck panel takes it) and a file removed before the run is not sent", async () => {
  api.runStage.mockImplementation(async (id, key) => ({ stage: key, status: "done" }));
  await mount();
  await attach("board.pptx", "revenue.csv", "pnl.csv");
  expect(q("chat-messages").textContent).toContain("board.pptx");
  expect(q("unstage-board.pptx")).toBeNull();
  await act(async () => { q("unstage-pnl.csv").click(); });
  await press("run-audit");
  expect(api.uploadChatFile.mock.calls.map((c) => c[1].name)).toEqual(["revenue.csv"]);
  expect(api.uploadDeck).not.toHaveBeenCalled();
});

test("while a run is in progress Map and Calculate wait, and Run audit waits while a file is being read", async () => {
  let release;
  api.runStage.mockImplementation(() => new Promise((resolve) => { release = () => resolve({ stage: "mapping", status: "needs_review" }); }));
  await mount();
  await attach("revenue.csv");
  await act(async () => { q("run-audit").click(); });
  await act(async () => { await Promise.resolve(); });
  expect(q("run-audit").disabled).toBe(true);
  expect(q("chat-map").disabled).toBe(true);
  expect(q("compute-button").disabled).toBe(true);
  await act(async () => { release(); });
  await act(async () => { await Promise.resolve(); });
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/review");
});
