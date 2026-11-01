import { useCallback, useEffect, useRef, useState } from "react";
import { Paperclip, FileSpreadsheet, FileText, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BLOCKERS_CHANGED } from "@/lib/useBlockers";
import { uploadChatFile, getDatasets, reportUsage } from "@/lib/api";
import {
  S4_DROP_ZONE_LEAD, S4_DROP_ZONE_BOLD, S7_REFUSED, S7B_XLS_REFUSED, S_UPLOAD_RETRY, ALLOWED_EXTENSIONS, MAP_LABEL, CALCULATE_CLASS,
  setCalculatePressed, fmtBytes, extensionOf,
} from "@/lib/chatUpload";

let nextId = 1;
const uid = () => `m${nextId++}`;

/**
 * The upload list (docs/design/read-check-review.md section 11.1): files in, one line per file. Nothing is asked about a file and no column is
 * mapped; the sheet reader reads the stored file after the upload and the reading screen shows what it found. The bar below holds the paperclip
 * and Map; there is no text field.
 *
 * `onFiles(files)` hands the attached files up; the page's Run audit reads them and then passes `leftover` (the files it did not send): the
 * lines of every other file are dropped, and the stored files are listed again.
 */
export default function UploadChat({ audit, onViews, onStaged, onMapping, mapButton, onFiles, leftover, deck = null }) {
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(0);
  const [dragging, setDragging] = useState(false);
  const staged = useRef(new Map());                   // line id -> File: attached, not yet sent (nothing runs until Map)
  const [mapping, setMapping] = useState(false);
  const mappingRef = useRef(false);
  const picker = useRef(null);
  const queue = useRef(Promise.resolve());

  const push = useCallback((m) => setMessages((all) => [...all, { id: uid(), ...m }]), []);
  const announce = () => window.dispatchEvent(new Event(BLOCKERS_CHANGED));
  const stored = (views) => views.map((v) => ({ id: uid(), kind: "analyst", file: v.file, size: v.size_bytes, ext: v.ext, view: v }));

  // On reload: one line per stored file. Text replies and refused files are not kept.
  useEffect(() => {
    getDatasets(audit.id).then((views) => setMessages(stored(views))).catch(() => {});
  }, [audit.id]); // eslint-disable-line

  useEffect(() => {
    onViews?.(messages.filter((m) => m.view).map((m) => m.view));
  }, [messages]); // eslint-disable-line

  // `line` is the id of the line the file already has (it shows a spinner until the file is stored).
  const send = async (file, line) => {
    setBusy((n) => n + 1);
    try {
      const res = await uploadChatFile(audit.id, file);
      setMessages((all) => all.map((m) => (m.id === line ? { ...m, pending: false, staged: false, file: res.file, size: res.size_bytes ?? file.size, ext: res.ext, view: res } : m)));
    } catch (err) {
      const detail = err.response?.data?.detail;
      setMessages((all) => all.map((m) => (m.id === line ? { ...m, pending: false } : m)));
      if (!err.response) {
        // No answer (timeout or network error): the file goes back to "attached", so Map sends it again.
        staged.current.set(line, file);
        setMessages((all) => all.map((m) => (m.id === line ? { ...m, staged: true } : m)));
        push({ kind: "text", text: S_UPLOAD_RETRY });
      } else {
        push({ kind: "text", text: typeof detail === "string" ? detail : "The file could not be read." });
      }
    } finally {
      setBusy((n) => n - 1);
    }
  };

  const takeFiles = (files) => {
    for (const file of Array.from(files || [])) {
      const ext = extensionOf(file.name);
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        push({ kind: "analyst", file: file.name, size: file.size, ext });
        push({ kind: "text", text: ext === "xls" ? S7B_XLS_REFUSED : S7_REFUSED });
        reportUsage(audit.id, { rejected_extension: ext || "other" });
        continue;
      }
      const line = uid();
      staged.current.set(line, file);
      setMessages((all) => [...all, { id: line, kind: "analyst", file: file.name, size: file.size, ext, staged: true }]);
    }
  };

  const unstage = (id) => {
    staged.current.delete(id);
    setMessages((all) => all.filter((m) => m.id !== id));
  };
  useEffect(() => { onStaged?.(messages.filter((m) => m.staged).length); }, [messages]); // eslint-disable-line
  useEffect(() => { onFiles?.([...staged.current.values()]); }, [messages]); // eslint-disable-line

  // The page has sent the files: only those it did not send stay attached; the stored files are listed again beside them.
  useEffect(() => {
    if (!leftover) return;
    for (const [line, file] of [...staged.current]) if (!leftover.includes(file)) staged.current.delete(line);
    setMessages((all) => all.filter((m) => !m.staged || staged.current.has(m.id)));
    getDatasets(audit.id).then((views) => setMessages((all) => [...stored(views), ...all.filter((m) => m.staged)])).catch(() => {});
  }, [leftover]); // eslint-disable-line

  // Map: send the attached files one at a time, in drop order. The page refreshes the banner once, after the last file. Calculating is Run audit's job.
  const map = async () => {
    if (mappingRef.current) return;                     // a second press while files are being sent does nothing
    mappingRef.current = true;
    setMapping(true);
    onMapping?.(true);
    try {
      for (const [line, file] of [...staged.current]) {
        staged.current.delete(line);
        setMessages((all) => all.map((m) => (m.id === line ? { ...m, staged: false, pending: true } : m)));
        queue.current = queue.current.then(() => send(file, line));
        await queue.current;
      }
      setCalculatePressed(audit.id);
      announce();
    } finally {
      mappingRef.current = false;
      setMapping(false);
      onMapping?.(false);
    }
  };

  const bar = (
    <div className="border-b border-[#E5E7EB] px-3 py-3 flex items-center gap-2">
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
  );

  return (
    <section
      data-testid="upload-chat"
      className="bg-white border border-[#E5E7EB] rounded-lg flex flex-col"
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); takeFiles(e.dataTransfer?.files); }}
    >
      {bar}
      <div className="px-5 pt-4">
        {/* The drop zone stays after a drop: more files can be attached until Map is pressed. */}
        <div data-testid="chat-drop-zone" className={`border border-dashed rounded-lg text-center text-slate-500 ${messages.length === 0 ? "py-14 text-sm" : "py-3 text-xs"} ${dragging ? "border-sky-500 bg-sky-50" : "border-[#D1D5DB]"}`}>
          {S4_DROP_ZONE_LEAD}<strong>{S4_DROP_ZONE_BOLD}</strong>
        </div>
      </div>
      {deck}
      <div data-testid="chat-messages" className="px-5 py-4 space-y-3">
        {messages.map((m) => (m.kind === "text" ? <Bubble key={m.id} side="left" testid="chat-text-system">{m.text}</Bubble>
          : <FileLine key={m.id} m={m} unstage={unstage} />))}
        {busy > 0 && <div className="text-xs text-slate-500 flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Reading…</div>}
      </div>
    </section>
  );
}

function Bubble({ side, children, testid }) {
  return (
    <div className={`flex ${side === "right" ? "justify-end" : "justify-start"}`}>
      <div data-testid={testid} className={`max-w-[860px] rounded-lg px-4 py-2.5 text-sm ${side === "right" ? "bg-sky-50 text-slate-900" : "bg-slate-50 text-slate-800 border border-[#E5E7EB]"}`}>{children}</div>
    </div>
  );
}

function FileLine({ m, unstage }) {
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
