"""A fresh session can run the tests as a contributor would: `pytest` from backend/, no variables set.

Weekly review of 2026-10-07, change 4: three session logs of 2026-10-05 found that `test_audit_validation.py`
could not even be collected until MONGO_URL was exported by hand (`server.py` reads it at import). The
defaults now live in backend/conftest.py, once, so the check below runs pytest's collection in a clean
environment and expects it to succeed.
"""
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_the_suite_collects_with_no_mongo_variables_set():
    env = {k: v for k, v in os.environ.items() if k not in ("MONGO_URL", "DB_NAME")}
    done = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-n", "0", "-p", "no:cacheprovider",
                           "test_audit_validation.py"], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert done.returncode == 0, \
        f"collection needs MONGO_URL or DB_NAME exported by hand:\n{done.stdout}\n{done.stderr}"
    assert "KeyError" not in done.stdout + done.stderr
