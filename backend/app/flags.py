"""Switches read from the environment (one place, so a test and a screen read the same value)."""
import os


def old_claims() -> bool:
    """OLD_CLAIMS: "on" brings back the claim register, the five-claims conclusion, the three reasons, the key gates, the claim labels and the
    claim questions on the Audit screen and in the downloaded report (docs/design/read-check-review.md section 12, PR 4). Anything else, or
    nothing, is off: the default. The code stays; nothing computes or shows a claim label while it is off."""
    return os.environ.get("OLD_CLAIMS", "off").strip().lower() == "on"
