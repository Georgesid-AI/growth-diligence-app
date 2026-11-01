import { useNavigate, useLocation } from "react-router-dom";
import { LayoutList, Terminal } from "lucide-react";
import { fmtCurrency } from "@/lib/format";
import { STALE_LABEL } from "@/lib/deckClaims";
import { evidenceToText } from "@/lib/periods";
import BlockerBanner from "@/components/BlockerBanner";
import AllowanceBanner from "@/components/AllowanceBanner";

export function Layout({ audit, children }) {
  const nav = useNavigate();
  const loc = useLocation();
  const id = audit?.id;

  // The three pages of an open audit; Review left the menu, its open questions are a card on the Audit page (docs/design/simplified-flow.md), in the order of the work (docs/specs/chat-upload.md section 24).
  const tabs = id
    ? [
        { key: "mapping", label: "Upload", to: `/audit/${id}/mapping`, testid: "nav-tab-mapping-wizard" },
        { key: "dashboard", label: "Audit", to: `/audit/${id}/dashboard`, testid: "nav-tab-audit" },
        { key: "diagnostics", label: "Diagnostics", to: `/audit/${id}/diagnostics`, testid: "nav-tab-missing-data" },
      ]
    : [];

  return (
    <div className="min-h-screen bg-white">
      <header className="sticky top-0 z-50 bg-white/90 backdrop-blur-md border-b border-[#E5E7EB]">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
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
            {id && (
              <button
                data-testid="nav-all-audits"
                onClick={() => nav("/")}
                className="inline-flex items-center gap-1.5 rounded-md border border-[#E5E7EB] px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 hover:text-slate-900"
              >
                <LayoutList className="h-3.5 w-3.5" /> All audits
              </button>
            )}
          </div>

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
            </nav>
          )}

          <div className="flex items-center gap-3">
              {audit && (
                <div className="hidden sm:block text-right">
                  <div className="text-xs font-medium text-slate-800 truncate max-w-[220px]">{audit.company_name}</div>
                  <div className="text-[10px] font-mono text-slate-500" data-testid="header-target-line">
                    {audit.reporting_currency} · {Number(audit.target_arr) ? `target ${fmtCurrency(audit.target_arr, audit.reporting_currency)} ARR` : "target not set"}
                    {/* the data's own end, never the as-of setting (docs/specs/dates-and-periods.md section 2) */}
                    {audit.results_stale ? ` · ${STALE_LABEL}` : audit.results?.source_period ? ` · evidence to ${evidenceToText(audit.results)}` : ""}
                  </div>
                </div>
              )}
          </div>
        </div>
        {id && <BlockerBanner key={`${id}-${loc.pathname}`} auditId={id} omit={loc.pathname.endsWith("/dashboard") ? ["claim_contradicted"] : []} />}
      </header>
      <AllowanceBanner key={loc.pathname} />
      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-6">{children}</main>
    </div>
  );
}
