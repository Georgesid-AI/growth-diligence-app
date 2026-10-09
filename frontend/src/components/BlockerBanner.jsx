import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertOctagon } from "lucide-react";
import { getBlockers } from "@/lib/api";
import { REVENUE_REQUIRED_NOTE, S16a_MISSING, calculatePressed } from "@/lib/chatUpload";

export const BLOCKERS_CHANGED = "blockers:changed";

/**
 * The hard blockers at the top of every audit view (CLAUDE.md rule 21): the revenue file missing, a top-5 claim
 * contradicted, a revenue reconciliation gap above 2%. The server decides what is a blocker; this only shows it.
 */
export default function BlockerBanner({ auditId }) {
  const [blockers, setBlockers] = useState([]);

  useEffect(() => {
    let live = true;
    const stop = () => { live = false; window.removeEventListener(BLOCKERS_CHANGED, load); };
    // A failed read, a 404 after the audit is deleted included, empties the banner and ends the listening.
    const load = () => getBlockers(auditId).then((b) => live && setBlockers([...(b || [])])).catch(() => { if (live) setBlockers([]); stop(); });
    load();
    window.addEventListener(BLOCKERS_CHANGED, load);
    return stop;
  }, [auditId]);

  // The revenue file blocker is shown only once Calculate has been pressed (task of 2026-10-09, item 2); the other two kinds always.
  const pressed = calculatePressed(auditId);
  const shown = blockers.filter((b) => b.kind !== "revenue_file_missing" || pressed);
  if (!shown.length) return null;
  return (
    <div data-testid="blocker-banner" role="alert" className="border-b border-rose-300 bg-rose-50">
      <ul className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-2 space-y-1">
        {shown.map((b, i) => (
          <li key={`${b.kind}-${i}`} data-testid={`blocker-${b.kind}`} className="flex items-start gap-2 text-sm text-rose-900">
            <AlertOctagon className="h-4 w-4 mt-0.5 shrink-0 text-rose-700" />
            <span>
              {b.text}
              {b.kind === "revenue_file_missing" && b.text === S16a_MISSING && (
                <span className="block text-xs text-rose-800 mt-0.5" data-testid="blocker-revenue-note">{REVENUE_REQUIRED_NOTE}</span>
              )}
              {b.link && <> <Link to={b.link} data-testid="blocker-link" className="underline underline-offset-2">Evidence table</Link></>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
