import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { setAccessToken } from "@/lib/api";

// The tester page of docs/specs/access-links.md: the token in the address is kept in this browser and sent with every request.
export const LINK_IS_LOGIN = "Your link is your login. Anyone with the link can open your audits.";

export default function AccessLink() {
  const { token } = useParams();
  const nav = useNavigate();
  const [kept, setKept] = useState(null);
  useEffect(() => { setKept(setAccessToken(token)); }, [token]);
  return (
    <main className="min-h-screen flex items-center justify-center px-4" data-testid="access-link-page">
      <div className="max-w-md w-full border border-[#D1D5DB] rounded-md p-6 bg-white">
        <h1 className="font-heading text-xl font-semibold text-slate-900 mb-3">Growth Diligence</h1>
        <p className="text-sm text-slate-800 mb-4" data-testid="access-link-statement">{LINK_IS_LOGIN}</p>
        {kept === false && (
          <p className="text-sm text-rose-700 mb-4" data-testid="access-link-not-kept">
            This browser would not keep your link. Open the link again each time you come back.
          </p>
        )}
        <Button onClick={() => nav("/")} className="bg-sky-600 hover:bg-sky-500" data-testid="access-link-open">Open your audits</Button>
      </div>
    </main>
  );
}
