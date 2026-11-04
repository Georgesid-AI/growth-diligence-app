Date: 2026-10-02
Deleted: the narrow NRR-0 "ARR change per NRR point" branch and its Missing item; the NRR <= 0 rule covers both.
Optimized: dashboard anomaly rows moved into one pure helper (gapLists.anomalyFlags) that the null case can test.
Slow or unclear: the reported settings did not reproduce on demo data and no file was attached; frontend Jest could not run (npm registry blocked by network policy).
Process change to propose: moved to docs/pr6-cleanup.md.
