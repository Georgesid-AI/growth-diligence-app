import { useCallback, useEffect, useRef, useState } from "react";
import { Paperclip, FileSpreadsheet, FileText, Loader2, ChevronRight, ChevronDown, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { BLOCKERS_CHANGED } from "@/components/BlockerBanner";
import SheetMap from "@/components/SheetMap";
import RecognitionLine from "@/components/RecognitionLine";
import { uploadChatFile, getDatasets, decideColumns, decideLines, decideRecognition, reportUsage, changeDatasetType, confirmForecastClaims } from "@/lib/api";
import {
  S2_EXPLAINER_CONSENT, S3_EXPLAINER_NO_CONSENT, S4_DROP_ZONE_LEAD, S4_DROP_ZONE_BOLD, S6_UNKNOWN_TYPE, S7_REFUSED, S7B_XLS_REFUSED, S12_MODEL_FAILED, S_UPLOAD_RETRY,
  S20_NOTE_PLACEHOLDER, S21_NOTE_REFUSED, NOTE_MAX, ALLOWED_EXTENSIONS, REASONS, TYPE_LABELS, S5_head, S8_replace,
  S9_confidence, S13_status, S13_READY, S26_type, S26_CHANGE, S26_sheet, S27_miss, S27_SHOW_COLUMNS, S28_read, S28_SHOW_CLAIMS, S28_cap, S28_CONFIRM,
  forecastValueText, forecastCells, MAP_LABEL, CALCULATE_CLASS, ALL_CONFIRMED_LINE, mappingComplete, setCalculatePressed, S14_same, MAPPING_HEADERS, S25_TITLE, S25_PARAGRAPHS, S25_STATEMENT_PARAGRAPHS, S29_TITLE, S29_PARAGRAPHS, mappedBy, sortColumns, fieldName, fmtBytes, extensionOf, heldFields,
} from "@/lib/chatUpload";

const NONE = "";
const AI_FAILED = ["timeout", "not_read", "refused", "stopped", "too_large"];
let nextId = 1;
const uid = () => `m${nextId++}`;

/**
 * The chat-style upload (docs/specs/chat-upload.md section 2): one message list, files in, one analyst bubble and one
 * system bubble per file, the mapping table in the system bubble. The bar below holds the paperclip and Map; there is no text
 * field. `extras(view)` renders what follows the table of a revenue file (FX rates, billing terms).
 *
 * `onFiles(files)` hands the attached files up; the page's Run audit reads them and then passes `leftover` (the files it did not
 * send): the bubbles of every other file are dropped, and the stored files are read again.
 */
export default function UploadChat({ audit, extras, onViews, onStaged, onMapping, mapButton, onFiles, leftover }) {
  const [messages, setMessages] = useState([]);
  const [decided, setDecided] = useState(false);          // the analyst confirmed or corrected a column on this page
  const [busy, setBusy] = useState(0);
  const [dragging, setDragging] = useState(false);
  const staged = useRef(new Map());                   // bubble id -> File: attached, not yet read (nothing runs until Map)
  const openPrompts = useRef(new Set());              // bubbles whose file waits for a type or a replace answer
  const [mapping, setMapping] = useState(false);
  const mappingRef = useRef(false);
  const [lastReason, setLastReason] = useState("header_misleading");   // stays for the next correction on this page
  const picker = useRef(null);
  const queue = useRef(Promise.resolve());
  const consent = audit.structure_reading_consent === true;
  const views = messages.filter((m) => m.kind === "system" && m.view).map((m) => m.view);
  const allConfirmed = decided && mappingComplete({ attached: messages.filter((m) => m.staged).length, views });   // after the last open column
  const firstTable = messages.find((m) => m.kind === "system" && m.view)?.id;       // the info box sits above the first table

  const push = useCallback((m) => setMessages((all) => [...all, { id: uid(), ...m }]), []);
  const announce = () => window.dispatchEvent(new Event(BLOCKERS_CHANGED));

  // On reload: one analyst bubble and one system bubble per stored dataset. Text replies and refused files are not kept.
  useEffect(() => {
    getDatasets(audit.id).then((views) => {
      setMessages(views.flatMap((v) => [
        { id: uid(), kind: "analyst", dtype: v.dtype, file: v.file, size: v.size_bytes, ext: v.ext },
        { id: uid(), kind: "system", dtype: v.dtype, view: v },
      ]));
    }).catch(() => {});
  }, [audit.id]); // eslint-disable-line

  useEffect(() => {
    onViews?.(messages.filter((m) => m.kind === "system" && m.view).map((m) => m.view));
  }, [messages]); // eslint-disable-line

  // `bubble` is the id of the analyst bubble the file already has (it shows a spinner until the file is read).
  // `quiet`: the caller refreshes the blocker banner itself once, after the last file (Map does).
  const send = async (file, options = {}, bubble = null, quiet = false) => {
    setBusy((n) => n + 1);
    const settle = (patch) => setMessages((all) => all.map((m) => (m.id === bubble ? { ...m, pending: false, ...patch } : m)));
    try {
      const res = await uploadChatFile(audit.id, file, options);
      if (res.status === "unknown_type") {
        settle({});
        if (bubble) openPrompts.current.add(bubble);
        push({ kind: "unknown", file, bubble });
      } else {
        if (bubble) openPrompts.current.delete(bubble);
        // A file of a loaded type replaces that type's bubbles: one analyst and one system bubble per file.
        setMessages((all) => {
          const kept = all.filter((m) => !(m.dtype === res.dtype && m.kind !== "text") && m.id !== bubble);
          const analyst = { id: bubble || uid(), kind: "analyst", dtype: res.dtype, file: res.file, size: res.size_bytes ?? file.size, ext: res.ext };
          return [...kept, analyst, { id: uid(), kind: "system", dtype: res.dtype, view: res }];
        });
        // An answer to a type or replace prompt (Map was pressed to get here): the flag is set once nothing else waits,
        // so "Revenue file missing" shows without a second press.
        if (!quiet) { if (openPrompts.current.size === 0) setCalculatePressed(audit.id); announce(); }
      }
    } catch (err) {
      settle({});
      const detail = err.response?.data?.detail;
      if (err.response?.status === 409 && detail?.code === "type_loaded") {
        if (bubble) openPrompts.current.add(bubble);
        push({ kind: "replace", file, dtype: detail.dtype, loaded: detail.file, bubble });
      } else if (!err.response && bubble) {
        // No answer (timeout or network error): the file goes back to "attached", so Map sends it again.
        openPrompts.current.delete(bubble);
        staged.current.set(bubble, file);
        settle({ staged: true });
        push({ kind: "text", role: "system", text: S_UPLOAD_RETRY });
      } else {
        push({ kind: "text", role: "system", text: typeof detail === "string" ? detail : "The file could not be read." });
      }
    } finally {
      setBusy((n) => n - 1);
    }
  };

  // Files go one at a time, in drop order.
  const takeFiles = (files) => {
    for (const file of Array.from(files || [])) {
      const ext = extensionOf(file.name);
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        push({ kind: "analyst", file: file.name, size: file.size, ext });
        push({ kind: "text", role: "system", text: ext === "xls" ? S7B_XLS_REFUSED : S7_REFUSED });
        reportUsage(audit.id, { rejected_extension: ext || "other" });
        continue;
      }
      const bubble = uid();
      staged.current.set(bubble, file);
      setMessages((all) => [...all, { id: bubble, kind: "analyst", file: file.name, size: file.size, ext, staged: true }]);
    }
  };

  const unstage = (id) => {
    staged.current.delete(id);
    setMessages((all) => all.filter((m) => m.id !== id));
  };
  useEffect(() => { onStaged?.(messages.filter((m) => m.staged).length); }, [messages]); // eslint-disable-line
  useEffect(() => { onFiles?.([...staged.current.values()]); }, [messages]); // eslint-disable-line

  // The page has read the files: only those it did not send stay attached. On the Upload & Mapping page the files it sent are now
  // stored, so the stored bubbles are read again beside the ones still attached.
  useEffect(() => {
    if (!leftover) return;
    for (const [bubble, file] of [...staged.current]) if (!leftover.includes(file)) staged.current.delete(bubble);
    setMessages((all) => all.filter((m) => !m.staged || staged.current.has(m.id)));
    getDatasets(audit.id).then((views) => setMessages((all) => [
      ...views.flatMap((v) => [
        { id: uid(), kind: "analyst", dtype: v.dtype, file: v.file, size: v.size_bytes, ext: v.ext },
        { id: uid(), kind: "system", dtype: v.dtype, view: v },
      ]),
      ...all.filter((m) => m.staged),
    ])).catch(() => {});
  }, [leftover]); // eslint-disable-line

  // Map: read the attached files one at a time, in drop order; each loads with its mapping table and confirmation list.
  // The banner is refreshed once, after the last file, and not while a file still waits for its type or a replace answer:
  // "Revenue file missing" would then show while that file is being asked about. Computing is Run audit's job, not this one's.
  const map = async () => {
    if (mappingRef.current) return;                     // a second press while files are being read does nothing
    mappingRef.current = true;
    setMapping(true);
    onMapping?.(true);
    try {
      for (const [bubble, file] of [...staged.current]) {
        staged.current.delete(bubble);
        setMessages((all) => all.map((m) => (m.id === bubble ? { ...m, staged: false, pending: true } : m)));
        queue.current = queue.current.then(() => send(file, {}, bubble, true));
        await queue.current;
      }
      if (openPrompts.current.size === 0) { setCalculatePressed(audit.id); announce(); }
    } finally {
      mappingRef.current = false;
      setMapping(false);
      onMapping?.(false);
    }
  };

  // After Save claims the stored file is read as claims (chat-upload.md section 20): its view is read again, so its status line
  // follows the server.
  const claimsSaved = async (view) => {
    const fresh = (await getDatasets(audit.id).catch(() => [])).find((v) => v.dtype === view.dtype);
    if (fresh) setMessages((all) => all.map((m) => (m.kind === "system" && m.dtype === view.dtype ? { ...m, view: fresh } : m)));
    announce();
  };

  // A statement file's lines (section 26.7): the same refresh as a column decision.
  const decideSheetLines = async (view, decisions) => {
    const next = await decideLines(audit.id, view.dtype, decisions);
    setDecided(true);
    setMessages((all) => all.map((m) => (m.kind === "system" && m.dtype === view.dtype ? { ...m, view: next } : m)));
    announce();
    return next;
  };

  const decide = async (view, decisions) => {
    const next = await decideColumns(audit.id, view.dtype, decisions);
    setDecided(true);
    setMessages((all) => all.map((m) => (m.kind === "system" && m.dtype === view.dtype ? { ...m, view: next } : m)));
    announce();
    return next;
  };

  // One decision about the recognition of a file (revenue-file-recognition.md section 6.6): the server answers the dataset view.
  const decideRecognitionPart = async (view, body) => {
    const next = await decideRecognition(audit.id, view.dtype, body);
    setMessages((all) => all.map((m) => (m.kind === "system" && m.dtype === view.dtype ? { ...m, view: next } : m)));
    announce();
    return next;
  };

  // The analyst changes the type a stored file was read as: the stored sheet is read again as the new type.
  const retype = async (view, to, replace = false) => {
    const next = await changeDatasetType(audit.id, view.dtype, to, replace);
    setMessages((all) => all.filter((m) => !(m.dtype === next.dtype && m.dtype !== view.dtype && m.kind !== "text"))
      .map((m) => (m.dtype === view.dtype && m.kind !== "text"
        ? (m.kind === "system" ? { ...m, dtype: next.dtype, view: next } : { ...m, dtype: next.dtype })
        : m)));
    announce();
    return next;
  };

  return (
    <section
      data-testid="upload-chat"
      className="bg-white border border-[#E5E7EB] rounded-lg flex flex-col"
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); takeFiles(e.dataTransfer?.files); }}
    >
      <p data-testid="chat-explainer" className="px-5 pt-4 text-xs text-slate-600">
        {consent ? S2_EXPLAINER_CONSENT : S3_EXPLAINER_NO_CONSENT}
      </p>
      <div data-testid="chat-messages" className="px-5 py-4 space-y-3 min-h-[240px]">
        {/* The drop zone stays after a drop: more files can be attached until Map is pressed. */}
        <div data-testid="chat-drop-zone" className={`border border-dashed rounded-lg text-center text-slate-500 ${messages.length === 0 ? "py-14 text-sm" : "py-3 text-xs"} ${dragging ? "border-sky-500 bg-sky-50" : "border-[#D1D5DB]"}`}>
          {S4_DROP_ZONE_LEAD}<strong>{S4_DROP_ZONE_BOLD}</strong>
        </div>
        {messages.map((m) => (
          <Message key={m.id} m={m} audit={audit} unstage={unstage} extras={extras} lastReason={lastReason} setLastReason={setLastReason}
            decide={decide} decideLines={decideSheetLines} decideRecognition={decideRecognitionPart} retype={retype} claimsSaved={claimsSaved} showInfo={m.id === firstTable}
            onType={(file, dtype) => { setMessages((all) => all.filter((x) => x.id !== m.id)); send(file, { dtype }, m.bubble); }}
            onReplace={(file, dtype) => { setMessages((all) => all.filter((x) => x.id !== m.id)); send(file, { dtype, replace: true }, m.bubble); }}
            onKeep={() => { openPrompts.current.delete(m.bubble); setMessages((all) => all.filter((x) => x.id !== m.id && x.id !== m.bubble)); }} />
        ))}
        {busy > 0 && <div className="text-xs text-slate-500 flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Reading…</div>}
        {allConfirmed && <p className="text-xs text-emerald-700" data-testid="all-confirmed">{ALL_CONFIRMED_LINE}</p>}
      </div>
      <div className="border-t border-[#E5E7EB] px-3 py-3 flex items-center gap-2">
        <input ref={picker} type="file" multiple accept={ALLOWED_EXTENSIONS.map((e) => `.${e}`).join(",")} className="hidden" data-testid="chat-file-input"
          onChange={(e) => { takeFiles(e.target.files); e.target.value = ""; }} />
        <button type="button" aria-label="Attach files" data-testid="chat-paperclip" onClick={() => picker.current?.click()}
          className="p-2 rounded-md text-slate-600 hover:bg-slate-100"><Paperclip className="h-4 w-4" /></button>
        {/* A disabled button shows no tooltip of its own, so the wrapper carries it. */}
        <span title={mapButton.tooltip} data-testid="chat-map-wrap">
          <Button type="button" size="sm" data-testid="chat-map" disabled={mapButton.disabled} onClick={map}
            className={CALCULATE_CLASS} title={mapButton.tooltip}>
            {mapping ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{MAP_LABEL}
          </Button>
        </span>
      </div>
    </section>
  );
}

