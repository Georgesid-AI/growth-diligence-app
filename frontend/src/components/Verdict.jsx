import { fmtExact } from "@/lib/format";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getClaimRegister, getMemo, putIcInputs, updateClaimInputs } from "@/lib/api";
import { describeRequestError } from "@/lib/requestError";
import { seeGlossary } from "@/lib/glossary";
import ContradictionBanner from "@/components/ContradictionBanner";
import GateEditor from "@/components/GateEditor";
import { registerRows } from "@/lib/claimRegister";
import {
  CHANGE, DETAIL_HEADING, GATE_EDIT, MEMO_BUTTON, NOTE_HELP, NOTE_LABEL, PART_GAPS, PART_INPUTS, PART_KEY_GATES, PART_RATINGS, PART_REASONS,
  PART_UNRESOLVED, RATING_DETAILS, RATING_RULES, REPLACE, RESET, REVIEW_LABEL, SELECTION_CHANGED, THESIS_MAX, TOP5_HEADING,
  USE_SELECTION, candidateText, initialPicks, refusalText, replacePick, samePicks,
  CONCLUSION_HEADING, NO_OTHER_CONTRADICTIONS, OTHER_CONTRADICTIONS, SCOPE_SENTENCE,
} from "@/lib/verdict";
import { CONFLICTS_HEADING } from "@/lib/claimGroups";

const selectClass = "h-8 rounded-md border border-[#E5E7EB] bg-white px-2 text-xs";

/** The top 5 the analyst may change: the five in force, a pick per row from the register, and "Use this selection". The app's own selection
 *  is in force without any confirmation (docs/design/simplified-flow.md section 3). */
export function TopFive({ verdict, candidates, onSave, busy }) {
  const stored = initialPicks(verdict);
  const [picks, setPicks] = useState(stored);
  const key = stored.join("|");
  useEffect(() => setPicks(key ? key.split("|") : []), [key]);
  const byId = Object.fromEntries(candidates.map((c) => [c.claim_id, c]));
  return (
    <div className="mb-4" data-testid="verdict-top5">
      <h3 className="text-sm font-semibold text-slate-900">{TOP5_HEADING}</h3>
      <ul className="space-y-1.5 mt-1">
        {picks.map((id, i) => (
          <li key={i} className="flex flex-wrap items-center gap-2 text-xs" data-testid="verdict-pick-row">
            <span className="text-slate-900 min-w-[16rem]">{byId[id] ? candidateText(byId[id]) : id}</span>
            <select value="" onChange={(e) => e.target.value && setPicks((p) => replacePick(p, i, e.target.value))} className={`${selectClass} max-w-[16rem]`}
              data-testid="verdict-pick-select" aria-label={REPLACE}>
              <option value="">{REPLACE}</option>
              {candidates.filter((c) => !picks.includes(c.claim_id)).map((c) => <option key={c.claim_id} value={c.claim_id}>{candidateText(c)}</option>)}
            </select>
          </li>
        ))}
      </ul>
      <Button size="sm" disabled={busy || samePicks(picks, stored)} onClick={() => onSave(picks)} className="mt-2 h-8 bg-sky-600 hover:bg-sky-500" data-testid="verdict-use">
        {USE_SELECTION}
      </Button>
    </div>
  );
}

/** The memo as a file: the server builds it from what is stored, or refuses and says why. */
export async function downloadMemo(auditId) {
  try {
    const r = await getMemo(auditId);
    const name = /filename="([^"]+)"/.exec(r.headers?.["content-disposition"] || "")?.[1] || "ic_memo.md";
    const url = URL.createObjectURL(new Blob([r.data], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
    return true;
  } catch (e) { toast.error(refusalText(e)); return false; }
}

/** The three thesis sentences. They start as the draft the server writes from computed text (Plan, Evidence, Condition) and are editable; a
 *  sentence is stored only once the analyst changes it, and an emptied one gives the draft back. */
export function ThesisFields({ verdict, save }) {
  const ic = verdict.ic_inputs || {};
  const draft = verdict.thesis_draft || {};
  const baseline = (part) => ic.thesis?.[part] ?? draft[part] ?? "";
  const [thesis, setThesis] = useState({});
  const stored = JSON.stringify([ic.thesis || {}, draft]);
  useEffect(() => setThesis({}), [stored]);
  return Object.entries(verdict.thesis_labels || {}).map(([part, label]) => (
    <label key={part} className="flex flex-col gap-1 text-slate-700 md:col-span-2">
      <span>{label}{ic.thesis?.[part] ? "" : <span className="text-[10px] font-mono text-slate-500" data-testid={`inputs-thesis-${part}-draft`}> · draft from computed text</span>}</span>
      <textarea value={thesis[part] ?? baseline(part)} maxLength={THESIS_MAX} rows={2} data-testid={`inputs-thesis-${part}`}
        className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
        onChange={(e) => setThesis((t) => ({ ...t, [part]: e.target.value }))}
        onBlur={() => thesis[part] !== undefined && thesis[part] !== baseline(part) && save({ thesis: { [part]: thesis[part].trim() || null } })} />
    </label>
  ));
}

