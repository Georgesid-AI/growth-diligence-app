import { useCallback, useEffect, useRef, useState } from "react";
import { Paperclip, FileSpreadsheet, FileText, Loader2, Send, ChevronRight, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { BLOCKERS_CHANGED } from "@/components/BlockerBanner";
import { uploadChatFile, getDatasets, decideColumns, reportUsage } from "@/lib/api";
import {
  S1_TEXT_REPLY, S2_EXPLAINER_CONSENT, S3_EXPLAINER_NO_CONSENT, S4_DROP_ZONE, S6_UNKNOWN_TYPE, S7_REFUSED, S12_MODEL_FAILED,
  S20_NOTE_PLACEHOLDER, S21_NOTE_REFUSED, NOTE_MAX, ALLOWED_EXTENSIONS, REASONS, TYPE_LABELS, S5_head, S8_replace,
  S9_confidence, S13_status, S14_same, SOURCE_LABELS, fieldName, fmtBytes, extensionOf, heldFields,
} from "@/lib/chatUpload";

const NONE = "";
const AI_FAILED = ["timeout", "not_read", "refused", "stopped", "too_large"];
let nextId = 1;
const uid = () => `m${nextId++}`;

/**
 * The chat-style upload (docs/specs/chat-upload.md section 2): one message list, files in, one analyst bubble and one
 * system bubble per file, the mapping table in the system bubble. Typed text is answered on the page (S1) and goes
 * nowhere else. `extras(view)` renders what follows the table of a revenue file (FX rates, billing terms).
 */
export default function UploadChat({ audit, extras, onViews }) {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [lastReason, setLastReason] = useState("header_misleading");   // stays for the next correction on this page
  const picker = useRef(null);
  const queue = useRef(Promise.resolve());
  const consent = audit.structure_reading_consent === true;

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
  }, [audit.id]);

  useEffect(() => {
    onViews?.(messages.filter((m) => m.kind === "system" && m.view).map((m) => m.view));
  }, [messages]); // eslint-disable-line

  // `bubble` is the id of the analyst bubble the file already has (it shows a spinner until the file is read).
  const send = async (file, options = {}, bubble = null) => {
    setBusy((n) => n + 1);
    const settle = (patch) => setMessages((all) => all.map((m) => (m.id === bubble ? { ...m, pending: false, ...patch } : m)));
    try {
      const res = await uploadChatFile(audit.id, file, options);
      if (res.status === "unknown_type") {
        settle({});
        push({ kind: "unknown", file, bubble });
      } else {
        // A file of a loaded type replaces that type's bubbles: one analyst and one system bubble per file.
        setMessages((all) => {
          const kept = all.filter((m) => !(m.dtype === res.dtype && m.kind !== "text") && m.id !== bubble);
          const analyst = { id: bubble || uid(), kind: "analyst", dtype: res.dtype, file: res.file, size: res.size_bytes ?? file.size, ext: res.ext };
          return [...kept, analyst, { id: uid(), kind: "system", dtype: res.dtype, view: res }];
        });
        announce();
      }
    } catch (err) {
      settle({});
      const detail = err.response?.data?.detail;
      if (err.response?.status === 409 && detail?.code === "type_loaded") {
        push({ kind: "replace", file, dtype: detail.dtype, loaded: detail.file, bubble });
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
        push({ kind: "text", role: "system", text: S7_REFUSED });
        reportUsage(audit.id, { rejected_extension: ext || "other" });
        continue;
      }
      const bubble = uid();
      setMessages((all) => [...all, { id: bubble, kind: "analyst", file: file.name, size: file.size, ext, pending: true }]);
      queue.current = queue.current.then(() => send(file, {}, bubble));
    }
  };

  const submitText = (e) => {
    e.preventDefault();
    const typed = text.trim();
    if (!typed) return;
    // Typed text is answered here. It is never sent to the server, stored or logged.
    push({ kind: "text", role: "analyst", text: typed });
    push({ kind: "text", role: "system", text: S1_TEXT_REPLY });
    setText("");
  };

  const decide = async (view, decisions) => {
    const next = await decideColumns(audit.id, view.dtype, decisions);
    setMessages((all) => all.map((m) => (m.kind === "system" && m.dtype === view.dtype ? { ...m, view: next } : m)));
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
      <div data-testid="chat-messages" className="px-5 py-4 space-y-3 min-h-[240px] max-h-[640px] overflow-y-auto">
        {messages.length === 0 && (
          <div data-testid="chat-drop-zone" className={`border border-dashed rounded-lg py-14 text-center text-sm text-slate-500 ${dragging ? "border-sky-500 bg-sky-50" : "border-[#D1D5DB]"}`}>
            {S4_DROP_ZONE}
          </div>
        )}
        {messages.map((m) => (
          <Message key={m.id} m={m} audit={audit} extras={extras} lastReason={lastReason} setLastReason={setLastReason}
            decide={decide}
            onType={(file, dtype) => { setMessages((all) => all.filter((x) => x.id !== m.id)); send(file, { dtype }, m.bubble); }}
            onReplace={(file, dtype) => { setMessages((all) => all.filter((x) => x.id !== m.id)); send(file, { dtype, replace: true }, m.bubble); }}
            onKeep={() => setMessages((all) => all.filter((x) => x.id !== m.id && x.id !== m.bubble))} />
        ))}
        {busy > 0 && <div className="text-xs text-slate-500 flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Reading…</div>}
      </div>
      <form onSubmit={submitText} className="border-t border-[#E5E7EB] px-3 py-3 flex items-center gap-2">
        <input ref={picker} type="file" multiple accept=".xlsx,.xls,.csv" className="hidden" data-testid="chat-file-input"
          onChange={(e) => { takeFiles(e.target.files); e.target.value = ""; }} />
        <button type="button" aria-label="Attach files" data-testid="chat-paperclip" onClick={() => picker.current?.click()}
          className="p-2 rounded-md text-slate-600 hover:bg-slate-100"><Paperclip className="h-4 w-4" /></button>
        <Input data-testid="chat-text-input" value={text} onChange={(e) => setText(e.target.value)} placeholder={S4_DROP_ZONE}
          className="h-9 bg-white border-[#E5E7EB]" />
        <Button type="submit" size="sm" aria-label="Send" data-testid="chat-send" className="bg-sky-600 hover:bg-sky-500"><Send className="h-4 w-4" /></Button>
      </form>
    </section>
  );
}

