import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ownerAuditCosts, ownerIssueTester, ownerPrompts, ownerReissueTester, ownerRevokeTester, ownerSetAllowance, ownerTesters, ownerUploadPrompt, ownerUsage,
} from "@/lib/api";
import { describeRequestError } from "@/lib/requestError";
import OwnerUsage from "@/components/OwnerUsage";
import OwnerAuditCosts from "@/components/OwnerAuditCosts";

// The owner page (docs/specs/prompt-store.md section 3). The owner token lives in this component's state only: never in
// storage, never in the address. The page shows the prompt store and the tester links and no audit data; prompt text goes up
// from here and is never shown again.
export const NO_PROMPT_NOTICE = "No prompt loaded for";
// docs/specs/prompt-store.md section 1: the same limit as prompt_store.MAX_TEXT_CHARS; counted on text with \n line ends, as stored.
export const PROMPT_LIMIT = 10000;
export const promptLength = (text) => text.replace(/\r\n/g, "\n").length;
export const overLimitMessage = (n) => `Prompt is ${n} characters; the limit is ${PROMPT_LIMIT.toLocaleString("en-US")}.`;
export const LINK_ONCE = "Shown once. Copy it now; it cannot be shown again, only replaced by Re-issue.";

const when = (iso) => (iso ? String(iso).slice(0, 16).replace("T", " ") + " UTC" : "—");
const STATUS = { active: "text-emerald-700", expired: "text-amber-700", revoked: "text-rose-700" };
// The server lists id, label, dates and revoked_at (access-links.md section 2); the status is read from them.
export const statusOf = (t, now = Date.now()) => (t.revoked_at ? "revoked" : new Date(t.expires_at).getTime() <= now ? "expired" : "active");
// A link is built on this page's address: the token is the part after /t/ whatever address the server printed.
const linkOf = (serverLink) => `${window.location.origin}/t/${String(serverLink).split("/t/").pop()}`;

