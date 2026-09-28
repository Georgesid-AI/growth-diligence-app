import { Loader2, Sparkles, RefreshCw } from "lucide-react";

/**
 * The generate / regenerate control and its explanation.
 *
 * Spending is always an explicit act here. Opening an audit reads whatever was
 * already written (no AI request); this button is the only thing that costs one,
 * and the helper text says so before the reader commits to it rather than after.
 */
export function NarrativeControl({ status, generatedAt, superseded, busy, onGenerate }) {
  const hasNarrative = status === "ok" || status === "flagged";

  if (hasNarrative) {
    return (
      <div className="mb-6" data-testid="narrative-control">
        <button
          type="button"
          data-testid="narrative-regenerate"
          onClick={onGenerate}
          disabled={busy}
          className="inline-flex items-center gap-1.5 text-sm text-sky-700 underline underline-offset-2 hover:text-sky-800 disabled:cursor-not-allowed disabled:text-slate-400 disabled:no-underline"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          {busy ? "Regenerating…" : "Regenerate"}
        </button>
        <p className="mt-1.5 text-xs text-slate-500">
          Written {formatWrittenDate(generatedAt)}. Only regenerate if the data has
          changed — it costs another AI request.
        </p>
      </div>
    );
  }

  return (
    <div className="mb-6" data-testid="narrative-control">
      <button
        type="button"
        data-testid="narrative-generate"
        onClick={onGenerate}
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-md border border-[#D1D5DB] bg-white px-3.5 py-2 text-sm font-medium text-slate-900 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4 text-sky-700" />}
        {busy ? "Generating…" : "Generate narrative"}
      </button>
      <p data-testid="narrative-helper" className="mt-1.5 max-w-2xl text-xs text-slate-500">
        {superseded ? (
          // One was written, but for numbers that have since changed. Say so:
          // the reader may remember reading it and wonder where it went.
          <>
            The data changed since the last summary was written, so it no longer
            applies. Generate a new one when you're ready.
          </>
        ) : (
          <>
            Writes a short summary of the numbers below, in plain English. The numbers
            themselves are calculated by the app, not written by AI. Costs one AI request —
            after that you can open this audit as often as you like for free.
          </>
        )}
      </p>
    </div>
  );
}

/**
 * "2026-09-28T10:00:00Z" -> "28 Sep 2026".
 *
 * Built from the UTC parts rather than the viewer's locale, so the date shown
 * is the date the narrative was actually written and does not shift by timezone.
 */
export function formatWrittenDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${date.getUTCDate()} ${months[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}
