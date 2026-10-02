Date: 2026-10-02
Deleted: logger.exception (message + traceback) from the auto-recompute handler.
Optimized: the engine step comes from the traceback's function names, so no step tracking was added to the engine.
Slow or unclear: "run_id" here is the audit id (the gateway uses the audit id as run id); confirmed in gateway.py before using it.
Process change: make "no exception text in logs" a CLAUDE.md rule, so new handlers start safe instead of being fixed in review.
