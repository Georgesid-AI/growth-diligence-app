import { useEffect, useRef, useState, useCallback } from "react";
import { useLocation, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Loader2, Plus, X } from "lucide-react";
import { Layout } from "@/components/Layout";
import DeckPanel from "@/components/DeckPanel";
import { ConsentBlock, AssumptionsSetup, ParkedBlocks } from "@/components/AuditSetup";
import UploadChat from "@/components/UploadChat";
import RunAuditPanel from "@/components/RunAuditPanel";
import ReadingScreen, { ReadingTop } from "@/components/ReadingScreen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { BLOCKERS_CHANGED } from "@/components/BlockerBanner";
import { getAudit, reportUsage, saveFx } from "@/lib/api";
import { asOfInputValue } from "@/lib/auditForm";
import { mapState } from "@/lib/chatUpload";
import { splitFiles } from "@/lib/runAudit";

export default function MappingWizard() {
  const { id } = useParams();
  const missing = useLocation()?.state?.missing;        // the audit list sent the analyst here: one line saying what stopped the run
  const [topHost, setTopHost] = useState(null);       // the top of the page, where the second Run audit button is drawn
  const [audit, setAudit] = useState(null);
  const [views, setViews] = useState([]);
  const [asOf, setAsOf] = useState("");
  const [mapping, setMapping] = useState(false);        // Map is reading files: Run audit waits
  const [attached, setAttached] = useState(0);        // files attached in the chat and not read yet
  const [fxVersion, setFxVersion] = useState(0);      // bumped when a rate is saved: the deck panel reloads
  const [running, setRunning] = useState(false);      // Run audit is in progress: Map waits (and it waits for Map)
  const [leftover, setLeftover] = useState(null);     // the attached files the last run did not send; the box keeps only those
  const pick = useRef({ data: [], decks: [] });       // the files attached in the box, for Run audit
  const attach = useCallback((files) => { pick.current = splitFiles(files); }, []);

  const load = useCallback(() => getAudit(id).then((a) => { setAudit(a); setAsOf(asOfInputValue(a.as_of_month)); }), [id]);
  useEffect(() => { load(); reportUsage(id, { screen: "mapping" }); }, [load, id]);

  // Map is on whenever a file is attached or loaded.
  const [readKey, setReadKey] = useState(0);        // bumped when a read or a run ends: the reading screen loads again
  useEffect(() => { if (!mapping && !running) setReadKey((k) => k + 1); }, [mapping, running, views.length]);
  // The sheet reader runs after the upload's response (read-check-review.md section 3): follow the audit while it works.
  useEffect(() => {
    if (!audit || !(audit.sheet_reads_pending > 0)) return undefined;
    const timer = setTimeout(() => { load(); setReadKey((k) => k + 1); }, 3000);
    return () => clearTimeout(timer);
  }, [audit]); // eslint-disable-line react-hooks/exhaustive-deps
  // When the background reading finishes, the blockers (a "No file has been read yet" line) are read again: no page reload.
  const wasPending = useRef(false);
  useEffect(() => {
    const pending = Number(audit?.sheet_reads_pending) > 0;
    if (wasPending.current && !pending) window.dispatchEvent(new Event(BLOCKERS_CHANGED));
    wasPending.current = pending;
  }, [audit]);
  const busy = mapping || running;
  const map = mapState({ attached, loaded: views.length, busy });

  if (!audit) {
    return <Layout audit={audit}><div className="flex justify-center py-32 text-slate-500"><Loader2 className="h-6 w-6 animate-spin" /></div></Layout>;
  }

  return (
    <Layout audit={audit}>
      <ReadingTop audit={audit} setAudit={setAudit} host={<div ref={setTopHost} data-testid="run-audit-top-host" />} />
      {missing && <p role="status" className="mb-4 text-sm text-amber-800" data-testid="run-missing-line">{missing}</p>}

      <UploadChat audit={audit} onViews={setViews} onStaged={setAttached} onMapping={setMapping}
        onFiles={attach} leftover={leftover} mapButton={map}
        deck={<div className="px-5 pt-4"><DeckPanel auditId={audit.id} reloadKey={fxVersion} compact /></div>} />

      <ReadingScreen audit={audit} setAudit={setAudit} reloadKey={readKey + fxVersion} />

      <RunAuditPanel auditId={audit.id} pick={pick} onRan={setLeftover} onRunning={setRunning} blocked={mapping} topHost={topHost} />

      <details className="mt-5" data-testid="more-settings">
        <summary className="cursor-pointer text-sm text-sky-700">More settings</summary>
        <div className="mt-3">
          <div className="mt-5"><FxSettings audit={audit} onSaved={() => setFxVersion((n) => n + 1)} /></div>
          <AssumptionsSetup audit={audit} setAudit={setAudit} asOf={asOf} setAsOf={setAsOf} />
          <ParkedBlocks audit={audit} setAudit={setAudit} asOf={asOf} />
        </div>
      </details>
    </Layout>
  );
}