/** Saves an input of the IC memo and tells the parent to read the verdict again. */
export const icSaver = (auditId, onChanged) => (body) => putIcInputs(auditId, body).then(() => onChanged && onChanged())
  .catch((e) => { toast.error(describeRequestError(e).message); if (onChanged) onChanged(); });

function Inputs({ auditId, verdict, onChanged }) {
  const ic = verdict.ic_inputs || {};
  const save = icSaver(auditId, onChanged);
  return (
    <div data-testid="verdict-inputs">
      <h3 className="text-sm font-semibold text-slate-900 mb-2">{PART_INPUTS}</h3>
      <div className="grid gap-3 md:grid-cols-2 text-xs">
        <label className="flex items-center gap-2 text-slate-700">
          {REVIEW_LABEL}
          <Input type="date" value={ic.first_quarterly_review ?? ""} className="h-8 text-xs font-mono w-40" data-testid="inputs-review-date"
            onChange={(e) => save({ first_quarterly_review: e.target.value || null })} />
        </label>
        <ThesisFields verdict={verdict} save={save} />
      </div>
    </div>
  );
}

/** The analyst note: one optional free text beside Download report, at most 1,000 characters, stored on the audit, one line in the
 *  report, never sent to a model. It saves when the field loses focus with a changed text. */
export function AnalystNote({ auditId, note, noteMax }) {
  const [text, setText] = useState(note ?? "");
  useEffect(() => setText(note ?? ""), [note]);
  const save = () => text.trim() !== (note ?? "") && putIcInputs(auditId, { note: text.trim() || null })
    .catch((e) => toast.error(describeRequestError(e).message));
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-700 w-full max-w-xl" data-testid="analyst-note">
      {NOTE_LABEL}
      <textarea value={text} maxLength={noteMax} rows={2} onChange={(e) => setText(e.target.value)} onBlur={save}
        className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs" data-testid="analyst-note-text" />
      {noteMax != null && (
        <span className={`self-end text-[10px] ${text.length >= noteMax ? "text-red-600" : "text-slate-500"}`} data-testid="analyst-note-count">
          {fmtExact(text.length)}/{fmtExact(noteMax)}
        </span>
      )}
      <span className="text-[10px] text-slate-500" data-testid="analyst-note-help">{NOTE_HELP}</span>
    </label>
  );
}

/** Download report: the IC memo. Nothing is required first: the server builds the report from what is stored, or refuses (toast) only for a
 *  number it cannot find, the word limit or results that fail the contract. The button sits at the top of the report page and again at the
 *  very end (`end`); both call the same download. The analyst note sits in the page, before the anomaly flags (`ReportNote`). */
export function ReportDownload({ auditId, end = false }) {
  return (
    <section className="mb-6 flex flex-wrap items-start gap-4" data-testid={end ? "report-download-end" : "report-download"}>
      <Button size="sm" variant="outline" onClick={() => downloadMemo(auditId)} className="h-8" data-testid={end ? "verdict-memo-end" : "verdict-memo"}>
        <Download className="h-3.5 w-3.5 mr-1.5" />{MEMO_BUTTON}
      </Button>
    </section>
  );
}

/** The analyst note, placed at the end of the report page, directly before the anomaly flags. Text and behaviour as before. */
export function ReportNote({ auditId, note, noteMax }) {
  return (
    <section className="mb-6" data-testid="report-note">
      <AnalystNote auditId={auditId} note={note} noteMax={noteMax} />
    </section>
  );
}

/** The claims beside the conclusion that it does not assess: every Contradicted register row outside the five, by rank, with its
 *  metric, gap and source (claim-review-conclusion.md section 3). */
