"""What a tester token never receives: cost, token and USD fields (docs/specs/usage-and-allowance.md section 9).

The app keeps calculating and storing them; this removes them from the JSON of every response that is not the owner's. A closed key
set, at any depth, so a new route cannot leak one by accident; a key that carries a cost is added here and to the data boundary test.
"""
import json

HIDDEN_KEYS = frozenset({
    "input_tokens", "output_tokens", "estimated_cost_usd", "ai_cost_usd", "cost_usd", "estimate_usd", "total_usd",
    "structure_tokens", "structure_token_cap", "tokens", "allowance_usd", "used_usd",
})


def strip(value):
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in HIDDEN_KEYS}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


def strip_body(body: bytes) -> bytes:
    """The JSON body without the hidden keys; a body that is not JSON is returned as it is."""
    try:
        data = json.loads(body)
    except ValueError:
        return body
    return json.dumps(strip(data), separators=(",", ":")).encode("utf-8")
