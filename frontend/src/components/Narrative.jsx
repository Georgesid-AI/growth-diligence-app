import { useEffect, useState } from "react";
import { AlertTriangle, Loader2, FileText } from "lucide-react";
import { NARRATIVE_EXPECTED_SECONDS, NARRATIVE_TIMEOUT_MS } from "@/lib/api";

/**
 * Renders a generated narrative and, more importantly, how much of it is
 * verified.
 *
 * The gateway checks every number the model wrote against the calculation
 * engine's output. Numbers in the headline and the table are hard-verified — a
 * mismatch there means no narrative at all. Numbers in the prose are not, so a
 * "flagged" narrative is shown with the unverified figures named explicitly.
 * The reader should never have to guess which numbers were checked.
 */
export function Narrative({ state }) {
  if (state?.loading) {
    return (
      <Card>
        <GeneratingProgress />
      </Card>
    );
  }
  if (!state) return null;

  const { narrative_status: status, narrative, reason, unmatched_numbers: unmatched = [] } = state;

  if (status === "unavailable") {
    return (
      <Card>
        <div
          data-testid="narrative-unavailable"
          className="rounded-md border border-[#E5E7EB] bg-slate-50 px-4 py-3 text-sm text-slate-700"
        >
          <div className="font-medium text-slate-900">Narrative could not be generated.</div>
          <p className="mt-1 text-slate-600">
            The computed metrics below are unaffected — they come from the calculation
            engine, not the narrative.
          </p>
          {reason && (
            <p className="mt-2 font-mono text-[11px] text-slate-500">{reason}</p>
          )}
        </div>
      </Card>
    );
  }

  if (!narrative) return null;

  return (
    <Card>
      {status === "flagged" && unmatched.length > 0 && (
        <div
          data-testid="narrative-flagged-banner"
          className="mb-4 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-700" />
          <div>
            <span className="font-medium">
              Unverified figures in this text: {unmatched.join(", ")}.
            </span>{" "}
            Numbers in the headline and table are verified against the calculation
            engine; these are not.
          </div>
        </div>
      )}

      <h3 className="font-heading text-base font-semibold text-slate-900">
        {narrative.headline}
      </h3>
      <p className="mt-2 text-sm leading-relaxed text-slate-700">
        {narrative.what_this_means}
      </p>

      {narrative.table_rows?.length > 0 && (
        <table className="mt-4 w-full text-sm">
          <tbody>
            {narrative.table_rows.map((row, i) => (
              <tr key={`${row.source_key}-${i}`} className="border-t border-[#E5E7EB]">
                <td className="py-1.5 pr-3 text-slate-700">
                  {/* Plain-English name from the server's label map; the model's own
                      label only if the server sent none (e.g. an older response). */}
                  <div data-testid="narrative-row-label">{state.row_labels?.[row.source_key] ?? row.label}</div>
                  {/* The engine path this figure came from - the audit trail, kept
                      underneath so any row can be traced back. */}
                  <div data-testid="narrative-row-source" className="font-mono text-[10px] text-slate-500">
                    {row.source_key}
                  </div>
                </td>
                <td className="py-1.5 text-right font-mono text-slate-900">{row.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <Section title="Worth flagging" items={narrative.worth_flagging} />
      <Section title="Next actions" items={narrative.next_actions} />
    </Card>
  );
}

/** Shown while a generation runs, so a call that takes half a minute reads as work, not a hang. */
function GeneratingProgress() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, []);
  const giveUpAfter = Math.round(NARRATIVE_TIMEOUT_MS / 1000);
  const slow = elapsed > NARRATIVE_EXPECTED_SECONDS * 2;
  return (
    <div data-testid="narrative-progress" role="status" aria-live="polite" className="py-6 text-center text-sm text-slate-600">
      <div className="flex items-center justify-center gap-2">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>Generating the narrative… <span className="font-mono" data-testid="narrative-elapsed">{elapsed}s</span></span>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        {slow
          ? `Taking longer than usual. The server retries temporary provider errors, so this can still finish; the request gives up after ${giveUpAfter} seconds.`
          : `This usually takes about ${NARRATIVE_EXPECTED_SECONDS} seconds. The figures below are already calculated.`}
      </p>
    </div>
  );
}

function Section({ title, items }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mt-4">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{title}</div>
      <ul className="mt-1 space-y-1">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2 text-sm text-slate-700">
            <span className="text-slate-500">·</span>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Card({ children }) {
  return (
    <div
      data-testid="narrative-panel"
      className="bg-white border border-[#E5E7EB] rounded-lg p-5 mb-6"
    >
      <div className="mb-3 flex items-center gap-2">
        <FileText className="h-4 w-4 text-slate-500" />
        <h3 className="font-heading text-sm font-semibold text-slate-900">Narrative</h3>
        <span className="text-[10px] font-mono text-slate-500">
          generated · figures verified against the engine
        </span>
      </div>
      {children}
    </div>
  );
}