function Message({ m, audit, unstage, extras, lastReason, setLastReason, decide, decideLines, decideRecognition, retype, claimsSaved, showInfo, onType, onReplace, onKeep }) {
  if (m.kind === "analyst") return <AnalystBubble m={m} unstage={unstage} />;
  if (m.kind === "text") {
    return <Bubble side="left" testid="chat-text-system">{m.text}</Bubble>;
  }
  if (m.kind === "unknown") {
    return (
      <Bubble side="left" testid="chat-unknown">
        <p>{S6_UNKNOWN_TYPE}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {Object.entries(TYPE_LABELS).map(([dtype, label]) => (
            <Button key={dtype} size="sm" variant="outline" data-testid={`pick-type-${dtype}`} onClick={() => onType(m.file, dtype)}>{label}</Button>
          ))}
        </div>
      </Bubble>
    );
  }
  if (m.kind === "replace") {
    return (
      <Bubble side="left" testid="chat-replace">
        <p>{S8_replace(m.dtype, m.loaded)}</p>
        <div className="mt-2 flex gap-2">
          <Button size="sm" data-testid="replace-yes" onClick={() => onReplace(m.file, m.dtype)} className="bg-sky-600 hover:bg-sky-500">Replace</Button>
          <Button size="sm" variant="outline" data-testid="replace-no" onClick={onKeep}>Keep current</Button>
        </div>
      </Bubble>
    );
  }
  return <SystemBubble view={m.view} audit={audit} extras={extras} lastReason={lastReason} setLastReason={setLastReason} decide={decide}
    decideLines={decideLines} decideRecognition={decideRecognition} retype={retype}
    claimsSaved={claimsSaved} showInfo={showInfo} />;
}

