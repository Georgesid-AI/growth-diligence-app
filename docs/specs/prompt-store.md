# Spec: The server-side prompt store and the owner page
Status: Agreed scope (task of 15 Oct 2026, plan docs/plans/app-plan_V2_amendments_15_10_2026.md section 6: "no methodology prompt
text in the repo"). Location: docs/specs/prompt-store.md. Companion: docs/specs/access-links.md (the owner token and the tester
links, built with this spec).

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: the repository is public (decision of 15 Oct 2026) and the prompts are the methodology. Anyone could read
  them. Emergent deploys from GitHub only, so the prompts need another way in: the owner types or uploads them once, into the app's own
  database. Simplest version: one collection, append-only, one page with an upload field. No editor, no diff, no rollback
  button (a rollback is an upload of the older text).
- Deleted first: `backend/app/llm/prompts/` (the four prompt files and RELEASE.md), the release stamp and the hash manifest (a
  stored version names one text by construction), the tests that read a prompt's wording, and every file read in `prompt_store.py`.

## 1. The store
Collection `prompts`, one document per upload: `name`, `version`, `text`, `uploaded_at`, `sha256` (of the UTF-8 text).
- `name` is one of the four the gateway reads: `growth_engine`, `data_inventory`, `data_integrity`, `structure_reading`
  (`prompt_store.NAMES`; a test fails if the gateway reads a name this list lacks). Any other name is refused (422).
- `version` is `v1`, `v2`, ... per name, the next number at upload. Unique on (name, version) (index), so two uploads at the
  same moment cannot share a number. The latest version is the highest number.
- Every upload creates a version, including the same text again. Nothing is updated or deleted: there is no route, button or
  code path that does either. Text is refused when empty or over 100,000 characters (422); line endings are stored as `\n`.
- The text is never in a response, a log line, `llm_calls`, `llm_narratives`, `llm_structures` or the cache. It leaves the server
  once per call, as the system prompt of the model request.

## 2. The gateway
- `prompt_store.load(db, name)` returns the latest version or raises `PromptMissing`. The gateway reads prompts here and nowhere else;
  no module of `backend/app/llm/` touches a file.
- A prompt that is not loaded means no model call, for the narrative steps and the structure path alike:
  - `POST /api/runs/{id}/narrative/{step}` answers 200 with `narrative_status: "unavailable"`, `reason: "No prompt loaded —
    upload prompts on the owner page"` and the computed metrics (CLAUDE.md rule 20: every metric still renders). No `llm_calls`
    row, no lock, no spend.
  - A read (`GET`) says `not_generated`; the estimate lists the step as not available; a structure read is "Not read by AI".
- The prompt identity in a cache key is `store:{version}` (`prompt_store.tag_for`): the namespace keeps a narrative written under the
  retired file prompts (plain `v1`, `v7` ...) from being served as if a store version of the same number had written it. A new upload therefore moves the key: the earlier narrative is kept,
  not shown, with the reason code `prompt_release_changed` the screen already words ("The summary prompt was updated ..."). The
  release stamp (r1 ... r10) is gone; stored records keep their `prompt_version`, and the old `prompt_release` field is no longer written.
  Narratives stored under the file prompts (version strings like `v7`) match no store version and show as "data changed".
- Stored model output and `llm_calls` keep the prompt version and the model, as before (rule 17).

## 3. The owner page (`/owner`)
Owner token only (`OWNER_TOKEN_SHA256`, access-links.md section 2). The page asks for the token once; it is kept in the page's
memory (component state) and sent as `Authorization: Bearer` on each call. It is not written to storage, not put in the address,
and is gone on reload. The page shows no audit data and imports no audit call.
- **Prompts.** A table of every stored version: name, version, upload date, first 12 characters of the hash. A note names the
  prompts that have none. To upload: choose the name, then either choose a file (read in the browser as text) or paste text, then "Upload as new version".
  After the upload the text is cleared from the page. Prompt text is never sent to the browser; there is no read, edit or delete.
- **Tester links.** Issue (name; the expiry is fixed at 30 days): the link `{app}/t/{token}` is shown once in a box that stays until
  the owner dismisses it. List: name, status (active, expired, revoked), expiry. Revoke. Re-issue (revokes and returns a new link; the
  tester keeps their id and so their audits).

| Route (owner token only) | Does |
|---|---|
| `GET /api/admin/prompts` | `{names, prompts: [{name, version, uploaded_at, sha256}], missing}` |
| `POST /api/admin/prompts` `{name, text}` | stores the next version; returns `{name, version, uploaded_at, sha256}` |
| `GET /api/admin/testers` | a list `[{id, label, created_at, expires_at, revoked_at}]`; the page derives the status (active, expired, revoked) from the dates |
| `POST /api/admin/testers` `{label}` | issues, expiry 30 days; returns `{id, label, link}` |
| `POST /api/admin/testers/{id}/revoke` | sets `revoked_at` |
| `POST /api/admin/testers/{id}/reissue` | new token, same id; returns `{id, link}` |

