Date and branch: 2026-10-21, claude/compassionate-bohr-79zr6u.
Deleted: the old deck scope text and the separate Upload deck button (folded into the upload box); the in-file blocker fetch hook (moved to lib/useBlockers.js).
Decided: contradiction lines render in their own ContradictionBanner under the register heading row, because the register has no separate summary block; the header omits that kind on the Audit page only, other pages unchanged; file type refused in the browser by extension, the picker still filters by accept.
Slow or unclear: the brief names a "Claim register graphic block" that does not exist in main; existing test mocks lacked getBlockers once ClaimRegister fetched blockers.
Root cause and rule: a spec anchor named in the brief was not in the code; check named anchors in the code before editing and report the interpretation.
Process change to propose: briefs name the component or test id of each anchor they refer to.
