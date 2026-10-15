// Release 1, committed before the code: docs/specs/access-links.md (plan section 6). The page waits on the architecture note of
// the spec (section 6); it is required inside each test, so the file always loads. failing() becomes test() in the code PR.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import { failing } from "@/testing/expectedFailure";

jest.mock("react-router-dom", () => ({ useParams: () => ({ token: "tester-token-123" }), useNavigate: () => jest.fn() }), { virtual: true });

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

failing("the tester page states that the link is the login, and keeps the token for the API", async () => {
  const AccessLink = require("./AccessLink").default;
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  try {
    await act(async () => { root.render(<AccessLink />); });
    expect(host.textContent).toContain("Your link is your login. Anyone with the link can open your audits.");
    expect(window.localStorage.getItem("access_token")).toBe("tester-token-123");
  } finally {
    await act(async () => { root.unmount(); });
    host.remove();
  }
});
