import { STAGES, runAudit, splitFiles, idleStages, stagesFromState } from "./runAudit";

const file = (name) => ({ name });
const mk = (answers = {}) => {
  const calls = [];
  const api = {
    uploadChatFile: jest.fn(async (id, f, o) => { calls.push(`upload:${f.name}`); return answers.upload?.(f, o) ?? { status: "ok", dtype: "revenue" }; }),
    uploadDeck: jest.fn(async (id, f) => { calls.push(`deck:${f.name}`); if (answers.deck) return answers.deck(f); return {}; }),
    runStage: jest.fn(async (id, key) => { calls.push(`stage:${key}`); return answers[key]?.() ?? { stage: key, status: "done" }; }),
  };
  return { api, calls };
};

test("the stages are file mapping, engine calculations, claim extraction from decks, in that order", () => {
  expect(STAGES.map((s) => s.key)).toEqual(["mapping", "engine", "claims"]);
  expect(Object.keys(idleStages())).toEqual(["mapping", "engine", "claims"]);
});

test("spreadsheets map into the engine and everything else is a deck", () => {
  const { data, decks } = splitFiles([file("revenue.csv"), file("pnl.XLSX"), file("board.pptx"), file("plan.pdf")]);
  expect(data.map((f) => f.name)).toEqual(["revenue.csv", "pnl.XLSX"]);
  expect(decks.map((f) => f.name)).toEqual(["board.pptx", "plan.pdf"]);
});

test("one press: the data files, the three stages in order, the decks before the claims stage", async () => {
  const { api, calls } = mk();
  const pick = splitFiles([file("revenue.csv"), file("board.pptx")]);
  const out = await runAudit({ api, auditId: "a1", pick });
  expect(out).toEqual({ stopped: null, status: "done" });
  expect(calls).toEqual(["upload:revenue.csv", "stage:mapping", "stage:engine", "deck:board.pptx", "stage:claims"]);
  expect(api.uploadChatFile.mock.calls[0]).toHaveLength(2);           // the file and nothing else: no type, no replace
  expect(pick).toEqual({ data: [], decks: [] });
});

test("a failed stage shows the server's plain-English message and Retry stage carries on from it, sending only the files left", async () => {
  let fail = true;
  const { api, calls } = mk({ engine: () => (fail ? { stage: "engine", status: "failed", message: "The calculations could not be completed." } : { status: "done" }) });
  const pick = splitFiles([file("revenue.csv"), file("board.pptx")]);
  const first = await runAudit({ api, auditId: "a1", pick });
  expect(first).toEqual({ stopped: "engine", status: "failed" });
  fail = false;
  calls.length = 0;
  const retry = await runAudit({ api, auditId: "a1", pick, from: "engine" });
  expect(retry.status).toBe("done");
  expect(calls).toEqual(["stage:engine", "deck:board.pptx", "stage:claims"]);
});

test("a file that cannot be sent fails the stage with a message and stays in the pick for Retry stage", async () => {
  const { api } = mk({ upload: () => { throw Object.assign(new Error("x"), { response: { data: { detail: "Only .xlsx and .csv files are supported" } } }); } });
  const pick = splitFiles([file("revenue.csv")]);
  const seen = [];
  const out = await runAudit({ api, auditId: "a1", pick, onUpdate: (k, r) => seen.push(r) });
  expect(out).toEqual({ stopped: "mapping", status: "failed" });
  expect(seen.at(-1).message).toBe("Only .xlsx and .csv files are supported");
  expect(pick.data).toHaveLength(1);
});

test("decks still being read are waited for, then the stage is asked again", async () => {
  let n = 0;
  const { api, calls } = mk({ claims: () => (++n < 3 ? { stage: "claims", status: "running" } : { stage: "claims", status: "done", accepted: 4 }) });
  const waits = [];
  const out = await runAudit({ api, auditId: "a1", from: "claims", wait: async (ms) => waits.push(ms) });
  expect(out.status).toBe("done");
  expect(calls.filter((c) => c === "stage:claims")).toHaveLength(3);
  expect(waits).toHaveLength(2);
});

test("a deck that never finishes reading fails the stage instead of waiting for ever", async () => {
  const { api } = mk({ claims: () => ({ stage: "claims", status: "running" }) });
  const out = await runAudit({ api, auditId: "a1", from: "claims", wait: async () => {} });
  expect(out).toEqual({ stopped: "claims", status: "failed" });
});

test("a network failure on a stage reads as a message, not a stack", async () => {
  const { api } = mk({ engine: () => { throw new Error("Network Error"); } });
  const seen = [];
  await runAudit({ api, auditId: "a1", from: "engine", onUpdate: (k, r) => seen.push(r) });
  expect(seen.at(-1).message).toContain("Retry it");
  expect(seen.at(-1).message).not.toContain("Network Error");
});

describe("stagesFromState", () => {
  const view = (over = {}) => ({ dtype: "revenue", pending: 0, missing_required: [], ...over });
  const status = (state) => Object.values(stagesFromState(state)).map((s) => s.status);
  test("nothing stored: every stage is idle", () => {
    expect(status({})).toEqual(["idle", "idle", "idle"]);
    expect(status({ views: [], summary: { computed: false }, deckData: { decks: [], candidates: [] } })).toEqual(["idle", "idle", "idle"]);
  });
  test("mapped files, results and read decks: every stage is done", () => {
    expect(status({ views: [view()], summary: { computed: true }, deckData: { decks: [{ deck_id: "d" }], candidates: [{ status: "approved" }] } })).toEqual(["done", "done", "done"]);
  });
  test("nothing needs review: a file with answers open, or a pending claim, leaves its stage done (read-check-review.md section 12)", () => {
    expect(status({ views: [view({ pending: 1 })] })[0]).toBe("done");
    expect(status({ views: [view({ missing_required: ["month"] })] })[0]).toBe("done");
    expect(status({ deckData: { decks: [{ deck_id: "d" }], candidates: [{ status: "pending" }] } })[2]).toBe("done");
  });
  test("a deck with no claim in it is done: it was read", () => {
    expect(status({ deckData: { decks: [{ deck_id: "d" }], candidates: [] } })[2]).toBe("done");
  });
});
