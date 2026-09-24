import { useNavigate, useLocation } from "react-router-dom";
import { Activity, Terminal } from "lucide-react";
import { money } from "@/lib/format";

export function Layout({ audit, children }) {
  const nav = useNavigate();
  const loc = useLocation();
  const id = audit?.id;

  const tabs = id
    ? [
        { key: "dashboard", label: "Growth Dashboard", to: `/audit/${id}/dashboard`, testid: "nav-tab-growth-dashboard" },
        { key: "mapping", label: "Upload & Mapping", to: `/audit/${id}/mapping`, testid: "nav-tab-mapping-wizard" },
        { key: "diagnostics", label: "Diagnostics", to: `/audit/${id}/diagnostics`, testid: "nav-tab-missing-data" },
      ]
    : [];

  return (
    <div className="min-h-screen bg-[#0B0F17]">
      <header className="sticky top-0 z-50 bg-[#0B0F17]/90 backdrop-blur-md border-b border-[#1E293B]">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center justify-between gap-4">
          <button
            data-testid="nav-tab-audit-list"
            onClick={() => nav("/")}
            className="flex items-center gap-2.5 group"
          >
            <div className="h-8 w-8 rounded-md bg-sky-600/20 border border-sky-500/40 flex items-center justify-center">
              <Terminal className="h-4 w-4 text-sky-400" />
            </div>
            <div className="text-left">
              <div className="font-heading font-bold tracking-tight text-sm text-white leading-none group-hover:text-sky-300 transition-colors">
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
                      active ? "bg-[#1D2840] text-white" : "text-slate-400 hover:text-slate-200 hover:bg-[#161F33]"
                    }`}
                  >
                    {t.label}
                  </button>
                );
              })}
            </nav>
          )}

          <div className="flex items-center gap-3">
            {audit && (
              <div className="hidden sm:block text-right">
                <div className="text-xs font-medium text-slate-200 truncate max-w-[220px]">{audit.company_name}</div>
                <div className="text-[10px] font-mono text-slate-500">
                  {audit.reporting_currency} · target {money(audit.target_arr, audit.reporting_currency)} ARR
                  {audit.as_of_month ? ` · as of ${audit.as_of_month}` : ""}
                </div>
              </div>
            )}
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30">
              <Activity className="h-3 w-3 text-emerald-400 animate-pulse" />
              <span className="text-[10px] font-mono text-emerald-400 uppercase tracking-wide">0% Heuristics</span>
            </div>
          </div>
        </div>
      </header>
      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-6">{children}</main>
    </div>
  );
}
