/**
 * Data integrity (docs/specs/integrity-coverage.md): the two blocks the server computes, never folded into each other. Block A lists
 * the checks that ran with their result; Block B lists the six checks of the method with their status. Display strings only.
 */
export const INTEGRITY_HEADING = "Data integrity";
export const RESULTS_HEADING = "Results of completed checks";
export const COVERAGE_HEADING = "Assessment coverage";
export const REQUESTS_HEADING = "Data requests";
export const RESULT_COLUMNS = ["Check", "Result", "Finding", "Source"];
export const COVERAGE_COLUMNS = ["Check", "Status", "Reason"];
export const NO_RESULTS = "No check could be completed with the files supplied.";

// Red is the reconciliation's hard blocker only; Amber is anything found; Green is nothing found.
export const RESULT_STYLE = { Green: "text-emerald-700", Amber: "text-amber-800", Red: "text-rose-700" };

/** "Blocked: Revenue reconciliation, Smoothness", or null when nothing is blocked. */
export const blockedText = (integrity) => (integrity?.blocked?.length ? `Blocked: ${integrity.blocked.join(", ")}` : null);
