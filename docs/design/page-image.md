# Addendum: page image for the page reader

**Status:** proposed, 27 October 2026 (George). Addendum to `claim-review-simplified-design.md`, which is not amended. Sections 4 and 5 built 27 October 2026 (engine contract 11); sections 1 to 3 and 6 (the image, no masking and the model allow-list, the disclosure, the owner page) built 27 October 2026. Section 7 is an estimate, not a feature.
The page reader is the `page_claims` step of `ai-reads-rules-check.md`. Check codes (L1, C4, P2, C1, C3, X2) are used as George named them; the repository does not define them by those codes, so the build mapped each to its check in `structures/checker.py` and its helpers (George's definitions, 27 October 2026; codes are handled as the two groups of section 5):

| Code | Group | Check | Function |
|---|---|---|---|
| L1 | Label correction | the legend or axis label found by position replaces the cited one | `page_check.check` (local label) |
| C4 | Label correction | one-candidate label correction | `corrections.plan` (flag `label mismatch`, field `label`) |
| P2 | Period fill | the period from the page heading or another cell | `page_check.period_check` |
| C1 | Period fill | the one-option "period from another cell" | `corrections.plan` (`PERIOD_FROM_OTHER_CELL`) |
| C3 | Period fill | the heading's period when the model's is not on the page | `corrections.plan` (`PERIOD_NOT_ON_PAGE`), removed: it only ever applied to a model period |
| X2 | Sign | rewrite of the value to its absolute value | `checker.check`, now only sets `sign not on page` |

## 1. What the reader sends

For each page selected for reading, two things: the page's text lines with positions (as today) and one rendered image of the whole page. PNG, 1,568 px on the long edge, no crops, no second pass. The model reads printed values only. It never estimates a value from an unlabelled bar, point or slice; such a figure is not a claim.

## 2. No customer-name masking; ZDR model only

Customer-name masking is removed entirely. Pages go to the model as printed. Reason: the API organisation runs under an Anthropic zero-data-retention (ZDR) arrangement and the audit terms disclose it.

The page reader runs only on a ZDR-eligible model: Sonnet or Opus, never Fable or Mythos. A model off the allow-list is logged as an error at startup and the server stays up; the gateway then blocks every page read, and the pipeline converts, draws and sends nothing (the check runs first). This is recorded as CLAUDE.md rule 31.

Not changed by this addendum: rule 17 (no deck text in logs or MongoDB; model JSON may be stored) and rule 18 (model output is never Verified on its own).

## 3. Disclosure

Shown on the Upload page and in the tester terms, in these words:

> Deck pages are processed by Anthropic under a zero-data-retention arrangement. Nothing is retained after the reply and nothing is used for training.

## 4. Answer form

Four nullable fields are added to each claim: `label_text`, `segment`, `share_of`, `is_quote`. `label_text` is the label as printed; `label_cell` only locates it. Null means the model did not read one. Any field that is a closed word, number or cell id keeps today's validation; `label_text`, `segment` and `share_of` are short printed text, validated for length and stored as model JSON output under rule 17. `is_quote` is a boolean.

What each field does (George, 2026-10-27, PR #193):

- `is_quote` true: the figure is a quotation, not a company claim. It is not entered as a claim. The pipeline writes one Diagnostics line, "page n: quoted figure, not a company claim", and the deck panel counts it ("Quoted figures skipped: n"). Null or false changes nothing.
- `segment`: shown on the claim row after the label ("Label from: <label> · <segment>"; "Segment: <segment>" when no label was read). Display only; it is not the register's segment and sets nothing.
- `share_of`: shown in the Why column (the reasons under Extraction confidence) as "Share of: <text>". Display only.

No other behaviour. The row keeps `segment` and `share_of` as `page_segment` and `page_share_of`; the stored read still keeps neither (rule 17).

## 5. Rule changes

- **Label corrections (L1, C4):** run only when `label_text` is empty. When `label_text` is present and the cell text disagrees, the claim is flagged, not corrected.
- **Period fills (P2, C1, C3):** from a heading or another cell, they fill a blank period only. They never replace a period the model set. The same holds for the cell the model cites for its period, the figure's own text or header included (George, review of PR #193, 2026-10-27): a model period the cited cell reads otherwise is kept, flagged `sources disagree`, logged as one Diagnostics line, and the model's period and the cell's are the two buttons. The year-under-bar check (`year under bar differs`, the year label under the figure's bar by place) is the only check that still changes a non-null model period.
- **No-minus-sign rule (X2):** becomes the flag `sign not on page`, listed under Review, instead of a change to the claim.
- All other checks are unchanged.

## 6. Owner page

Image tokens and their cost are shown per deck read, separately from text tokens and cost.

## 7. Expected cost

About 1,000 to 2,500 extra input tokens per page. A deck read roughly doubles (`ai-reads-rules-check.md` §4: about $0.09 for a 20-page deck with batching and caching). A page call stays outside the USD 5 daily cap and inside the tester's monthly allowance, as today.

## Built, 27 October 2026

- Rule 16 and the consent text are rewritten (pages go as printed, no redaction), the Upload page explainer carries the disclosure line of section 3, and `test_gateway_data_boundary.py` follows (rule 14). The tester terms are not in the repository and are not edited here.
- Image count per call: no cap. The audit reads one page per call (eight at a time, 60-second timeout), so one image goes with each call; the scripts' five-page calls carry five.
- The page images are drawn from the uploaded file, which the app now keeps (collection `deck_files`, removed with the deck and with the audit). A PDF is drawn as it is; a .pptx or .docx is turned into a PDF by LibreOffice first. A deck that cannot be drawn (no LibreOffice, another page count than the parser read, no stored file) goes as text alone, never "not read" for that reason; the panel says "page images unavailable for this file; text only".
- Allow-list: `gateway.PAGE_READER_MODELS` (Sonnet and Opus families); `PAGE_READER_MODEL` overrides the default model and is checked at startup and before each page read.
- The instruction of section 1 (printed values only) is in the stored `deck_reading` prompt; the gateway carries no copy of it.
