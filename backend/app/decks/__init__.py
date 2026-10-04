"""Board decks and growth plans: parsed text and candidate claims for the analyst to approve.

Spec: docs/specs/deck-parser.md. Nothing in this package imports or calls the LLM gateway,
and the gateway never reads the parsed text or the snippets stored here
(tests/test_gateway_data_boundary.py).
"""
# MongoDB collections, both keyed by audit_id. Parsed text holds every text block with its
# source reference; candidates hold the structured claim fields plus snippet and sources.
TEXT_COLLECTION = "deck_text"
CANDIDATES_COLLECTION = "deck_candidates"

# The only candidate fields the gateway may ever read (spec section 4).
GATEWAY_READABLE_FIELDS = frozenset({"claim_type", "value", "unit", "target_date", "status"})
