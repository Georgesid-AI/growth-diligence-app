Date and branch: 2026-10-27, claude/page-image-reading-impl-y3u3iy.
Deleted: the gateway constant PAGE_IMAGE_RULE and the "no_image" refusal; the "not read" outcome for a deck that cannot be drawn.
Decided: a deck or page with no image goes as text alone and the deck panel says "page images unavailable for this file; text only" (deck field images_unavailable, kept by a retry run); the printed-values-only wording lives only in the stored deck_reading prompt; architecture.md paragraphs follow rule 16; Upload explainer ends with the storage sentence (the disclosure line stays word for word).
Slow or unclear: pip install of the backend requirements took ~10 minutes in this container and the first attempt hung inside a venv in the scratchpad; the second, in backend/.venv, finished in under two minutes.
Root cause and rule: the image requirement was enforced as a refusal in the gateway instead of degrading (rule 20 applies to any new input to the model); rule 14 caught two log lines formatting exc.reason, so log lines carry no exception attributes.
Process change to propose: a one-line setup note in CLAUDE.md for the backend venv and the pinned ruff, so sessions do not rediscover it.
