import { useState } from "react";
import { toast } from "sonner";
import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { saveFx } from "@/lib/api";
import { FX_HELP } from "@/lib/auditForm";

/** The audit's FX rates, a part of the Audit settings block directly under Reporting currency: one set for the uploaded files and the deck claims,
 * needing no file. Saved as they change; onSaved runs after a save, so the results load again. */
export default function FxEditor({ audit, onSaved }) {
  const baseCcy = audit.reporting_currency || "EUR";
  const [fx, setFxState] = useState({ ...(audit.datasets?.revenue?.fx || {}), ...(audit.fx || {}) });
  const [ccy, setCcy] = useState("");
  const [rate, setRate] = useState("");
  const setFx = async (next) => {
    const before = fx;
    setFxState(next);
    try { await saveFx(audit.id, next); onSaved?.(); } catch (e) { setFxState(before); toast.error("Save failed"); }
  };
  const add = () => {
    if (!ccy.trim() || !parseFloat(rate)) return;
    setFx({ ...fx, [ccy.trim().toUpperCase()]: parseFloat(rate) });
    setCcy(""); setRate("");
  };
  const remove = (k) => { const n = { ...fx }; delete n[k]; setFx(n); };
  return (
    <div className="pt-3 pb-1" data-testid="fx-settings">
      <div className="text-xs text-slate-700 mb-2">
        FX rates to {baseCcy} <span className="text-slate-500">(add a rate for each non-{baseCcy} currency in your revenue lines or in the deck claims)</span>
      </div>
      <div className="flex flex-wrap gap-2 mb-3">
        {Object.entries(fx).map(([k, v]) => (
          <span key={k} className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-sky-50 border border-[#D1D5DB] text-xs font-mono text-slate-800">
            1 {k} = {v} {baseCcy}
            <button onClick={() => remove(k)} className="text-slate-500 hover:text-rose-700"><X className="h-3 w-3" /></button>
          </span>
        ))}
        {Object.keys(fx).length === 0 && <span className="text-xs text-slate-600 font-mono">no FX rates — single-currency assumed</span>}
      </div>
      <div className="flex gap-2 items-center">
        <Input value={ccy} onChange={(e) => setCcy(e.target.value)} placeholder="USD" className="w-24 h-9 bg-white border-[#E5E7EB] font-mono uppercase" data-testid="fx-ccy-input" />
        <span className="text-slate-500 text-sm">=</span>
        <Input value={rate} onChange={(e) => setRate(e.target.value)} placeholder="0.92" type="number" step="0.0001" className="w-28 h-9 bg-white border-[#E5E7EB] font-mono" data-testid="fx-rate-input" />
        <span className="text-slate-500 text-sm">{baseCcy}</span>
        <Button size="sm" variant="outline" onClick={add} className="bg-transparent border-[#D1D5DB] text-slate-800 gap-1"><Plus className="h-3.5 w-3.5" /> Add</Button>
      </div>
      <p className="muted fx-help" data-testid="fx-help" style={{ fontSize: 12, margin: "6px 0 0" }}>{FX_HELP}</p>
    </div>
  );
}
