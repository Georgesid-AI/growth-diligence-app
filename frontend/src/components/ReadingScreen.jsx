import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import ReadingResults, { SourceLink } from "@/components/ReadingResults";
import FxEditor from "@/components/FxEditor";
import { answerCorrection, changeReading, decideUncertain, downloadReading, getAudit, getReading, updateAudit } from "@/lib/api";
import { MONTHS, DEFAULT_FISCAL_YEAR_END, REPORTING_CURRENCIES, SETUP_HELP, SETUP_LABELS, asOfDisplay, asOfEvidenceLine, parseMonthYear } from "@/lib/auditForm";
import { monthName, shortMonth } from "@/lib/periods";
import { describeRequestError } from "@/lib/requestError";
import {
  FIGURE_HOVERS, FIGURE_WIDTHS, HOVERS, OUTCOME_LABELS, UNCERTAIN_LABEL, UNCERTAIN_TITLE, WIDTHS, actualPlanText, candidateText, deckSummary, differsText, lastActualText,
  periodLabel, readingsText, sheetSummary, splitEvidence, uncertainEntries, uncertainTitle, valueText, whereText,
} from "@/lib/readingView";
import { OPEN_UNCERTAIN } from "@/lib/uploadView";
import { PLACEHOLDER, fmtCount } from "@/lib/format";

/**
 * The audit page's reading screen (docs/design/read-check-review.md section 11; docs/design/audit-page-mockup.html): the Check results heading with its
 * sentence, the two blocks "Audit settings" and "Detected layout and calculation inputs", the file tabs and the three result tables with the cards.
 * The upload cards and the run card above it are UploadSection's.
 */
const EMPTY = { files: [], tables: { confirmed: [], rejected: [], cannot_check: [] }, counts: { confirmed: 0, rejected: 0, cannot_check: 0 }, cards: [], review: {} };

/**
 * The state of one change menu: it opens with the current value in it (the detected value, or the last one saved), Save stays off until the value
 * differs from the current one, and Cancel puts the current value back and closes it. `same(a, b)` says when two spellings are one value.
 */
function useChange(current, same, onSave) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(current);
  const close = () => { setOpen(false); setValue(current); };
  const unchanged = same(String(value).trim(), String(current).trim()) || !String(value).trim();
  return {
    open, value, setValue, unchanged,
    show: () => { setValue(current); setOpen(true); },
    cancel: close,
    save: async () => { if (await onSave(String(value).trim())) setOpen(false); },
  };
}
const sameText = (a, b) => a === b;
const sameMonth = (a, b) => a === b || (parseMonthYear(a) != null && parseMonthYear(a) === parseMonthYear(b));

function SaveCancel({ menu, testid }) {
  return (
    <>
      <button type="button" className="btn quiet" data-testid={`${testid}-save`} disabled={menu.unchanged} onClick={menu.save}>Save</button>
      <a href="#cancel" data-testid={`${testid}-cancel`} onClick={(e) => { e.preventDefault(); menu.cancel(); }}>Cancel</a>
    </>
  );
}

function InlineChange({ label, placeholder, current = "", same = sameText, onSave, testid, type = "text" }) {
  const menu = useChange(current, same, onSave);
  if (!menu.open) return <a href="#change" data-testid={testid} onClick={(e) => { e.preventDefault(); menu.show(); }}>Change</a>;
  return (
    <span>
      <input aria-label={label} type={type} placeholder={placeholder} value={menu.value} onChange={(e) => menu.setValue(e.target.value)} data-testid={`${testid}-input`} />
      <SaveCancel menu={menu} testid={testid} />
    </span>
  );
}

const monthIndex = (m) => { const x = /^(\d{4})-(\d{2})/.exec(m || ""); return x ? Number(x[1]) * 12 + Number(x[2]) : null; };

/** "Jan 2019 – May 2022 (41 months)": from the first month with revenue to the as-of month, counted inclusively; without an as-of month, to the last month read; never "—" while an as-of month exists. */
export function reportingPeriodText(audit, period) {
  const first = period?.first || audit.datasets?.revenue?.months?.first;
  const last = audit.as_of_month || period?.last || audit.datasets?.revenue?.months?.last;
  const n = monthIndex(last) - monthIndex(first) + 1;
  if (first && last && n >= 1) return `${shortMonth(first)} – ${shortMonth(last)} (${n} ${n === 1 ? "month" : "months"})`;
  return audit.as_of_month ? monthName(audit.as_of_month) : "—";
}

