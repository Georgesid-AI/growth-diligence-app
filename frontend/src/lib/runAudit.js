/**
 * Run audit, on the Upload & Mapping page: the three stages the analyst starts with one button, in order. The files go through the endpoints that already
 * exist; each stage then answers through POST /audits/{id}/run/{stage}. The runner stops at the first stage that is not done:
 * failed shows a plain-English message and a Retry stage button. Nothing waits for a confirmation (read-check-review.md section 12).
 */
export const STAGES = [
  { key: "mapping", label: "Reading files" },        // the stage key stays "mapping" (the server's route); the label says what happens (PR 4)
  { key: "engine", label: "Engine calculations" },
  { key: "claims", label: "Claim extraction from decks" },
];
export const STAGE_STATUS_TEXT = {
  idle: "Not started", running: "Running…", done: "Done", waiting: "Waiting", failed: "Failed",
};
export const DATA_EXTENSIONS = ["xlsx", "csv"];
export const RUN_LABEL = "Run audit";
export const RETRY_LABEL = "Retry stage";
// The Run audit buttons of Upload & Mapping are slightly larger than the standard button (h-9 px-4 text-sm) (George, 2026-10-27).
export const RUN_BUTTON_CLASS = "h-11 px-6 text-base";
export const POLL_MS = 5000;
export const MAX_POLLS = 24;

const extension = (name) => (String(name).includes(".") ? String(name).split(".").pop().toLowerCase() : "");

/** The files the analyst picked, split the way the app reads them: spreadsheets map into the engine, anything else is a deck. */
export function splitFiles(files) {
  const all = Array.from(files || []);
  return { data: all.filter((f) => DATA_EXTENSIONS.includes(extension(f.name))), decks: all.filter((f) => !DATA_EXTENSIONS.includes(extension(f.name))) };
}

export const idleStages = () => Object.fromEntries(STAGES.map((s) => [s.key, { status: "idle", message: null }]));

/**
 * The stages as the audit stands now, for a page that is opened or reloaded: done once the work exists, idle only when nothing was done.
 * `views` are the stored files, `summary` the review summary (its `computed` is whether results exist, its `engine_stale` whether the
 * results are older than the engine or a set-up input: the engine is then not done), `deckData` the decks and their candidates.
 */
export function stagesFromState({ views = [], summary = null, deckData = { decks: [], candidates: [] } } = {}) {
  const stages = idleStages();
  if (views.length) stages.mapping = { status: "done", message: null };
  if (summary?.computed && !summary.engine_stale) stages.engine = { status: "done", message: null };
  if ((deckData.decks || []).length || (deckData.candidates || []).length) stages.claims = { status: "done", message: null };
  return stages;
}

/**
 * Where Run audit carries on: the first stage that is not done. Files still attached count against their stage (spreadsheets:
 * mapping, decks: claims). With every stage done it runs the last one again, which accepts nothing twice and costs nothing.
 */
export function firstStageNotDone(stages, pick = { data: [], decks: [] }) {
  const attached = { mapping: pick.data.length > 0, claims: pick.decks.length > 0 };
  return STAGES.find((s) => stages[s.key].status !== "done" || attached[s.key])?.key || STAGES[STAGES.length - 1].key;
}

const detailOf = (e, fallback) => {
  const detail = e?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
};

/** Send the spreadsheets of the pick: each is stored and read; nothing is asked about its type. */
async function uploadData(api, auditId, pick) {
  while (pick.data.length) {
    const file = pick.data[0];
    try {
      await api.uploadChatFile(auditId, file);
    } catch (e) {
      return { status: "failed", message: detailOf(e, `${file.name} could not be read. Retry this stage.`) };
    }
    pick.data.shift();
  }
  return null;
}

async function uploadDecks(api, auditId, pick) {
  while (pick.decks.length) {
    const file = pick.decks[0];
    try {
      await api.uploadDeck(auditId, file);
    } catch (e) {
      return { status: "failed", message: detailOf(e, `${file.name} could not be read. Retry this stage.`) };
    }
    pick.decks.shift();
  }
  return null;
}

/**
 * Runs the stages from `from` onwards. `pick` is {data, decks}: the files not yet sent; a file leaves it once it is sent, so
 * Retry stage sends only what is left. `onUpdate(key, {status, message, ...counts})` is called as each stage moves.
 * Resolves with {stopped: key or null, status}.
 */
export async function runAudit({ api, auditId, pick = { data: [], decks: [] }, from = "mapping", onUpdate = () => {},
  wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) }) {
  const order = STAGES.map((s) => s.key);
  for (const key of order.slice(order.indexOf(from))) {
    onUpdate(key, { status: "running", message: null });
    let result = null;
    try {
      result = key === "mapping" ? await uploadData(api, auditId, pick) : key === "claims" ? await uploadDecks(api, auditId, pick) : null;
      if (!result) {
        result = await api.runStage(auditId, key);
        for (let polls = 0; result.status === "running" && polls < MAX_POLLS; polls += 1) {
          onUpdate(key, result);
          await wait(POLL_MS);
          result = await api.runStage(auditId, key);
        }
        if (result.status === "running") result = { ...result, status: "failed", message: "The decks are taking longer than expected to read. Retry this stage." };
      }
    } catch (e) {
      result = { status: "failed", message: detailOf(e, "This stage could not be completed. Retry it; nothing already done is lost.") };
    }
    onUpdate(key, result);
    if (result.status !== "done") return { stopped: key, status: result.status };
  }
  return { stopped: null, status: "done" };
}

/**
 * Whether the audit can run at all: it needs a file (George, 2026-10-27; since 2026-10-28 Target ARR and Target date are parked and
 * never block). One line saying what is missing, or null. `views` are the audit's stored datasets.
 */
export function missingForRun({ audit, views = [] }) {
  const missing = [
    !views.length && "a file",
  ].filter(Boolean);
  return missing.length ? `The audit cannot run yet. Missing: ${missing.join(", ")}.` : null;
}

const auditPath = (auditId, page) => `/audit/${auditId}/${page}`;

/**
 * Run audit from the audit list: the run the Upload & Mapping button makes, with the files already stored (nothing attached). Resolves with
 * where to go: the Audit page when the run is done or waits for the analyst's answers on it, else Upload & Mapping with one line (`line`)
 * saying what is missing, or what stopped the run.
 */
export async function runFromList({ api, audit, wait, onStart = () => {} }) {
  const safe = (p, fallback) => p.catch(() => fallback);
  const [views, summary, deckData] = await Promise.all([
    safe(api.getDatasets(audit.id), []), safe(api.getReview(audit.id), null), safe(api.getDecks(audit.id), { decks: [], candidates: [] })]);
  const line = missingForRun({ audit, views });
  if (line) return { to: auditPath(audit.id, "mapping"), line };
  const messages = {};
  onStart();                                          // the run begins: the caller marks it (the "revenue file missing" blocker shows from here)
  const from = firstStageNotDone(stagesFromState({ views, summary, deckData }));
  const out = await runAudit({ api, auditId: audit.id, from, wait, onUpdate: (key, result) => { messages[key] = result.message; } });
  if (out.status === "done") return { to: auditPath(audit.id, "dashboard") };
  const stage = STAGES.find((s) => s.key === out.stopped);
  return { to: auditPath(audit.id, "mapping"), line: messages[out.stopped] || `${stage.label}: ${STAGE_STATUS_TEXT[out.status].toLowerCase()}.` };
}
