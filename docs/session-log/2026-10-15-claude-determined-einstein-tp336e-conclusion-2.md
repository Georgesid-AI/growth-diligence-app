2026-10-15, claude/determined-einstein-tp336e-conclusion (fix on PR 5: decisions 3, 10 and 11)
Deleted: the open "Decisions for you" items of claim-review-conclusion.md (Inconclusive, click limit, Review page).
Decided: the two judgment fields (Reasons, Unresolved questions) are section 8 of the Review page, after the ratings and before Write all narratives, using the Dashboard's own component and the same stored text, so there is one place the text lives; the Generate IC memo button keeps its ratings rule and the server's refusal still names a missing judgment field; Inconclusive counts as untested and the 23-click limit stand as confirmed.
Slow or unclear: nothing.
Root cause and rule: a required input was reachable from one screen while the export button sat on another; a field that gates an export is on every screen that holds the export button (the Review test now pins both fields there).
Process change to propose: each spec lists the screens that hold its inputs next to the screens that hold the action they gate.