function Bubble({ side, children, testid }) {
  return (
    <div className={`flex ${side === "right" ? "justify-end" : "justify-start"}`}>
      <div data-testid={testid} className={`max-w-[860px] rounded-lg px-4 py-2.5 text-sm ${side === "right" ? "bg-sky-50 text-slate-900" : "bg-slate-50 text-slate-800 border border-[#E5E7EB]"}`}>{children}</div>
    </div>
  );
}

function AnalystBubble({ m, unstage }) {
  const Icon = m.ext === "csv" ? FileText : FileSpreadsheet;
  return (
    <Bubble side="right" testid="chat-analyst-bubble">
      <span className="inline-flex items-center gap-2"><Icon className="h-4 w-4 text-slate-600" data-testid={`type-icon-${m.ext}`} />
        <span className="font-mono text-xs">{m.file}</span><span className="text-xs text-slate-500">{fmtBytes(m.size)}</span>
        {m.pending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {m.staged && (
          <>
            <span className="text-[10px] font-mono text-slate-500" data-testid="attachment-note">attached – not read yet</span>
            <button type="button" aria-label={`Remove ${m.file}`} data-testid={`unstage-${m.file}`} onClick={() => unstage(m.id)}
              className="text-slate-500 hover:text-rose-700"><X className="h-3.5 w-3.5" /></button>
          </>
        )}</span>
    </Bubble>
  );
}

function SystemBubble({ view, audit, extras, lastReason, setLastReason, decide, decideLines, decideRecognition, retype, claimsSaved, showInfo }) {
  const [openUnused, setOpenUnused] = useState(false);
  const [showColumns, setShowColumns] = useState(false);       // a miss hides the rows behind its message until asked
  const shown = sortColumns(view.columns.filter((c) => c.state !== "unused"));
  const unused = view.columns.filter((c) => c.state === "unused");
  const missed = !!view.miss && !showColumns;
  const modelFailed = AI_FAILED.includes(view.ai_reading?.status);
  const status = S13_status(view);
  const props = { view, decide, lastReason, setLastReason };
  return (
    <Bubble side="left" testid={`chat-system-${view.dtype}`}>
      <div className="font-medium text-slate-900" data-testid="bubble-head">{S5_head(view)}</div>
      {!view.recognition_only && <TypeLine view={view} retype={retype} />}
      <RecognitionLine view={view} decide={decideRecognition} reportingCurrency={audit.reporting_currency} />
      {view.unit_note && <p className="text-xs text-slate-600 mt-1" data-testid="bubble-units">{view.unit_note}</p>}
      {view.status === "same_file" && view.version != null && (
        <p className="text-xs text-slate-600 mt-1" data-testid="bubble-same">{S14_same(view.version)}</p>
      )}
      {modelFailed && <p className="text-xs text-amber-700 mt-1" data-testid="bubble-ai-failed">{S12_MODEL_FAILED}</p>}
      {showInfo && <WhyThisMatters statement={!!view.sheet_map} />}
      {view.dtype === "crm" && <CrmFieldsHelp />}
      {view.sheet_map && <SheetMap view={view} decideLines={decideLines} />}
      {!view.sheet_map && !view.recognition_only && <div className="overflow-x-auto mt-3">
        <table className="w-full text-xs" data-testid={`mapping-table-${view.dtype}`}>
          {view.sheet && <caption className="text-left text-slate-500 pb-1" data-testid={`mapping-sheet-${view.dtype}`}>{S26_sheet(view)}</caption>}
          <thead>
            <tr className="text-left text-slate-500 border-b border-[#E5E7EB]">
              {MAPPING_HEADERS.map((h, i) => <th key={i} className="py-1.5 pr-3 font-medium">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {missed && (
              <tr>
                <td colSpan={5} className="py-2" data-testid={`mapping-miss-${view.dtype}`}>
                  <p className="text-slate-800">{S27_miss(view)}</p>
                  <button type="button" data-testid={`miss-show-${view.dtype}`} onClick={() => setShowColumns(true)}
                    className="mt-1 text-slate-600 hover:text-slate-900 underline">{S27_SHOW_COLUMNS}</button>
                </td>
              </tr>
            )}
            {!missed && shown.map((c) => <ColumnRow key={c.column} row={c} {...props} />)}
            {!missed && unused.length > 0 && (
              <tr>
                <td colSpan={5} className="pt-2">
                  <button type="button" data-testid={`unused-toggle-${view.dtype}`} aria-expanded={openUnused}
                    onClick={() => setOpenUnused((v) => !v)} className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900">
                    {openUnused ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />} Not used ({unused.length})
                  </button>
                </td>
              </tr>
            )}
            {!missed && openUnused && unused.map((c) => <ColumnRow key={c.column} row={c} {...props} />)}
          </tbody>
        </table>
      </div>}
      {view.forecast_claims && !view.read_as_claims && (
        <ForecastClaims key={`${view.file}:${view.uploaded_at}`} view={view} auditId={audit.id} onSaved={() => claimsSaved?.(view)} />)}
      {view.dtype === "revenue" && !view.recognition_only && extras?.(view)}
      <div className={`mt-3 text-xs font-mono ${status === S13_READY || view.read_as_claims ? "text-emerald-700" : "text-amber-700"}`} data-testid={`status-${view.dtype}`}>
        {status}
      </div>
    </Bubble>
  );
}

/** A forecast table read as claims (chat-upload.md section 20): S28a and, over the cap, S28b; "Show claims" lists the lines, each with a
 *  checkbox, ticked; Save claims saves the ticked lines (the server reads their values again), and the file's view is read again: it is
 *  then read as claims, its status line says S28d and this block is gone. Nothing is saved before Save claims; an unticked line is dropped,
 *  and with none ticked the button is off. */
function ForecastClaims({ view, auditId, onSaved }) {
  const found = view.forecast_claims;
  const [open, setOpen] = useState(false);
  const [ticked, setTicked] = useState(() => new Set(found.lines.map((line) => line.row)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const id = view.dtype;
  const toggle = (row) => setTicked((before) => {
    const next = new Set(before);
    if (next.has(row)) next.delete(row); else next.add(row);
    return next;
  });
  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await confirmForecastClaims(auditId, id, found.lines.filter((line) => ticked.has(line.row)).map((line) => line.row));
      await onSaved();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "The claims could not be saved.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mt-2 text-xs text-slate-700" data-testid={`forecast-claims-${id}`}>
      <p>
        <span data-testid={`forecast-read-${id}`}>{S28_read(found)}</span>
        <button type="button" data-testid={`forecast-show-${id}`} aria-expanded={open} onClick={() => setOpen((v) => !v)}
          className="ml-2 text-slate-600 hover:text-slate-900 underline">{S28_SHOW_CLAIMS}</button>
      </p>
      {found.capped && <p className="mt-1 text-amber-700" data-testid={`forecast-cap-${id}`}>{S28_cap(found)}</p>}
      {open && (
        <div className="mt-2" data-testid={`forecast-list-${id}`}>
          <ul className="space-y-1">
            {found.lines.map((line) => (
              <li key={line.row} data-testid={`forecast-line-${line.row}`}>
                <label className="flex items-start gap-2">
                  <input type="checkbox" checked={ticked.has(line.row)} onChange={() => toggle(line.row)} data-testid={`forecast-tick-${line.row}`} className="mt-0.5" />
                  <span className="font-medium text-slate-900" data-testid={`forecast-label-${line.row}`}>{line.label}</span>
                  <span data-testid={`forecast-values-${line.row}`}>{line.values.map((v) => forecastValueText(line, v)).join(" · ")}</span>
                  <span className="font-mono text-slate-500" data-testid={`forecast-cells-${line.row}`}>{forecastCells(line)}</span>
                </label>
              </li>
            ))}
          </ul>
          <Button type="button" size="sm" disabled={busy || ticked.size === 0} onClick={confirm} data-testid={`forecast-confirm-${id}`}
            className="mt-2 h-7 bg-sky-600 hover:bg-sky-500">{S28_CONFIRM}</Button>
          {error && <span className="ml-2 text-rose-700" data-testid={`forecast-error-${id}`}>{error}</span>}
        </div>
      )}
    </div>
  );
}

/** The detected type, how it was found, and the Change button: the analyst can override it (chat-upload.md section 19). */
function TypeLine({ view, retype }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [ask, setAsk] = useState(null);                  // a type already loaded: the replace question
  const go = async (to, replace = false) => {
    setBusy(true);
    setError(null);
    try {
      await retype(view, to, replace);
      setOpen(false);
      setAsk(null);
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (err.response?.status === 409 && detail?.code === "type_loaded") setAsk({ to, loaded: detail.file });
      else setError(typeof detail === "string" ? detail : "The type could not be changed.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mt-1 text-xs text-slate-600" data-testid={`type-line-${view.dtype}`}>
      <span data-testid={`type-label-${view.dtype}`}>{S26_type(view)}</span>
      <button type="button" data-testid={`type-change-${view.dtype}`} onClick={() => setOpen((v) => !v)} className="ml-2 underline hover:text-slate-900">{S26_CHANGE}</button>
      {open && (
        <span className="ml-2 inline-flex gap-1.5">
          {Object.entries(TYPE_LABELS).filter(([dtype]) => dtype !== view.dtype).map(([dtype, label]) => (
            <Button key={dtype} size="sm" variant="outline" disabled={busy} data-testid={`type-pick-${dtype}`} onClick={() => go(dtype)} className="h-6 px-2">{label}</Button>
          ))}
        </span>
      )}
      {ask && (
        <span className="ml-2" data-testid="type-replace">
          {S8_replace(ask.to, ask.loaded)}
          <Button size="sm" disabled={busy} data-testid="type-replace-yes" onClick={() => go(ask.to, true)} className="h-6 px-2 ml-1.5 bg-sky-600 hover:bg-sky-500">Replace</Button>
          <Button size="sm" variant="outline" data-testid="type-replace-no" onClick={() => setAsk(null)} className="h-6 px-2 ml-1.5">Keep current</Button>
        </span>
      )}
      {error && <span className="ml-2 text-rose-700" data-testid="type-error">{error}</span>}
    </div>
  );
}

/** S25: why the mapping step matters; one box above the first mapping table, open until the analyst folds it. */
function WhyThisMatters({ statement }) {
  return (
    <details open data-testid="why-this-matters" className="mt-3 rounded-md border border-sky-200 bg-sky-50/60 px-3 py-2 text-xs text-slate-700">
      <summary className="cursor-pointer font-medium text-slate-900" data-testid="why-this-matters-title">{S25_TITLE}</summary>
      <div className="mt-2 space-y-2">
        {(statement ? S25_STATEMENT_PARAGRAPHS : S25_PARAGRAPHS).map((p) => <p key={p}>{p}</p>)}
      </div>
    </details>
  );
}

/** S29: the fields a CRM file feeds and what each is used for; one box above the CRM file's mapping table, open until folded. */
function CrmFieldsHelp() {
  return (
    <details open data-testid="crm-fields-help" className="mt-3 rounded-md border border-sky-200 bg-sky-50/60 px-3 py-2 text-xs text-slate-700">
      <summary className="cursor-pointer font-medium text-slate-900" data-testid="crm-fields-help-title">{S29_TITLE}</summary>
      <div className="mt-2 space-y-2">
        {S29_PARAGRAPHS.map((p) => <p key={p}>{p}</p>)}
      </div>
    </details>
  );
}

const MONEY_QUESTION = "Is this money the company earned (revenue) or the value of transactions processed (volume)?";

export function ColumnRow({ row, view, decide, lastReason, setLastReason }) {
  const [editing, setEditing] = useState(false);
  const [field, setField] = useState(row.field || NONE);
  const reason = lastReason;                       // one reason for the whole page: it stays for the next correction
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const held = heldFields(view.columns, row.column);
  const fields = [...view.fields.required, ...view.fields.optional];
  const needs = row.state === "needs";
  const pending = row.pending;

  const send = async (decision) => {
    setSaving(true);
    setError(null);
    try {
      await decide(view, [decision]);
      setEditing(false);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(err.response?.status === 400 && typeof detail === "string" && detail.startsWith("Leave out") ? S21_NOTE_REFUSED
        : typeof detail === "string" ? detail : "The decision could not be saved.");
    } finally {
      setNote("");                                  // the note clears after each correction; the reason stays
      setSaving(false);
    }
  };

  const fieldSelect = (value, onChange, testid) => (
    <select data-testid={testid} value={value} onChange={(e) => onChange(e.target.value)} className="h-8 rounded border border-[#D1D5DB] bg-white text-xs px-1.5">
      <option value={NONE}>Not used</option>
      {fields.map((f) => (
        <option key={f} value={f} disabled={!!held[f]}>{fieldName(f)}{held[f] ? ` (held by ${held[f]})` : ""}</option>
      ))}
    </select>
  );

  return (
    <>
      <tr className="border-b border-[#F1F5F9] align-top" data-testid={`column-row-${row.column}`} data-state={row.state}>
        <td className="py-1.5 pr-3 font-mono">{row.column}</td>
        <td className="py-1.5 pr-3">
          {needs ? fieldSelect(field, setField, `needs-field-${row.column}`) : fieldName(row.field)}
        </td>
        <td className="py-1.5 pr-3" data-testid={`confidence-${row.column}`}>{S9_confidence(row)}</td>
        <td className={`py-1.5 pr-3 ${pending ? "text-amber-700" : ""}`} data-testid={`source-${row.column}`}>
          {mappedBy(row)}
        </td>
        <td className="py-1.5 whitespace-nowrap">
          {(pending && !needs && ["unsure", "ai"].includes(row.state)) && (
            <Button size="sm" variant="outline" data-testid={`confirm-${row.column}`} disabled={saving}
              onClick={() => send({ column: row.column, action: "confirm", field: row.field })} className="h-7 mr-1.5">Confirm</Button>
          )}
          {needs && (
            <Button size="sm" variant="outline" data-testid={`confirm-${row.column}`} disabled={saving}
              onClick={() => send({ column: row.column, action: "confirm", field: field || null })} className="h-7 mr-1.5">Confirm</Button>
          )}
          {!needs && (
            <Button size="sm" variant="ghost" data-testid={`correct-${row.column}`} onClick={() => setEditing((v) => !v)} className="h-7">Correct</Button>
          )}
          {row.money_ask && (
            <div className="mt-1 whitespace-normal max-w-xs" data-testid={`money-ask-${row.column}`}>
              <div className="text-xs text-slate-700">{MONEY_QUESTION}</div>
              {[["revenue", "Revenue"], ["volume", "Volume"]].map(([kind, label]) => (
                <Button key={kind} size="sm" variant={row.money_kind === kind ? "default" : "outline"} disabled={saving} className="h-7 mr-1.5 mt-1"
                  data-testid={`money-${kind}-${row.column}`}
                  onClick={() => send({ column: row.column, action: "confirm", money_kind: kind })}>{label}</Button>
              ))}
            </div>
          )}
          {(row.decision === "confirm" || row.decision === "correct") && !pending && (
            <span className="ml-2 text-[10px] text-slate-500">{row.decision === "confirm" ? "Confirmed" : "Corrected"}</span>
          )}
        </td>
      </tr>
      {editing && (
        <tr data-testid={`correct-editor-${row.column}`}>
          <td colSpan={5} className="pb-2">
            <div className="flex flex-wrap items-center gap-2 bg-slate-100/60 rounded px-3 py-2">
              {fieldSelect(field, setField, `correct-field-${row.column}`)}
              <select data-testid={`correct-reason-${row.column}`} value={reason}
                onChange={(e) => setLastReason(e.target.value)}
                className="h-8 rounded border border-[#D1D5DB] bg-white text-xs px-1.5">
                {REASONS.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
              </select>
              {reason === "other" && (
                <Input data-testid={`correct-note-${row.column}`} value={note} maxLength={NOTE_MAX} placeholder={S20_NOTE_PLACEHOLDER}
                  onChange={(e) => setNote(e.target.value)} className="h-8 w-80 bg-white border-[#D1D5DB] text-xs" />
              )}
              <Button size="sm" data-testid={`correct-apply-${row.column}`} disabled={saving}
                onClick={() => send({ column: row.column, action: "correct", field: field || null, reason, note: reason === "other" ? note : undefined })}
                className="h-8 bg-sky-600 hover:bg-sky-500">Confirm</Button>
              {error && <span className="text-xs text-rose-700" data-testid={`correct-error-${row.column}`}>{error}</span>}
            </div>
          </td>
        </tr>
      )}
      {!editing && error && (
        <tr><td colSpan={5} className="text-xs text-rose-700" data-testid={`row-error-${row.column}`}>{error}</td></tr>
      )}
    </>
  );
}
