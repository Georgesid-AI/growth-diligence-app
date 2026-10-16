import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import OwnerPage from "@/pages/OwnerPage";
import { clearToken, listAudits, ownerPrompts, setToken } from "@/lib/api";

export const LINK_NOTICE = "Your link is your login. Anyone with the link can open your audits.";

export const FULL_LINK_TITLE = "Use your full access link";
export const FULL_LINK_TEXT = "Open the complete link you received by email or message; this page cannot be reached without it.";

/** The bare /t/ path, and /t/{token} when the API answers 401 (docs/specs/access-links.md section 2): no form, no token input, no link. */
export function FullLinkNeeded() {
  return (
    <div className="max-w-md mx-auto py-24 text-center" data-testid="full-link-needed">
      <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900">{FULL_LINK_TITLE}</h1>
      <p className="mt-3 text-sm text-slate-700">{FULL_LINK_TEXT}</p>
    </div>
  );
}

/** The tester's link, {app}/t/{token} (docs/specs/access-links.md section 1): the token is kept for the API and the audit list opens.
 *  The owner token has no audits (the list answers 404, the admin routes 200): it opens the owner page and is not kept. */
export default function AccessLink() {
  const { token } = useParams();
  const nav = useNavigate();
  const [state, setState] = useState("checking");    // checking | tester | owner | rejected
  useEffect(() => {
    if (!token) return;
    setToken(token);
    const asTester = () => setState("tester");
    listAudits().then(asTester, (e) => {
      const status = e?.response?.status;
      if (status === 401) { clearToken(); setState("rejected"); return; }
      if (status !== 404) { asTester(); return; }
      ownerPrompts(token).then(() => { clearToken(); setState("owner"); }, asTester);    // only the owner token reaches the admin routes
    });
  }, [token]);
  if (state === "rejected") return <FullLinkNeeded />;
  if (state === "owner") return <OwnerPage />;
  return (
    <div className="max-w-md mx-auto py-24 text-center" data-testid="access-link">
      <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900">Welcome</h1>
      <p className="mt-3 text-sm text-slate-700" data-testid="access-link-notice">{LINK_NOTICE}</p>
      {state === "tester" && <Button className="mt-6 bg-sky-600 hover:bg-sky-500" onClick={() => nav("/")} data-testid="access-link-open">Open my audits</Button>}
    </div>
  );
}
