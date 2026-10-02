Date: 2026-10-02
Deleted: the `.get("stage", "")` fallback that crashed on a missing column; nothing else.
Optimized: the ratio reason goes through the existing missing_data path, so no gateway allowlist change was needed.
Slow or unclear: "unparseable date" never reaches the engine raw (normalize coerces to NaT), and the release pin tests had to move with the prompt bump.
Process change: when a request bumps a prompt release, say that the release-pin tests move with it.