function Message({ m, audit, extras, lastReason, setLastReason, decide, onType, onReplace, onKeep }) {
  if (m.kind === "analyst") return <AnalystBubble m={m} />;
  if (m.kind === "text") {
    return m.role === "analyst"
      ? <Bubble side="right" testid="chat-text-analyst">{m.text}</Bubble>
      : <Bubble side="left" testid="chat-text-system">{m.text}</Bubble>;
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
  return <SystemBubble view={m.view} audit={audit} extras={extras} lastReason={lastReason} setLastReason={setLastReason} decide={decide} />;
}

function Bubble({ side, children, testid }) {
  return (
    <div className={`flex ${side === "right" ? "justify-end" : "justify-start"}`}>
      <div data-testid={testid} className={`max-w-[860px] rounded-lg px-4 py-2.5 text-sm ${side === "right" ? "bg-sky-50 text-slate-900" : "bg-slate-50 text-slate-800 border border-[#E5E7EB]"}`}>{children}</div>
    </div>
  );
}

function AnalystBubble({ m }) {
  const Icon = m.ext === "csv" ? FileText : FileSpreadsheet;
  return (
    <Bubble side="right" testid="chat-analyst-bubble">
      <span className="inline-flex items-center gap-2"><Icon className="h-4 w-4 text-slate-600" data-testid={`type-icon-${m.ext}`} />
        <span className="font-mono text-xs">{m.file}</span><span className="text-xs text-slate-500">{fmtBytes(m.size)}</span>
        {m.pending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}</span>
    </Bubble>
  );
}

function SystemBubble({ view, audit, extras, lastReason, setLastReason, decide }) {
  const [openUnused, setOpenUnused] = useState(false);
  const shown = view.columns.filter((c) => c.state !== "unused");
  const unused = view.columns.filter((c) => c.state === "unused");
  const modelFailed = AI_FAILED.includes(view.ai_reading?.status);
  const status = S13_status(view);
  const props = { view, decide, lastReason, setLastReason };
  return (
    <Bubble side="left" testid={`chat-system-${view.dtype}`}>
      <div className="font-medium text-slate-900" data-testid="bubble-head">{S5_head(view)}</div>
      {view.status === "same_file" && view.version != null && (
        <p className="text-xs text-slate-600 mt-1" data-testid="bubble-same">{S14_same(view.version)}</p>
      )}
      {modelFailed && <p className="text-xs text-amber-700 mt-1" data-testid="bubble-ai-failed">{S12_MODEL_FAILED}</p>}
      <div className="overflow-x-auto mt-3">
        <table className="w-full text-xs" data-testid={`mapping-table-${view.dtype}`}>
          <thead>
            <tr className="text-left text-slate-500 border-b border-[#E5E7EB]">
              {["Column", "Field", "Confidence", "Source", ""].map((h, i) => <th key={i} className="py-1.5 pr-3 font-medium">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {shown.map((c) => <ColumnRow key={c.column} row={c} {...props} />)}
            {unused.length > 0 && (
              <tr>
                <td colSpan={5} className="pt-2">
                  <button type="button" data-testid={`unused-toggle-${view.dtype}`} aria-expanded={openUnused}
                    onClick={() => setOpenUnused((v) => !v)} className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900">
                    {openUnused ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />} Not used ({unused.length})
                  </button>
                </td>
              </tr>
            )}
            {openUnused && unused.map((c) => <ColumnRow key={c.column} row={c} {...props} />)}
          </tbody>
        </table>
      </div>
      {view.dtype === "revenue" && extras?.(view)}
      <div className={`mt-3 text-xs font-mono ${status === "Ready for compute" ? "text-emerald-700" : "text-amber-700"}`} data-testid={`status-${view.dtype}`}>
        {status}
      </div>
    </Bubble>
  );
}

function ColumnRow({ row, view, decide, lastReason, setLastReason }) {
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
        <td className={`py-1.5 pr-3 ${row.source === "ai" ? "text-amber-700" : needs ? "text-amber-700" : ""}`} data-testid={`source-${row.column}`}>
          {row.source ? SOURCE_LABELS[row.source] : "—"}
        </td>
        <td className="py-1.5 whitespace-nowrap">
          {(pending && !needs) && (
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
