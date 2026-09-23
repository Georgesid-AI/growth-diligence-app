import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { FileSpreadsheet } from "lucide-react";

/**
 * Wraps a value so hovering reveals its exact source lineage (file / sheet / rows / rule).
 * source = { file, sheet, rows, rule }
 */
export function Provenance({ source, children, id }) {
  if (!source) return <span className="tabular">{children}</span>;
  return (
    <HoverCard openDelay={80} closeDelay={40}>
      <HoverCardTrigger asChild>
        <span
          data-testid={id ? `provenance-hover-${id}` : undefined}
          className="tabular cursor-help decoration-dotted underline-offset-4 underline decoration-sky-500/50 hover:decoration-sky-400"
        >
          {children}
        </span>
      </HoverCardTrigger>
      <HoverCardContent
        data-testid={id ? `provenance-popover-${id}` : undefined}
        align="start"
        className="w-80 border-[#38BDF8]/60 bg-[#0F172A] text-slate-200 shadow-xl"
      >
        <div className="flex items-center gap-2 mb-2">
          <FileSpreadsheet className="h-4 w-4 text-sky-400" />
          <span className="text-[11px] uppercase tracking-wider font-mono text-sky-400 font-semibold">
            Source Lineage
          </span>
        </div>
        <dl className="space-y-1.5 text-xs">
          <Row label="File" value={source.file} mono />
          <Row label="Sheet" value={source.sheet} mono />
          <Row label="Rows" value={source.rows} mono />
          {source.rule && (
            <div className="pt-2 mt-2 border-t border-slate-700">
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Deterministic rule</div>
              <p className="text-[11px] leading-relaxed text-slate-300">{source.rule}</p>
            </div>
          )}
        </dl>
      </HoverCardContent>
    </HoverCard>
  );
}

function Row({ label, value, mono }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-slate-500">{label}</dt>
      <dd className={`text-slate-200 text-right ${mono ? "font-mono" : ""}`}>{value || "—"}</dd>
    </div>
  );
}
