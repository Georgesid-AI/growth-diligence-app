import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import ReadingResults, { SourceLink } from "@/components/ReadingResults";
import { changeReading, downloadReading, getAudit, getReading, updateAudit } from "@/lib/api";
import { SETUP_LABELS, MONTHS, DEFAULT_FISCAL_YEAR_END, asOfEvidenceLine, parseMonthYear } from "@/lib/auditForm";
import { fmtBytes } from "@/lib/format";
import { monthName, periodText } from "@/lib/periods";
import { describeRequestError } from "@/lib/requestError";
import {
  EXPLAINER, FIGURE_HOVERS, FIGURE_WIDTHS, HOVERS, OUTCOME_LABELS, WIDTHS, deckSummary, lastActualText, periodLabel, sheetSummary, splitEvidence, valueText,
} from "@/lib/readingView";
import { PLACEHOLDER } from "@/lib/format";

/**
 * The audit page's reading screen (docs/design/read-check-review.md section 11; docs/design/audit-page-mockup.html; PR 3 step d): the one-sentence
 * explainer with the AI-reading tick, the assumptions strip with the as-of evidence, one block per file, and the three result tables with the
 * cards. The Run audit button is drawn at the right of the top row by RunAuditPanel (the page's `topHost`).
 */
const EMPTY = { files: [], tables: { confirmed: [], rejected: [], cannot_check: [] }, counts: { confirmed: 0, rejected: 0, cannot_check: 0 }, cards: [], review: {} };

export function ReadingTop({ audit, setAudit, host }) {
  const consent = audit.structure_reading_consent === true;
  const save = async (value) => {
    try {
      await updateAudit(audit.id, { structure_reading_consent: value });
      setAudit(await getAudit(audit.id));
    } catch (e) {
      toast.error(`${SETUP_LABELS.structure_reading_consent} could not be saved: ${describeRequestError(e).message}`);
    }
  };
  return (
    <section className="reading-top" data-testid="reading-top">
      <div>
        <p data-testid="reading-explainer">{EXPLAINER}</p>
        <label>
          <input type="checkbox" data-testid="setup-consent-checkbox" checked={consent} onChange={(e) => save(e.target.checked)} />
          <span data-testid="setup-consent-tick-label">{SETUP_LABELS.structure_reading_consent}</span>
        </label>
      </div>
      {host}
    </section>
  );
}

function InlineChange({ label, placeholder, onSave, testid, type = "text" }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  if (!open) return <a href="#change" data-testid={testid} onClick={(e) => { e.preventDefault(); setOpen(true); }}>Change</a>;
  return (
    <span>
      <input aria-label={label} type={type} placeholder={placeholder} value={value} onChange={(e) => setValue(e.target.value)} data-testid={`${testid}-input`} />
      <button type="button" className="btn quiet" data-testid={`${testid}-save`} disabled={!value.trim()}
        onClick={async () => { if (await onSave(value.trim())) { setOpen(false); setValue(""); } }}>Save</button>
    </span>
  );
}

/** The reporting period of the strip: the first and last actual month across the files; else the engine's revenue period; never "—" while an as-of month exists. */
export function reportingPeriodText(audit, period) {
  return periodText(period) || periodText(audit.datasets?.revenue?.months) || (audit.as_of_month ? monthName(audit.as_of_month) : "—");
}

