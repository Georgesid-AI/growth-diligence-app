2026-11-02 · claude/intelligent-dirac-ieixue
Deleted: the "Checking figures" step (screen, mockup, spec lines, tests), the header line under the company name, currency and fiscal year-end from More settings, the bold on "Confirmed on column", the old explainer and processing paragraphs.
Decided: the reading counter runs from the first upload the page saw to the last file processed (page state), falling back to the longest single file time after a reload, because the server stores no absolute upload times and the task was screen only; Actual data counts months to the as-of month, falling back to the last month read when none is set.
Slow or unclear: "first upload to last file processed" has no stored source after a reload; the Dashboard's assumptions strip still says "Reporting period" (Audit page, out of scope).
Root cause and rule: the step count was spread over code, mockup, spec and five tests, so a removal touched all of them; rule: wording and step lists live once in lib/uploadView.js and tests read them.
Process change to propose: moved to docs/pr6-cleanup.md or docs/pr6-cleanup-archive.md.
