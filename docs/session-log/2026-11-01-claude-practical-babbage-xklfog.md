1. 2026-11-01, claude/practical-babbage-xklfog
2. Deleted: the ReportNote placement inside Supporting detail.
3. Decided: ReportNote moved to the end of the page, outside the collapsed block, directly above the final Download report button; component, text and behaviour untouched; test now asserts it is outside details and immediately precedes report-download-end, and that the anomaly flags remain in Supporting detail.
4. Slow or unclear: nothing.
5. Root cause: the note was placed relative to the anomaly flags, which sit in a collapsed block; the test asserted that adjacency instead of visibility. The test now asserts it is outside any details element.
6. Process change: assert visibility (not inside details) for any element meant to be seen without expanding.
