import { LABEL_ORDER, LABEL_DEFINITIONS, LABEL_STYLE, labelDefinition, labelText } from "@/lib/claimRegister";

/** A row's evidence label as a chip; its definition is on hover (docs/design/simplified-flow.md, Evidence labels). While a
 *  Definition check is open the chip reads that, which is not a label and has no definition. */
export function EvidenceLabel({ row, className = "", testId }) {
  return (
    <span title={row.definition_check === "ask" ? undefined : labelDefinition(row.evidence_label)} data-testid={testId}
      className={`text-[10px] font-mono border rounded px-1.5 py-0.5 whitespace-nowrap ${LABEL_STYLE[row.evidence_label] || ""} ${className}`}>
      {labelText(row)}
    </span>
  );
}

/** All five definitions in full, once, under the five findings. */
export function EvidenceDefinitions() {
  return (
    <dl className="mt-3 space-y-0.5 text-[11px] text-slate-600" data-testid="label-definitions">
      {LABEL_ORDER.map((label) => (
        <div key={label} className="flex gap-1.5" data-testid={`label-definition-${label}`}>
          <dt className="font-semibold text-slate-800">{label}</dt>
          <dd>— {LABEL_DEFINITIONS[label]}</dd>
        </div>
      ))}
    </dl>
  );
}
