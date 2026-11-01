"""OLD_CLAIMS (read-check-review.md section 12; PR 4): the claim register, the five-claims conclusion, the three reasons, the key gates, the claim
labels and "claim questions open" leave the default screen and the downloaded report. They stay in the code behind the flag. This module tests the
default (off) and the flag on; every other module runs with the flag on (conftest.old_claims_on_unless_testing_the_default)."""
import pytest

pytest.importorskip("fastapi")

from test_run_audit import AUDIT, ready_for_review  # noqa: E402

TESTS_THE_DEFAULT = True

CLAIM_WORDS = ("Verdict:", "Reasons:", "Other contradictions:", "Key gate", "claims Verified", "Claims: ", "Contradicted", "Unverified", "Top 5",
               "Top-5 claim contradicted")


def memo(client):
    r = client.get(f"/api/audits/{AUDIT}/memo.md")
    assert r.status_code == 200, r.text
    return r.text


def test_the_flag_is_off_unless_it_says_on(monkeypatch):
    from app import flags
    monkeypatch.delenv("OLD_CLAIMS", raising=False)
    assert flags.old_claims() is False
    for value in ("off", "OFF", "", "true", "1", "yes"):
        monkeypatch.setenv("OLD_CLAIMS", value)
        assert flags.old_claims() is False, value
    monkeypatch.setenv("OLD_CLAIMS", "on")
    assert flags.old_claims() is True


def test_the_audit_tells_the_screen_whether_the_old_claims_show(run_api, monkeypatch):
    assert run_api.get(f"/api/audits/{AUDIT}").json()["old_claims"] is False
    monkeypatch.setenv("OLD_CLAIMS", "on")
    assert run_api.get(f"/api/audits/{AUDIT}").json()["old_claims"] is True


def test_the_downloaded_report_holds_no_claim_register_conclusion_reasons_gates_or_labels(run_api):
    ready_for_review(run_api)
    text = memo(run_api)
    for word in CLAIM_WORDS:
        assert word not in text, f"{word!r} is in the report with OLD_CLAIMS off"
    assert "Not part of this report." in text, "the claim appendix says so instead of listing claims"
    assert "Deal thesis" in text and "Data reliability" in text, "the rest of the report is there"


def test_the_report_with_the_flag_on_is_the_one_with_claims(run_api, monkeypatch):
    ready_for_review(run_api)
    monkeypatch.setenv("OLD_CLAIMS", "on")
    text = memo(run_api)
    assert "Verdict:" in text and "Reasons:" in text and "Claims: " in text
    assert "Not part of this report." not in text


def test_a_contradicted_claim_is_no_blocker_with_the_flag_off_and_is_with_it_on(run_api, monkeypatch):
    ready_for_review(run_api)
    off = run_api.get(f"/api/audits/{AUDIT}/blockers").json()["blockers"]
    assert not [b for b in off if b["kind"] == "claim_contradicted"]
    monkeypatch.setenv("OLD_CLAIMS", "on")
    on = run_api.get(f"/api/audits/{AUDIT}/blockers").json()["blockers"]
    assert [b for b in on if b["kind"] == "claim_contradicted"], "fixture: the full TestCo audit has a contradicted top-5 claim"
