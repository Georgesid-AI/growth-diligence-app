/**
 * Run audit: the three stages the analyst starts with one button, in order. The files go through the endpoints that already
 * exist; each stage then answers through POST /audits/{id}/run/{stage}. The runner stops at the first stage that is not done:
 * needs_review sends the analyst to the review screen, failed shows a plain-English message and a Retry stage button.
 */
export const STAGES = [
  { key: "mapping", label: "File mapping" },
  { key: "engine", label: "Engine calculations" },
  { key: "claims", label: "Claim extraction from decks" },
];
export const STAGE_STATUS_TEXT = {
  idle: "Not started", running: "Running…", done: "Done", needs_review: "Needs your review", waiting: "Waiting", failed: "Failed",
};
export const DATA_EXTENSIONS = ["xlsx", "csv"];
export const RUN_LABEL = "Run audit";
export const RETRY_LABEL = "Retry stage";
export const POLL_MS = 5000;
export const MAX_POLLS = 24;

const extension = (name) => (String(name).includes(".") ? String(name).split(".").pop().toLowerCase() : "");

/** The files the analyst picked, split the way the app reads them: spreadsheets map into the engine, anything else is a deck. */
export function splitFiles(files) {
  const all = Array.from(files || []);
  return { data: all.filter((f) => DATA_EXTENSIONS.includes(extension(f.name))), decks: all.filter((f) => !DATA_EXTENSIONS.includes(extension(f.name))) };
}

export const idleStages = () => Object.fromEntries(STAGES.map((s) => [s.key, { status: "idle", message: null }]));

const detailOf = (e, fallback) => {
  const detail = e?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
};

/** Send the spreadsheets of the pick (a file of a loaded type replaces it: the analyst attached it on purpose). */
async function uploadData(api, auditId, pick) {
  while (pick.data.length) {
    const file = pick.data[0];
    let res;
    try {
      res = await api.uploadChatFile(auditId, file, { replace: true });
    } catch (e) {
      return { status: "failed", message: detailOf(e, `${file.name} could not be read. Retry this stage.`) };
    }
    if (res.status === "unknown_type") {
      return { status: "failed", message: `Could not tell what ${file.name} holds. Choose its type under Details, Upload & Mapping, then run the audit again.` };
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
