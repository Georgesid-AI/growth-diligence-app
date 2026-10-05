"""Board decks and growth plans: parsed text, candidate claims and the structures in them.

Spec: docs/specs/deck-parser.md. The rules this package keeps (CLAUDE.md rules 16-18):
- The deck parser has no direct link to the gateway: nothing here imports or calls it, and the
  gateway never reads the parsed text, the snippets or the source references stored here.
- Rule 16: the structures the parser finds (section 7) may reach the model only through
  app.structures: after redaction, only with the audit's consent, only as extracted text with cell
  positions. Never raw files, full pages or prose slides.
- Rule 17: logs and Mongo keep the model's JSON output (values with cell references) and its
  metadata, never deck text sent to the model; Delete audit removes the model outputs.
- Rule 18: model output never becomes Verified on its own; Python matches every value to a source
  cell, and an unmatched value is shown as "AI suggestion, not verified" or dropped.
Enforced in tests/test_gateway_data_boundary.py.
"""
# MongoDB collections, both keyed by audit_id. Parsed text holds every text block with its
# source reference; candidates hold the structured claim fields plus snippet and sources.
TEXT_COLLECTION = "deck_text"
CANDIDATES_COLLECTION = "deck_candidates"

# The only candidate fields the gateway may ever read (spec section 4).
GATEWAY_READABLE_FIELDS = frozenset({"claim_type", "value", "value_high", "unit", "target_date", "status"})
