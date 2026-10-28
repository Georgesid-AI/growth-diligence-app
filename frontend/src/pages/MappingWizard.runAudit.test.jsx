import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";

import MappingWizard from "./MappingWizard";
import { RunToMapping } from "@/App";
import * as api from "@/lib/api";

// Run audit on the Upload & Mapping page (docs/specs/chat-upload.md section 24): the button and its stages sit below the set-up
// section and above the mapping; Map stays, Calculate is gone and Run audit is the only way to calculate.
const mockNavigate = jest.fn();
let mockLocation = { pathname: "/audit/a1/mapping" };
jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), updateAudit: jest.fn(), reportUsage: jest.fn(), getBlockers: jest.fn(),
  uploadChatFile: jest.fn(), uploadDeck: jest.fn(), runStage: jest.fn(), decideColumns: jest.fn(), changeDatasetType: jest.fn(),
  confirmForecastClaims: jest.fn(), saveMapping: jest.fn(), saveFx: jest.fn(), computeAudit: jest.fn(), getRevenueCustomers: jest.fn(),
  getDatasets: jest.fn(), getReview: jest.fn(), getDecks: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({
  useParams: () => ({ id: "a1" }), useNavigate: () => mockNavigate, useLocation: () => mockLocation,
  Navigate: ({ to }) => <span data-testid="redirect" data-to={to} />,
  BrowserRouter: ({ children }) => <div>{children}</div>, Routes: ({ children }) => <div>{children}</div>, Route: () => null,
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a>,
}), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));
jest.mock("@/components/AuditSetup", () => ({ __esModule: true, ConsentBlock: () => null, AssumptionsSetup: () => <div data-testid="audit-setup" />, ParkedBlocks: () => null }));
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
  mockLocation = { pathname: "/audit/a1/mapping" };
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

