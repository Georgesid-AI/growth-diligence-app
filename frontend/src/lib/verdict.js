/**
 * The claim-review conclusion, Data gaps sections of the Dashboard (docs/specs/verdict-and-memo.md sections 4,
 * 6.4 and 8; docs/specs/claim-review-conclusion.md; docs/design/simplified-flow.md).
 * Everything shown is a register row, a gap row, a stored input or a computed line from the server; nothing is rated, ranked or tested here.
 */

// docs/specs/claim-review-conclusion.md: the section describes the five selected claims, never a recommendation. The server sends
// the heading and the scope sentence; these are the same words for a response that lacks them.
export const CONCLUSION_HEADING = "Claim-review conclusion — assessment of the five selected claims";
export const SCOPE_SENTENCE = "This assesses the five claims selected by the app by value at stake; the analyst may change the selection. It is not an investment recommendation.";
export const OTHER_CONTRADICTIONS = "Other contradictions";
export const NO_OTHER_CONTRADICTIONS = "None found among tested claims.";
export const TOP5_HEADING = "Top 5";
// The five are selected by the app and in force at once; the analyst may change the set (simplified-flow.md section 3, decision 11).
export const SELECTION_CHANGED = "Top 5 changed by the analyst —";
export const RESET = "reset";
export const REPLACE = "Replace with…";
export const USE_SELECTION = "Use this selection";
export const MEMO_BUTTON = "Download report";
export const CHANGE = "Change";
export const NOTE_LABEL = "Analyst note (optional)";
export const NOTE_MAX = 1000;
export const NOTE_HELP = "One line in the report, after the computed reasons. Never sent to a model.";
export const DETAIL_HEADING = "Verdict detail";
export const PART_FIVE = "Five claims";
export const PART_REASONS = "Three reasons";
export const PART_KEY_GATES = "Key gates";
export const PART_GAPS = "Top data gaps";
export const PART_RATINGS = "Ratings";
export const PART_UNRESOLVED = "Unresolved questions";
export const PART_INPUTS = "Inputs";
export const GATE_EDIT = "Edit gate";
export const RATING_DETAILS = "details";
export const RATING_RULES = "Data reliability follows the Data integrity conclusion: Reliable is Strong, Needs clarification Adequate, Material concerns Weak. Growth engine follows NRR, gross revenue churn and CAC payback: Strong needs all three present and green (NRR at least 100%, churn at most 8%, payback at most 12 months), Weak when churn is above 15% or payback above 18 months, Adequate otherwise; NRR or churn missing is not rated.";

export const GAPS_HEADING = "Data gaps";
export const GAP_COLUMNS = ["What the company cannot measure", "Why it matters", "Requested", "Target date"];
export const REVIEW_LABEL = "First quarterly review";

export const THESIS_MAX = 300;

/** The top 5 as the pick shows it: the stored or proposed set, or the draft the analyst is editing. */
export const initialPicks = (verdict) => [...(verdict?.top5?.in_force || [])];

/** A pick replaced by another register row: the row it replaces leaves the set, no row is in it twice. */
export function replacePick(picks, index, claimId) {
  if (picks.includes(claimId) && picks[index] !== claimId) return picks;
  return picks.map((id, i) => (i === index ? claimId : id));
}

export const samePicks = (a, b) => a.length === b.length && [...a].sort().join("|") === [...b].sort().join("|");

/** "Median sales cycle, Q4 2023" for a candidate of the verdict response: the claim by name, no rank prefix. */
export const candidateText = (c) => c.claim;

/** The reason a download of the memo was refused, from the body the server sent (its detail), else the status text. */
export function refusalText(err) {
  const raw = err?.response?.data;
  try {
    const detail = JSON.parse(raw).detail;
    if (typeof detail === "string") return detail;
  } catch (e) { /* not JSON */ }
  return typeof raw === "string" && raw ? raw : "The memo could not be built";
}