export function ReadingStrip({ audit, onAsOf, period }) {
  const asOf = audit.as_of_month;
  const items = [
    ["currency", "Currency", audit.reporting_currency || "—"],
    ["period", "Reporting period", reportingPeriodText(audit, period)],
    ["fy-end", "FY end", MONTHS[(Number(audit.fiscal_year_end) || DEFAULT_FISCAL_YEAR_END) - 1]],
  ];
  const evidence = splitEvidence(asOfEvidenceLine(audit));
  return (
    <>
      <section className="strip" data-testid="assumptions-strip">
        {items.slice(0, 2).map(([key, name, value]) => <div key={key} data-testid={`assumption-${key}`}><span>{name}</span>{value}</div>)}
        <div data-testid="assumption-as-of">
          <span>As-of month</span>
          {asOf ? `${monthName(asOf)}${audit.as_of_by === "analyst" ? " (set by analyst)" : ""}` : "not determined"}{" "}
          <InlineChange label="As-of month" placeholder="Jun 2021" testid="assumptions-change" onSave={onAsOf} />
        </div>
        {items.slice(2).map(([key, name, value]) => <div key={key} data-testid={`assumption-${key}`}><span>{name}</span>{value}</div>)}
      </section>
      {(evidence.text || evidence.confirmed) && (
        <p className="evidence" data-testid="assumption-as-of-evidence">
          {evidence.text}{evidence.confirmed && <> <b>{evidence.confirmed}</b></>}
        </p>
      )}
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
            <td data-h="Read as">{ln.read_as}</td>
            <td data-h="Basis">{ln.basis}</td>
            <td data-h="Actual / plan">{ln.actual_plan}</td>
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

function SheetBlock({ file, auditId, onChanged, onAsOf }) {
  const [open, setOpen] = useState(false);
  const a = file.anchors;
  const change = async (body) => {
    try { await changeReading(auditId, file.file_hash, body); onChanged(); return true; }
    catch (e) { toast.error(e.response?.data?.detail || "The change could not be saved."); return false; }
  };
  const sheet = a.revenue_row?.sheet || a.actual_plan?.sheet || file.lines[0]?.sheet;
  return (
    <section className="file" data-testid="file-block">
      <h2>{file.file} {file.size != null && <small>{fmtBytes(file.size)}</small>}</h2>
      <Summary lines={sheetSummary(file.summary)} />
      {(file.notes || []).map((n, i) => <p key={i} className="note" data-testid="file-note">{n.name}: {n.reason}</p>)}
      <div className="anchors">
        <span className="k">Last actual</span>
        <span data-testid="anchor-as-of">{a.as_of ? `${lastActualText(a.as_of.month, file.summary.granularity)} — ${splitEvidence(a.as_of.evidence).text}` : "not determined"}</span>
        <InlineChange label="As-of month" placeholder="Jun 2021" testid="anchor-as-of-change" onSave={onAsOf} />
        <span className="k">Revenue row</span>
        <span data-testid="anchor-revenue">{a.revenue_row ? `Row ${a.revenue_row.row}, ${a.revenue_row.label}, ${a.revenue_row.basis}` : "not found"}</span>
        <InlineChange label="Revenue row" placeholder="Row number" type="number" testid="anchor-revenue-change"
          onSave={(v) => change({ what: "revenue_row", sheet, row: Number(v) })} />
        <span className="k">Actual / plan</span>
        <span data-testid="anchor-boundary">{a.actual_plan ? `Actual to column ${a.actual_plan.last_actual}, plan from ${a.actual_plan.plan_from}` : "not determined"}</span>
        <InlineChange label="Last actual column" placeholder="AP" testid="anchor-boundary-change"
          onSave={(v) => change({ what: "boundary", sheet: a.actual_plan?.sheet || sheet, column: v })} />
      </div>
      <p className="exports">
        <a href="#json" data-testid="export-json" onClick={(e) => { e.preventDefault(); downloadReading(auditId, file.file_hash, "json"); }}>Export map (JSON)</a>
        {" · "}
        <a href="#csv" data-testid="export-csv" onClick={(e) => { e.preventDefault(); downloadReading(auditId, file.file_hash, "csv"); }}>Export series (CSV)</a>
      </p>
      <details open={open} data-testid="lines-details">
        <summary onClick={(e) => { e.preventDefault(); setOpen((v) => !v); }}>{open ? "Hide all lines" : "Show all lines"}</summary>
        {file.lines.map((entry) => <LinesTable key={entry.sheet} lines={entry.lines} file={file} auditId={auditId} sheet={entry.sheet} />)}
      </details>
    </section>
  );
}

function DeckBlock({ file }) {
  return (
    <section className="file" data-testid="file-block">
      <h2>{file.file} <small>{file.pages != null ? `${file.pages} ${file.pages === 1 ? "page" : "pages"}` : ""}</small></h2>
      <Summary lines={deckSummary(file.summary, file.anchors.figures)} />
    </section>
  );
}

/** The deck tab's full figures list, in the bordered box of the lines table: every figure read from the deck, with its page and outcome. */
function DeckFigures({ file }) {
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
              <td data-h="Outcome" className="nw">{OUTCOME_LABELS[f.outcome] || f.outcome}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const TAB_NOTE = "Each tab shows the Confirmed, Rejected and Cannot check results for one file. For decks, it also lists every figure read from the deck, with its page number and outcome.";
const LEAD = "Every figure the model read, after code opened its cell or page and compared the value. Three tables: Confirmed, Rejected, Cannot check.";
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
  const view = data || EMPTY;
  const current = view.files.find((f) => fileKey(f) === tab);
  const shown = current ? [current] : view.files;
  const results = current ? narrowed(view, current) : view;
  const changed = () => { load(); reloadAudit(); };
  const block = (f) => (f.kind === "sheet"
    ? <SheetBlock key={f.file_hash} file={f} auditId={auditId} onChanged={changed} onAsOf={onAsOf} />
    : <DeckBlock key={f.deck_id} file={f} />);
  return (
    <div className="reading" data-testid="reading-screen">
      <h1 className="section" data-testid="results-heading">Check results</h1>
      <p className="lead" data-testid="results-lead">{LEAD}</p>
      <nav className="tabs" aria-label="Files" data-testid="file-tabs">
        <a href="#all" className={current ? "" : "on"} data-testid="tab-all" onClick={(e) => { e.preventDefault(); setTab("all"); }}>
          All <span>{view.files.reduce((n, f) => n + (f.summary?.confirmed || 0), 0)}</span>
        </a>
        {view.files.map((f) => (
          <a key={fileKey(f)} href={`#${fileKey(f)}`} className={tab === fileKey(f) ? "on" : ""} data-testid="tab-file"
            onClick={(e) => { e.preventDefault(); setTab(fileKey(f)); }}>{f.file} <span>{f.summary?.confirmed || 0}</span></a>
        ))}
      </nav>
      <p className="tabnote" data-testid="tab-note">{TAB_NOTE}</p>
      {!current && <ReadingStrip audit={audit} onAsOf={onAsOf} period={view.period} />}
      {shown.map(block)}
      {current?.kind === "deck" && <DeckFigures file={current} />}
      {!current && view.review?.not_completed && <p className="evidence" data-testid="review-not-completed">{view.review.not_completed}</p>}
      <ReadingResults data={results} auditId={auditId} confirmedOpen={confirmedOpen} setConfirmedOpen={setConfirmedOpen} onChanged={changed} />
    </div>
  );
}
