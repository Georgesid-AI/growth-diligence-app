import { Provenance } from "./Provenance";

const STATUS = {
  growth_positive: "text-emerald-400",
  warning: "text-amber-400",
  critical: "text-rose-400",
  neutral: "text-slate-100",
};

export function MetricCard({ id, label, value, source, sub, status = "neutral", note, caption }) {
  return (
    <div
      data-testid={`metric-card-${id}`}
      className="bg-[#111726] border border-[#1E293B] rounded-lg p-5 hover:border-[#334155] transition-colors relative"
    >
      <div className="text-[11px] uppercase tracking-wider text-slate-400 font-mono font-semibold mb-2">{label}</div>
      <div className={`text-3xl font-mono font-bold tracking-tight ${STATUS[status]}`}>
        <Provenance source={source} id={id}>
          {value}
        </Provenance>
      </div>
      {sub && <div className="text-xs text-slate-400 mt-2 font-mono">{sub}</div>}
      {note && <div className="text-[11px] text-slate-500 mt-1">{note}</div>}
      {/* Static plain-language caption — always visible, never computed. */}
      {caption && <div className="text-[11px] text-slate-500 mt-1.5 italic">{caption}</div>}
    </div>
  );
}
