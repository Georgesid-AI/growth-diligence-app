/**
 * The Verdict, Data gaps and AI usage and cost sections of the Dashboard (docs/specs/verdict-and-memo.md sections 4, 6.4 and 8).
 * The wording is W7, W8, W20, W21, W23 and W24 as approved; the part names are those of section 6.4. Everything shown is a
 * register row, a gap row, a stored input or a count from the server; nothing is rated, ranked or tested here.
 */
import { seeGlossary } from "./glossary";

export const VERDICT_HEADING = "Verdict";
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

export const USAGE_HEADING = "AI usage and cost (this audit)";
export const USAGE_COLUMNS = ["Step", "Calls", "Cache hits", "Input tokens", "Output tokens", "Cost (USD)"];
const STEP_NAMES = { deck_structure: "Deck structure reading", column_mapping: "Column mapping" };

export const stepName = (step) => STEP_NAMES[step] || `Narrative – ${step}`;

/** The cost table: one row per step the server counted, then the total (cost in USD with 2 decimals). */
export function usageRows(usage) {
  if (!usage) return [];
  const rows = Object.entries(usage.by_step || {}).map(([step, u]) => ({
    key: step, step: stepName(step), calls: u.calls, cacheHits: u.cache_hits, input: u.input_tokens, output: u.output_tokens,
    cost: u.estimated_cost_usd.toFixed(2),
  }));
  rows.push({
    key: "total", step: "Total", calls: usage.calls + (usage.structure_calls || 0), cacheHits: usage.cache_hits, input: usage.input_tokens,
    output: usage.output_tokens, cost: usage.estimated_cost_usd.toFixed(2),
  });
  return rows;
}

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
