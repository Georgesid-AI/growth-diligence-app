One file per feature. The agreed scope. Prompts point here.

## Bug request template (CLAUDE.md rule 13)

A bug request carries these four fields. The session starts with a failing test built from them.

1. Run id.
2. Stored audit settings as the engine used them: as-of month and whether it was defaulted,
   target date, P&L present.
3. The anonymised upload, or the one server log line (error type, run id, engine step).
4. What was observed, not what is suspected.

## A rule that names a deck outcome (weekly review of 2026-10-07)

Measure before the spec commit. A decision that cites a deck names the page and the position of its example
("moz p20, the label beside the value"). The spec line that states the rule carries the count it is expected to
produce on the 10 public test decks ("buffer p6: 7 of 7 figures dated"), measured on the branch with
`python scripts/consistency_run.py --probe --deck 03-buffer.pptx --page 6` (no network, no MongoDB; public decks
only), and the spec commit follows the measurement. The order spec, failing test, code is unchanged. A rule whose
measured count disagrees with the decision's stated outcome goes back as a question before anything is committed.
