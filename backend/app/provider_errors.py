"""A provider error in plain words for the Upload page: one closed sentence per kind, never the provider's own text (which can quote a request).
The raw status, type and message go to the log (gateway._logged_provider_message), not to the screen."""
from typing import Optional

PREFIX = "Anthropic API: "
CREDIT = PREFIX + "insufficient credit – add credit and re-run"
AUTH = PREFIX + "the API key was refused – check the key and re-run"
RATE_LIMIT = PREFIX + "rate limit reached – wait a few minutes and re-run"
MODEL = PREFIX + "model not found – check the model name and re-run"


def plain_words(status: Optional[int], error_type: Optional[str], message: Optional[str]) -> Optional[str]:
    """The sentence for a provider failure the analyst can act on, else None (a failure with no such sentence stays per file)."""
    text = (message or "").lower()
    if "credit balance" in text or "insufficient" in text and "credit" in text:
        return CREDIT
    if status in (401, 403) or error_type in ("authentication_error", "permission_error"):
        return AUTH
    if status == 429 or error_type == "rate_limit_error":
        return RATE_LIMIT
    if status == 404 or error_type == "not_found_error":
        return MODEL
    return None
