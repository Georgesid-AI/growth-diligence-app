import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { setToken } from "@/lib/api";

export const LINK_NOTICE = "Your link is your login. Anyone with the link can open your audits.";

/** The tester's link, {app}/t/{token} (docs/specs/access-links.md section 1): the token is kept for the API and the audit list opens. */
export default function AccessLink() {
  const { token } = useParams();
  const nav = useNavigate();
  useEffect(() => { if (token) setToken(token); }, [token]);
  return (
    <div className="max-w-md mx-auto py-24 text-center" data-testid="access-link">
      <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900">Welcome</h1>
      <p className="mt-3 text-sm text-slate-700" data-testid="access-link-notice">{LINK_NOTICE}</p>
      <Button className="mt-6 bg-sky-600 hover:bg-sky-500" onClick={() => nav("/")} data-testid="access-link-open">Open my audits</Button>
    </div>
  );
}
