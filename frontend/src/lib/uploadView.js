/**
 * The Upload page's words and shapes (docs/design/audit-page-mockup.html; docs/specs/chat-upload.md section 5). Pure functions over what the server
 * sends for each file: a spreadsheet's stored view (read_state, read_stage, read_checked, read_total, read_matched, read_items, read_elapsed,
 * read_checking_elapsed) and a deck's record (ai_status, read_progress, pages, figure_pages, skipped_pages, read_elapsed). Every number goes through
 * lib/format.js. The elapsed seconds are the server's; the page adds the seconds since it received them, so it needs no clock of its own.
 */
import { fmtCount, fmtElapsed } from "./format";
import { s2Explainer } from "./chatUpload";
import { aiReadStatus, deckSummaryLine } from "./deckClaims";
import { VERIFIED_LINE } from "./auditForm";

export const HEADER_TEXT = "Files are read by an AI model (Anthropic API, not used for training). Personal data is removed and company names are coded before sending. Page images are sent without changes. Uploading a file counts as consent.";
export const PROCESSING_LINK = "How your files are processed";
export const PROCESSING_TITLE = "How your files are processed";
export const PROCESSING_PARAGRAPHS = (zdr) => [
  "Before anything is sent, names, contact details and ID numbers are removed, and client and company names are replaced by codes that exist only in this audit. Figures and labels are sent as they are. Deck pages are also sent as an image of the page, which is not masked. Narratives use AI on computed results.",
  VERIFIED_LINE,
  s2Explainer(zdr),          // the ZDR sentence only when the server says PROVIDER_ZDR is on, else the existing off-text
];

export const SHEET_CARD = {
  title: "Financial data",
  line: "Required: a monthly revenue or ARR report. A P&L, revenue by customer or CRM export add more metrics. .xlsx or .csv",
  drop: "Drop files here",
};
export const DECK_CARD = {
  title: "Board deck or growth plan",
  line: "Board decks, investor updates, growth model or business plan. .pdf, .pptx or .docx · up to 8 documents",
  muted: "Page images work for PDF only – export PowerPoint or Word to PDF for the best read. Cannot read: scanned PDFs, images, Keynote or Google Slides links.",
  drop: "Drop documents here",
  note: "Page images are sent without masking.",
};
export const UPLOAD_LABEL = "Upload";
export const REMOVE_LABEL = "Remove";

export const headerText = (audit) => `Company: ${audit.company_name} · ${audit.reporting_currency || "EUR"}`;

// The stage tags of a spreadsheet's line. The server reports read_stage; "done" is Processed.
export const STAGE_TAGS = {
  removing_personal_data: "Removing personal data",
  reading_the_sheet: "Reading the sheet",
  checking_cells: "Checking cells",
};
export const PROCESSED = "Processed";
export const NOT_PROCESSED = "Not processed";
export const DECK_READING_TAG = "Reading the pages";
export const READING_HINT = "usually 1–3 minutes";
export const NOT_READ_LINE = "The file is stored but could not be read.";

const DECK_BUSY = ["reading", "waiting"];
export const sheetBusy = (v) => Boolean(v.local ? v.local.state === "uploading" : v.read_state === "reading");
export const deckBusy = (d) => Boolean(d.local ? d.local.state === "uploading" : DECK_BUSY.includes(d.ai_status));

/** Seconds a running item has run: the server's count when it was fetched, plus the seconds since. A local line counts from its own start. */
export function runningSeconds(item, seconds, now) {
  if (item.local) return Math.max(0, (now - item.local.startedAt) / 1000);
  return Math.max(0, (seconds ?? 0) + Math.max(0, now - (item.fetchedAt ?? now)) / 1000);      // the clock may tick before the reply lands: never count backwards
}
const elapsedText = (s) => `Elapsed ${fmtElapsed(s)}`;

/** The line of one spreadsheet: {tag, tone: run|done|bad, time, sub}. */
export function sheetLine(v, now) {
  if (v.local) {
    if (v.local.state === "failed") return { tag: NOT_PROCESSED, tone: "bad", time: "", sub: v.local.message };
    return { tag: STAGE_TAGS.removing_personal_data, tone: "run", time: elapsedText(runningSeconds(v, null, now)), sub: null };
  }
  if (v.read_state === "reading") {
    const stage = STAGE_TAGS[v.read_stage] ? v.read_stage : "removing_personal_data";
    let sub = null;
    if (stage === "reading_the_sheet") sub = READING_HINT;
    if (stage === "checking_cells" && v.read_total != null) sub = `${fmtCount(v.read_checked ?? 0)} of ${fmtCount(v.read_total)} figures checked`;
    return { tag: STAGE_TAGS[stage], tone: "run", time: elapsedText(runningSeconds(v, v.read_elapsed, now)), sub };
  }
  if (v.read_state === "failed") return { tag: NOT_PROCESSED, tone: "bad", time: v.read_elapsed != null ? fmtElapsed(v.read_elapsed) : "", sub: NOT_READ_LINE };
  return { tag: PROCESSED, tone: "done", time: v.read_elapsed != null ? fmtElapsed(v.read_elapsed) : "", sub: null };
}

const unit = (n, one, many) => `${fmtCount(n)} ${n === 1 ? one : many}`;
/** "24 pages · 17 with figures processed · 7 skipped (no numbers)". */
export function deckSummary(d) {
  if (d.figure_pages == null) return unit(d.pages ?? 0, d.page_unit || "page", `${d.page_unit || "page"}s`) + " processed";
  const skipped = d.skipped_pages?.length || 0;
  return [unit(d.pages ?? 0, d.page_unit || "page", `${d.page_unit || "page"}s`), `${fmtCount(d.figure_pages)} with figures processed`,
    ...(skipped ? [`${fmtCount(skipped)} skipped (no numbers)`] : [])].join(" · ");
}