/** The audit's FX rates: one set for the uploaded files and the deck claims, needing no file. Saved as they change. */
function FxSettings({ audit, onSaved }) {
  const [fx, setFx] = useState({ ...(audit.datasets?.revenue?.fx || {}), ...(audit.fx || {}) });
  const change = async (next) => {
    const before = fx;
    setFx(next);
    try { await saveFx(audit.id, next); onSaved?.(); } catch (e) { setFx(before); toast.error("Save failed"); }
  };
  return (
    <section id="fx-settings" data-testid="fx-settings" className="bg-white border border-[#E5E7EB] rounded-lg px-5 pb-5">
      <FxEditor fx={fx} setFx={change} baseCcy={audit.reporting_currency} />
    </section>
  );
}

function FxEditor({ fx, setFx, baseCcy }) {
  const [ccy, setCcy] = useState("");
  const [rate, setRate] = useState("");
  const add = () => {
    if (!ccy.trim() || !parseFloat(rate)) return;
    setFx({ ...fx, [ccy.trim().toUpperCase()]: parseFloat(rate) });
    setCcy(""); setRate("");
  };
  const remove = (k) => { const n = { ...fx }; delete n[k]; setFx(n); };
  return (
    <div className="pt-5">
      <div className="text-xs text-slate-700 mb-2">
        FX rates to {baseCcy} <span className="text-slate-500">(add a rate for each non-{baseCcy} currency in your revenue lines or in the deck claims)</span>
      </div>
      <div className="flex flex-wrap gap-2 mb-3">
        {Object.entries(fx).map(([k, v]) => (
          <span key={k} className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-sky-50 border border-[#D1D5DB] text-xs font-mono text-slate-800">
            1 {k} = {v} {baseCcy}
            <button onClick={() => remove(k)} className="text-slate-500 hover:text-rose-700"><X className="h-3 w-3" /></button>
          </span>
        ))}
        {Object.keys(fx).length === 0 && <span className="text-xs text-slate-600 font-mono">no FX rates — single-currency assumed</span>}
      </div>
      <div className="flex gap-2 items-center">
        <Input value={ccy} onChange={(e) => setCcy(e.target.value)} placeholder="USD" className="w-24 h-9 bg-white border-[#E5E7EB] font-mono uppercase" data-testid="fx-ccy-input" />
        <span className="text-slate-500 text-sm">=</span>
        <Input value={rate} onChange={(e) => setRate(e.target.value)} placeholder="0.92" type="number" step="0.0001" className="w-28 h-9 bg-white border-[#E5E7EB] font-mono" data-testid="fx-rate-input" />
        <span className="text-slate-500 text-sm">{baseCcy}</span>
        <Button size="sm" variant="outline" onClick={add} className="bg-transparent border-[#D1D5DB] text-slate-800 gap-1"><Plus className="h-3.5 w-3.5" /> Add</Button>
      </div>
    </div>
  );
}
