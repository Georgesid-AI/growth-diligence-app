/**
 * The claim-review conclusion, Data gaps sections of the Dashboard (docs/specs/verdict-and-memo.md sections 4,
 * 6.4 and 8; docs/specs/claim-review-conclusion.md).
 * The wording is W7, W8, W20, W21, W23 and W24 as approved; the part names are those of section 6.4. Everything shown is a
 * register row, a gap row, a stored input or a count from the server; nothing is rated, ranked or tested here.
 */
import { seeGlossary } from "./glossary";

// docs/specs/claim-review-conclusion.md: the section describes the five selected claims, never a recommendation. The server sends
// the heading and the scope sentence; these are the same words for a response that lacks them.
export const CONCLUSION_HEADING = "Claim-review conclusion — assessment of the five selected claims";
export const SCOPE_SENTENCE = "This assesses the five claims the analyst selected. It is not an investment recommendation.";
export const OTHER_CONTRADICTIONS = "Other contradictions";
export const NO_OTHER_CONTRADICTIONS = "None found among tested claims.";
export const JUDGMENT_HEADING = "Analyst judgment";
export const JUDGMENT_MAX = 1000;
export const TOP5_HEADING = "Top 5";
export const PROPOSED = "Proposed by shortfall – confirm or replace.";
export const REPLACE = "Replace with…";
export const CONFIRM = "Confirm top 5";
export const TOP5_STATEMENT = seeGlossary("Top 5 set by the analyst pending ARR bridge.");
export const MEMO_BUTTON = "Download IC memo (Markdown)";
export const PART_FIVE = "Five claims";
export const PART_REASONS = "Three reasons";
export const PART_KEY_GATES = "Key gates";
export const PART_GAPS = "Top data gaps";
export const PART_INPUTS = "Inputs";
export const OTHER_GATES = (n) => `${n} other claims still need a gate.`;

export const GAPS_HEADING = "Data gaps";
export const GAP_COLUMNS = ["What the company cannot measure", "Why it matters", "Requested", "Target date"];
export const REVIEW_LABEL = "First quarterly review";

export const RATING_OPTIONS = ["Strong", "Adequate", "Weak"];
export const THESIS_MAX = 300;

/** The top 5 as the pick shows it: the stored or proposed set, or the draft the analyst is editing. */
export const initialPicks = (verdict) => [...(verdict?.top5?.in_force || [])];

/** A pick replaced by another register row: the row it replaces leaves the set, no row is in it twice. */
export function replacePick(picks, index, claimId) {
  if (picks.includes(claimId) && picks[index] !== claimId) return picks;
  return picks.map((id, i) => (i === index ? claimId : id));
}

export const samePicks = (a, b) => a.length === b.length && [...a].sort().join("|") === [...b].sort().join("|");

/** "#3 Median sales cycle" for a candidate of the verdict response. */
export const candidateText = (c) => `#${c.rank} ${c.claim}`;

/** The reason a download of the memo was refused, from the body the server sent (its detail), else the status text. */
export function refusalText(err) {
  const raw = err?.response?.data;
  try {
    const detail = JSON.parse(raw).detail;
    if (typeof detail === "string") return detail;
  } catch (e) { /* not JSON */ }
  return typeof raw === "string" && raw ? raw : "The memo could not be built";
}
