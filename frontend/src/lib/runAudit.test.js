import { MAX_POLLS, POLL_MS, STAGES, firstStageNotDone, pollLimit, runAudit, splitFiles, idleStages, stagesFromState } from "./runAudit";

const file = (name) => ({ name });
const polled = [];
const mk = (answers = {}) => {
  polled.length = 0;
  const calls = [];
  const api = {
    uploadChatFile: jest.fn(async (id, f, o) => { calls.push(`upload:${f.name}`); return answers.upload?.(f, o) ?? { status: "ok", dtype: "revenue" }; }),
    uploadDeck: jest.fn(async (id, f) => { calls.push(`deck:${f.name}`); if (answers.deck) return answers.deck(f); return {}; }),
    runStage: jest.fn(async (id, key, opts) => { calls.push(`stage:${key}`); if (opts?.poll) polled.push(key); return answers[key]?.() ?? { stage: key, status: "done" }; }),
  };
  return { api, calls };
};

test("the stages are file mapping, claim extraction from decks, engine calculations, in that order: the results never rest on partial deck figures", () => {
  expect(STAGES.map((s) => s.key)).toEqual(["mapping", "claims", "engine"]);
  expect(Object.keys(idleStages())).toEqual(["mapping", "claims", "engine"]);
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
  expect(calls).toEqual(["upload:revenue.csv", "stage:mapping", "deck:board.pptx", "stage:claims", "stage:engine"]);
  expect(api.uploadChatFile.mock.calls[0]).toHaveLength(2);           // the file and nothing else: no type, no replace
  expect(pick).toEqual({ data: [], decks: [] });
});

test("a failed stage shows the server's plain-English message and Retry stage carries on from it, sending only the files left", async () => {
  let fail = true;
  const { api, calls } = mk({ mapping: () => (fail ? { stage: "mapping", status: "failed", message: "The files could not be read." } : { status: "done" }) });
  const pick = splitFiles([file("revenue.csv"), file("board.pptx")]);
  const first = await runAudit({ api, auditId: "a1", pick });
  expect(first).toEqual({ stopped: "mapping", status: "failed" });
  fail = false;
  calls.length = 0;
  const retry = await runAudit({ api, auditId: "a1", pick, from: "mapping" });
  expect(retry.status).toBe("done");
  expect(calls).toEqual(["stage:mapping", "deck:board.pptx", "stage:claims", "stage:engine"]);
});

test("a retry of the claims stage calculates the results again afterwards, and only after the claims are done", async () => {
  let incomplete = true;
  const msg = "Deck claims incomplete: 3 of 44 pages. Retry this stage.";
  const { api, calls } = mk({ claims: () => (incomplete ? { stage: "claims", status: "failed", message: msg } : { stage: "claims", status: "done" }) });
  const seen = [];
  const first = await runAudit({ api, auditId: "a1", onUpdate: (k, r) => seen.push([k, r.message]) });
  expect(first).toEqual({ stopped: "claims", status: "failed" });
  expect(seen).toContainEqual(["claims", msg]);
  expect(calls).toEqual(["stage:mapping", "stage:claims"]);          // the results stage did not run on partial deck figures
  incomplete = false;
  calls.length = 0;
  expect((await runAudit({ api, auditId: "a1", from: "claims" })).status).toBe("done");
  expect(calls).toEqual(["stage:claims", "stage:engine"]);
});

test("results older than the latest reading offer the results step again, and decks with pages missing offer the claims step", () => {
  const views = [{ dtype: "revenue" }];
  const done = { views, summary: { computed: true, engine_stale: false }, deckData: { decks: [{ deck_id: "d" }], candidates: [] } };
  expect(firstStageNotDone(stagesFromState(done))).toBe("engine");   // all done: the last stage again
  expect(stagesFromState({ ...done, summary: { computed: true, engine_stale: true, results_older: true } }).engine.status).toBe("idle");
  expect(firstStageNotDone(stagesFromState({ ...done, summary: { computed: true, engine_stale: true, results_older: true } }))).toBe("engine");
  const incomplete = { ...done, deckData: { decks: [{ deck_id: "d", claims_incomplete: true }], candidates: [] } };
  expect(stagesFromState(incomplete).claims.status).toBe("idle");
  expect(firstStageNotDone(stagesFromState(incomplete))).toBe("claims");
});

test("the time a stage may take grows with the work the server reports, and polling asks again without queueing a deck twice", async () => {
  expect(pollLimit({})).toBe(MAX_POLLS);
  expect(pollLimit({ timeout_seconds: 824 })).toBe(Math.ceil((824 * 1000) / POLL_MS));          // a 44-page audit read twice
  expect(pollLimit({ timeout_seconds: 824 })).toBeGreaterThan(MAX_POLLS);
  let n = 0;
  const { api } = mk({ claims: () => (++n < 40 ? { stage: "claims", status: "running", timeout_seconds: 824 } : { stage: "claims", status: "done" }) });
  const out = await runAudit({ api, auditId: "a1", from: "claims", wait: async () => {} });
  expect(out.status).toBe("done");                                  // 40 asks: past the fixed 24 polls
  expect(polled.filter((k) => k === "claims")).toHaveLength(39);       // every ask after the first is a poll
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

test("a results stage that times out names the stage and what was still running, never 'the decks are taking longer'", async () => {
  const run = async (key) => {
    const { api } = mk({ [key]: () => ({ stage: key, status: "running" }) });
    const seen = [];
    await runAudit({ api, auditId: "a1", from: key, wait: async () => {}, onUpdate: (k, r) => seen.push(r) });
    return seen.at(-1).message;
  };
  expect(await run("claims")).toBe("Calculating results timed out while reading deck claims. Retry this stage.");
  expect(await run("engine")).toBe("Calculating results timed out while computing metrics. Retry this stage.");
  expect(await run("mapping")).toBe("Reading files timed out while the files were still being read. Retry this stage.");
  for (const key of ["claims", "engine", "mapping"]) expect(await run(key)).not.toMatch(/taking longer/);
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
    expect(status({})).toEqual(["idle", "idle", "idle"]);          // mapping, claims, engine
    expect(status({ views: [], summary: { computed: false }, deckData: { decks: [], candidates: [] } })).toEqual(["idle", "idle", "idle"]);
  });
  test("mapped files, results and read decks: every stage is done", () => {
    expect(status({ views: [view()], summary: { computed: true }, deckData: { decks: [{ deck_id: "d" }], candidates: [{ status: "approved" }] } })).toEqual(["done", "done", "done"]);
  });
  test("nothing needs review: a file with answers open, or a pending claim, leaves its stage done (read-check-review.md section 12)", () => {
    expect(status({ views: [view({ pending: 1 })] })[0]).toBe("done");
    expect(status({ views: [view({ missing_required: ["month"] })] })[0]).toBe("done");
    expect(status({ deckData: { decks: [{ deck_id: "d" }], candidates: [{ status: "pending" }] } })[1]).toBe("done");
  });
  test("a deck with no claim in it is done: it was read", () => {
    expect(status({ deckData: { decks: [{ deck_id: "d" }], candidates: [] } })[1]).toBe("done");
  });
});
