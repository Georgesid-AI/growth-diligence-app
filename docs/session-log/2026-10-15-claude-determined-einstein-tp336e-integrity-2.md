2026-10-15, claude/determined-einstein-tp336e-integrity (fix on PR 4: Opus review, decision 1a)
Deleted: the "Verdict:" line of the narrative panel on the Dashboard (it printed the data-integrity narrative's own verdict beside Python's conclusion).
Decided: the line is removed from the shared narrative panel, since only the data-integrity step carries a verdict; the narrative text, the stored narrative and the model call are untouched (screen change only); the test now asserts that no verdict element and no "Verdict:" text appear.
Slow or unclear: nothing.
Root cause and rule: when PR 4 moved the memo to Python's conclusion it left the model's verdict on the Dashboard, so two integrity conclusions could disagree on one screen; a conclusion is shown from one source on every surface (screen, memo, export), and the step-narrative test pins the screen.
Process change to propose: when a spec replaces a conclusion's source, its file list names every surface that printed the old one.
