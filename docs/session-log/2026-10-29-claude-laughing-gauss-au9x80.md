2026-10-29, branch claude/laughing-gauss-au9x80.
Deleted: Target ARR and Target date lines on the audit tile; the old intro tagline.
Decided: new intro text as given; a minimal "Show all lines" toggle in RecognitionLine (it did not exist in code, only in docs/design/simplified-flow.md) hides the Supports/Blocked paragraph and the claims line by default, for revenue and P&L blocks alike.
Slow or unclear: the brief called the toggle "existing"; it was not in the code.
Root cause and rule: design doc described a toggle that was never built; check the code, not the doc, before briefing "existing" UI.
Process change to propose: have specs flag which design-doc items are built.
