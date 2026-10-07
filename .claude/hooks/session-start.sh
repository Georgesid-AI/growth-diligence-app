#!/bin/bash
# SessionStart hook for Claude Code cloud sessions (weekly review of 2026-10-07, change 4).
# Installs what the tests need once per container, so no session builds a venv or shims the JS runner by hand.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
VENV="$ROOT/backend/.venv"

# Backend: a virtualenv, because pip into the container's Python collides with Debian-managed packages
# (PyYAML). The venv goes first on PATH for the whole session, so `python`, `pip` and `pytest` resolve to it.
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$VENV/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi
echo "backend: $("$VENV/bin/python" --version), requirements installed in backend/.venv"

# Frontend: `yarn install` needs registry.yarnpkg.com, which the environment's network policy must allow
# (owner action). A refused registry must not fail the hook: the backend is still usable.
if (cd "$ROOT/frontend" && timeout 600 yarn install --frozen-lockfile --non-interactive --network-timeout 60000 \
    > /tmp/yarn-install.log 2>&1); then
  echo "frontend: packages installed, \`yarn test\` runs under craco"
else
  echo "frontend: packages NOT installed (registry refused or offline; see /tmp/yarn-install.log)." \
       "JS tests cannot run until the environment allows registry.yarnpkg.com."
fi