/** The line of one deck: {tag, tone, time, summary} (one summary line, shown once). */
export function deckLine(d, now) {
  if (d.local) {
    if (d.local.state === "failed") return { tag: NOT_PROCESSED, tone: "bad", time: "", summary: d.local.message };
    return { tag: DECK_READING_TAG, tone: "run", time: elapsedText(runningSeconds(d, null, now)), summary: null };
  }
  if (DECK_BUSY.includes(d.ai_status)) {
    return { tag: DECK_READING_TAG, tone: "run", time: elapsedText(runningSeconds(d, d.read_elapsed, now)), summary: aiReadStatus(d) };
  }
  const time = d.read_elapsed != null ? fmtElapsed(d.read_elapsed) : "";
  if (d.ai_status === "read") return { tag: PROCESSED, tone: "done", time, summary: deckSummary(d) };
  return { tag: NOT_PROCESSED, tone: "bad", time, summary: deckSummaryLine(d) };
}

/** "A", "A and B", or "3 files": the files a line names. */
function named(names) {
  if (names.length <= 2) return names.join(" and ");
  return `${fmtCount(names.length)} files`;
}

/** The readiness line beside Run audit, and whether the button is held. `sheets` and `decks` are the lines of the cards (stored and local). */
export function readiness(sheets, decks) {
  const reading = [...sheets.filter(sheetBusy), ...decks.filter(deckBusy)].map((f) => f.file || f.name);
  const sheetsReady = sheets.filter((s) => !sheetBusy(s)).length;
  const decksReady = decks.filter((d) => !deckBusy(d)).length;
  const sheetWord = `data ${sheets.length === 1 ? "file" : "files"}`;
  const readyWord = decksReady === 1 ? "deck" : "decks";
  const deckWord = decks.length === 1 ? "deck" : "decks";
  if (reading.length) {
    return {
      held: true,
      text: `Run audit is off while ${named(reading)} ${reading.length === 1 ? "is" : "are"} being read. `
        + `${fmtCount(sheetsReady)} of ${fmtCount(sheets.length)} ${sheetWord} and ${fmtCount(decksReady)} ${readyWord} ready.`,
    };
  }
  if (!sheets.length && !decks.length) return { held: false, text: "The audit cannot run yet. Missing: a file." };
  return { held: false, text: `Ready: ${fmtCount(sheets.length)} ${sheetWord} and ${fmtCount(decks.length)} ${deckWord} processed.` };
}

export const STEP_LABELS = { reading: "Reading files", checking: "Checking figures", calculating: "Calculating results" };
const maxOf = (list) => list.reduce((m, n) => (n != null && n > m ? n : m), -1);

/**
 * The three steps of the run card: [{key, label, tone: done|run|wait|bad, second}]. Reading and checking follow the files; calculating follows the
 * run's own stages (`calc`: {status, seconds} - idle, running, done, failed - kept by the run panel).
 */
export function steps(sheets, decks, calc, now) {
  const all = [...sheets, ...decks];
  const busy = [...sheets.filter(sheetBusy), ...decks.filter(deckBusy)];
  const total = all.length;
  const readSeconds = all.map((f) => (f.local ? null : f.read_elapsed));
  const longest = (list) => list.map((f) => runningSeconds(f, f.read_elapsed, now));
  let reading;
  if (!total) reading = { tone: "wait", second: "not started" };
  else if (busy.length) reading = { tone: "run", second: `${elapsedText(Math.max(...longest(busy)))} · ${fmtCount(total - busy.length)} of ${fmtCount(total)} files read` };
  else reading = { tone: "done", second: maxOf(readSeconds) >= 0 ? fmtElapsed(maxOf(readSeconds)) : "Done" };

  const checking = sheets.filter((s) => s.read_state === "reading" && s.read_stage === "checking_cells");
  let check;
  if (!total) check = { tone: "wait", second: "not started" };
  else if (busy.length) {
    if (checking.length) {
      const items = checking.reduce((n, s) => n + (s.read_items ?? 0), 0);
      const matched = checking.reduce((n, s) => n + (s.read_matched ?? 0), 0);
      const time = elapsedText(Math.max(...checking.map((s) => runningSeconds(s, s.read_checking_elapsed, now))));
      check = { tone: "run", second: items ? `${time} · ${fmtCount(matched)} of ${fmtCount(items)} match` : time };
    } else check = { tone: "wait", second: "waits for reading" };
  } else {
    const t = maxOf(sheets.map((s) => s.read_checking_elapsed));
    check = { tone: "done", second: t >= 0 ? fmtElapsed(t) : "Done" };
  }

  let calculating;
  if (calc.status === "running") calculating = { tone: "run", second: elapsedText(calc.seconds ?? 0) };
  else if (calc.status === "done") calculating = { tone: "done", second: calc.seconds != null ? fmtElapsed(calc.seconds) : "Done" };
  else if (calc.status === "failed") calculating = { tone: "bad", second: "Failed" };
  else calculating = { tone: "wait", second: "not started" };
  return [["reading", reading], ["checking", check], ["calculating", calculating]].map(([key, s]) => ({ key, label: STEP_LABELS[key], ...s }));
}
