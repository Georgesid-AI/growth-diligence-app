2026-10-14, claude/lucid-franklin-y2bl4b
Deleted: nothing.
Decided: re-arm `alive.current = true` in the mount effect of Review, RunAudit, AuditHub (same form as DeckPanel); added "review" and "run" to UsageEvent.screen and the usage line in docs/specs/chat-upload.md, as asked.
Slow or unclear: the full backend suite takes about two minutes, so it must run in the background; polling with pgrep on "pytest" matches its own watcher and never ends.
Root cause and rule: an unmount-only cleanup sets a ref false and nothing sets it true again, so StrictMode's mount-unmount-mount leaves it false; every ref flag cleared on unmount is set true in the same effect, and each page has a StrictMode test.
Process change to propose: render page tests inside React.StrictMode by default, as index.js does.
