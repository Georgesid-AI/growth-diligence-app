import { useEffect, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Activity, ChevronDown, Terminal } from "lucide-react";
import { fmtCurrency } from "@/lib/format";
import { evidenceToText } from "@/lib/periods";
import BlockerBanner from "@/components/BlockerBanner";

export function Layout({ audit, children }) {
  const nav = useNavigate();
  const loc = useLocation();
  const id = audit?.id;

  // The flow: Run audit, then Review. Every earlier page stays reachable, step by step, under Details.
  const tabs = id
    ? [
        { key: "run", label: "Run audit", to: `/audit/${id}/run`, testid: "nav-tab-run-audit" },
        { key: "review", label: "Review", to: `/audit/${id}/review`, testid: "nav-tab-review" },
      ]
    : [];
  const details = id
    ? [
        { key: "dashboard", label: "Growth Dashboard", to: `/audit/${id}/dashboard`, testid: "nav-tab-growth-dashboard" },
        { key: "mapping", label: "Upload & Mapping", to: `/audit/${id}/mapping`, testid: "nav-tab-mapping-wizard" },
        { key: "diagnostics", label: "Diagnostics", to: `/audit/${id}/diagnostics`, testid: "nav-tab-missing-data" },
      ]
    : [];
  const [detailsOpen, setDetailsOpen] = useState(false);
  const inDetails = details.some((t) => t.to === loc.pathname);
  const detailsRef = useRef(null);
  const detailsButton = useRef(null);

  // The menu closes on a click outside it, on Escape (focus returns to the button) and after an item is chosen.
  useEffect(() => {
    if (!detailsOpen) return undefined;
    const onPointer = (e) => { if (detailsRef.current && !detailsRef.current.contains(e.target)) setDetailsOpen(false); };
    const onKey = (e) => { if (e.key === "Escape") { setDetailsOpen(false); detailsButton.current?.focus(); } };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onPointer); document.removeEventListener("keydown", onKey); };
  }, [detailsOpen]);

  return (
    <div className="min-h-screen bg-white">
      <header className="sticky top-0 z-50 bg-white/90 backdrop-blur-md border-b border-[#E5E7EB]">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center justify-between gap-4">
          <button
            data-testid="nav-tab-audit-list"
            onClick={() => nav("/")}
            className="flex items-center gap-2.5 group"
          >
            <div className="h-8 w-8 rounded-md bg-sky-600/20 border border-sky-500/40 flex items-center justify-center">
              <Terminal className="h-4 w-4 text-sky-700" />
            </div>
            <div className="text-left">
              <div className="font-heading font-bold tracking-tight text-sm text-slate-900 leading-none group-hover:text-sky-800 transition-colors">
                GROWTH DILIGENCE
              </div>
              <div className="text-[9px] uppercase tracking-widest text-slate-500 font-mono mt-0.5">
                Deterministic Engine v1.0
              </div>
            </div>
          </button>

          {tabs.length > 0 && (
            <nav className="hidden md:flex items-center gap-1">
              {tabs.map((t) => {
                const active = loc.pathname === t.to;
                return (
                  <button
                    key={t.key}
                    data-testid={t.testid}
                    onClick={() => nav(t.to)}
                    className={`px-3.5 py-1.5 rounded-md text-sm font-medium transition-colors ${
                      active ? "bg-sky-50 text-slate-900" : "text-slate-600 hover:text-slate-800 hover:bg-slate-50"
                    }`}
                  >
                    {t.label}
                  </button>
                );
              })}
              <div className="relative" ref={detailsRef}>
                <button
                  ref={detailsButton}
                  data-testid="nav-details"
                  aria-expanded={detailsOpen}
                  aria-haspopup="menu"
                  onClick={() => setDetailsOpen((v) => !v)}
                  className={`inline-flex items-center gap-1 px-3.5 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    inDetails ? "bg-sky-50 text-slate-900" : "text-slate-600 hover:text-slate-800 hover:bg-slate-50"
                  }`}
                >
                  Details <ChevronDown className="h-3.5 w-3.5" />
                </button>
                {detailsOpen && (
                  <div role="menu" data-testid="details-menu" className="absolute right-0 mt-1 w-52 rounded-md border border-[#E5E7EB] bg-white py-1 shadow-lg">
                    {details.map((t) => (
                      <button
                        key={t.key}
                        role="menuitem"
                        data-testid={t.testid}
                        onClick={() => { setDetailsOpen(false); nav(t.to); }}
                        className={`block w-full text-left px-3.5 py-2 text-sm hover:bg-slate-50 ${loc.pathname === t.to ? "bg-sky-50 text-slate-900" : "text-slate-700"}`}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </nav>
          )}

          <div className="flex items-center gap-3">
            {audit && (
              <div className="hidden sm:block text-right">
                <div className="text-xs font-medium text-slate-800 truncate max-w-[220px]">{audit.company_name}</div>
                <div className="text-[10px] font-mono text-slate-500" data-testid="header-target-line">
                  {audit.reporting_currency} · {Number(audit.target_arr) ? `target ${fmtCurrency(audit.target_arr, audit.reporting_currency)} ARR` : "target not set"}
                  {/* the data's own end, never the as-of setting (docs/specs/dates-and-periods.md section 2) */}
                  {audit.results?.source_period ? ` · evidence to ${evidenceToText(audit.results)}` : ""}
                </div>
              </div>
            )}
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30">
              <Activity className="h-3 w-3 text-emerald-700 animate-pulse" />
              <span className="text-[10px] font-mono text-emerald-700 uppercase tracking-wide">0% Heuristics</span>
            </div>
          </div>
        </div>
        {id && <BlockerBanner key={`${id}-${loc.pathname}`} auditId={id} />}
      </header>
      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-6">{children}</main>
    </div>
  );
}
