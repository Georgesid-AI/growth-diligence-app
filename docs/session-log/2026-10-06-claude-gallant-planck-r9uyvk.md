2026-10-06, claude/gallant-planck-r9uyvk: PR 44 decisions. Ranges stored as one (low, high) item-list range and one approval row; the AI-row dedupe returns exact / in range / no match; match rate also given apart, financial and roadmap.
Denominator change: the consistency report's match rate now counts roadmap figure items (it used to leave every roadmap item out); milestones stay out. Financial and roadmap rates are reported beside it.
Deleted: nothing; the value-keyed dedupe set became a per-cell list of (value, value_high).
Slow or unclear: "the matcher" had two candidates once the verifier stopped comparing values (AI-row dedupe, deck inconsistency check); asked before building.
Process change: when a decision names a component, name the function too (e.g. structures.value_match), so no question round is needed.
