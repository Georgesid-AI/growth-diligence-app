/**
 * "Needs your attention" on the Audit page (docs/design/simplified-flow.md, The Audit page, item 5): the claims a check asks about, the
 * Revenue / Volume and Definition questions and the columns that wait, one card each. Python enters every other claim on its own.
 * The claim questions come in the order the server ranks them (value at stake, then shortfall), the
 * questions of the five selected claims first. Nothing is decided here.
 */
import { definitionOf, turnoverOf } from "./claimRegister";
import { isOther } from "./deckClaims";
import { groupQuestions } from "./claimGroups";

export const ATTENTION_HEADING = "Needs your attention";
export const SHOWN_QUESTIONS = 3;
export const attentionCount = (n) => (n === 1 ? "1 question needs a word from you" : `${n} questions need a word from you`);
export const moreLabel = (n) => `${n} more`;
export const lessLabel = "Show fewer";
export const SALES_QUESTION = "Is 'Sales' in this deck revenue or bookings?";
export const SALES_ANSWERS = [["revenue", "Revenue"], ["bookings", "Bookings"]];
export const salesCount = (n) => (n === 1 ? "1 claim in this deck is labelled Sales." : `${n} claims in this deck are labelled Sales.`);
export const UNDATED_ACTION = "Set the period";
export const KEEP_UNDATED = "Keep undated";
export const undatedTitle = (n, page) => `Set the period for ${n} figures on ${page || "this page"}`;
export const addsUpText = (name) => `These add up to the ${name} total`;

/** The questions: the five's claim questions first, then the other claim questions; the claims keep the server's ranking (`attention`:
 *  [{id, in_top5}], best first). An Other figure is never a task. No question is about a column: there is no mapping to answer. */
export function openQuestions(candidates, attention, groups, sales = []) {
  const claims = [];
  // a claim in the register whose reason asks the analyst to set or confirm something (the server names the reason in `set`)
  const asked = new Map((attention || []).filter((a) => a.set).map((a) => [a.id, a.set]));
  (candidates || []).forEach((c) => {
    if (isOther(c)) return;
    if (c.status === "pending" && turnoverOf(c).open) claims.push({ key: `turnover-${c.id}`, kind: "turnover", c });
    else if (c.status === "pending" || (c.status !== "rejected" && definitionOf(c).open)) claims.push({ key: `claim-${c.id}`, kind: "claim", c });
    else if (c.status !== "rejected" && asked.has(c.id)) claims.push({ key: `set-${c.id}`, kind: "set", c, reason: asked.get(c.id) });
  });
  // two or more undated figures of one page are one question (the server names the page's key and their number)
  const undatedBy = new Map((attention || []).filter((a) => a.undated).map((a) => [a.id, a.undated]));
  const merged = new Map();
  const single = [];
  claims.forEach((item) => {
    const u = item.kind === "set" ? undatedBy.get(item.c.id) : null;
    if (!u) { single.push(item); return; }
    if (!merged.has(u.key)) { const card = { key: `undated-${u.key}`, kind: "undated", page: u.page, n: u.n, cs: [], c: item.c, reason: item.reason }; merged.set(u.key, card); single.push(card); }
    merged.get(u.key).cs.push(item.c);
  });
  claims.length = 0;
  claims.push(...single);
  const place = new Map((attention || []).map((a, i) => [a.id, { i, top: Boolean(a.in_top5) }]));
  const at = (item) => place.get(item.c.id) || { i: Number.MAX_SAFE_INTEGER, top: false };
  claims.sort((a, b) => at(a).i - at(b).i);
  // the questions the groups raise (which annual figure, which parts) and the conflicts that stay unresolved: after the claims that wait
  const related = groupQuestions(groups).map((q) => ({ key: `group-${q.id}`, kind: "group", q }));
  const asks = (sales || []).map((q) => ({ key: `sales-${q.deck_id}`, kind: "sales", q }));       // one per deck
  return [...claims.filter((x) => at(x).top), ...claims.filter((x) => !at(x).top), ...asks, ...related];
}
