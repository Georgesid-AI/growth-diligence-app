2026-10-16, claude/busy-rubin-rhklzo (owner link opens the owner page, not the audits button)
Deleted: the planned backend change (owner gets an empty list or all audits); the spec keeps the owner out of audit routes, so only the page was wrong.
Decided: AccessLink treats a 404 on the audit list followed by a 200 on /admin/prompts as the owner token, renders OwnerPage and does not keep the token in storage; the audits button shows only once the token is known to be a tester's, so it never flashes for the owner.
Slow or unclear: OwnerPage still asks the owner to paste the token (it keeps it in memory only), so the link opens the page but does not sign in; carrying the token over would put it in a component prop, which the owner-page design avoids.
Root cause and rule: the access spec gave the owner 404 on audit routes but nothing said what the owner link page shows; the spec now says it, and a test fails if the owner token renders the button (a deliberate removal of the owner branch failed it).
Process change to propose: when a spec makes a role get 404 on a route, its test table also lists the screen that role sees where the UI would otherwise call that route.
