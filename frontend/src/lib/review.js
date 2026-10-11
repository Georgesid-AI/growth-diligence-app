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

/** "Estimated cost: up to $0.08 for 3 narratives" / "All narratives are written: no cost" / "" while unknown. */
export function estimateText(estimate) {
  if (!estimate) return "";
  const todo = (estimate.steps || []).filter((s) => s.available && !s.cached);
  if (todo.length === 0) return "All narratives are written: no cost.";
  return `Estimated cost: up to ${usd(estimate.total_usd)} for ${todo.length} narrative${todo.length === 1 ? "" : "s"}`;
}
