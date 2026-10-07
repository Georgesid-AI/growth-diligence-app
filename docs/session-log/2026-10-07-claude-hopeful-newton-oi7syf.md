2026-10-07 · claude/hopeful-newton-oi7syf
Deleted: the always-visible consent explainer paragraph (now behind "What is sent"); no code removed otherwise.
Decided: layout asserted on classes in jsdom (no layout engine) plus a one-off Chromium check at 700px and 500px; fix is on the dialog in AuditHub only, shared dialog.jsx untouched so other dialogs do not change.
Slow or unclear: jsdom cannot measure visibility, so the "Create visible at 700px" test is structural, not geometric.
Process change to propose: add a Playwright layout smoke test to CI for dialogs at laptop heights.
