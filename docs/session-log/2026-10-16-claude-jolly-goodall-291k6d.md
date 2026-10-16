2026-10-16, claude/jolly-goodall-291k6d (full-link page for bare and rejected /t/ links)
Deleted: nothing; no form, input or link on the new page, so nothing to build for them.
Decided: the page asks GET /api/audits with the token and switches to the full-link page only on a 401, so the Welcome page renders as before for valid tokens and for any non-401 answer (a network error must not tell a tester their link is bad); /t is one route component, no new file.
Slow or unclear: the bare-path test renders the component, not the router (App.js is not mounted in any test); a rejected token stays in localStorage (not asked to clear it).
Root cause and rule: the spec had no case for a bare or rejected link, so a tester saw an empty or misleading Welcome page; the spec now lists both cases and each has a test (a deliberate 401 violation failed the rejected-link test).
Process change to propose: every route a spec adds states its failure answers (bare, rejected, expired) in the spec's test table, so the screen for each is decided before the code.
