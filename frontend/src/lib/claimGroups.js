/**
 * Claim groups and conflicts on the screen (docs/specs/claim-groups.md; docs/design/claim-review-simplified-design.md sections 1 and 2).
 * The server relates the claims (backend/app/claim_groups.py) and sends the roles, the groups, the questions and the conflicts; nothing is
 * related, summed or chosen here.
 */
import { PLACEHOLDER, fmtCurrency } from "./format";

export const PART_ROLES = ["part", "also", "repeat"];     // shown under another row's Details: a part, a part of a coarser set, a figure stated again
export const CONFLICTS_HEADING = "Unresolved conflicts";
export const GROUP_DETAILS = "Details";
export const GROUP_COLUMNS = ["Claim and period", "Result"];
export const CHOOSE_FIGURE = "Use this figure";
export const CHOSEN = "Chosen by you";
export const UNDO_CHOICE = "Undo choice";
export const EXCLUDE = "Not a company claim";
export const EXCLUDE_REASON = "Reason…";
export const KEPT_NOTE = "The other figures stay as claims until they are corrected, scoped or excluded. Edit a claim in the claims list to correct it or set its scope.";
export const QUESTION_HEADINGS = { total: "Which annual figure should the audit use?" };

/** The rows the claims list shows as items: a part of a reconciled total is shown under its total. */
export const visibleRows = (rows) => (rows || []).filter((r) => !PART_ROLES.includes(r.group_role));

/** The rows shown under a row's Details, in the order the server ranks them: the parts of a total, the parts of a coarser set that reconcile
 *  too, and the figures stated again (a repeat folds into the row of its first statement, also when nothing is grouped). */
export const partsOf = (row, rows) => (row.group_id && !PART_ROLES.includes(row.group_role)
  ? (rows || []).filter((r) => r.group_id === row.group_id && r !== row && PART_ROLES.includes(r.group_role)) : []);

/** Items shown against claims underneath, from the register rows (the server's `counts` says the same). */
export const countsOf = (rows) => ({ items: visibleRows(rows).length, claims: (rows || []).length, groups: (rows || []).filter((r) => r.group_role === "total").length });

export const partsLabel = (n) => `${n} ${n === 1 ? "part" : "parts"}`;

/** The collapsed line of a row's Details: its parts, the ones of another set, the repeats, and the parts that are contradicted: a verified
 *  annual total does not hide a contradicted quarter (design note section 1). */
export function detailsLabel(parts) {
  const n = (role) => parts.filter((p) => p.group_role === role).length;
  const bits = [];
  if (n("part")) bits.push(partsLabel(n("part")));
  if (n("also")) bits.push(`${n("also")} in another set`);
  if (n("repeat")) bits.push(`${n("repeat")} ${n("repeat") === 1 ? "repeat" : "repeats"}`);
  const bad = parts.filter((p) => p.evidence_label === "Contradicted").length;
  if (bad) bits.push(`${bad} contradicted`);
  return `${GROUP_DETAILS} · ${bits.join(" · ")}`;
}

/** "6 items shown for 9 claims": only when something is grouped, so the counts differ for a reason. */
export const countsText = (counts) => (counts && counts.groups > 0
  ? `${counts.items} ${counts.items === 1 ? "item" : "items"} shown for ${counts.claims} claims; ${counts.groups} annual ${counts.groups === 1 ? "total stands" : "totals stand"} for ${counts.groups === 1 ? "its" : "their"} parts.` : null);

/** A candidate figure of a question, in its own currency. */
export const figureText = (c) => (c.currency ? fmtCurrency(c.value, c.currency) : `${c.value}${c.unit ? ` ${c.unit}` : ""}`);

/** The questions and unresolved conflicts the Needs your attention card lists: the open ones, and the conflicts that stay after a figure was
 *  chosen (a conflict is unresolved until a figure is corrected, scoped or excluded). One card each, by question id. */
export function groupQuestions(data) {
  const seen = new Set();
  return [...(data?.reviews || []), ...(data?.conflicts || [])].filter((q) => !seen.has(q.id) && seen.add(q.id));
}

export const questionTitle = (q) => `${QUESTION_HEADINGS[q.kind] || QUESTION_HEADINGS.total} ${q.metric || ""}${q.period ? `, ${q.period}` : ""}`.trim();
export const sourceText = (c) => c.source || PLACEHOLDER;
