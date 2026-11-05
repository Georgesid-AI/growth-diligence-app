import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";

import MappingWizard from "./MappingWizard";
import { RunToMapping } from "@/App";
import * as api from "@/lib/api";

// Run audit on the Upload & Mapping page (docs/specs/chat-upload.md sections 5 and 24): the run card sits under the two upload cards; files are
// uploaded the moment they are picked, so a run sends none; Run audit is the only way to calculate.
const mockNavigate = jest.fn();
let mockLocation = { pathname: "/audit/a1/mapping" };
jest.mock("@/lib/api", () => ({
  getAudit: jest.fn(), updateAudit: jest.fn(), reportUsage: jest.fn(), getBlockers: jest.fn(),
  uploadChatFile: jest.fn(), uploadDeck: jest.fn(), runStage: jest.fn(), decideColumns: jest.fn(), changeDatasetType: jest.fn(),
  confirmForecastClaims: jest.fn(), saveMapping: jest.fn(), saveFx: jest.fn(), computeAudit: jest.fn(), getRevenueCustomers: jest.fn(),
  getDatasets: jest.fn(), getReview: jest.fn(), getDecks: jest.fn(), continueWithoutPages: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({
  useParams: () => ({ id: "a1" }), useNavigate: () => mockNavigate, useLocation: () => mockLocation,
  Navigate: ({ to }) => <span data-testid="redirect" data-to={to} />,
  BrowserRouter: ({ children }) => <div>{children}</div>, Routes: ({ children }) => <div>{children}</div>, Route: () => null,
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a>,
}), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));
jest.mock("@/components/AuditSetup", () => ({ __esModule: true, AssumptionsSetup: () => <div data-testid="audit-setup" />, ParkedBlocks: () => null }));
jest.mock("@/components/ReadingScreen", () => ({ __esModule: true, default: () => <div data-testid="reading-screen" /> }));

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
afterEach(async () => { if (root) { await act(async () => { root.unmount(); }); host.remove(); root = undefined; } });

async function mount(strict = false) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(strict ? <React.StrictMode><MappingWizard /></React.StrictMode> : <MappingWizard />); });
  await act(async () => { await Promise.resolve(); });
}
const press = async (id) => { await act(async () => { q(id).click(); }); await act(async () => { await Promise.resolve(); }); };
const follows = (a, b) => !!(q(a).compareDocumentPosition(q(b)) & Node.DOCUMENT_POSITION_FOLLOWING);

test("the old /audit/:id/run link redirects to Upload & Mapping", () => {
  const html = renderToStaticMarkup(<RunToMapping />);
  expect(html).toContain('data-to="/audit/a1/mapping"');
});

const FILE = () => VIEW("revenue", { file_hash: "h1", read_state: "done", read_elapsed: 5 });
const DECK = { deck_id: "d1", file: "board.pptx", pages: 12, page_unit: "slide", uploaded_at: "2026-10-02T08:00:00+00:00", ai_status: "read", figure_pages: 4, read_elapsed: 9 };
const stored = () => api.getDatasets.mockResolvedValue([FILE()]);
const tones = () => ["reading", "calculating"].map((k) => q(`step-${k}`).getAttribute("data-tone"));

test("one press runs the stages in order, sends no file (they went up when picked) and opens the Audit page", async () => {
  const order = [];
  stored();
  api.runStage.mockImplementation(async (id, key) => { order.push(`stage:${key}`); return { stage: key, status: "done" }; });
  await mount();
  await press("run-audit");
  expect(order).toEqual(["stage:claims", "stage:engine"]);          // the file is stored and read: the run starts at the first stage not done
  expect(api.uploadChatFile).not.toHaveBeenCalled();
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
});

test("a run with nothing stored starts at the mapping stage, as before", async () => {
  api.runStage.mockImplementation(async (id, key) => ({ stage: key, status: "done" }));
  await mount();
  await press("run-audit");
  expect(api.runStage.mock.calls.map((c) => c[1])).toEqual(["mapping", "claims", "engine"]);
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
});

test("a failed stage says what to do and Retry stage carries on from it", async () => {
  let fail = true;
  stored();
  api.runStage.mockImplementation(async (id, key) => (key === "engine" && fail
    ? { stage: key, status: "failed", message: "The calculations could not be completed. Check the mapping on the review screen, then retry this stage." }
    : { stage: key, status: "done" }));
  await mount();
  await press("run-audit");
  expect(q("stage-engine").getAttribute("data-status")).toBe("failed");
  expect(q("stage-engine-message").textContent).toContain("could not be completed");
  expect(tones()).toEqual(["done", "bad"]);
  expect(mockNavigate).not.toHaveBeenCalled();
  fail = false;
  await press("retry-engine");
  expect(api.uploadChatFile).not.toHaveBeenCalled();
  expect(q("stage-engine")).toBeNull();
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
});

test("under React.StrictMode the stage updates still land (alive ref is re-armed on the second mount)", async () => {
  stored();
  api.runStage.mockResolvedValue({ stage: "engine", status: "done" });
  await mount(true);
  await press("run-audit");
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
});

test("a new audit shows no file and every step as not started", async () => {
  await mount();
  expect(tones()).toEqual(["wait", "wait"]);
  expect(q("step-calculating-second").textContent).toBe("not started");
});

test("a finished audit shows the calculating step done on load, never not started", async () => {
  stored();
  api.getReview.mockResolvedValue({ computed: true });
  api.getDecks.mockResolvedValue({ decks: [DECK], candidates: [{ id: "c1", status: "approved" }] });
  await mount();
  expect(tones()).toEqual(["done", "done"]);
  expect(q("step-calculating-second").textContent).toBe("Done");
});

