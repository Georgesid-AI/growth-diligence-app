// docs/specs/access-links.md (plan section 6): the tester page.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

jest.mock("react-router-dom", () => ({ useParams: () => ({ token: "tester-token-123" }), useNavigate: () => jest.fn() }), { virtual: true });

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

test("the tester page states that the link is the login, and keeps the token for the API", async () => {
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
