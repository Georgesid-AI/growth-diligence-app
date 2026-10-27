Date and branch: 2026-10-27, claude/awesome-fermat-qm04s2.
Deleted: nothing.
Decided: the shared extraction-confidence explainer and the label-mismatch question now read George's wording in the tests, the backend constant and the docs that pinned the old text; claims_list_texts.json untouched.
Slow or unclear: the explainer was pinned in nine places (JSON, backend constant, two test files, three docs); no single source for the backend constant.
Root cause and prevention: wording lived as copies in tests and docs; a wording change must grep for the old sentence across the repo before the tests run.
Process change to propose: have the backend test read the explainer from evidence_labels.json instead of repeating the sentence.
