2026-10-05, claude/gallant-planck-r9uyvk: structure labelling (Python lists the items, the model labels them), spec steps 1-8, each rule test-first and broken once on purpose.
Deleted: model value matching (match_value, value_matches, period_matches, rebuilt_label, _rebuild, same_number), cited period cells, the redundant item-id and pair-id regexes, the "value not in cell" and "lowest-header rule" reasons.
Optimized: one figure finder (verify.figures) serves the verifier and the item list; cell lines and item raw text share one normalised cell text, so no item line can fall outside its cell.
Slow or unclear: steps 3-6 could not each end green (fixtures moved to step 4); the yarn and npm registries answer 403 here, so frontend tests ran under a Node shim; a range ("$12 -$13 million") is not in "today's normalisation".
Process change: a spec that changes a reply format names the fixture rewrite in the step that first consumes the format, so every step can end green.
