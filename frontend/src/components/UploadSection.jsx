import { useCallback, useEffect, useRef, useState } from "react";
import RunAuditPanel from "@/components/RunAuditPanel";
import { getDatasets, getDecks, getReading, removeDataset, removeDeck, rereadDataset, rereadDeck, reportUsage, uploadChatFile, uploadDeck } from "@/lib/api";
import { ALLOWED_EXTENSIONS, S7B_XLS_REFUSED, extensionOf } from "@/lib/chatUpload";
import { DECK_ACCEPT, isDeckFile } from "@/lib/deckClaims";
import {
  DECK_CARD, HEADER_TEXT, PROCESSING_LINK, PROCESSING_SECTIONS, PROCESSING_TITLE, REMOVE_CONFIRM, REMOVE_LABEL, REPLACE_LABEL, REREAD_FAILED_LABEL,
  REREAD_LABEL, SHEET_CARD, UPLOAD_LABEL, READINGS_CHANGED, deckBusy, deckLine, headerText, replaceLine, sharedReadError, sheetBusy, sheetLine,
} from "@/lib/uploadView";
import { uncertainEntries } from "@/lib/readingView";

/**
 * The top of the Upload page as docs/design/audit-page-mockup.html draws it: the header and its explainer, the Financial data card, the Board deck
 * card and the run card. Files go to the server the moment they are picked or dropped (there is no Map step); each file has one line in its card
 * with its stage, its elapsed time and Remove. The page polls the files while any is being read.
 */
let nextLocal = 1;
const PICKER_SHEET = ALLOWED_EXTENSIONS.map((e) => `.${e}`).join(",");
const SHEET_ONLY = "Only .xlsx and .csv files go here.";
const DECK_ONLY = "Only .pdf, .pptx and .docx files go here.";
const POLL_MS = 3000;

const FileIcon = () => (
  <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="#5f6368" strokeWidth="1.4" strokeLinejoin="round" aria-hidden="true"><path d="M3.5 1.5h6l3 3v10h-9z M9.5 1.5v3h3" /></svg>
);
const UploadIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M8 11V2.5M4.5 6 8 2.5 11.5 6M2.5 11v2.5h11V11" /></svg>
);

function Card({ kind, title, lines, muted, drop, note, accept, onFiles, refusal, children }) {
  const picker = useRef(null);
  const [over, setOver] = useState(false);
  return (
    <section className="panel" data-testid={`${kind}-card`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); onFiles(e.dataTransfer?.files); }}>
      <div className="ph">
        <h2>{title}</h2>
        <button type="button" className="btn up" data-testid={`${kind}-upload`} onClick={() => picker.current?.click()}><UploadIcon />{UPLOAD_LABEL}</button>
        <input ref={picker} type="file" multiple accept={accept} className="hidden" data-testid={`${kind}-file-input`} style={{ display: "none" }}
          onChange={(e) => { onFiles(e.target.files); e.target.value = ""; }} />
      </div>
      {lines.map((l, i) => <p key={i} className={`line${i ? " muted" : ""}`}>{l}</p>)}
      <div className={`drop${over ? " over" : ""}`} data-testid={`${kind}-drop`}>{drop}</div>
      {refusal && <p className="line bad" role="alert" data-testid={`${kind}-refusal`}>{refusal}</p>}
      {children}
      {note && <p className="line muted deckline" data-testid={`${kind}-note`}>{note}</p>}
    </section>
  );
}

/**
 * One file's line. Remove turns into its own confirmation in place: "Remove – deletes this file and all its claims, including reviewed ones · Cancel",
 * where Remove deletes and Cancel puts the link back (no second line, no second button). A line with no `confirmRemove` removes at the first click.
 */
