import { blockedText, COVERAGE_COLUMNS, COVERAGE_HEADING, INTEGRITY_HEADING, NO_RESULTS, REQUESTS_HEADING, RESULT_COLUMNS, RESULT_STYLE,
  RESULTS_HEADING } from "@/lib/integrity";

const PLACEHOLDER = "—";

function Table({ columns, testid, children }) {
  return (
    <div className="overflow-x-auto rounded-md border border-[#E5E7EB] bg-white">
      <table className="w-full text-xs" data-testid={testid}>
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500 border-b border-[#E5E7EB]">
            {columns.map((c) => <th key={c} className="py-2 px-3 font-medium whitespace-nowrap">{c}</th>)}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

/** Data integrity (docs/specs/integrity-coverage.md): the conclusion Python computes, the results of the checks that ran, and the
 *  coverage of all six checks with the data each blocked one needs. `integrity` is GET /audits/{id}/integrity. */
export default function IntegrityCoverage({ integrity }) {
  if (!integrity) return null;
  const blocked = blockedText(integrity);
  return (
    <section className="mb-6" data-testid="integrity">
      <h2 className="font-heading text-lg font-semibold text-slate-900">{INTEGRITY_HEADING}</h2>
      <p className="mt-1 text-sm font-semibold text-slate-900" data-testid="integrity-conclusion">{integrity.conclusion}</p>
      <p className="text-xs text-slate-600 font-mono" data-testid="integrity-completed">{integrity.completed_text}</p>
      {blocked && <p className="text-xs text-slate-600" data-testid="integrity-blocked">{blocked}</p>}
      {integrity.memo_sentence && <p className="text-xs text-slate-500 mt-1" data-testid="integrity-note">{integrity.memo_sentence}</p>}

      <h3 className="mt-4 mb-2 text-sm font-semibold text-slate-800">{RESULTS_HEADING}</h3>
      {integrity.results?.length ? (
        <Table columns={RESULT_COLUMNS} testid="integrity-results">
          {integrity.results.map((r) => (
            <tr key={r.check} className="border-b border-[#F1F5F9] align-top">
              <td className="py-2 px-3 text-slate-900 whitespace-nowrap">{r.check}</td>
              <td className={`py-2 px-3 font-mono ${RESULT_STYLE[r.result] || ""}`}>{r.result}</td>
              <td className="py-2 px-3 text-slate-700 min-w-[16rem]">{r.finding}</td>
              <td className="py-2 px-3 font-mono text-[11px] text-slate-500">{r.source || PLACEHOLDER}</td>
            </tr>
          ))}
        </Table>
      ) : <p className="text-xs text-slate-600" data-testid="integrity-results-none">{NO_RESULTS}</p>}

      <h3 className="mt-4 mb-2 text-sm font-semibold text-slate-800">{COVERAGE_HEADING}</h3>
      <Table columns={COVERAGE_COLUMNS} testid="integrity-coverage">
        {(integrity.coverage || []).map((r) => (
          <tr key={r.check} className="border-b border-[#F1F5F9] align-top">
            <td className="py-2 px-3 text-slate-900 whitespace-nowrap">{r.check}</td>
            <td className="py-2 px-3 text-slate-700 whitespace-nowrap">{r.status}</td>
            <td className="py-2 px-3 text-slate-600">{r.reason || PLACEHOLDER}</td>
          </tr>
        ))}
      </Table>
      {integrity.data_requests?.length > 0 && (
        <div className="mt-3 text-xs text-slate-700" data-testid="integrity-requests">
          <div className="font-semibold text-slate-800">{REQUESTS_HEADING}</div>
          <ul className="list-disc pl-5">{integrity.data_requests.map((d) => <li key={d}>{d}</li>)}</ul>
        </div>
      )}
    </section>
  );
}
