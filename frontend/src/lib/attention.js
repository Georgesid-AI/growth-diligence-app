/**
 * "Needs your attention" on the Audit page (docs/design/simplified-flow.md, The Audit page, item 5): the claims a check asks about, the
 * Revenue / Volume and Definition questions and the columns that wait, one card each. Python enters every other claim on its own.
 * The claim questions come in the order the server ranks them (value at stake, then shortfall), the
 * questions of the five selected claims first. Nothing is decided here.
 */
import { definitionOf, turnoverOf } from "./claimRegister";
import { isOther } from "./deckClaims";

export const ATTENTION_HEADING = "Needs your attention";
export const SHOWN_QUESTIONS = 3;
export const attentionCount = (n) => (n === 1 ? "1 question needs a word from you" : `${n} questions need a word from you`);
export const moreLabel = (n) => `${n} more`;
export const lessLabel = "Show fewer";

/** The views of the uploaded files that hold a column or a required field waiting for the analyst. */
export const openViews = (views) => (views || []).filter((v) => v.pending > 0 || v.missing_required.length > 0);

/** The questions: the five's claim questions first, then the columns that wait, then the other claim questions; the claims keep the server's
 *  ranking (`attention`: [{id, in_top5}], best first). An Other figure is never a task. */
export function openQuestions(views, candidates, attention) {
  const columns = [];
  openViews(views).forEach((view) => {
    const rows = view.missing_required.length ? view.columns : view.columns.filter((c) => c.pending);
    rows.forEach((row) => columns.push({ key: `col-${view.dtype}-${row.column}`, kind: "mapping", view, row }));
  });
  const claims = [];
  (candidates || []).forEach((c) => {
    if (isOther(c)) return;
    if (c.status === "pending" && turnoverOf(c).open) claims.push({ key: `turnover-${c.id}`, kind: "turnover", c });
    else if (c.status === "pending" || (c.status !== "rejected" && definitionOf(c).open)) claims.push({ key: `claim-${c.id}`, kind: "claim", c });
  });
  const place = new Map((attention || []).map((a, i) => [a.id, { i, top: Boolean(a.in_top5) }]));
  const at = (item) => place.get(item.c.id) || { i: Number.MAX_SAFE_INTEGER, top: false };
  claims.sort((a, b) => at(a).i - at(b).i);
  return [...claims.filter((x) => at(x).top), ...columns, ...claims.filter((x) => !at(x).top)];
}