function FileRow({ name, line, onRemove, confirmRemove, onReread, testid }) {
  const [asking, setAsking] = useState(false);
  const remove = !onRemove ? <span />
    : asking
      ? (
        <span className="rm" data-testid="file-remove-confirm">
          <a href="#remove" data-testid="file-remove-yes" onClick={(e) => { e.preventDefault(); onRemove(); }}>{REMOVE_LABEL}</a>
          {" – "}{REMOVE_CONFIRM}{" · "}
          <a href="#cancel" data-testid="file-remove-cancel" onClick={(e) => { e.preventDefault(); setAsking(false); }}>Cancel</a>
        </span>
      )
      : <a href="#remove" className="rm" data-testid="file-remove" onClick={(e) => { e.preventDefault(); if (confirmRemove) setAsking(true); else onRemove(); }}>{REMOVE_LABEL}</a>;
  return (
    <li data-testid={testid} data-tone={line.tone}>
      <span className="fi"><FileIcon /></span>
      <span className="fn" data-testid="file-name">{name}</span>
      <span className={`tag ${line.tone === "done" ? "done" : line.tone === "bad" ? "bad" : ""}`} data-testid="file-tag">{line.tag}</span>
      <span className="time" data-testid="file-time">{line.time}</span>
      {remove}
      {onReread && <a href="#reread" className="rm" data-testid="file-reread" onClick={(e) => { e.preventDefault(); onReread(); }}>{REREAD_LABEL}</a>}
      {line.sub && <span className="sub muted" data-testid="file-sub">{line.sub}</span>}
      {line.summary && <span className="sum summary" data-testid="file-summary">{line.summary}</span>}
    </li>
  );
}

/** The one-line question when a file's name is already stored: "A file named X is already stored. Replace it? Replace · Cancel". */
function ReplaceLine({ entry, onAnswer }) {
  return (
    <p className="line" data-testid="replace-confirm">
      {replaceLine(entry.file.name)}{" "}
      <a href="#replace" data-testid="replace-yes" onClick={(e) => { e.preventDefault(); onAnswer(entry, true); }}>{REPLACE_LABEL}</a>{" · "}
      <a href="#cancel" data-testid="replace-cancel" onClick={(e) => { e.preventDefault(); onAnswer(entry, false); }}>Cancel</a>
    </p>
  );
}

