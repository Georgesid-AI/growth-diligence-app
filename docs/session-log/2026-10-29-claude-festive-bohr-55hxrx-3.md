Date and branch: 2026-10-29, claude/festive-bohr-55hxrx (two fixes on PR 204: unknown company names, people-header scope).
Deleted: the [person] fallback for a company under a "... name" header, and the people-header rule on deck page text.
Decided: the gateway (pages) and the sheet and deck-structure callers add unmapped names under a company-name header to the token map before masking; the header must be the word itself with at most two words before and "name" or "list" after, and a cell with a digit is a label, not a name (a looser pattern tokenised KPI labels in the moz deck).
Slow or unclear: pages are one flat column of lines, so a title "Customers" makes every name-shaped line below it a name; file-type, recognition and column-mapping callers do not learn names yet.
Root cause and rule: the header pattern was a word search, so "Implied Customer Life" counted as a header; header patterns are anchored and a false-positive test sits beside the rule (rule 14 file).
Process change to propose: run the deck fixture tests (moz) after any change to a masking pattern, since their replies are keyed on the sent text.
