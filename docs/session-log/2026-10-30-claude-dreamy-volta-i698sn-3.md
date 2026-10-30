2026-10-30, claude/dreamy-volta-i698sn
Deleted: nothing.
Decided: typed an as-of month in three engine configs of test_growth_engine.py that F4 left without one (same fix as the 40 tests of F4); left the case "No as-of month passed" unchanged because it asserts the deleted fallback (16 months with no month), a different cause.
Slow or unclear: test_all_metrics wraps all cases in one item, so the first failing case hides the others; the full suite takes about 3 minutes.
Root cause and rule: F4 changed behaviour and its test sweep missed configs inside test_growth_engine.py; after a behaviour change run run_all() and list every failing case, not the first.
Process change to propose: make test_all_metrics parametrised per case so one failure names all failing cases.
Open: the "No as-of month passed" expectation (None, 16) needs George's decision.
