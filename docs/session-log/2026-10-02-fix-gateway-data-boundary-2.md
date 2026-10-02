Date: 2026-10-02
Deleted: the free-text [redacted] scrub of founder values, replaced by a neutral reason.
Optimized: one table (_NEUTRAL_REASONS) rewrites both missing-data reasons that quote cell values.
Slow or unclear: the demo run never stores a column header (only management questions do), so that path is covered by the stub test only.
Process change: any new engine reason that interpolates upload content gets a _NEUTRAL_REASONS entry in the same PR.
