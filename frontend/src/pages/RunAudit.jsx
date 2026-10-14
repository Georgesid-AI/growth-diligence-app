import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Check, Circle, Loader2, Paperclip, X, AlertTriangle } from "lucide-react";
import { Layout } from "@/components/Layout";
import AuditSetup from "@/components/AuditSetup";
import { BLOCKERS_CHANGED } from "@/components/BlockerBanner";
import { Button } from "@/components/ui/button";
import * as apiModule from "@/lib/api";
import { getAudit, reportUsage } from "@/lib/api";
import { asOfInputValue } from "@/lib/auditForm";
import { setCalculatePressed } from "@/lib/chatUpload";
import { RETRY_LABEL, RUN_LABEL, STAGES, STAGE_STATUS_TEXT, idleStages, runAudit, splitFiles } from "@/lib/runAudit";

const ACCEPT = ".xlsx,.csv,.pptx,.pdf,.docx";

/**
 * Run audit: pick the files, press one button. The files are mapped, the metrics calculated and the deck claims read, in that
 * order; the page then opens the review screen. Each stage shows its progress; one that fails says what to do and has a Retry
 * stage button. Every existing page stays under Details.
 */
export default function RunAudit() {
  const { id } = useParams();
  const nav = useNavigate();
  const [audit, setAudit] = useState(null);
  const [asOf, setAsOf] = useState("");
  const [files, setFiles] = useState([]);
  const [stages, setStages] = useState(idleStages());
  const [running, setRunning] = useState(false);
  const pick = useRef({ data: [], decks: [] });
  const picker = useRef(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  useEffect(() => {
    getAudit(id).then((a) => { setAudit(a); setAsOf(asOfInputValue(a.as_of_month)); }).catch(() => {});
    reportUsage(id, { screen: "run" });
  }, [id]);

  const take = (list) => {
    const added = Array.from(list || []);
    if (!added.length) return;
    setFiles((all) => [...all, ...added]);
    const { data, decks } = splitFiles(added);
    pick.current = { data: [...pick.current.data, ...data], decks: [...pick.current.decks, ...decks] };
  };
  const drop = (file) => {
    setFiles((all) => all.filter((f) => f !== file));
    pick.current = { data: pick.current.data.filter((f) => f !== file), decks: pick.current.decks.filter((f) => f !== file) };
  };

  const update = useCallback((key, result) => { if (alive.current) setStages((s) => ({ ...s, [key]: result })); }, []);
  const start = useCallback(async (from) => {
    if (running) return;
    setRunning(true);
    if (from === "mapping") setStages(idleStages());
    setCalculatePressed(id);                       // the "revenue file missing" blocker shows from the first run, as after Map
    const out = await runAudit({ api: apiModule, auditId: id, pick: pick.current, from, onUpdate: update });
    window.dispatchEvent(new Event(BLOCKERS_CHANGED));
    if (!alive.current) return;
    setRunning(false);
    if (out.status === "done" || out.status === "needs_review") {
      setFiles([]);
      nav(`/audit/${id}/review`);
    }
  }, [id, running, update, nav]);

  if (!audit) {
    return <Layout audit={audit}><div className="flex justify-center py-32 text-slate-500"><Loader2 className="h-6 w-6 animate-spin" /></div></Layout>;
  }
  const failed = STAGES.find((s) => stages[s.key].status === "failed");

  return (
    <Layout audit={audit}>
      <h1 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 mb-1">Run audit</h1>
      <p className="text-sm text-slate-600 mb-6 max-w-3xl">
        Add the files and press Run audit. The columns are mapped, the metrics calculated and the deck claims read. You stop only
        where a decision is yours, on the review screen.
      </p>

      <AuditSetup audit={audit} setAudit={setAudit} asOf={asOf} setAsOf={setAsOf} />

      <section
        data-testid="run-files" className="mt-5 bg-white border border-[#E5E7EB] rounded-lg p-5"
        onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); take(e.dataTransfer?.files); }}
      >
        <input ref={picker} type="file" multiple accept={ACCEPT} className="hidden" data-testid="run-file-input"
          onChange={(e) => { take(e.target.files); e.target.value = ""; }} />
        <Button type="button" variant="outline" size="sm" data-testid="run-attach" onClick={() => picker.current?.click()} className="gap-2">
          <Paperclip className="h-4 w-4" /> Add files
        </Button>
        <p className="mt-2 text-xs text-slate-500">
          Revenue by customer is required (.xlsx or .csv). Also useful: the CRM export and the P&amp;L (.xlsx or .csv), and board decks (.pptx, .pdf or .docx).
        </p>
        <ul className="mt-3 space-y-1" data-testid="run-file-list">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center gap-2 text-xs font-mono text-slate-700">
              {f.name}
              <button type="button" aria-label={`Remove ${f.name}`} onClick={() => drop(f)} className="text-slate-500 hover:text-rose-700"><X className="h-3.5 w-3.5" /></button>
            </li>
          ))}
        </ul>
      </section>

      <div className="mt-5 flex items-center gap-3">
        <Button data-testid="run-audit" onClick={() => start("mapping")} disabled={running} className="bg-sky-600 hover:bg-sky-500 gap-2">
          {running && <Loader2 className="h-4 w-4 animate-spin" />}{RUN_LABEL}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => nav(`/audit/${id}/review`)} data-testid="run-to-review">Go to the review screen</Button>
      </div>

      <ol className="mt-6 space-y-2 max-w-3xl" data-testid="run-stages">
        {STAGES.map((s) => {
          const st = stages[s.key];
          return (
            <li key={s.key} data-testid={`stage-${s.key}`} data-status={st.status}
              className="flex items-start gap-3 rounded-md border border-[#E5E7EB] bg-white px-4 py-3">
              <StageIcon status={st.status} />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-slate-900">{s.label}</div>
                <div className="text-xs text-slate-600" data-testid={`stage-${s.key}-status`}>{STAGE_STATUS_TEXT[st.status]}</div>
                {st.message && <p className={`mt-1 text-xs ${st.status === "failed" ? "text-rose-800" : "text-slate-600"}`} data-testid={`stage-${s.key}-message`}>{st.message}</p>}
              </div>
              {st.status === "failed" && (
                <Button size="sm" variant="outline" disabled={running} data-testid={`retry-${s.key}`} onClick={() => start(s.key)}>{RETRY_LABEL}</Button>
              )}
            </li>
          );
        })}
      </ol>
      {failed && <p className="mt-2 text-xs text-slate-500">Nothing already done is lost: Retry stage carries on from the stage that failed.</p>}
    </Layout>
  );
}

function StageIcon({ status }) {
  if (status === "running") return <Loader2 className="h-4 w-4 mt-0.5 animate-spin text-sky-700" />;
  if (status === "done") return <Check className="h-4 w-4 mt-0.5 text-emerald-700" />;
  if (status === "failed") return <AlertTriangle className="h-4 w-4 mt-0.5 text-rose-700" />;
  if (status === "needs_review") return <AlertTriangle className="h-4 w-4 mt-0.5 text-amber-700" />;
  return <Circle className="h-4 w-4 mt-0.5 text-slate-400" />;
}
