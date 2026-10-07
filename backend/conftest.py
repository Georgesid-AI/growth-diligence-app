"""Test-session defaults for the two variables `server.py` reads at import.

`server` needs MONGO_URL and DB_NAME before any test can import it, and a plain `pytest` in a fresh
checkout has neither (three session logs of 2026-10-05 lost time to the KeyError). The defaults here
run before any test module is imported, so no test file needs its own. Nothing connects: the Motor
client is lazy, and the API tests use a fake database. `server.py` itself stays strict, so a deployment
with no MONGO_URL still fails at start instead of talking to localhost.
"""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "growth_diligence_test")
