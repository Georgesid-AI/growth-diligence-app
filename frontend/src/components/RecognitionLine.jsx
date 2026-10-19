import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  TYPE_LABELS, TYPE_SOURCE_TEXT, TYPE_REASON_TEXT, TYPE_CHOOSE, REASON_TEXT, MONTH_REASON_TEXT, CONFIRM_ONLY, TURNOVER_QUESTION,
  supportsText, rowText, rowChoice, monthText, claimsText, currencyChoices, CURRENCY_NOT_FOUND, TABLES_TEXT, sourceText, SOURCE_CHOICES,
} from "@/lib/recognition";

const SMALL = "h-6 px-2 ml-1.5";

/**
 * The recognition of a revenue file under its bubble head (docs/specs/revenue-file-recognition.md section 7, S31a-S31k): the type with
 * how it was found, what the file supports and blocks, the revenue row, the last actual month, the currency, the other sheets and the
 * rows kept out of revenue. The component renders the `recognition` block of the dataset view; every decision goes through
 * `decide(view, body)`, which sends one part at a time and hands back the dataset view. It never shows a confidence or a cost.
 */
export default function RecognitionLine({ view, decide, reportingCurrency }) {
  const rec = view.recognition;
  const d = view.dtype;
  const id = (name) => `recognition-${name}-${d}`;
  const [open, setOpen] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  if (!rec) return null;
  if (!rec.recognised) {
    return <div className="mt-1 text-xs text-slate-700" data-testid={`recognition-${d}`}><p data-testid={id("message")}>{rec.message}</p></div>;
  }

  const send = async (body) => {
    setBusy(true);
    setError(null);
    try {
      await decide(view, body);
      setOpen({});
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "The choice could not be saved.");
    } finally {
      setBusy(false);
    }
  };
  const toggle = (key) => setOpen((o) => ({ ...o, [key]: !o[key] }));
  const select = (testid, options, onPick, placeholder = "Choose") => (
    <select data-testid={testid} disabled={busy} defaultValue="" onChange={(e) => e.target.value && onPick(e.target.value)}
      className="ml-1.5 h-6 border border-[#D1D5DB] rounded bg-white text-xs">
      <option value="">{placeholder}</option>
      {options}
    </select>
  );

  // S31a: the type
  const unclassed = rec.file_type == null;
  const typeText = unclassed ? TYPE_CHOOSE
    : `Type: ${TYPE_LABELS[rec.file_type]} (${TYPE_SOURCE_TEXT[rec.type_source] || TYPE_SOURCE_TEXT.rules})`
      + (rec.type_state === "click" && TYPE_REASON_TEXT[rec.type_reason] ? `. ${TYPE_REASON_TEXT[rec.type_reason]}` : "");
  const typeOptions = (unclassed ? rec.type_candidates : Object.keys(TYPE_LABELS).filter((t) => t !== rec.file_type))
    .map((t) => <option key={t} value={t}>{TYPE_LABELS[t]}</option>);
  const pickType = (t) => send({ action: "change", part: "file_type", file_type: t });

  // S31c / S31d: the revenue row and the last actual month
  const row = rec.revenue_row || rec.revenue_column;
  const last = rec.last_actual;
  const rowKey = rec.revenue_column ? "column" : "row";
  const rowWaitsConfirm = row && row.state === "click" && CONFIRM_ONLY.includes(row.reason);
  const rowNeedsChoice = row && row.state === "click" && !CONFIRM_ONLY.includes(row.reason) && row.reason !== "turnover_question";
  const lastWaitsConfirm = last && last.state === "click" && CONFIRM_ONLY.includes(last.reason);
  const lastNeedsChoice = last && last.state === "click" && !CONFIRM_ONLY.includes(last.reason);
  const lastKey = (c) => c.column ?? c.row;
  const rowLine = rowNeedsChoice ? `Revenue row: choose the row. ${REASON_TEXT[row.reason] || ""}`.trim()
    : rowWaitsConfirm ? `${rowText(row)}. ${REASON_TEXT[row.reason]}` : row ? rowText(row) : null;
  const base = last && last.month ? `Last actual month: ${monthText(last.month)}.${(rec.excluded_columns || []).length > 0 ? " Columns after it are not used." : ""}` : null;
  const lastLine = lastNeedsChoice ? `Last actual month: choose the month. ${MONTH_REASON_TEXT[last.reason] || ""}`.trim()
    : lastWaitsConfirm ? `${base} ${MONTH_REASON_TEXT[last.reason]}` : base;

  const rowSelect = row && (rowNeedsChoice || open.row) && select(id("row-select"),
    row.candidates.map((c) => <option key={c[rowKey]} value={c[rowKey]}>{rowChoice(c)}</option>),
    (v) => send({ action: "change", part: "revenue_row", row: Number(v) }));
  const lastSelect = last && (lastNeedsChoice || open.last) && select(id("last-select"),
    last.candidates.map((c) => <option key={lastKey(c)} value={lastKey(c)}>{monthText(c.month)}</option>),
    (v) => send({ action: "change", part: "last_actual", column: Number(v) }));

  // S31k: the currency; the codes are shown as the option label so the line reads no code but the file's own
  const currency = rec.currency || {};
  const others = rec.other_sheets || [];
  const claims = claimsText(rec.non_revenue_rows);
  const asked = rec.money_kind && rec.money_kind.asked && !rec.money_kind.answer;

  return (
    <div className="mt-1 text-xs text-slate-700 space-y-1" data-testid={`recognition-${d}`}>
      <div>
        <span data-testid={id("type")}>{typeText}</span>
        {!unclassed && <button type="button" data-testid={id("type-change")} onClick={() => toggle("type")} className="ml-2 underline hover:text-slate-900">Change</button>}
        {!unclassed && rec.type_state === "click" && (
          <Button size="sm" variant="outline" disabled={busy} data-testid={id("type-correct")} className={SMALL}
            onClick={() => send({ action: "confirm", part: "file_type" })}>Correct</Button>)}
        {(unclassed || open.type) && select(id("type-select"), typeOptions, pickType)}
      </div>
      {rec.file_type && rec.supports && rec.supports.length > 0 && <p data-testid={id("supports")}>{supportsText(rec)}</p>}
      {rec.series_source && (rec.tables || []).length > 1 && (
        <div>
          <p data-testid={id("tables")}>{TABLES_TEXT}</p>
          <span data-testid={id("source")}>{sourceText(rec.series_source)}</span>
          {(rec.series_source.state === "click" || rec.series_source.cross_check.status === "mismatch") &&
            Object.entries(SOURCE_CHOICES).map(([supplier, label]) => (
              <Button key={supplier} size="sm" variant="outline" disabled={busy || (rec.series_source.state === "you" && rec.series_source.supplier === supplier)}
                data-testid={`${id("source")}-${supplier}`} className={SMALL}
                onClick={() => send({ action: "change", part: "series_source", series_source: supplier })}>{label}</Button>))}
        </div>
      )}
      {row && (
        <div>
          <span data-testid={id("row")}>{rowLine}</span>
          {row.state === "auto" && (
            <Button size="sm" variant="outline" disabled={busy} data-testid={id("row-correct")} className={SMALL}
              onClick={() => send({ action: "confirm", part: "revenue_row" })}>Correct</Button>)}
          {!rowNeedsChoice && <button type="button" data-testid={id("row-change")} onClick={() => toggle("row")} className="ml-2 underline hover:text-slate-900">Change</button>}
          {rowSelect}
        </div>
      )}
      {asked && (
        <div data-testid={id("money-kind")}>
          {TURNOVER_QUESTION}
          <Button size="sm" variant="outline" disabled={busy} data-testid={`${id("money-kind")}-revenue`} className={SMALL}
            onClick={() => send({ action: "change", part: "money_kind", money_kind: "revenue" })}>Revenue</Button>
          <Button size="sm" variant="outline" disabled={busy} data-testid={`${id("money-kind")}-volume`} className={SMALL}
            onClick={() => send({ action: "change", part: "money_kind", money_kind: "volume" })}>Volume</Button>
        </div>
      )}
      {last && lastLine && (
        <div>
          <span data-testid={id("last")}>{lastLine}</span>
          {last.state === "auto" && (
            <Button size="sm" variant="outline" disabled={busy} data-testid={id("last-correct")} className={SMALL}
              onClick={() => send({ action: "confirm", part: "last_actual" })}>Correct</Button>)}
          {!lastNeedsChoice && <button type="button" data-testid={id("last-change")} onClick={() => toggle("last")} className="ml-2 underline hover:text-slate-900">Change</button>}
          {lastSelect}
        </div>
      )}
      {(rowWaitsConfirm || lastWaitsConfirm) && (
        <div>
          <Button size="sm" variant="outline" disabled={busy} data-testid={id("correct")} className="h-6 px-2"
            onClick={() => send({ action: "confirm", part: "pending" })}>Correct</Button>
        </div>
      )}
      {currency.state === "confirm" ? (
        <div data-testid={id("currency")}>
          {CURRENCY_NOT_FOUND}
          <select data-testid={id("currency-select")} disabled={busy} defaultValue=""
            onChange={(e) => e.target.value && send({ action: "change", part: "currency", currency: e.target.value })}
            className="ml-1.5 h-6 border border-[#D1D5DB] rounded bg-white text-xs">
            <option value="">Choose</option>
            {currencyChoices(reportingCurrency).map((c) => <option key={c} value={c} label={c} />)}
          </select>
        </div>
      ) : currency.code ? <p data-testid={id("currency")}>{`Currency: ${currency.code}`}</p> : null}
      {others.length > 0 && (
        <div data-testid={id("others")}>
          Other sheets in this file:{" "}
          {others.map((o, i) => (
            <span key={o.sheet}>{i > 0 && "; "}{o.sheet} ({TYPE_LABELS[o.file_type] || "type to choose"}){" "}
              <Button size="sm" variant="outline" disabled={busy} data-testid={`recognition-use-sheet-${d}-${o.sheet}`} className="h-6 px-2"
                onClick={() => send({ action: "change", part: "sheet", sheet: o.sheet })}>Use this sheet</Button></span>
          ))}
        </div>
      )}
      {claims && <p data-testid={id("claims")}>{claims}</p>}
      {error && <p className="text-rose-700" data-testid={id("error")}>{error}</p>}
    </div>
  );
}
