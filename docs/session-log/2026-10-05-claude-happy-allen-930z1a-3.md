2026-10-05, claude/happy-allen-930z1a.
Deleted: the loose "FY periods convert to calendar periods" wording.
Optimized: periods are now compared by start and end date, so a fiscal and a calendar label match only when they cover the same months; the 3-row header cap names which rows are kept; the year-end edit reuses PUT /audits/{id} and the existing MappingWizard settings.
Slow/unclear: "value at stake" is named in the rule but defined nowhere in the specs or code, and revenue-file comparisons are not built yet.
Process change: before a rule names a downstream use, check that the use is defined in a spec, and link to it or mark it "not built yet".
