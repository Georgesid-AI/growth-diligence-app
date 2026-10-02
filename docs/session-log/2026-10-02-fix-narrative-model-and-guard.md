2026-10-02, fix/narrative-model-and-guard.
Deleted: undocumented LLM_MODEL name (replaced by NARRATIVE_MODEL); nothing else, price table, cache key and footer already carried the model.
Optimized: numeric guard allows the magnitude of negative engine figures only; no prompt change, no release bump.
Slow/unclear: the reported run's payload was not available, so the cause was traced from code (change_arr is sent signed), not from the stored run.
Process change: when reporting an unverified figure, include the run id so the outbound payload can be checked directly.
