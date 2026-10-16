/** Wording of the review screen's closing section. */
export const WRITE_ALL_LABEL = "Write all narratives";
export const writeAllLabel = (progress) => (progress ? `Writing ${progress}…` : WRITE_ALL_LABEL);
export const WRITE_ALL_HELP =
  "Writes a short summary of the numbers for each analysis, in plain English. The numbers themselves are calculated by the app, not written by AI. " +
  "Costs one AI request per summary not yet written — after that you can open this audit as often as you like for free.";
export const MEMO_LABEL = "Generate IC memo";
export const MEMO_WAITING = "Enter both ratings to generate the memo.";
export const RECONCILIATION_NOTE = "A reconciliation gap over 2% is reported in the memo; it does not block it.";

const usd = (v) => `$${Number(v).toFixed(2)}`;

export const ALL_WRITTEN_LEAD = "All narratives are written – read them on the ";
export const ALL_WRITTEN_LINK = "Growth Dashboard";

/** True when at least one narrative can be written and every one that can is already stored. */
export function allWritten(estimate) {
  const steps = (estimate?.steps || []).filter((s) => s.available);
  return steps.length > 0 && steps.every((s) => s.cached);
}

/** "Estimated cost: up to $0.08 for 3 narratives" / "" while unknown, or when all are written (the screen says so with a link). */
export function estimateText(estimate) {
  if (!estimate || allWritten(estimate)) return "";
  const todo = (estimate.steps || []).filter((s) => s.available && !s.cached);
  if (todo.length === 0) return "";
  return `Estimated cost: up to ${usd(estimate.total_usd)} for ${todo.length} narrative${todo.length === 1 ? "" : "s"}`;
}

// Mapping summary (chat-upload.md section 18).
const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
export const DTYPE_SHORT = { revenue: "Revenue", crm: "CRM", pnl: "P&L" };

/** A matched column the analyst has not decided that is worth a look: confidence under 100, or the file's name and the app's differ. */
export function isUnsure(c, fieldLabel) {
  if (c.decision === "confirm" || c.decision === "correct") return false;
  if (c.confidence != null && c.confidence < 100) return true;
  return norm(c.column) !== norm(fieldLabel(c.field));
}

/** Matched = used columns that do not wait for a decision (those sit under Open mappings). Unsure rows are the ones to check. */
export function mappingSummary(views, fieldLabel) {
  const matched = [];
  // a file read as claims (chat-upload.md section 20) is no calculation input: its columns are not listed
  views.filter((v) => !v.read_as_claims)
    .forEach((v) => v.columns.filter((c) => c.state !== "unused" && !c.pending).forEach((c) => matched.push({ view: v, col: c })));
  const unsure = matched.filter(({ col }) => isUnsure(col, fieldLabel));
  return { matched, unsure };
}

export const summaryHeadline = (n, check) =>
  check === 0 ? `✓ ${n} column${n === 1 ? "" : "s"} matched – nothing to do.` : `${n} column${n === 1 ? "" : "s"} matched – ${check} to check.`;
