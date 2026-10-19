import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  S26_lines, S30a_sent, S30B_HEADERS, S30c_checks, S30D_TOO_LONG, S30E_ONE_PERIOD, S30_confidence, LINE_ROLES, LINE_MEANINGS, LINE_BASES,
  meaningName, CONFIRM_ALL, usedText,
} from "@/lib/chatUpload";

/**
 * A P&L read as a statement (docs/specs/chat-upload.md section 26.7): one row per sheet line, in place of the mapping table. Line
 * (as in the file, indented by its level) · Role · Meaning · Basis · Used · Confidence · Checks. Role, Meaning and Basis save on change (one click); a
 * line that waits has Confirm. The server orders the lines: failed checks, then the lines that wait, then sheet order.
 */
export default function SheetMap({ view, decideLines }) {
  const map = view.sheet_map;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const waiting = map.lines.filter((l) => l.pending);
  // Confirm all: every line that waits, in one request.
  const confirmAll = async () => {
    setSaving(true);
    setError(null);
    try {
      await decideLines(view, waiting.map((l) => ({ row: l.row, action: "confirm" })));
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "The decisions could not be saved.");
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="mt-3" data-testid={`sheet-map-${view.dtype}`}>
      <p className="text-xs text-slate-500" data-testid={`sheet-map-caption-${view.dtype}`}>{S26_lines(view)}</p>
      {map.counts && <p className="text-xs text-slate-600 mt-1" data-testid="sheet-map-sent">{S30a_sent(map.counts)}</p>}
      {map.too_long && <p className="text-xs text-amber-700 mt-1" data-testid="sheet-map-too-long">{S30D_TOO_LONG}</p>}
      {map.one_period && <p className="text-xs text-amber-700 mt-1" data-testid="sheet-map-one-period">{S30E_ONE_PERIOD}</p>}
      {waiting.length > 0 && (
        <div className="mt-2">
          <Button size="sm" variant="outline" className="h-7" disabled={saving} data-testid={`lines-confirm-all-${view.dtype}`}
            onClick={confirmAll}>{CONFIRM_ALL}</Button>
          {error && <span className="ml-2 text-xs text-rose-700" data-testid={`lines-confirm-all-error-${view.dtype}`}>{error}</span>}
        </div>
      )}
      <div className="overflow-x-auto mt-2">
        <table className="w-full text-xs" data-testid={`sheet-lines-${view.dtype}`}>
          <thead>
            <tr className="text-left text-slate-500 border-b border-[#E5E7EB]">
              {S30B_HEADERS.map((h) => <th key={h} className="py-1.5 pr-3 font-medium">{h}</th>)}
              <th />
            </tr>
          </thead>
          <tbody>
            {map.lines.map((line) => <LineRow key={line.row} line={line} view={view} decideLines={decideLines} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LineRow({ line, view, decideLines }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const checks = S30c_checks(line);
  const failed = Object.keys(line.checks || {}).some((c) => ["total_mismatch", "no_breakdown", "ytd_mismatch", "ltm_mismatch"].includes(c));
  const send = async (decision) => {
    setSaving(true);
    setError(null);
    try {
      await decideLines(view, [{ row: line.row, ...decision }]);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "The decision could not be saved.");
    } finally {
      setSaving(false);
    }
  };
  const select = (key, options, label) => (
    <select data-testid={`line-${key}-${line.row}`} value={line[key]} disabled={saving} aria-label={`${label} of row ${line.row}`}
      onChange={(e) => send({ action: "change", [key]: e.target.value })}
      className="h-7 rounded border border-[#D1D5DB] bg-white text-xs px-1">
      {options.map((o) => <option key={o} value={o}>{key === "meaning" ? meaningName(o) : o}</option>)}
    </select>
  );
  return (
    <tr className="border-b border-[#F1F5F9] align-top" data-testid={`line-row-${line.row}`} data-pending={line.pending ? "1" : "0"}>
      <td className="py-1.5 pr-3" style={{ paddingLeft: `${(line.indent || 0) * 12}px` }} data-testid={`line-label-${line.row}`}>{line.label}</td>
      <td className="py-1.5 pr-3">{select("role", LINE_ROLES, "Role")}</td>
      <td className="py-1.5 pr-3">{select("meaning", LINE_MEANINGS, "Meaning")}</td>
      <td className="py-1.5 pr-3">{line.basis ? select("basis", LINE_BASES, "Basis") : null}</td>
      <td className="py-1.5 pr-3" data-testid={`line-used-${line.row}`}>{usedText(line)}</td>
      <td className={`py-1.5 pr-3 ${line.pending ? "text-amber-700" : ""}`} data-testid={`line-confidence-${line.row}`}>{S30_confidence(line)}</td>
      <td className={`py-1.5 pr-3 ${failed ? "text-rose-700" : "text-slate-600"}`} data-testid={`line-checks-${line.row}`}>
        {checks.join(" · ")}
        {error && <div className="text-rose-700" data-testid={`line-error-${line.row}`}>{error}</div>}
      </td>
      <td className="py-1.5 whitespace-nowrap">
        {line.pending && (
          <Button size="sm" variant="outline" className="h-7" disabled={saving} data-testid={`line-confirm-${line.row}`}
            onClick={() => send({ action: "confirm" })}>Confirm</Button>
        )}
      </td>
    </tr>
  );
}