function OtherContradictions({ v }) {
  const others = v.other_contradictions || [];
  return (
    <div className="mb-4" data-testid="other-contradictions">
      <h3 className="text-sm font-semibold text-slate-900 mb-1">{OTHER_CONTRADICTIONS}</h3>
      {others.length === 0 ? <p className="text-xs text-slate-600">{v.other_contradictions_text || NO_OTHER_CONTRADICTIONS}</p> : (
        <ul className="space-y-1 text-xs text-slate-800">
          {others.map((o) => (
            <li key={o.claim_id} data-testid="other-contradiction-row">
              {o.metric}: {o.gap}
              <span className="block text-[11px] font-mono text-slate-500">{o.source}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The annual figures that conflict and stay unresolved (docs/specs/claim-groups.md section 5): beside the contradictions, shown even when no
 *  single figure can be in the five, until one is corrected, scoped or excluded. */
function UnresolvedConflicts({ conflicts }) {
  return (
    <div className="mb-4" data-testid="unresolved-conflicts">
      <h3 className="text-sm font-semibold text-slate-900 mb-1">{CONFLICTS_HEADING}</h3>
      <ul className="space-y-1 text-xs text-slate-800">
        {conflicts.map((c) => <li key={c.id} data-testid="unresolved-conflict">{c.text}</li>)}
      </ul>
    </div>
  );
}

/** The conclusion (docs/design/simplified-flow.md, The conclusion screen): the outcome with its one-line rule and the scope sentence,
 *  the contradiction lines directly under them, the claims outside the five, the selection sentence and the one Change link of the top 5.
 *  `verdict` is GET /audits/{id}/verdict, read again by the parent after every change. The conclusion is always computed: an open question
 *  is a count in the rule line, not a state. */
export function Conclusion({ auditId, verdict, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [changing, setChanging] = useState(false);
  if (!verdict) return null;
  const v = verdict.verdict;
  const use = (ids) => {
    setBusy(true);
    return putIcInputs(auditId, { top5: ids }).then(() => { setChanging(false); return onChanged && onChanged(); })
      .catch((e) => toast.error(describeRequestError(e).message))
      .finally(() => setBusy(false));
  };
  const reset = () => use(null);
  const changed = Boolean(v.top5?.changed);
  return (
    <section className="mb-6 rounded-md border border-[#E5E7EB] bg-white p-4" data-testid="verdict">
      <h2 className="font-heading text-lg font-semibold text-slate-900 mb-1">{v.heading || CONCLUSION_HEADING}</h2>
      {v.message && <p className="text-sm text-slate-800 mb-2" data-testid="verdict-message">{seeGlossary(v.message)}</p>}
      {v.status === "ok" && (
        <div className="mb-2" data-testid="verdict-outcome">
          <p className="text-base font-semibold text-slate-900">{v.outcome}</p>
          <p className="text-sm text-slate-700" data-testid="verdict-rule">{seeGlossary(v.rule)}</p>
        </div>
      )}
      <p className="text-xs text-slate-600 mb-3" data-testid="conclusion-scope">{v.scope_sentence || SCOPE_SENTENCE}</p>
      <ContradictionBanner auditId={auditId} />
      {v.status !== "no_verdict" && <OtherContradictions v={v} />}
      {(v.conflicts || []).length > 0 && <UnresolvedConflicts conflicts={v.conflicts} />}
      {v.status !== "no_verdict" && (
        <>
          {changed && (
            <p className="text-xs text-slate-600" data-testid="verdict-top5-note">
              {SELECTION_CHANGED} <button type="button" className="text-sky-700 underline underline-offset-2" disabled={busy} data-testid="top5-reset" onClick={reset}>{RESET}</button>
            </p>
          )}
          <button type="button" className="text-xs text-sky-700 underline underline-offset-2" aria-expanded={changing} data-testid="top5-change"
            onClick={() => setChanging((c) => !c)}>{CHANGE}</button>
          {changing && <div className="mt-2"><TopFive verdict={v} candidates={verdict.candidates || []} onSave={use} busy={busy} /></div>}
        </>
      )}
    </section>
  );
}

/** The ratings, computed: two lines and the rule under details. Any rating that uses an industry threshold carries the label. */
function Ratings({ verdict }) {
  const ratings = verdict.ratings;
  const [open, setOpen] = useState(false);
  if (!ratings) return null;
  const rows = [["Data reliability", ratings.data_reliability], ["Growth engine", ratings.growth_engine]];
  return (
    <div className="mb-4" data-testid="verdict-ratings">
      <h3 className="text-sm font-semibold text-slate-900 mb-1">{PART_RATINGS}</h3>
      <ul className="space-y-1 text-xs text-slate-800">
        {rows.map(([label, r]) => (
          <li key={label} data-testid="verdict-rating">
            {label}: {r.line}
            {r.benchmark && <span className="ml-1 text-[10px] font-mono text-slate-500" data-testid="rating-benchmark">{verdict.benchmark_label}</span>}
          </li>
        ))}
      </ul>
      <button type="button" className="text-xs text-sky-700 underline underline-offset-2" aria-expanded={open} data-testid="ratings-details" onClick={() => setOpen((o) => !o)}>{RATING_DETAILS}</button>
      {open && <p className="mt-1 text-[11px] text-slate-600" data-testid="ratings-rules">{rows.map(([, r]) => r.rule).join(" · ")} · {RATING_RULES}</p>}
    </div>
  );
}

/** The key gates: the gate of each non-Verified claim of the five, "(proposed)" until the analyst edits it here, then "(set by the analyst)". */
function KeyGates({ auditId, verdict, rows, ccy, onChanged }) {
  const key = verdict.key_gates;
  const [editing, setEditing] = useState(null);
  const byId = Object.fromEntries((rows || []).map((r) => [r.claim_id, r]));
  const save = (row, edit) => updateClaimInputs(auditId, row.claim_id, edit)
    .then(() => { if (onChanged) onChanged(); })
    .catch((e) => { toast.error(describeRequestError(e).message); throw e; });
  return (
    <div className="mb-4" data-testid="verdict-key-gates">
      <h3 className="text-sm font-semibold text-slate-900 mb-1">{PART_KEY_GATES}</h3>
      {key.note && <p className="text-xs text-slate-600">{seeGlossary(key.note)}</p>}
      <ul className="space-y-1 text-xs text-slate-800">
        {key.sentences.map((s) => (
          <li key={s.claim_id} data-testid="key-gate">
            {seeGlossary(s.text || s.sentence)}{" "}
            {byId[s.claim_id] && (
              <button type="button" className="text-sky-700 underline underline-offset-2" aria-expanded={editing === s.claim_id} data-testid="key-gate-edit"
                onClick={() => setEditing(editing === s.claim_id ? null : s.claim_id)}>{GATE_EDIT}</button>
            )}
            {editing === s.claim_id && byId[s.claim_id] && <GateEditor key={`${s.claim_id}-${s.status}`} row={byId[s.claim_id]} ccy={ccy} onSave={save} />}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The detail of the conclusion, for Supporting detail: the three reasons, the key gates (edited here only), the deal terms, the top data
 *  gaps, the computed ratings and unresolved questions, and the inputs. `tick` reads the register rows the gate editor needs again. */
export function VerdictDetail({ auditId, verdict, onChanged, ccy, tick }) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    let cancelled = false;
    Promise.resolve(getClaimRegister(auditId)).then((d) => { if (!cancelled) setRows(registerRows(d)); }).catch(() => {});
    return () => { cancelled = true; };
  }, [auditId, tick, verdict]);
  if (!verdict) return null;
  const v = verdict.verdict;
  return (
    <section className="mb-6 rounded-md border border-[#E5E7EB] bg-white p-4" data-testid="verdict-detail">
      <h2 className="font-heading text-lg font-semibold text-slate-900 mb-3">{DETAIL_HEADING}</h2>
      {v.status === "ok" && (
        <>
          <div className="mb-4" data-testid="verdict-reasons">
            <h3 className="text-sm font-semibold text-slate-900 mb-1">{PART_REASONS}</h3>
            <ol className="list-decimal pl-5 space-y-1 text-xs text-slate-800">{v.reasons.map((r) => <li key={r}>{seeGlossary(r)}</li>)}</ol>
          </div>
          <KeyGates auditId={auditId} verdict={verdict} rows={rows} ccy={ccy} onChanged={onChanged} />
          <p className="text-xs text-slate-700 mb-4" data-testid="verdict-deal-terms">{verdict.deal_terms}</p>
          <div className="mb-4" data-testid="verdict-top-gaps">
            <h3 className="text-sm font-semibold text-slate-900 mb-1">{PART_GAPS}</h3>
            <ul className="space-y-1 text-xs text-slate-800">{verdict.top_gaps.map((g) => <li key={g.item}>{g.item} · {seeGlossary(g.why)}</li>)}</ul>
          </div>
        </>
      )}
      <Ratings verdict={verdict} />
      {(verdict.unresolved_questions || []).length > 0 && (
        <div className="mb-4" data-testid="verdict-unresolved">
          <h3 className="text-sm font-semibold text-slate-900 mb-1">{PART_UNRESOLVED}</h3>
          <ul className="space-y-1 text-xs text-slate-800 list-disc pl-5">{verdict.unresolved_questions.map((q) => <li key={q}>{seeGlossary(q)}</li>)}</ul>
        </div>
      )}
      <Inputs auditId={auditId} verdict={verdict} onChanged={onChanged} />
    </section>
  );
}
