2026-11-04, claude/pensive-cori-70n1we
Deleted: nothing.
Decided: one golden file per contract (yearly and monthly fixtures keyed in it), reusing test_role_engine's synthetic fixtures rather than new ones; the constant is CONTRACT_VERSION (no ENGINE_CONTRACT_VERSION exists); a missing golden file for the current version also fails, so a bump forces regeneration.
Slow or unclear: the request named ENGINE_CONTRACT_VERSION; read as CONTRACT_VERSION in schemas/metrics.py.
Root cause and rule: engine output could change under an unchanged contract version, leaving stored results inconsistent with a re-run; rule 23 now requires the bump and the regenerated golden file.
Process change to propose: have the golden test also cover the legacy blocks (arr, yearly_basis) the map feeds.