export default function OwnerPage() {
  const [draftToken, setDraftToken] = useState("");
  const [token, setToken] = useState(null);       // accepted by the server; in memory only
  const [error, setError] = useState(null);
  const [prompts, setPrompts] = useState(null);   // { names, prompts, missing }
  const [testers, setTesters] = useState(null);
  const [usage, setUsage] = useState(null);       // GET /api/admin/usage: counts and USD by tester link
  const [costs, setCosts] = useState(null);       // GET /api/admin/audit-costs: calls, tokens and USD per audit, no names
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState(null);
  const [label, setLabel] = useState("");
  const [shown, setShown] = useState(null);       // { label, link } of the link just issued: held until dismissed
  const [busy, setBusy] = useState(false);

  const loadUsage = async (owner) => {
    setUsage(await ownerUsage(owner));
    setCosts(await ownerAuditCosts(owner).catch(() => null));
  };

  const fail = (e) => setError(describeRequestError(e).message);

  const enter = async () => {
    setError(null);
    setBusy(true);
    try {
      const entered = draftToken.trim();
      const list = await ownerPrompts(entered);
      setPrompts(list);
      setName(list.names[0] || "");
      setTesters(await ownerTesters(entered));
      await loadUsage(entered);
      setToken(entered);
      setDraftToken("");
    } catch (e) {
      setError(e.response?.status === 401 || e.response?.status === 404 ? "The owner token was not accepted." : describeRequestError(e).message);
    } finally {
      setBusy(false);
    }
  };

  const readFile = (file) => {
    if (!file) return;
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = () => setText(String(reader.result || ""));
    reader.onerror = () => setError("The file could not be read.");
    reader.readAsText(file);
  };

  const upload = async () => {
    setError(null);
    if (promptLength(text) > PROMPT_LIMIT) { setError(overLimitMessage(promptLength(text))); return; }   // refused, never cut
    setBusy(true);
    try {
      await ownerUploadPrompt(token, name, text);
      setPrompts(await ownerPrompts(token));
      setText("");                                 // the text is not kept in the browser after it is stored
      setFileName(null);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const issue = async () => {
    setError(null);
    setBusy(true);
    try {
      const out = await ownerIssueTester(token, label.trim());
      setShown({ label: out.label, link: linkOf(out.link) });
      setLabel("");
      setTesters(await ownerTesters(token));
      await loadUsage(token);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const saveAllowance = async (tester, value) => {
    setError(null);
    setBusy(true);
    try {
      await ownerSetAllowance(token, tester.id, value);
      await loadUsage(token);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const change = async (call, tester) => {
    setError(null);
    setBusy(true);
    try {
      const out = await call(token, tester.id);
      if (out.link) setShown({ label: tester.label, link: linkOf(out.link) });
      setTesters(await ownerTesters(token));
      await loadUsage(token);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  if (!token) {
    return (
      <main className="max-w-md mx-auto px-4 py-12" data-testid="owner-page">
        <h1 className="font-heading text-xl font-semibold text-slate-900 mb-3">Owner page</h1>
        <label className="block text-sm text-slate-800 mb-1" htmlFor="owner-token">Owner token</label>
        <Input id="owner-token" type="password" autoComplete="off" value={draftToken} data-testid="owner-token-input"
          onChange={(e) => setDraftToken(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && draftToken.trim()) enter(); }} />
        <p className="text-xs text-slate-500 mt-1">Kept in this page's memory only. It is gone when you reload or close the page.</p>
        {error && <p className="text-sm text-rose-700 mt-3" data-testid="owner-error">{error}</p>}
        <Button className="mt-4 bg-sky-600 hover:bg-sky-500" disabled={busy || !draftToken.trim()} onClick={enter} data-testid="owner-enter">
          Continue
        </Button>
      </main>
    );
  }

  return (
    <main className="max-w-4xl mx-auto px-4 py-8 space-y-10" data-testid="owner-page">
      <h1 className="font-heading text-xl font-semibold text-slate-900">Owner page</h1>
      {error && <p className="text-sm text-rose-700" data-testid="owner-error">{error}</p>}

      <section data-testid="owner-prompts">
        <h2 className="font-heading text-lg font-semibold text-slate-900 mb-2">Prompts</h2>
        {prompts.missing.length > 0 && (
          <p className="text-sm text-amber-800 mb-2" data-testid="owner-prompts-missing">
            {NO_PROMPT_NOTICE}: {prompts.missing.join(", ")}. Narratives for these steps are not written until a prompt is uploaded.
          </p>
        )}
        <table className="w-full text-sm mb-4" data-testid="owner-prompts-table">
          <thead><tr className="text-left text-slate-500"><th className="py-1">Name</th><th>Version</th><th>Characters</th><th>Uploaded</th><th>SHA-256</th></tr></thead>
          <tbody>
            {prompts.prompts.map((p) => (
              <tr key={`${p.name}-${p.version}`} className="border-t border-[#E5E7EB]" data-testid="owner-prompt-row">
                <td className="py-1 font-mono">{p.name}</td><td>{p.version}</td><td data-testid="owner-prompt-chars">{p.chars}</td><td>{when(p.uploaded_at)}</td>
                <td className="font-mono text-xs">{p.sha256.slice(0, 12)}</td>
              </tr>
            ))}
            {prompts.prompts.length === 0 && <tr><td colSpan={5} className="py-2 text-slate-500">No prompt uploaded yet.</td></tr>}
          </tbody>
        </table>
        <div className="space-y-2">
          <label className="block text-sm text-slate-800" htmlFor="owner-prompt-name">Upload a new version of</label>
          <select id="owner-prompt-name" value={name} onChange={(e) => setName(e.target.value)} data-testid="owner-prompt-name"
            className="h-9 rounded-md border border-input px-2 text-sm bg-transparent">
            {prompts.names.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <div>
            <input type="file" accept=".md,.txt,text/plain,text/markdown" data-testid="owner-prompt-file"
              onChange={(e) => { readFile(e.target.files && e.target.files[0]); e.target.value = ""; }} />
            {fileName && <span className="text-xs text-slate-500 ml-2">{fileName}</span>}
          </div>
          <Textarea rows={8} value={text} onChange={(e) => { setText(e.target.value); setFileName(null); }} placeholder="Or paste the prompt text"
            data-testid="owner-prompt-text" className="font-mono text-xs" />
          <p className={`text-xs ${promptLength(text) > PROMPT_LIMIT ? "text-rose-700" : "text-slate-500"}`} data-testid="owner-prompt-count">
            {promptLength(text)} / {PROMPT_LIMIT.toLocaleString("en-US")}
          </p>
          <p className="text-xs text-slate-500">Each page read sends this prompt; longer prompts cost more per audit.</p>
          <p className="text-xs text-slate-500">Every upload creates a new version. Nothing is deleted, and the text is not shown again.</p>
          <Button disabled={busy || !text.trim() || !name} onClick={upload} className="bg-sky-600 hover:bg-sky-500" data-testid="owner-prompt-upload">
            Upload as new version
          </Button>
        </div>
      </section>

      <section data-testid="owner-testers">
        <h2 className="font-heading text-lg font-semibold text-slate-900 mb-2">Tester links</h2>
        {shown && (
          <div className="border border-sky-300 bg-sky-50 rounded-md p-3 mb-4" data-testid="owner-link-once">
            <p className="text-sm text-slate-800 mb-1">Link for {shown.label}</p>
            <input readOnly value={shown.link} onFocus={(e) => e.target.select()} data-testid="owner-link"
              className="w-full font-mono text-xs border border-input rounded px-2 py-1 bg-white" />
            <p className="text-xs text-slate-600 mt-1">{LINK_ONCE}</p>
            <Button variant="outline" size="sm" className="mt-2" onClick={() => setShown(null)} data-testid="owner-link-dismiss">I have copied it</Button>
          </div>
        )}
        <div className="flex flex-wrap items-end gap-2 mb-4">
          <div>
            <label className="block text-sm text-slate-800" htmlFor="owner-tester-name">Name</label>
            <Input id="owner-tester-name" value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} data-testid="owner-tester-name" />
          </div>
          <Button disabled={busy || !label.trim()} onClick={issue} className="bg-sky-600 hover:bg-sky-500" data-testid="owner-tester-issue">Issue link</Button>
        </div>
        <table className="w-full text-sm" data-testid="owner-testers-table">
          <thead><tr className="text-left text-slate-500"><th className="py-1">Name</th><th>Status</th><th>Expires</th><th /></tr></thead>
          <tbody>
            {testers.map((t) => (
              <tr key={t.id} className="border-t border-[#E5E7EB]" data-testid="owner-tester-row">
                <td className="py-1">{t.label}</td>
                <td className={STATUS[statusOf(t)]} data-testid="owner-tester-status">{statusOf(t)}</td>
                <td>{when(t.expires_at)}</td>
                <td className="text-right space-x-2">
                  <Button variant="outline" size="sm" disabled={busy || statusOf(t) === "revoked"} onClick={() => change(ownerRevokeTester, t)}
                    data-testid="owner-tester-revoke">Revoke</Button>
                  <Button variant="outline" size="sm" disabled={busy} onClick={() => change(ownerReissueTester, t)}
                    data-testid="owner-tester-reissue">Re-issue</Button>
                </td>
              </tr>
            ))}
            {testers.length === 0 && <tr><td colSpan={5} className="py-2 text-slate-500">No tester yet.</td></tr>}
          </tbody>
        </table>
      </section>

      <OwnerUsage usage={usage} busy={busy} onSave={saveAllowance} />

      <OwnerAuditCosts costs={costs} />
    </main>
  );
}