test("Run audit and its stages sit under the assumptions strip, below the Board deck box and the mapped files; Map stays and there is no Calculate button", async () => {
  await mount();
  expect(document.body.querySelectorAll('[data-testid="run-audit"]')).toHaveLength(1);
  expect(q("run-audit").textContent).toBe("Run audit");
  expect(follows("chat-drop-zone", "deck-panel")).toBe(true);
  expect(follows("deck-panel", "chat-messages")).toBe(true);
  expect(follows("upload-chat", "fx-settings")).toBe(true);
  expect(follows("fx-settings", "audit-setup")).toBe(true);
  expect(follows("audit-setup", "run-audit-panel")).toBe(true);
  expect(q("chat-map")).not.toBeNull();
  expect(q("chat-calculate")).toBeNull();
  expect(q("compute-button")).toBeNull();
  expect(document.body.textContent).not.toMatch(/\bCalculate\b/);
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

test("one press sends the attached spreadsheets, runs the three stages in order and opens the Audit page", async () => {
  const order = [];
  api.uploadChatFile.mockImplementation(async (id, f) => { order.push(`upload:${f.name}`); return { status: "ok" }; });
  api.runStage.mockImplementation(async (id, key) => { order.push(`stage:${key}`); return { stage: key, status: "done" }; });
  await mount();
  await attach("revenue.csv");
  expect(q("chat-messages").textContent).toContain("revenue.csv");
  await press("run-audit");
  expect(order).toEqual(["upload:revenue.csv", "stage:mapping", "stage:engine", "stage:claims"]);
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
});

test("a stage that needs the analyst sends them to the Audit page", async () => {
  api.runStage.mockResolvedValue({ stage: "mapping", status: "needs_review", open: 1 });
  await mount();
  await attach("revenue.csv");
  await press("run-audit");
  expect(api.runStage).toHaveBeenCalledTimes(1);
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
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
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
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
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
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

test("while a run is in progress Map waits, and Run audit waits while a file is being read", async () => {
  let release;
  api.runStage.mockImplementation(() => new Promise((resolve) => { release = () => resolve({ stage: "mapping", status: "needs_review" }); }));
  await mount();
  await attach("revenue.csv");
  await act(async () => { q("run-audit").click(); });
  await act(async () => { await Promise.resolve(); });
  expect(q("run-audit").disabled).toBe(true);
  expect(q("chat-map").disabled).toBe(true);
  await act(async () => { release(); });
  await act(async () => { await Promise.resolve(); });
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
});

// --- Run audit continues from the first stage that is not done (chat-upload.md section 24) ----------------------------------------------

const ranStages = () => api.runStage.mock.calls.map((c) => c[1]);
const allDone = () => {
  api.getDatasets.mockResolvedValue([VIEW("revenue")]);
  api.getReview.mockResolvedValue({ computed: true, engine_stale: false });
  api.getDecks.mockResolvedValue({ decks: [DECK], candidates: [{ id: "c1", status: "approved" }] });
  api.runStage.mockImplementation(async (id, key) => ({ stage: key, status: "done" }));
};

test("with the mapping done and the engine not, Run audit starts at the engine and does not map again", async () => {
  api.getDatasets.mockResolvedValue([VIEW("revenue")]);
  api.runStage.mockImplementation(async (id, key) => ({ stage: key, status: "done" }));
  await mount();
  await press("run-audit");
  expect(ranStages()).toEqual(["engine", "claims"]);
  expect(api.uploadChatFile).not.toHaveBeenCalled();
});

test("a mapping confirmed or corrected after the last calculation makes the engine stage not done: Run audit calculates again", async () => {
  allDone();
  await mount();
  expect(stageOf()).toEqual(["done", "done", "done"]);
  api.getReview.mockResolvedValue({ computed: true, engine_stale: true });          // the analyst confirmed a column since
  await press("run-audit");
  expect(ranStages()).toEqual(["engine", "claims"]);
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
});

test("the engine of a stale audit shows as not done on load, not Done", async () => {
  allDone();
  api.getReview.mockResolvedValue({ computed: true, engine_stale: true });
  await mount();
  expect(stageOf()).toEqual(["done", "idle", "done"]);
});

test("a second Run audit with nothing new sends no file and reads no deck again: the decks already read are served from the cache", async () => {
  allDone();
  await mount();
  await press("run-audit");
  await press("run-audit");
  expect(ranStages()).toEqual(["claims", "claims"]);
  expect(api.uploadDeck).not.toHaveBeenCalled();
  expect(api.uploadChatFile).not.toHaveBeenCalled();
});

test("a file attached after a finished run goes through the mapping stage first, then the rest", async () => {
  allDone();
  await mount();
  await attach("revenue.csv");
  await press("run-audit");
  expect(api.uploadChatFile).toHaveBeenCalledTimes(1);
  expect(ranStages()).toEqual(["mapping", "engine", "claims"]);
});

describe("a second Run audit button at the top of the page, and both a little larger (George, 2026-10-27)", () => {
  test("the page has Run audit at the top, above the set-up section, and the one at the bottom; the two are the only ones", async () => {
    await mount();
    expect(q("run-audit-top").textContent).toBe("Run audit");
    expect(q("run-audit").textContent).toBe("Run audit");
    expect(document.body.querySelectorAll("button[data-testid^='run-audit']")).toHaveLength(2);
    expect(follows("run-audit-top", "audit-setup")).toBe(true);
    expect(follows("deck-panel", "run-audit")).toBe(true);
  });
  test("both are larger than the standard button (h-9 px-4 text-sm)", async () => {
    await mount();
    ["run-audit-top", "run-audit"].forEach((id) => {
      const tokens = q(id).className.split(/\s+/);
      expect(tokens).toEqual(expect.arrayContaining(["h-11", "px-6", "text-base"]));
      expect(tokens).not.toContain("h-9");
      expect(tokens).not.toContain("text-sm");
    });
  });
  test("the top button makes the same run as the bottom one, and one run holds both", async () => {
    const order = [];
    let release;
    api.runStage.mockImplementation((id, key) => new Promise((resolve) => { order.push(`stage:${key}`); if (key === "mapping") release = () => resolve({ stage: key, status: "done" }); else resolve({ stage: key, status: "done" }); }));
    await mount();
    await press("run-audit-top");
    expect(order).toEqual(["stage:mapping"]);
    expect(q("run-audit-top").disabled).toBe(true);
    expect(q("run-audit").disabled).toBe(true);
    await act(async () => { release(); });
    await act(async () => { await Promise.resolve(); });
    expect(order).toEqual(["stage:mapping", "stage:engine", "stage:claims"]);
    expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
  });
  test("the audit list opened this page because the audit could not run: one line says what is missing", async () => {
    mockLocation = { pathname: "/audit/a1/mapping", state: { missing: "The audit cannot run yet. Missing: a mapped file." } };
    await mount();
    expect(q("run-missing-line").textContent).toBe("The audit cannot run yet. Missing: a mapped file.");
  });
  test("a visit with no such line shows none", async () => {
    await mount();
    expect(q("run-missing-line")).toBeNull();
  });
});
