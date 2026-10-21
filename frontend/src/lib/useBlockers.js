import { useEffect, useState } from "react";
import { getBlockers } from "@/lib/api";

export const BLOCKERS_CHANGED = "blockers:changed";

/** The blockers the server returns for an audit, read again whenever BLOCKERS_CHANGED fires. */
export function useBlockers(auditId) {
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
  return blockers;
}
