# Spec: Access links for the tester phase, and the deployment rule (Release 1)
Status: Agreed scope. Source: docs/plans/app-plan_V2_amendments_15_10_2026.md section 6 and 7.1 (D6 amended, decisions of
15 Oct 2026, final). Location: docs/specs/access-links.md (new: no earlier access spec existed in docs/specs/).
Implementation order: 6 of 6. **Architecture change approved by George (15 Oct 2026, decision 1, option a): the `access_tokens` collection and the token check are
in docs/architecture.md.**

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: testers will hold real audits on a public URL; today any visitor can list and open every audit. The simpler
  version: one random link per tester, checked on every route, until the magic-link accounts of the AWS move. No account,
  password or session store.
- Deleted first: nothing in the code (there is no access code to remove). The review's request to make the repository
  private is declined (§5).

## 1. Access model (tester phase, on Emergent)
- Identity is possession of a per-tester token link. The tester page states, word for word: "Your link is your login.
  Anyone with the link can open your audits."
- Ownership: the token that created the audit owns it (`audits.owner`, the token's id, never the token).
- Magic-link accounts replace tokens at the AWS move (unchanged, out of scope).

## 2. Tokens
- Random, 32 bytes from a cryptographic source, sent once in the link `{app}/t/{token}` (URL-safe base64); stored only as
  its SHA-256 hash with an id, a label (the tester's name as the owner typed it), `created_at`, `expires_at` (30 days) and
  `revoked_at`.
- One token per tester. The owner token (its hash in the environment, `OWNER_TOKEN_SHA256`, never in the repository) can
  issue, revoke or re-issue any tester token: `POST /api/admin/testers` `{label}` (returns the link once),
  `POST /api/admin/testers/{id}/revoke`, `POST /api/admin/testers/{id}/reissue` (revokes and returns a new link). Re-issue
  keeps the tester's id, so the tester keeps their audits.
- A revoked or expired token is refused on every route (401).
- The browser keeps the token from the link in `localStorage` and sends it as `Authorization: Bearer {token}` on every
  request; the link page then opens the audit list.
- Two link cases show one plain page, no form, no token input, no link to any other page: title "Use your full access
  link", text "Open the complete link you received by email or message; this page cannot be reached without it."
  (1) The bare `/t/` path. (2) `/t/{token}` when the API answers 401 (the page asks `GET /api/audits` with the token;
  the Welcome page shows meanwhile and stays unchanged for a valid token). On a 401 the stored token is also removed from `localStorage`. Any other answer keeps the Welcome page and the token.

## 3. Authorization matrix
Every API route that reads or changes an audit checks that the audit belongs to the request's token: list audits, read
audit, read results, upload a file, download or view a file (deck page view, claims CSV, xlsx export), edit claim, edit
mapping, edit set-up, run calculation, run narratives (the `/runs/{run_id}/...` routes, where run id is the audit id),
generate memo, export CSV/xlsx, delete audit, and every other `/audits/{audit_id}/...` route of `server.py`.
| Request | Answer |
|---|---|
| No token, or a token that matches no stored hash | 401 |
| An expired or revoked tester token | 401 |
| A tester token on an audit another token owns (or an audit id that does not exist) | 404, the same body as a missing audit, so the answer never reveals that the audit exists |
| The owner token on any audit route | 404 |
| The owner token on `GET /api/usage/totals` and the admin routes | 200: usage totals only (counts and cost, no company, file or claim), the product stance "we cannot see your deals"; the totals sum all audits |
| The owner token on `GET /api/admin/audit-costs` | 200: per audit the tester label, creation time, calls, tokens and cost; no audit, company or file name (usage-and-allowance.md §9) |
| A tester token on `GET /api/usage/totals` | 404, as on the admin routes: the route is owner-only (George, 18 Oct 2026, usage-and-allowance.md D3; it replaced the 15 Oct rule of own-audit totals) |
| `GET /api/` (health) and `GET /api/fields` (the field list, no audit data) | open (George, 15 Oct 2026, decision 2a: they stay open; neither holds audit data) |
List audits returns only the token's own audits; the owner token gets 404 on it too (George, 15 Oct 2026).

The owner has no audits of their own and sees none. To test the audit screens the owner creates a tester link for themselves on the owner page and opens that. The owner link (`/t/{owner token}`) opens the owner page, never the audits button: the page detects the owner token by the 404 on the audit list followed by a 200 on the admin routes, and does not keep the token.

## 4. Tests required before tester deployment
| Test | File |
|---|---|
| 1. No token → 401 on every route of §3 | `test_access_links.py` |
| 2. Tester A's token on tester B's audit id → 404 on every route of §3, including file download, memo and export | `test_access_links.py` |
| 3. Expired token → 401; revoked token → 401, on every route of §3 and on the audit list and create | `test_access_links.py` |
| 4. Owner token on any audit route → 404 | `test_access_links.py` |
| The tester page states "Your link is your login. Anyone with the link can open your audits." | `AccessLink.test.jsx` |
| `/t/{token}` rejected with 401 shows only the full-link page (no Welcome, no input, form, link or button) | `AccessLink.test.jsx` |
| The bare `/t/` path shows only the full-link page | `AccessLink.test.jsx` |
The route list of tests 1, 2 and 4 is read from the app's own router, so a route added later is covered without editing the
test. A token never reaches a log line (`test_gateway_data_boundary.py`, rule 14).

## 5. Deployment instruction
Decision (George, 15 Oct 2026): the repository stays public. Emergent imports from GitHub only and cannot push back, so the
repository holds source code only. The standing rules that make this safe remain: no `.env` (only `backend/.env.example`
is tracked), no client data (CLAUDE.md rule 15), no methodology prompt text. The review's request to remove the
public-repo step is noted and declined on these grounds. No deployment step changes.

Data inventory before deployment: "Nothing real is in the app yet" is confirmed, not assumed: list every audit in the
deployed app and every stored file, confirm all are synthetic (TestCo) or public-deck (Zero2Hero) data, delete them, and
record the result in the session log before testers receive links. This needs the deployed app's database and is done by
the engineering owner; no session of this spec has that access.

## 6. Architecture note (CLAUDE.md rule 1)
- §2 needs a store for token hashes that the owner can change at run time (issue, revoke, re-issue). docs/architecture.md
  lists the MongoDB collections (Storage row) and every collection the code uses is on that list; a new collection
  (`access_tokens`) changes what that row says, so it is an architecture change. The API row would also gain the token
  check on every route.
- Options for George: (a) approve the collection `access_tokens` and the check in the API row (recommended: one collection,
  hashes only, removed at the AWS move); (b) keep tester tokens in the environment (hashes and expiry dates set at deploy),
  which drops run-time revoke and re-issue from §2 and needs a redeploy for each change.
- Decided: option (a). docs/architecture.md now lists `access_tokens` and the token check.

## 7. Found while writing this spec (reported, not changed)
- The plan names "no methodology prompt text in the repo (CLAUDE.md)". CLAUDE.md has no such rule, and the narrative and
  structure prompts are tracked in `backend/app/llm/prompts/` (marked "server-side only"), so a public repository publishes
  them. Since Emergent deploys from GitHub only, moving them out of the repository needs another delivery path for the
  prompts. Done: docs/specs/prompt-store.md and CLAUDE.md rule 26 (the old texts remain in git history).

## Files (once §6 is decided)
`backend/server.py` (a dependency on every audit route), `backend/app/access.py` (new: hashing, expiry, ownership),
`frontend/src/lib/api.js` (the header), `frontend/src/pages/AccessLink.jsx` (new: the link page), `frontend/src/App.js`,
the tests of §4.

## Done when
§4 passes with the full suite, and the data inventory of §5 is recorded in the session log.
