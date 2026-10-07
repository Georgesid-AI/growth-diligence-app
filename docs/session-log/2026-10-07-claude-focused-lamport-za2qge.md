2026-10-07, claude/focused-lamport-za2qge: docs/specs/claim-matching.md built (two engine series, matching module, register rows, claims.csv, Claim register screen, boundary tests).
Deleted: nothing from the product; two tests I drafted (CSV formula-escaping, a duplicated suggestion branch) as outside the spec.
Decided: one pure module (app/claim_matching.py) computed on read from stored results; the analyst's inputs sit on the candidate row under claim_inputs[claim_id]; the screen's metric list is a JSON file pinned to the module by a test; extra fixture run D covers the table 2a metrics run A lacks, so run A's ranks stay as the spec states them.
Slow or unclear: several points the spec leaves open (listed as Open questions in the PR); the repeated-pkill of a server killed my own shell once.
Process change: when a spec lists a fixture table, also list which table-2a metrics it leaves uncovered, so the extra fixture rows are agreed rather than added.
