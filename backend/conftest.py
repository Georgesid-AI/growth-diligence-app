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



import pytest  # noqa: E402

TEST_TESTER = "test-suite-tester"


@pytest.fixture(autouse=True)
def tester_token_for_every_route(request):
    """The API tests were written before access links: every /api route now needs a token (docs/specs/access-links.md), so
    the guard answers with a fixed tester here and the tests keep their subject. tests/test_access_links.py marks itself
    `real_access` and runs the real guard; everything the guard decides is tested there."""
    if request.node.get_closest_marker("real_access"):
        yield
        return
    try:
        import server
    except ImportError:                      # a checkout without the API dependencies runs the pure tests only
        yield
        return
    from app import access
    server.app.dependency_overrides[server.access_guard] = lambda: access.Principal(access.TESTER, TEST_TESTER)
    yield
    server.app.dependency_overrides.pop(server.access_guard, None)


def pytest_configure(config):
    config.addinivalue_line("markers", "real_access: run the real access guard instead of the fixed test tester (conftest.py)")