/** One audit setting on its own line: "Label: value" and a Change link that opens a select in place, on the current value; Save stores a different one. */
function SettingLine({ label, value, options, current, testid, help, onSave }) {
  const menu = useChange(current, sameText, onSave);
  return (
    <p className="setting" data-testid={testid}>
      <span className="k">{label}:</span><span data-testid={`${testid}-value`}>{value}</span>
      {!menu.open
        ? <a href="#change" data-testid={`${testid}-change`} onClick={(e) => { e.preventDefault(); menu.show(); }}>Change</a>
        : (
          <>
            <select aria-label={label} value={menu.value} data-testid={`${testid}-select`} autoFocus onChange={(e) => menu.setValue(e.target.value)}>
              {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
            </select>
            <SaveCancel menu={menu} testid={testid} />
          </>
        )}
      {menu.open && help && <span className="help" data-testid={`${testid}-help`}>{help}</span>}
    </p>
  );
}

/**
 * The items of a spreadsheet the two reads of the file disagree on (docs/design/reading-consistency.md): "Reading uncertain – confirm", both candidates, and a
 * button for each. Nothing is picked for the analyst; a pick is an override record. `kinds` says which items this place lists: the rows go on the file's
 * tab, the sheet-level fields and sheets on the Detected layout block.
 */
function UncertainItems({ file, auditId, kinds, onChange }) {
  const items = (file.consistency?.uncertain || []).filter((i) => kinds.includes(i.kind));
  const pick = async (item, which) => {
    try { await decideUncertain(auditId, file.file_hash, { key: item.key, pick: which }); onChange(); }
    catch (e) { toast.error(e.response?.data?.detail || "The choice could not be saved."); }
  };
  if (!items.length) return null;
  return (
    <div className="uncertain" data-testid="uncertain-items">
      {items.map((item) => (
        <p key={item.key} className="note" data-testid="uncertain-item">
          <b data-testid="uncertain-label">{UNCERTAIN_LABEL}</b> · {uncertainTitle(item)}{" "}
          {["first", "second"].map((which) => (
            <button key={which} type="button" className="btn quiet" data-testid={`uncertain-${which}`} onClick={() => pick(item, which)}
              title={`Use the ${which} reading`}>{which === "first" ? "First reading" : "Second reading"}: {candidateText(item, which)}</button>
          ))}
        </p>
      ))}
    </div>
  );
}

/**
 * The rows of a spreadsheet the two reads disagree on, as cards on the file's tab (brief of George, 2026-11-05, item 10): the same words as the Uncertain
 * list - what differs, the first and the second reading, Use first and Use second. The Detected layout block keeps UncertainItems above.
 */
function UncertainCards({ file, auditId, onChange }) {
  const items = (file.consistency?.uncertain || []).filter((i) => i.kind === "row");
  const pick = async (item, which) => {
    try { await decideUncertain(auditId, file.file_hash, { key: item.key, pick: which }); onChange(); }
    catch (e) { toast.error(e.response?.data?.detail || "The choice could not be saved."); }
  };
  if (!items.length) return null;
  return (
    <div className="uncertain" data-testid="uncertain-items">
      {items.map((item) => (
        <p key={item.key} className="note" data-testid="uncertain-item">
          <b data-testid="uncertain-label">{UNCERTAIN_TITLE}</b> · {whereText(item)} · {differsText(item)}{" "}
          <span data-testid="uncertain-first-text">First reading: {readingsText(item, "first")}</span>{" "}
          <button type="button" className="btn quiet" data-testid="uncertain-first" onClick={() => pick(item, "first")} title="Use the first reading">Use first</button>{" "}
          <span data-testid="uncertain-second-text">Second reading: {readingsText(item, "second")}</span>{" "}
          <button type="button" className="btn quiet" data-testid="uncertain-second" onClick={() => pick(item, "second")} title="Use the second reading">Use second</button>
        </p>
      ))}
    </div>
  );
}

/** Audit settings and Detected layout and calculation inputs: the two blocks under the Check results sentence (docs/design/audit-page-mockup.html). */
export function SettingsBlocks({ audit, files, period, onAsOf, onChange, onSetting, onFxSaved }) {
  const asOf = audit.as_of_month;
  const evidence = splitEvidence(asOfEvidenceLine(audit));
  const sheets = files.filter((f) => f.kind === "sheet");
  const fy = Number(audit.fiscal_year_end) || DEFAULT_FISCAL_YEAR_END;
  return (
    <>
      <div className="block" data-testid="audit-settings">
        <h3>Audit settings</h3>
        <p className="muted">Set for this audit, not read from the files.</p>
        <SettingLine label="Fiscal year-end" testid="setting-fy" value={MONTHS[fy - 1]} current={String(fy)}
          options={MONTHS.map((m, i) => [String(i + 1), m])} help={SETUP_HELP.fiscal_year_end}
          onSave={(v) => onSetting("fiscal_year_end", { fiscal_year_end: Number(v) }, "Fiscal year-end saved; claim periods re-mapped")} />
        <div style={{ height: "1.2em" }} data-testid="setting-gap" aria-hidden="true" />
        <SettingLine label="Reporting currency" testid="setting-currency" value={audit.reporting_currency || "EUR"} current={audit.reporting_currency || "EUR"}
          options={REPORTING_CURRENCIES.map((c) => [c, c])} help={SETUP_HELP.reporting_currency}
          onSave={(v) => onSetting("reporting_currency", { reporting_currency: v })} />
        <FxEditor key={audit.reporting_currency || "EUR"} audit={audit} onSaved={onFxSaved} />
      </div>
      <div className="block" data-testid="detected-layout">
        <h3>Detected layout and calculation inputs</h3>
        <p className="muted">This block shows only the inputs that decide periods and the main revenue row. Every other mapped row (ARR, MRR, customers, churn, S&M, costs) is used by its role and listed on each file's tab under "Show all lines". Review and change if needed.</p>
        <div className="anchors">
          <span className="k">Actual data</span><span data-testid="assumption-period">{reportingPeriodText(audit, period)}</span><span />
          <span className="k">As-of month</span>
          <span data-testid="assumption-as-of">
            {asOf ? `${monthName(asOf)}${audit.as_of_by === "analyst" ? " (set by analyst)" : ""}` : "not determined"}
            {(evidence.text || evidence.confirmed) && <span data-testid="assumption-as-of-evidence"> — {evidence.text}{evidence.confirmed && <> {evidence.confirmed}</>}</span>}
          </span>
          <InlineChange label="As-of month" placeholder="Jun 2021" testid="assumptions-change" current={asOfDisplay(asOf)} same={sameMonth} onSave={onAsOf} />
          {sheets.map((f) => <SheetAnchors key={f.file_hash} file={f} audit={audit} onAsOf={onAsOf} onChange={onChange} />)}
        </div>
        {sheets.map((f) => <UncertainItems key={f.file_hash} file={f} auditId={audit.id} kinds={["field", "sheet"]} onChange={onChange} />)}
      </div>
    </>
  );
}

/** One <p> per summary line; the parts of a line are joined by " · ", a part's number (or period) in the heavier weight. */
const Summary = ({ lines }) => lines.map((parts, n) => (
  <p key={n} className="summary" data-testid="file-summary">
    {parts.map((p, i) => (
      <span key={i}>{i ? " · " : ""}{p.bold && p.text.startsWith(" ") ? <><b>{p.bold}</b>{p.text}</> : p.bold ? <>{p.text}<b>{p.bold}</b></> : p.text}</span>
    ))}
  </p>
));

function LinesTable({ lines, file, auditId, sheet }) {
  const heads = Object.keys(HOVERS.lines);
  return (
    <table className="rows" data-testid="lines-table">
      <colgroup>{WIDTHS.lines.map((w, i) => <col key={i} style={{ width: `${w}%` }} />)}</colgroup>
      <thead><tr>{heads.map((h) => <th key={h} title={HOVERS.lines[h]}>{h}</th>)}</tr></thead>
      <tbody>
        {lines.map((ln) => (
          <tr key={ln.row} className={[ln.indent ? "sub" : "", ln.moved ? "moved" : ""].join(" ").trim()} data-testid={`line-${ln.row}`}>
            <td data-h="Line" data-indent={ln.indent || 0} style={ln.indent > 1 ? { paddingLeft: `${10 + 16 * ln.indent}px` } : undefined}>{ln.label}{ln.moved && <span className="note" data-testid="moved-note"> · shown under its line</span>}{ln.note && <span className="note" data-testid="line-note"> · {ln.note}</span>}</td>
            <td data-h="Interpreted as">{ln.read_as}</td>
            <td data-h="Basis">{ln.basis}</td>
            <td data-h="Actual / plan">{actualPlanText(ln.actual_plan)}</td>
            <td data-h="Cells" className="src">
              {ln.cells ? <SourceLink auditId={auditId} source={{ file: file.file, file_hash: file.file_hash, sheet, cell: ln.cells }} label={<b>{ln.cells}</b>} /> : PLACEHOLDER_DASH}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
const PLACEHOLDER_DASH = "—";

/** One spreadsheet's rows of the layout block: Last actual (when another file set the as-of month), Revenue row, Actual / plan; each with its Change link. */
function SheetAnchors({ file, audit, onAsOf, onChange }) {
  const a = file.anchors;
  const change = async (body) => {
    try { await changeReading(audit.id, file.file_hash, body); onChange(); return true; }
    catch (e) { toast.error(e.response?.data?.detail || "The change could not be saved."); return false; }
  };
  const sheet = a.revenue_row?.sheet || a.actual_plan?.sheet || file.lines[0]?.sheet;
  const setsAsOf = audit.as_of_file && audit.as_of_file === file.file;       // the audit-level As-of month row above already says this file's last actual
  const of = ` (${file.file})`;
  return (
    <>
      {!setsAsOf && (
        <>
          <span className="k">Last actual</span>
          <span data-testid="anchor-as-of">{a.as_of ? `${lastActualText(a.as_of.month, file.summary.granularity)} — ${splitEvidence(a.as_of.evidence).text}${of}` : `not determined${of}`}</span>
          <InlineChange label="As-of month" placeholder="Jun 2021" testid="anchor-as-of-change" current={a.as_of ? shortMonth(a.as_of.month) : ""} same={sameMonth} onSave={onAsOf} />
        </>
      )}
      <span className="k">Revenue row</span>
      <span data-testid="anchor-revenue">{a.revenue_row ? `Row ${a.revenue_row.row}, ${a.revenue_row.label}, ${a.revenue_row.basis}${of}` : `not found${of}`}</span>
      <InlineChange label="Revenue row" placeholder="Row number" type="number" testid="anchor-revenue-change" current={a.revenue_row ? String(a.revenue_row.row) : ""}
        onSave={(v) => change({ what: "revenue_row", sheet, row: Number(v) })} />
      <span className="k">Actual / plan</span>
      <span data-testid="anchor-boundary">{a.actual_plan ? `actual to column ${a.actual_plan.last_actual}, plan from ${a.actual_plan.plan_from}${of}` : `not determined${of}`}</span>
      <InlineChange label="Last actual column" placeholder="AP" testid="anchor-boundary-change" current={a.actual_plan?.last_actual || ""}
        onSave={(v) => change({ what: "boundary", sheet: a.actual_plan?.sheet || sheet, column: v })} />
    </>
  );
}

/** What a sheet's tab adds under the tabs: its summary lines, the reader's notes, the exports and every line of the map. */
function SheetDetail({ file, auditId, onChange }) {
  const [open, setOpen] = useState(false);
  const sheet = file.anchors.revenue_row?.sheet || file.anchors.actual_plan?.sheet || file.lines[0]?.sheet;
  return (
    <section className="file" data-testid="file-block">
      <Summary lines={sheetSummary(file.summary)} />
      {(file.notes || []).map((n, i) => <p key={i} className="note" data-testid="file-note">{n.name}: {n.reason}</p>)}
      {file.consistency?.status === "not_compared" && <p className="note" data-testid="consistency-note">{file.consistency.reason}</p>}
      <UncertainCards file={file} auditId={auditId} onChange={onChange} />
      <p className="exports">
        <a href="#json" data-testid="export-json" onClick={(e) => { e.preventDefault(); downloadReading(auditId, file.file_hash, "json"); }}>Export map (JSON)</a>
        {" · "}
        <a href="#csv" data-testid="export-csv" onClick={(e) => { e.preventDefault(); downloadReading(auditId, file.file_hash, "csv"); }}>Export series (CSV)</a>
      </p>
      <details open={open} data-testid="lines-details">
        <summary onClick={(e) => { e.preventDefault(); setOpen((v) => !v); }}>{open ? "Hide all lines" : "Show all lines"}</summary>
        {file.lines.map((entry) => <LinesTable key={entry.sheet} lines={entry.lines} file={file} auditId={auditId} sheet={entry.sheet || sheet} />)}
      </details>
    </section>
  );
}

function DeckDetail({ file }) {
  return (
    <section className="file" data-testid="file-block">
      <Summary lines={deckSummary(file.summary, file.anchors.figures)} />
    </section>
  );
}

/** The deck tab's full figures list, in the bordered box of the lines table: every figure read from the deck, with its page and outcome. */
function DeckFigures({ file, auditId, onChange }) {
  const choose = async (f, option) => {
    try { await answerCorrection(auditId, f.id, { index: f.reading.index, action: "choose", option }); onChange(); }
    catch (e) { toast.error(e.response?.data?.detail || "The choice could not be saved."); }
  };
  const heads = Object.keys(FIGURE_HOVERS);
  return (
    <div className="box" data-testid="deck-figures">
      <table className="rows">
        <colgroup>{FIGURE_WIDTHS.map((w, i) => <col key={i} style={{ width: `${w}%` }} />)}</colgroup>
        <thead><tr>{heads.map((h) => <th key={h} title={FIGURE_HOVERS[h]} className={h === "Value" ? "num" : ""}>{h}</th>)}</tr></thead>
        <tbody>
          {(file.figures || []).map((f, n) => (
            <tr key={`${f.key}-${n}`} data-testid="deck-figure">
              <td data-h="Metric">{f.metric}</td>
              <td data-h="Value" className="num">{valueText(f.value, f.unit, f.currency)}</td>
              <td data-h="Period" className="nw">{periodLabel(f.period)}</td>
              <td data-h="Label">{f.label || PLACEHOLDER}</td>
              <td data-h="Page">{f.page ?? PLACEHOLDER}</td>
              <td data-h="Outcome" className="nw">
                {f.uncertain ? <b data-testid="deck-figure-uncertain">{UNCERTAIN_TITLE}</b> : (OUTCOME_LABELS[f.outcome] || f.outcome)}
                {f.uncertain && (f.reading?.options || []).map((text, i) => (
                  <button key={i} type="button" className="btn quiet" data-testid="deck-figure-choose" title={text} onClick={() => choose(f, i)}>{i === 0 ? "Use first" : "Use second"}</button>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const TAB_NOTE = "Each tab shows the Matches source, Doesn't match source and Needs attention results for one file. For decks, it also lists every figure read from the deck, with its page number and outcome.";
const LEAD = "Every figure the model read, after code opened its cell or page and compared the value. Four lists: Matches source, Doesn't match source, Uncertain, Needs attention.";
const fileKey = (f) => f.file_hash || f.deck_id;
const rowsOf = (rows, f) => rows.filter((r) => (f.kind === "sheet" ? r.source?.file_hash === f.file_hash : r.source?.deck_id === f.deck_id));

/** The register narrowed to one file: its rows of the three tables, their counts, and the open cards of its cells. */
function narrowed(view, f) {
  const tables = Object.fromEntries(Object.entries(view.tables).map(([k, rows]) => [k, rowsOf(rows, f)]));
  const cards = view.cards.filter((c) => f.kind === "sheet" && c.source?.file_hash === f.file_hash);
  return { ...view, tables, counts: Object.fromEntries(Object.entries(tables).map(([k, rows]) => [k, rows.length])), cards };
}

export default function ReadingScreen({ audit, setAudit, reloadKey = 0 }) {
  const [data, setData] = useState(null);
  const [confirmedOpen, setConfirmedOpen] = useState(false);
  const [tab, setTab] = useState("all");
  const auditId = audit.id;
  const load = useCallback(() => getReading(auditId).then(setData).catch(() => setData(EMPTY)), [auditId]);
  useEffect(() => { load(); }, [load, reloadKey]);
  const reloadAudit = async () => { try { setAudit(await getAudit(auditId)); } catch (e) { /* the page keeps what it has */ } };
  const onAsOf = async (text) => {
    const next = parseMonthYear(text);
    if (!next) { toast.error("As-of month must be a month and year, e.g. Jun 2021"); return false; }
    try { await updateAudit(auditId, { as_of_month: next }); await reloadAudit(); load(); return true; }
    catch (e) { toast.error(`As-of month could not be saved: ${describeRequestError(e).message}`); return false; }
  };
  const onSetting = async (field, patch, success) => {
    try { await updateAudit(auditId, patch); await reloadAudit(); load(); if (success) toast.success(success); return true; }
    catch (e) { toast.error(`${SETUP_LABELS[field]} could not be saved: ${describeRequestError(e).message}`); return false; }
  };
  const view = data || EMPTY;
  const current = view.files.find((f) => fileKey(f) === tab);
  const results = current ? narrowed(view, current) : view;
  const changed = () => { load(); reloadAudit(); };
  // The Uncertain list is the All section's (brief of George, 2026-11-05): "Review →" above Run audit opens it.
  useEffect(() => {
    const open = () => { setTab("all"); setTimeout(() => document.getElementById("uncertain-list")?.scrollIntoView?.({ behavior: "smooth" }), 0); };
    window.addEventListener(OPEN_UNCERTAIN, open);
    return () => window.removeEventListener(OPEN_UNCERTAIN, open);
  }, []);
  const uncertain = current ? undefined : uncertainEntries(view.files);
  const pick = async (entry, which) => {
    try {
      if (entry.kind === "deck") await answerCorrection(auditId, entry.figure.id, { index: entry.figure.reading.index, action: "choose", option: which === "first" ? 0 : 1 });
      else await decideUncertain(auditId, entry.fileHash, { key: entry.item.key, pick: which });
      changed();
    } catch (e) { toast.error(e.response?.data?.detail || "The choice could not be saved."); }
  };
  const stopped = view.review?.stopped;
  return (
    <div className="reading" data-testid="reading-screen">
      <h1 className="section" data-testid="results-heading">Check results</h1>
      <p className="lead" data-testid="results-lead">{LEAD}</p>
      <SettingsBlocks audit={audit} files={view.files} period={view.period} onAsOf={onAsOf} onChange={changed} onSetting={onSetting} onFxSaved={changed} />
      <nav className="tabs" aria-label="Files" data-testid="file-tabs">
        <a href="#all" className={current ? "" : "on"} data-testid="tab-all" onClick={(e) => { e.preventDefault(); setTab("all"); }}>
          All <span>{fmtCount(view.files.reduce((n, f) => n + (f.summary?.confirmed || 0), 0))}</span>
        </a>
        {view.files.map((f) => (
          <a key={fileKey(f)} href={`#${fileKey(f)}`} className={tab === fileKey(f) ? "on" : ""} data-testid="tab-file"
            onClick={(e) => { e.preventDefault(); setTab(fileKey(f)); }}>{f.file} <span>{fmtCount(f.summary?.confirmed || 0)}</span></a>
        ))}
      </nav>
      <p className="tabnote" data-testid="tab-note">{TAB_NOTE}</p>
      {current?.kind === "sheet" && <SheetDetail file={current} auditId={auditId} onChange={changed} />}
      {current?.kind === "deck" && <DeckDetail file={current} />}
      {current?.kind === "deck" && <DeckFigures file={current} auditId={auditId} onChange={changed} />}
      {!current && stopped && (
        <p className="bad" role="alert" data-testid="review-stopped">
          Review stopped: token allowance reached after {fmtCount(stopped.reviewed)} of {fmtCount(stopped.total)} figures. Figures after that are unreviewed.
        </p>
      )}
      {!current && !stopped && view.review?.not_completed && <p className="evidence" data-testid="review-not-completed">{view.review.not_completed}</p>}
      <ReadingResults data={results} auditId={auditId} confirmedOpen={confirmedOpen} setConfirmedOpen={setConfirmedOpen} onChanged={changed} uncertain={uncertain} onPick={pick} />
    </div>
  );
}
