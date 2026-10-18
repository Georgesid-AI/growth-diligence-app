import { useEffect, useState } from "react";
import { getAllowance } from "@/lib/api";
import { ALLOWANCE_REACHED, allowanceLine } from "@/lib/allowance";
import { BLOCKERS_CHANGED } from "@/components/BlockerBanner";

/**
 * The monthly AI allowance on every tester screen (docs/specs/usage-and-allowance.md section 5): one line from 80%, the full
 * message at 100%. It is not one of the three blockers of rule 21. Read when the screen opens and again after an upload or a
 * calculation (the same event the blockers use); no polling. A failed read, the owner token's 404 included, shows nothing.
 */
export default function AllowanceBanner() {
  const [state, setState] = useState(null);
  useEffect(() => {
    let live = true;
    const load = () => Promise.resolve().then(() => getAllowance()).then((a) => { if (live) setState(a); }).catch(() => { if (live) setState(null); });
    load();
    window.addEventListener(BLOCKERS_CHANGED, load);
    return () => { live = false; window.removeEventListener(BLOCKERS_CHANGED, load); };
  }, []);
  if (state?.state === "warn") {
    return (
      <div data-testid="allowance-warn" role="status" className="border-b border-amber-300 bg-amber-50">
        <p className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-2 text-sm text-amber-900">{allowanceLine(state)}</p>
      </div>
    );
  }
  if (state?.state === "blocked") {
    return (
      <div data-testid="allowance-reached" role="status" className="border-b border-amber-300 bg-amber-50">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-3 space-y-2 text-sm text-amber-900">
          {ALLOWANCE_REACHED.map((line, i) => <p key={i} className={i === 0 ? "font-semibold" : ""}>{line}</p>)}
        </div>
      </div>
    );
  }
  return null;
}
