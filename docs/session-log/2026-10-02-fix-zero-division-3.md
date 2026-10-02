Date: 2026-10-02
Deleted: nothing; the crash was already handled by the NRR <= 0 rule, so only one Missing Data item was added.
Optimized: reproduced through the real upload and compute API with an in-memory DB and a combination sweep, instead of guessing settings.
Slow or unclear: the stated as-of month did not reproduce; the crash needs the as-of month unset and no P&L, which the stored audit must have had.
Process change: show the stored as-of month (and whether it was defaulted) on the dashboard header, so a bug report quotes what the engine actually used.
