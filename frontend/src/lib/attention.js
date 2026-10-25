/**
 * "Needs your attention" on the Audit page (docs/design/simplified-flow.md, The Audit page, item 5): the questions the Review page
 * lists as open, one card each, taken from the same rules, so nothing that waited on Review is lost when Review leaves the menu.
 * Nothing is decided here; each card carries the control Review gave it.
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

/** The questions, in the order Review lists them: columns, claims, then Revenue / Volume answers. An Other figure is never a task. */
export function openQuestions(views, candidates) {
  const out = [];
  openViews(views).forEach((view) => {
    const rows = view.missing_required.length ? view.columns : view.columns.filter((c) => c.pending);
    rows.forEach((row) => out.push({ key: `col-${view.dtype}-${row.column}`, kind: "mapping", view, row }));
  });
  (candidates || []).forEach((c) => {
    if (isOther(c)) return;
    if ((c.status === "pending" && !turnoverOf(c).open) || (c.status !== "rejected" && definitionOf(c).open)) out.push({ key: `claim-${c.id}`, kind: "claim", c });
  });
  (candidates || []).forEach((c) => {
    if (c.status === "pending" && turnoverOf(c).open) out.push({ key: `turnover-${c.id}`, kind: "turnover", c });
  });
  return out;
}
