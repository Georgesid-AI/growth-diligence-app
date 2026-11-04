Date: 2026-10-02
Deleted: nothing; the crash was already handled by the NRR <= 0 rule, so only one Missing Data item was added.
Optimized: reproduced through the real upload and compute API with an in-memory DB and a combination sweep, instead of guessing settings.
Slow or unclear: the stated as-of month did not reproduce; the crash needs the as-of month unset and no P&L, which the stored audit must have had.
Process change to propose: moved to docs/pr6-cleanup.md or docs/pr6-cleanup-archive.md.
