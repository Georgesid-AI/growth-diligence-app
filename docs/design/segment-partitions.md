# Segment from the label, and segment partitions

**Status:** built 2026-10-26 (George, from the live run). Adds to `docs/design/claim-review-simplified-design.md` (not amended) and `docs/specs/claim-groups.md`. Code: `claim_matching.label_segment`, `claim_groups.py`, `NeedsAttention.jsx`. No architecture change: nothing new reaches a model, nothing new is stored, the engine output is unchanged.

**Challenge (rule 4).** Needed: a deck that splits ARR by product, with a company total, produced "annual conflicts" between the products and a contradicted "total". The simplest version is the three rules below; no new field, no stored relationship. Deleted first: any model call for the segment, any stored segment, any automatic exclusion.

## 1. Segment from the label

When the cited label of a money figure (`label_from`) names a product, customer, use case, segment or chart legend item rather than the metric itself, the claim's segment is that name; the metric stays the metric ("Product A" on an ARR figure: ARR, segment Product A). Python reads the label: the metric words, period words, currency words, scale words and the words that name the whole company or a scenario ("total", "annual", "forecast", "best case") are removed; what is left, one to four capitalised words, is the segment. A label of the metric alone, a dimension word alone ("Product", "Segment"), a sentence or a lower-case phrase gives none: the claim stays whole company. A segment the revenue file has keeps its existing rule (the engine's name). A name the data does not have is tested as before: "segment not in the data", never against the whole company. The analyst's own segment always wins; the field stays editable under Details.

Figures with different segments are never candidates in the same annual conflict: the segment is part of the scope key, so each segment is its own scope.

## 2. Segment partitions

Figures of one scope (metric, population, period, currency, unit, scenario, basis) with different segments, at most one figure per segment, whose sum is within the 2% reconciliation tolerance of a stated total for the whole company (the preferred total of the period) become parts of that total, role `segment_part`:
- shown under the total's Details, with the segment name; no top-five slot, no value at stake of their own: the total's counts once;
- the set is searched among the segment figures of the period (a deck may state a product split and a customer split of the same total): the subset that reconciles, with the smallest difference, then from one page, then the earliest. A set that does not reconcile, or is partial, leaves its figures independent claims, each with the relationship note "Segment figures sum to X, outside ±2% of the company total Y; kept as independent claims";
- a period partition (quarters, halves, months) and a segment partition of the same total are both shown under the total's Details; both count as parts, neither adds exposure;
- while the annual figure is still in conflict, the segment parts of each candidate's reconciling set wait with the question (role `pending_part`, as the period parts do);
- a contradicted segment part stays visible and counted on the Details line, as every part (design note section 1).

## 3. The conflict card

A card offers the candidates of one scope only (the server relates by scope, so a candidate of another segment never appears). With more than four candidates it offers none: it shows one line ("n annual figures are stated for this period; too many to choose from here. Review them in the claims list.") and a button that opens the claims list.
