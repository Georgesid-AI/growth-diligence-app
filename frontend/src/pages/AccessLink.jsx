import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { listAudits, setToken } from "@/lib/api";

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

/** The tester's link, {app}/t/{token} (docs/specs/access-links.md section 1): the token is kept for the API and the audit list opens. */
export default function AccessLink() {
  const { token } = useParams();
  const nav = useNavigate();
  const [rejected, setRejected] = useState(false);
  useEffect(() => {
    if (!token) return;
    setToken(token);
    listAudits().catch((e) => { if (e?.response?.status === 401) setRejected(true); });   // the Welcome page shows meanwhile
  }, [token]);
  if (rejected) return <FullLinkNeeded />;
  return (
    <div className="max-w-md mx-auto py-24 text-center" data-testid="access-link">
      <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900">Welcome</h1>
      <p className="mt-3 text-sm text-slate-700" data-testid="access-link-notice">{LINK_NOTICE}</p>
      <Button className="mt-6 bg-sky-600 hover:bg-sky-500" onClick={() => nav("/")} data-testid="access-link-open">Open my audits</Button>
    </div>
  );
}