test("a stale engine shows calculating as not started on load, not Done", async () => {
  stored();
  api.getReview.mockResolvedValue({ computed: true, engine_stale: true });
  api.getDecks.mockResolvedValue({ decks: [DECK], candidates: [{ id: "c1", status: "approved" }] });
  await mount();
  expect(tones()).toEqual(["done", "wait"]);
});

test("while a run is in progress Run audit waits, and the calculating step runs with its elapsed time", async () => {
  let release;
  stored();
  api.runStage.mockImplementation((id, key) => new Promise((resolve) => { release = () => { api.runStage.mockImplementation(async (i, k) => ({ stage: k, status: "done" })); resolve({ stage: key, status: "done" }); }; }));
  await mount();
  await act(async () => { q("run-audit").click(); });
  await act(async () => { await Promise.resolve(); });
  expect(q("run-audit").disabled).toBe(true);
  expect(q("step-calculating").getAttribute("data-tone")).toBe("run");
  expect(q("step-calculating-second").textContent).toBe("Elapsed 0:00");
  await act(async () => { release(); });
  for (let i = 0; i < 6; i += 1) await act(async () => { await Promise.resolve(); });
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
});

// --- Run audit continues from the first stage that is not done (chat-upload.md section 24) ----------------------------------------------

const ranStages = () => api.runStage.mock.calls.map((c) => c[1]);
const allDone = () => {
  stored();
  api.getReview.mockResolvedValue({ computed: true, engine_stale: false });
  api.getDecks.mockResolvedValue({ decks: [DECK], candidates: [{ id: "c1", status: "approved" }] });
  api.runStage.mockImplementation(async (id, key) => ({ stage: key, status: "done" }));
};

test("a mapping confirmed or corrected after the last calculation makes the engine stage not done: Run audit calculates again", async () => {
  allDone();
  await mount();
  expect(tones()).toEqual(["done", "done"]);
  api.getReview.mockResolvedValue({ computed: true, engine_stale: true });          // the analyst changed a layout input since
  await press("run-audit");
  expect(ranStages()).toEqual(["engine"]);          // the deck claims are done: only the results are calculated again
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
});

test("results older than the latest reading offer the results step again (2026-11-05)", async () => {
  allDone();
  api.getReview.mockResolvedValue({ computed: true, engine_stale: true, results_older: true });
  await mount();
  await press("run-audit");
  expect(ranStages()).toEqual(["engine"]);
});

test("a deck with pages missing from its claims is read again from those pages, then the results are calculated again", async () => {
  allDone();
  api.getDecks.mockResolvedValue({ decks: [{ ...DECK, claims_incomplete: true }], candidates: [{ id: "c1", status: "approved" }] });
  api.getReview.mockResolvedValue({ computed: true, engine_stale: false });
  await mount();
  await press("run-audit");
  expect(ranStages()).toEqual(["claims", "engine"]);
});

test("a claims failure on a page that can never be read offers Continue without page N; it stores the choice, runs the claims stage again and then the results", async () => {
  allDone();
  api.getDecks.mockResolvedValue({ decks: [{ ...DECK, claims_incomplete: true }], candidates: [] });
  api.getReview.mockResolvedValue({ computed: false });
  let failing = true;
  const offer = { deck_id: "d1", file: "board.pptx", pages: [{ page: 3, reason: "too large for the token cap" }] };
  api.runStage.mockImplementation(async (id, key) => (key === "claims" && failing
    ? { stage: key, status: "failed", message: "Deck claims incomplete: 1 of 12 pages. Retry this stage.", can_continue: [offer] }
    : { stage: key, status: "done" }));
  api.continueWithoutPages.mockImplementation(async () => { failing = false; return {}; });
  await mount();
  await press("run-audit");
  expect(q("stage-claims-message").textContent).toContain("Deck claims incomplete: 1 of 12 pages.");
  expect(q("continue-without-d1").textContent).toBe("Continue without page 3");
  expect(ranStages()).toEqual(["claims"]);
  await press("continue-without-d1");
  for (let i = 0; i < 6; i += 1) await act(async () => { await Promise.resolve(); });
  expect(api.continueWithoutPages).toHaveBeenCalledWith("a1", "d1", [3]);
  expect(ranStages()).toEqual(["claims", "claims", "engine"]);
  expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/dashboard");
});

test("a claims failure with nothing that can never be read offers only Retry stage", async () => {
  allDone();
  api.getDecks.mockResolvedValue({ decks: [{ ...DECK, claims_incomplete: true }], candidates: [] });
  api.getReview.mockResolvedValue({ computed: false });
  api.runStage.mockImplementation(async (id, key) => (key === "claims" ? { stage: key, status: "failed", message: "x", can_continue: [] } : { stage: key, status: "done" }));
  await mount();
  await press("run-audit");
  expect(document.querySelector('[data-testid^="continue-without"]')).toBeNull();
  expect(q("retry-claims")).not.toBeNull();
});

test("a second Run audit with nothing new sends no file and reads no deck again", async () => {
  allDone();
  await mount();
  await press("run-audit");
  await press("run-audit");
  expect(ranStages()).toEqual(["engine", "engine"]);
  expect(api.uploadDeck).not.toHaveBeenCalled();
  expect(api.uploadChatFile).not.toHaveBeenCalled();
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