The link is built on `PUBLIC_APP_URL` if set, else on the request's base URL: `{base}/t/{token}`.
Access rules are those of docs/specs/access-links.md section 3: no token, an unknown, expired or revoked one is 401; a tester token on an
admin route is 404 (the routes are not revealed); the owner token on an audit route is 404.

## 4. Getting the prompts in
The four texts are in git history up to commit 142cd0b (`git show 142cd0b:backend/app/llm/prompts/growth_engine.md`, and so on). The
owner uploads them from there on the owner page; each file's `version:` comment line is part of the text and is harmless. **The
history of a public repository still publishes the old prompts; removing them needs a history rewrite, which this task does not do
(see "Decisions for you").** Until the owner uploads, no narrative is written and no deck structure is read by the model; every
computed metric renders.

## 5. Data-boundary entries (CLAUDE.md rule 14; `backend/tests/test_gateway_data_boundary.py`)
- Prompt text reaches the provider as the system prompt only and sits in no collection but `prompts`; the response, the log and
  `llm_calls` hold the version only.
- `prompts` and `access_tokens` documents have fixed fields; a token is stored only as its hash and never listed.
- The missing-prompt reason is the closed sentence above; it holds no name, text or path.
- No module of the gateway reads a token or the owner hash; `prompt_store.py` and `access.py` log nothing; the one owner-route log
  line (prompt uploaded) holds a prompt name and a version only, never a label, token or text.
- A token never reaches a log line in a request (`test_owner_page_api.py`).

## 6. Tests
- `tests/test_prompt_store.py`: versions, hash, nothing changed or deleted, numeric order, refusals, names against the gateway, the
  repository holds stubs only, the latest version is sent, a missing prompt is the message and no call (every step, the structure
  path, reads and estimates), a new version hides the earlier narrative.
- `tests/test_owner_page_api.py` (real access guard): 401 and 404 on every admin route, upload and list without text, no delete, issue,
  expiry, revoke, re-issue, one-time link, no token or text in a log.
- `tests/test_access_links.py`: the four tests of access-links.md section 4, now passing (they were strict expected failures).
- Frontend: `OwnerPage.test.jsx`, `AccessLink.test.jsx`, `api.test.js` (the bearer header; downloads fetched with it).
- Stubs: `backend/tests/fixtures/prompts/*.md`, one line each, marked "test only"; `tests/prompt_fixtures.py` loads them into the fake store
  (`FakeDB` and the consistency script's `MemoryDB` start with them). The live consistency run copies the latest `structure_reading`
  prompt from the app's database into its scratch database (the text is never printed; the report names the version).
- Removed: tests that asserted a prompt's wording (nine, in test_llm_gateway, test_structure_reading, test_calc_correctness,
  test_gateway_data_boundary) and the release-manifest tests. Their subject is no longer in the repository (CLAUDE.md rule 26).

## 7. Architecture note (CLAUDE.md rule 1)
docs/architecture.md says "Prompts are server-side files with a version and a release stamp (`prompt_store.py`, `prompts/`)" and its
Storage row lists the collections. This spec adds the collections `prompts` and `access_tokens` and replaces the files. The task
instruction named the prompt store as the frozen component, so the code follows it; **docs/architecture.md was not edited in the first
commit** (rule 1); George instructed the edit on 15 Oct 2026 and it is applied as written below:
- LLM gateway row: "Prompts are versioned documents in the MongoDB collection `prompts`, uploaded on the owner page and read by the
  gateway only (`prompt_store.py`); a missing prompt means no model call."
- Storage row: add `prompts` and `access_tokens` (no `audit_id`; Delete audit leaves them, they hold no audit data).
- API row: every route but the health check and the field list needs a token (access-links.md section 3).

## Files
`backend/app/llm/prompt_store.py` (rewritten), `backend/app/llm/gateway.py`, `backend/app/access.py` (new), `backend/server.py` (the guard,
the owner routes), `backend/conftest.py`, `backend/.env.example`, `frontend/src/pages/{OwnerPage,AccessLink}.jsx`, `frontend/src/lib/api.js`,
`frontend/src/App.js`, `frontend/src/pages/Dashboard.jsx` and `frontend/src/components/ClaimRegister.jsx` (downloads carry the header),
`scripts/consistency_run.py`, CLAUDE.md rule 26, the tests above.

## Done when
CI is green (backend suite, frontend suite with `--no-cache`), the four prompts are uploaded on the deployed owner page, and one narrative per step is written
from the store.
