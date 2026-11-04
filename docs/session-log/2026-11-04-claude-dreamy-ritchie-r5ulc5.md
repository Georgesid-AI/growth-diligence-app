date and branch: 2026-11-04, claude/dreamy-ritchie-r5ulc5
deleted: the FX block from More settings on the mapping page (FxSettings, FxEditor, fxVersion in MappingWizard.jsx) and its three tests there.
decided: FX editor now lives in components/FxEditor.jsx and renders inside Audit settings under Reporting currency (it was in More settings, not in Audit settings, so the move was needed to meet item 1); Fiscal year-end first, a spacer line, then currency; help text is the constant FX_HELP in lib/auditForm.js; a saved rate reloads results through ReadingScreen's own reload instead of a reloadKey.
slow or unclear: the request read as display-only but the FX block was in a different component, so this is a move, not a reorder.
root cause and rule: none (display change); the order and help text are now asserted in ReadingScreen.test.jsx.
Process change to propose: moved to docs/pr6-cleanup.md or docs/pr6-cleanup-archive.md.
