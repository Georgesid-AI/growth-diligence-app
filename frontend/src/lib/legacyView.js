/**
 * The earlier screen (PR 3, docs/design/read-check-review.md section 11): the Upload & Mapping page's per-file mapping tables, the deck panel's claims
 * list, "Needs your attention", the claims list and the five-claims conclusion stay in the code and leave the default screen. `?view=legacy` brings them
 * back for as long as they exist (PR 4 removes the rules reading they belong to).
 */
export const legacyView = () => {
  try { return new URLSearchParams(window.location.search).get("view") === "legacy"; } catch (e) { return false; }
};
