Date and branch: 2026-10-31, claude/awesome-newton-l3l4zq.
Deleted: nothing.
Decided: fixture job cap is the first reading plus one fix-request retry (recognised by the "fix" key of the payload), item re-reads and any third call stay refused, tokens now summed over both calls; a sheet reading that fails validation keeps its schema error when the retry fails or is blocked, and its log line says reason=schema_mismatch with the first three errors (path: message, capped), llm_calls keeps parse_failed.
Slow or unclear: the full backend suite takes about 3.5 minutes, past the tool's foreground timeout; waited on its pid instead of polling.
Root cause and rule: the cap's RuntimeError on the retry was classed as a network outage and replaced the schema error; a later failure must never overwrite the first cause, and the test blocks the retry to prove it.
Process change to propose: a log-line reason should come from the first failure of a chain, and every chain with a retry gets a test where the retry itself is blocked.