export default function UploadSection({ audit, onChanged, onRunning }) {
  const auditId = audit.id;
  const [stored, setStored] = useState([]);           // the stored spreadsheets, as the server lists them
  const [decks, setDecks] = useState([]);
  const [local, setLocal] = useState([]);             // files on their way up, or refused by the server: {id, kind, file, local: {state, startedAt, message}}
  const [refusal, setRefusal] = useState({ sheet: null, deck: null });
  const [replacing, setReplacing] = useState([]);       // files whose name is already stored, waiting for the analyst: [{id, file (File)}]
  const [processing, setProcessing] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [uncertain, setUncertain] = useState(0);        // the readings that await confirmation (the Uncertain list's lines)
  const alive = useRef(true);
  const queue = useRef({ sheet: Promise.resolve(), deck: Promise.resolve() });
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const stamp = (rows) => rows.map((r) => ({ ...r, fetchedAt: Date.now() }));
  const refresh = useCallback(async () => {
    const [views, deckData] = await Promise.all([getDatasets(auditId).catch(() => null), getDecks(auditId).catch(() => null)]);
    if (!alive.current) return;
    if (views) setStored(stamp(views));
    if (deckData) setDecks(stamp(deckData.decks || []));
    // The readings that await confirmation: asked of the register once the files are read (not on every poll of a file being read).
    if ((views || []).some(sheetBusy) || (deckData?.decks || []).some(deckBusy)) return;
    const read = await Promise.resolve().then(() => getReading(auditId)).catch(() => null);
    if (alive.current) setUncertain(read ? uncertainEntries(read.files).length : 0);
  }, [auditId]);
  useEffect(() => { refresh(); reportUsage(auditId, { screen: "mapping" }); }, [refresh, auditId]);
  // A pick on the Uncertain list changes the count of items still waiting: ask the register again, no reload (combined fixes, item 6).
  useEffect(() => {
    const again = () => { refresh(); };
    window.addEventListener(READINGS_CHANGED, again);
    return () => window.removeEventListener(READINGS_CHANGED, again);
  }, [refresh]);

  const sheets = [...stored, ...local.filter((l) => l.kind === "sheet").map((l) => ({ file: l.file, local: l.local, id: l.id }))];
  const deckRows = [...decks, ...local.filter((l) => l.kind === "deck").map((l) => ({ file: l.file, local: l.local, id: l.id }))];
  const running = sheets.some(sheetBusy) || deckRows.some(deckBusy);

  // Follow the files while any is being read; tick the clock each second for the elapsed times.
  useEffect(() => {
    if (!running) return undefined;
    const timer = setTimeout(refresh, POLL_MS);
    return () => clearTimeout(timer);
  }, [running, stored, decks, refresh]);
  useEffect(() => {
    if (!running) return undefined;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [running]);
  // When the last file has been read, the page's results and blockers follow.
  const wasRunning = useRef(false);
  useEffect(() => { if (wasRunning.current && !running) onChanged?.(); wasRunning.current = running; }, [running]); // eslint-disable-line
  // The counter of "Reading and checking files": from the first upload of a batch to the last file processed.
  const [readClock, setReadClock] = useState({ start: null, end: null });
  useEffect(() => { if (!running) setReadClock((c) => (c.start != null && c.end == null ? { ...c, end: Date.now() } : c)); }, [running]);

  const fail = (id, message) => setLocal((all) => all.map((l) => (l.id === id ? { ...l, local: { ...l.local, state: "failed", message } } : l)));
  const send = (kind, file, id, replace = false) => {
    queue.current[kind] = queue.current[kind].then(async () => {
      try {
        if (kind === "sheet") await uploadChatFile(auditId, file, { replace }); else await uploadDeck(auditId, file);
        if (alive.current) setLocal((all) => all.filter((l) => l.id !== id));
        await refresh();
        onChanged?.();
      } catch (err) {
        const detail = err.response?.data?.detail;
        fail(id, typeof detail === "string" ? detail : "The file could not be uploaded.");
      }
    });
  };
  const takeFiles = (kind, list) => {
    const files = Array.from(list || []);
    setRefusal((r) => ({ ...r, [kind]: null }));
    for (const file of files) {
      const ext = extensionOf(file.name);
      const ok = kind === "sheet" ? ALLOWED_EXTENSIONS.includes(ext) : isDeckFile(file.name);
      if (!ok) {
        setRefusal((r) => ({ ...r, [kind]: ext === "xls" && kind === "sheet" ? S7B_XLS_REFUSED : `${file.name}: ${kind === "sheet" ? SHEET_ONLY : DECK_ONLY}` }));
        reportUsage(auditId, { rejected_extension: ext || "other" });
        continue;
      }
      if (stored.some((r) => r.file === file.name && !r.local) && kind === "sheet") {      // the same name: one line asks before it replaces the stored file
        setReplacing((all) => [...all.filter((x) => x.file.name !== file.name), { id: `r${nextLocal++}`, file }]);
        continue;
      }
      if (kind === "deck" && decks.some((d) => d.file === file.name)) {
        setReplacing((all) => [...all.filter((x) => x.file.name !== file.name), { id: `r${nextLocal++}`, file, deck: true }]);
        continue;
      }
      const id = `l${nextLocal++}`;
      setReadClock((c) => (c.start == null || c.end != null ? { start: Date.now(), end: null } : c));
      setLocal((all) => [...all, { id, kind, file: file.name, local: { state: "uploading", startedAt: Date.now() } }]);
      send(kind, file, id);
    }
  };

  const startUpload = (kind, file, replace) => {
    const id = `l${nextLocal++}`;
    setReadClock((c) => (c.start == null || c.end != null ? { start: Date.now(), end: null } : c));
    setLocal((all) => [...all, { id, kind, file: file.name, local: { state: "uploading", startedAt: Date.now() } }]);
    send(kind, file, id, replace);
  };
  const answerReplace = (entry, yes) => {
    setReplacing((all) => all.filter((x) => x.id !== entry.id));
    if (yes) startUpload(entry.deck ? "deck" : "sheet", entry.file, true);
  };

  const removeLocal = (id) => setLocal((all) => all.filter((l) => l.id !== id));
  const afterChange = async () => { await refresh(); onChanged?.(); };
  const removeStored = async (call, id) => {
    try { await call(auditId, id); } catch (e) { /* the file stays listed */ }
    await afterChange();
  };
  const reread = async (call, id) => {
    try { await call(auditId, id); } catch (e) { /* the file keeps its line; the next refresh shows where it stands */ }
    await afterChange();
  };
  const shared = sharedReadError(sheets, deckRows);          // the one provider error every file met: the run card names it, the files' lines give way
  const failedSheets = stored.filter((v) => sheetLine(v, now).tone === "bad");        // the files the page shows as Not processed
  const failedDecks = decks.filter((d) => deckLine(d, now).tone === "bad");
  const failedCount = failedSheets.length + failedDecks.length;
  const rereadFailed = async () => {
    await Promise.all([...failedSheets.map((v) => rereadDataset(auditId, v.file_hash).catch(() => null)), ...failedDecks.map((d) => rereadDeck(auditId, d.deck_id).catch(() => null))]);
    await afterChange();
  };

  return (
    <div className="upload-page" data-testid="upload-page">
      <header className="head" data-testid="upload-header">
        <h1 data-testid="upload-company">{headerText(audit)}</h1>
        <p data-testid="reading-explainer">
          {HEADER_TEXT}{" "}
          <a href="#processing" data-testid="processing-link" onClick={(e) => { e.preventDefault(); setProcessing((v) => !v); }}>{PROCESSING_LINK}</a>
        </p>
      </header>

      {processing && (
        <div id="processing" className="panel" data-testid="processing-text">
          <h2>{PROCESSING_TITLE}</h2>
          {PROCESSING_SECTIONS(audit.provider_zdr === true).map((s) => <p key={s.heading} className="line"><b>{s.heading}</b> {s.text}</p>)}
        </div>
      )}

      {failedCount >= 2 && (
        <p className="line" data-testid="reread-failed">
          <a href="#reread-failed" className="rm" data-testid="reread-failed-link" onClick={(e) => { e.preventDefault(); rereadFailed(); }}>{REREAD_FAILED_LABEL}</a>
        </p>
      )}

      <Card kind="sheet" title={SHEET_CARD.title} lines={[SHEET_CARD.line]} drop={SHEET_CARD.drop} accept={PICKER_SHEET}
        onFiles={(f) => takeFiles("sheet", f)} refusal={refusal.sheet}>
        {replacing.filter((x) => !x.deck).map((x) => <ReplaceLine key={x.id} entry={x} onAnswer={answerReplace} />)}
        {sheets.length > 0 && (
          <ul className="files" data-testid="sheet-files">
            {sheets.map((v) => (
              <FileRow key={v.file_hash || v.id} testid="sheet-file" name={v.file} line={sheetLine(v, now, shared)}
                onRemove={v.local ? (v.local.state === "failed" ? () => removeLocal(v.id) : undefined) : () => removeStored(removeDataset, v.file_hash)}
                confirmRemove={!v.local}
                onReread={!v.local && sheetLine(v, now).tone === "bad" ? () => reread(rereadDataset, v.file_hash) : undefined} />
            ))}
          </ul>
        )}
      </Card>

      <Card kind="deck" title={DECK_CARD.title} lines={[DECK_CARD.line, DECK_CARD.muted]} drop={DECK_CARD.drop} note={DECK_CARD.note} accept={DECK_ACCEPT}
        onFiles={(f) => takeFiles("deck", f)} refusal={refusal.deck}>
        {replacing.filter((x) => x.deck).map((x) => <ReplaceLine key={x.id} entry={x} onAnswer={answerReplace} />)}
        {deckRows.length > 0 && (
          <ul className="files" data-testid="deck-files">
            {deckRows.map((d) => (
              <FileRow key={d.deck_id || d.id} testid="deck-file" name={d.file} line={deckLine(d, now, shared)}
                onRemove={d.local ? (d.local.state === "failed" ? () => removeLocal(d.id) : undefined) : () => removeStored(removeDeck, d.deck_id)}
                confirmRemove={!d.local}
                onReread={!d.local && deckLine(d, now).tone === "bad" ? () => reread(rereadDeck, d.deck_id) : undefined} />
            ))}
          </ul>
        )}
      </Card>

      <RunAuditPanel auditId={auditId} sheets={sheets} decks={deckRows} now={now} readClock={readClock} onRunning={onRunning} uncertain={uncertain} />

    </div>
  );
}
