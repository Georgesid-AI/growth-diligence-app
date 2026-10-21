2026-10-21, claude/lucid-mendel-pwozfp
Deleted: nothing.
Decided: renamed the deck-list AI badge text in the frontend only (badgeText); stored labels and backend logic stay, so no badge timing or register label changes.
Slow or unclear: ruff was not in the backend venv; installed 0.16.8 by pip.
Root cause and rule: two meanings of "Verified" on one screen; badge names what Python did (matched to a page), the register keeps the evidence label.
Process change to propose: add ruff 0.16.8 to the session-start hook.
