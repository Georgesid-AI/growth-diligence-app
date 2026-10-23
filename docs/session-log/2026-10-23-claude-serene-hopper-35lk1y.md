2026-10-23, claude/serene-hopper-35lk1y (rebased on main after #168 and #169)
Deleted: the read counts (pages_read, pages_rejected), the server wiring and the panel line, because main now computes and shows them.
Decided: kept the closed-word reason from the gateway (StructureRead.rejected) and the log line "page n: reply rejected (reason)" per page of a rejected whole reply, with the entry's reason stored; one claim failing a check is dropped alone on main and logged "claim rejected", so the log test sends a reply that is not JSON.
Slow or unclear: nothing; the conflicts were the same feature built twice.
Root cause and rule: a failed validation was recorded as not_read, the same as an outage; a failure with its own cause needs its own closed-word reason from the start, tested in test_gateway_data_boundary.py.
Process change to propose: before drafting a PR on a deck-panel feature, fetch main and check the open brief against merged PRs.
