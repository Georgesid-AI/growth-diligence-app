/**
 * Dates and periods (docs/specs/dates-and-periods.md): the requested analysis date, the latest valid source period, and the
 * period and missing months of every metric, as the screen words them. The as-of month is a setting; it is never shown as the
 * period of a figure. Pure functions over the stored results.
 */
import { displayDate } from "./datePicker";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
  "December"];
const parts = (month) => {
  const m = /^(\d{4})-(\d{2})/.exec(month || "");
  return m ? [Number(m[1]), Number(m[2])] : null;
};

/** "2019-06" -> "June 2019". */
export function monthName(month) {
  const p = parts(month);
  return p ? `${MONTHS[p[1] - 1]} ${p[0]}` : "—";
}

/** "2019-06" -> "Jun 2019". */
export function shortMonth(month) {
  const p = parts(month);
  return p ? `${MONTHS[p[1] - 1].slice(0, 3)} ${p[0]}` : "—";
}

/** "June 2019 (Complete)" / "June 2019 (Possibly partial)"; "—" with no revenue file. */
export const sourcePeriodText = (source) => (source?.month ? `${monthName(source.month)} (${source.status})` : "—");

/** "June 2019": the last month any revenue figure reads (the evidence end), else the as-of month. */
export const evidenceToText = (results) => monthName(results?.source_period?.evidence_to || results?.as_of_month);

/** "Jul 2017 – Jun 2019": a block's period, or null when the engine stored none. */
export const periodText = (period) => (period?.first ? `${shortMonth(period.first)} – ${shortMonth(period.last)}` : null);

/** "Months missing: Mar 2018, Apr 2018", or null: the list of the months missing inside the period, never a count. */
export const missingText = (period) => (period?.missing?.length ? `Months missing: ${period.missing.map(shortMonth).join(", ")}` : null);

/** The requested analysis date as a date: the analyst's, else today. */
export function analysisDate(audit, today = new Date()) {
  if (audit?.analysis_date) return audit.analysis_date;
  const iso = new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())).toISOString();
  return iso.slice(0, 10);
}

/** The Dashboard's dates line: the two dates side by side, never merged into one. */
export const datesLine = (audit, results, today) =>
  `Requested analysis date: ${displayDate(analysisDate(audit, today))} · Latest valid source period: ${sourcePeriodText(results?.source_period)}`;
