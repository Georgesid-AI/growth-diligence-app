2026-10-10, branch claude/peaceful-goodall-yec4sn
Deleted: nothing.
Decided: 120 s timeout on uploadChatFile; on a no-response error the file returns to "attached" and Map resends it (smallest change, no retry loop). The test mocks the axios timeout error, and a separate test checks the timeout value on the request. Kept 120 s: the AI step of an upload is capped at 20 s in code (MAPPING_AI_SECONDS, lock wait included), and no log or fixture records a read above 60 s. The new message is S26 in chat-upload.md §11.
Slow or unclear: the loop never stopped on prompts, so the first reading of the bug was wrong; the hung request was only confirmed from the Cloudflare error and the uvicorn reloads.
Root cause and rule: a request with no timeout can hang forever and leave a file spinning with no way out; every client call that awaits a server read needs a timeout and a recovery path.
Process change to propose: attach the server log and the browser Network tab to a bug task, so "never sent" and "never answered" are told apart at the start.
