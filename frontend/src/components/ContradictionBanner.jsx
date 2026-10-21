import { AlertOctagon } from "lucide-react";
import { useBlockers } from "@/lib/useBlockers";
import { seeGlossary } from "@/lib/glossary";

/**
 * The contradicted top-5 claims (CLAUDE.md rule 21), one red line each, full width of the page content. The Audit page shows
 * them under the claim register's summary and above its table, not in the header. Nothing is rendered when there are none.
 * The server decides what is a blocker; this only shows it.
 */
export default function ContradictionBanner({ auditId }) {
  const lines = useBlockers(auditId).filter((b) => b.kind === "claim_contradicted");
  if (!lines.length) return null;
  return (
    <div data-testid="contradiction-banner" role="alert" className="mb-3 w-full rounded-md border border-rose-300 bg-rose-50">
      <ul className="px-4 py-2 space-y-1">
        {lines.map((b, i) => (
          <li key={`${b.kind}-${i}`} data-testid={`blocker-${b.kind}`} className="flex items-start gap-2 text-sm text-rose-900">
            <AlertOctagon className="h-4 w-4 mt-0.5 shrink-0 text-rose-700" />
            <span>{seeGlossary(b.text)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
