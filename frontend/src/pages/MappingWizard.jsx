import { useEffect, useRef, useState, useCallback } from "react";
import { useLocation, useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Layout } from "@/components/Layout";
import { AssumptionsSetup, ParkedBlocks } from "@/components/AuditSetup";
import UploadSection from "@/components/UploadSection";
import ReadingScreen from "@/components/ReadingScreen";
import { BLOCKERS_CHANGED } from "@/components/BlockerBanner";
import { getAudit } from "@/lib/api";
import { asOfInputValue } from "@/lib/auditForm";

export default function MappingWizard() {
  const { id } = useParams();
  const missing = useLocation()?.state?.missing;        // the audit list sent the analyst here: one line saying what stopped the run
  const [audit, setAudit] = useState(null);
  const [asOf, setAsOf] = useState("");
  const [running, setRunning] = useState(false);      // Run audit is in progress

  const load = useCallback(() => getAudit(id).then((a) => { setAudit(a); setAsOf(asOfInputValue(a.as_of_month)); }), [id]);
  useEffect(() => { load(); }, [load]);

  const [readKey, setReadKey] = useState(0);        // bumped when a file is stored, a read or a run ends: the reading screen loads again
  useEffect(() => { if (!running) setReadKey((k) => k + 1); }, [running]);
  const changed = useCallback(() => { setReadKey((k) => k + 1); load(); }, [load]);
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

  if (!audit) {
    return <Layout audit={audit}><div className="flex justify-center py-32 text-slate-500"><Loader2 className="h-6 w-6 animate-spin" /></div></Layout>;
  }

  return (
    <Layout audit={audit}>
      {missing && <p role="status" className="mb-4 text-sm text-amber-800" data-testid="run-missing-line">{missing}</p>}

      <UploadSection audit={audit} onChanged={changed} onRunning={setRunning} />

      <ReadingScreen audit={audit} setAudit={setAudit} reloadKey={readKey} />

      <details className="mt-5" data-testid="more-settings">
        <summary className="cursor-pointer text-sm text-sky-700">More settings</summary>
        <div className="mt-3">
          <AssumptionsSetup audit={audit} setAudit={setAudit} asOf={asOf} setAsOf={setAsOf} />
          <ParkedBlocks audit={audit} setAudit={setAudit} asOf={asOf} />
        </div>
      </details>
    </Layout>
  );
}
