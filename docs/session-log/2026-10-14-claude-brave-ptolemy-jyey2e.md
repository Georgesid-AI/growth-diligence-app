2026-10-14, claude/brave-ptolemy-jyey2e
Deleted: nothing; the four Review reads lost their silent `.catch(() => null)` for audit and review.
Decided: Review shows the error (describeRequestError), Retry and a link to the audit list when getAudit or getReview fails; the four reads it opens with have a 30 s timeout (READ_TIMEOUT_MS), as axios had none, so a hung request spun forever.
Slow or unclear: part 2 (500 from /review on audits from before #95) does not reproduce: the pre-#95 TestCo candidates return 200 and `qualifier` is already read with .get(); backend not changed, waiting for the artefact (rule 13).
Root cause and rule: a read the screen stands on was turned into null by a shared "safe" helper; spinner state was derived from null. Rule: a null that means "failed" and a null that means "not loaded yet" must not be the same value.
Process change to propose: the bug task template names the artefact (run id or server log line) so rule 13 can start from it.
