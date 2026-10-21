import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Download, Loader2, Sparkles } from "lucide-react";
import { Layout } from "@/components/Layout";
import { BLOCKERS_CHANGED } from "@/components/BlockerBanner";
import { ColumnRow } from "@/components/UploadChat";
import { DefinitionCell, TurnoverCell, GateCell } from "@/components/ClaimRegister";
import { TopFive, ThesisFields, RatingFields, JudgmentFields, downloadMemo, icSaver } from "@/components/Verdict";
import { Button } from "@/components/ui/button";
import * as apiModule from "@/lib/api";
import {
  answerDefinitionCheck, answerTurnover, approveAll, decideColumns, generateNarrative, getAudit, getClaimRegister, getDatasets, getDecks, getNarrativeEstimate,
  getReview, getVerdict, putIcInputs, reportUsage, updateCandidate, updateClaimInputs,
} from "@/lib/api";
import { claimPeriod, claimValue, sourceRef, typeLabel, CLAIM_GROUPS, approveAllToast, isOther, STALE_LABEL } from "@/lib/deckClaims";
import { JUDGMENT_HEADING } from "@/lib/verdict";
import { definitionOf, turnoverHeading, turnoverOf, registerRows } from "@/lib/claimRegister";
import { useGateEdits } from "@/lib/useGateEdits";
import { S13_status, MAPPING_HEADERS, REASONS, fieldName, heldFields, sortColumns } from "@/lib/chatUpload";
import { describeRequestError, READ_TIMEOUT_MS } from "@/lib/requestError";
import { runAudit } from "@/lib/runAudit";
import { mappingSummary, summaryHeadline, DTYPE_SHORT, writeAllLabel, allWritten, ALL_WRITTEN_LEAD, ALL_WRITTEN_LINK, WRITE_ALL_HELP, MEMO_LABEL, MEMO_WAITING, RECONCILIATION_NOTE } from "@/lib/review";

const GROUP_TITLE = Object.fromEntries(CLAIM_GROUPS);

/**
 * The review screen: everything the analyst decides, in one place and in one order. Open mappings, open claims (with their Definition
 * checks), Revenue / Volume answers, the top 5, the deal thesis, the gates and the ratings; then Write all narratives and Generate IC memo. Whatever
 * the app could settle itself (columns above the mapping threshold, claims within tolerance) is a count with a Show link.
 */
export default function Review() {
  const { id } = useParams();
  const nav = useNavigate();
  const [audit, setAudit] = useState(null);
  const [summary, setSummary] = useState(null);
  const [views, setViews] = useState([]);
  const [deckData, setDeckData] = useState({ decks: [], candidates: [] });
  const [register, setRegister] = useState([]);
  const [gateExtras, setGateExtras] = useState({ prefill: {}, budgets: [] });
  const [verdict, setVerdict] = useState(null);
  const [estimate, setEstimate] = useState(null);
  const [proceeding, setProceeding] = useState(false);
  const [loadError, setLoadError] = useState(null);     // why the audit or its review could not be read: shown instead of a spinner
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const reload = useCallback(async () => {
    const safe = (p, fallback) => p.catch(() => fallback);
    // The audit and its review are what the screen stands on: a failure of either is shown, never swallowed.
    const [a, s, v, d] = await Promise.all([
      getAudit(id).catch((e) => ({ failed: e })), getReview(id).catch((e) => ({ failed: e })),
      safe(getDatasets(id), []), safe(getDecks(id), { decks: [], candidates: [] })]);
    if (!alive.current) return;
    const failed = a?.failed || s?.failed;
    if (failed) { setLoadError(describeRequestError(failed, { timeoutMs: READ_TIMEOUT_MS }).message); return; }
    setLoadError(null);
    setAudit(a); setSummary(s); setViews(v); setDeckData(d);
    if (s?.computed && !s.results_stale) {
      const [r, vd, est] = await Promise.all([safe(getClaimRegister(id), null), safe(getVerdict(id), null), safe(getNarrativeEstimate(id), null)]);
      if (!alive.current) return;
      setRegister(registerRows(r)); setGateExtras({ prefill: r?.gate_prefill || {}, budgets: r?.budget_decisions || [] }); setVerdict(vd); setEstimate(est);
    }
    window.dispatchEvent(new Event(BLOCKERS_CHANGED));
  }, [id]);
  useEffect(() => { reload(); reportUsage(id, { screen: "review" }); }, [id, reload]);

  // Once the last column is decided, the stages carry on by themselves: nothing more to press.
  const carryOn = useCallback(async () => {
    setProceeding(true);
    try { await runAudit({ api: apiModule, auditId: id, from: "mapping" }); } finally { if (alive.current) setProceeding(false); }
    await reload();
  }, [id, reload]);

  const decide = async (view, decisions) => {
    const next = await decideColumns(id, view.dtype, decisions);
    const fresh = await getDatasets(id).catch(() => []);
    if (alive.current) setViews(fresh);
    const waiting = fresh.some((x) => x.pending > 0 || x.missing_required.length > 0);
    if (!waiting && !summary?.computed) await carryOn(); else await reload();
    return next;
  };

  if (loadError) {
    return (
      <Layout audit={audit}>
        <div className="max-w-xl mx-auto py-24 text-center" data-testid="review-load-error">
          <p className="text-sm text-slate-900">The review could not be loaded.</p>
          <p className="mt-1 text-sm text-rose-800 font-mono break-words">{loadError}</p>
          <div className="mt-4 flex justify-center gap-3">
            <Button size="sm" onClick={() => { setLoadError(null); reload(); }} data-testid="review-load-retry">Retry</Button>
            <Button size="sm" variant="outline" asChild><Link to="/" data-testid="review-load-list">Back to the audit list</Link></Button>
          </div>
        </div>
      </Layout>
    );
  }
  if (!audit || !summary) {
    return <Layout audit={audit}><div className="flex justify-center py-32 text-slate-500"><Loader2 className="h-6 w-6 animate-spin" /></div></Layout>;
  }
  const saveIc = icSaver(id, reload);

  return (
    <Layout audit={audit}>
      <div className="flex items-end justify-between flex-wrap gap-3 mb-6">
        <div>
          <h1 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">Review</h1>
          <p className="text-sm text-slate-600 mt-1 max-w-3xl">Only what needs a decision from you is open below. Everything else is a count you can open with Show.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => nav(`/audit/${id}/mapping`)} data-testid="review-to-mapping">Back to Upload & Mapping</Button>
      </div>
      {proceeding && <p className="mb-4 flex items-center gap-2 text-sm text-slate-600" data-testid="review-continuing"><Loader2 className="h-4 w-4 animate-spin" /> Continuing the run…</p>}

      <MappingsSection views={views} decide={decide} />
      <ClaimsSection auditId={id} data={deckData} summary={summary} reload={reload} />
      <TurnoverSection auditId={id} data={deckData} reload={reload} />
      {summary.results_stale ? (
        <p className="text-sm text-slate-600 border border-dashed border-[#D1D5DB] rounded-md px-4 py-6" data-testid="review-stale">{STALE_LABEL}</p>
      ) : summary.computed && verdict ? (
        <>
          <TopFiveSection auditId={id} verdict={verdict} reload={reload} />
          <ThesisSection verdict={verdict} save={saveIc} />
          <GatesSection auditId={id} verdict={verdict} register={register} extras={gateExtras} audit={audit} reload={reload} />
          <RatingsSection verdict={verdict} save={saveIc} />
          <JudgmentSection verdict={verdict} save={saveIc} />
          <Finish auditId={id} verdict={verdict} summary={summary} estimate={estimate} reload={reload} />
        </>
      ) : (
        <p className="text-sm text-slate-600 border border-dashed border-[#D1D5DB] rounded-md px-4 py-6" data-testid="review-not-computed">
          The metrics are not calculated yet. Decide what is open above, or go back to Upload & Mapping.
        </p>
      )}
    </Layout>
  );
}

const sectionClass = "mb-6 rounded-md border border-[#E5E7EB] bg-white p-4";
const Heading = ({ n, children }) => <h2 className="font-heading text-base font-semibold text-slate-900 mb-2"><span className="font-mono text-slate-500 mr-2">{n}</span>{children}</h2>;

/** "12 claims within tolerance" with a Show link that opens the list. */
function Counted({ testid, text, children }) {
  return (
    <details className="mt-3 text-xs text-slate-700" data-testid={testid}>
      <summary className="cursor-pointer"><span data-testid={`${testid}-count`}>{text}</span> <span className="text-sky-700 underline underline-offset-2">Show</span></summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

function MappingsSection({ views, decide }) {
  const [lastReason, setLastReason] = useState("header_misleading");
  const open = views.filter((v) => v.pending > 0 || v.missing_required.length > 0);
  return (
    <section className={sectionClass} data-testid="review-mappings">
      <Heading n="1">Open mappings</Heading>
      {open.length === 0 && <p className="text-sm text-slate-600" data-testid="review-mappings-none">No column waits for you.</p>}
      {open.map((view) => {
        const rows = view.missing_required.length ? view.columns : view.columns.filter((c) => c.pending);
        return (
          <div key={view.dtype} className="mt-2" data-testid={`review-mapping-${view.dtype}`}>
            <div className="text-xs font-medium text-slate-900">{view.file} <span className="font-mono text-amber-700">· {S13_status(view)}</span></div>
            <table className="w-full text-xs mt-1">
              <thead><tr className="text-left text-slate-500 border-b border-[#E5E7EB]">{MAPPING_HEADERS.map((h, i) => <th key={i} className="py-1.5 pr-3 font-medium">{h}</th>)}</tr></thead>
              <tbody>
                {sortColumns(rows).map((c) => <ColumnRow key={c.column} row={c} view={view} decide={decide} lastReason={lastReason} setLastReason={setLastReason} />)}
              </tbody>
            </table>
          </div>
        );
      })}
      <MappingSummary views={views} decide={decide} lastReason={lastReason} setLastReason={setLastReason} />
    </section>
  );
}

const GREY_ROW = "bg-slate-900/[0.035]";                       // rows alternate: page colour, then 3-4% grey
const linkBtn = "text-slate-600 underline underline-offset-2 hover:text-slate-900";
const smallBtn = "rounded bg-slate-900/[0.06] px-2 py-0.5 text-slate-700 hover:bg-slate-900/10 disabled:opacity-50";

/** Mapping summary (chat-upload.md section 18): one line, the file chips, one row per unsure column, and a collapsed full list. One font size. */
function MappingSummary({ views, decide, lastReason, setLastReason }) {
  const [showAll, setShowAll] = useState(false);
  const { matched, unsure } = mappingSummary(views, fieldName);
  const chips = views.filter((v) => v.columns.some((c) => c.state !== "unused"));
  return (
    <div className="mt-4 text-sm leading-8 text-slate-800" data-testid="review-mappings-summary">
      <div className={`font-bold ${unsure.length ? "text-slate-900" : "text-emerald-700"}`} data-testid="review-mappings-headline">
        {summaryHeadline(matched.length, unsure.length)}
      </div>
      <div className="flex flex-wrap gap-2 my-1" data-testid="review-mappings-chips">
        {chips.map((v) => <span key={v.dtype} className="rounded-full bg-slate-900/[0.06] px-2.5 text-slate-600" data-testid="review-mappings-chip">{DTYPE_SHORT[v.dtype] || v.dtype}</span>)}
      </div>
      {unsure.map(({ view, col }, i) => (
        <UnsureRow key={`${view.dtype}-${col.column}`} view={view} col={col} striped={i % 2 === 1} decide={decide} lastReason={lastReason} setLastReason={setLastReason} />
      ))}
      <button type="button" className={`${linkBtn} mt-1`} aria-expanded={showAll} data-testid="review-details-toggle" onClick={() => setShowAll((v) => !v)}>
        {showAll ? "Hide details" : "Show details"}
      </button>
      {showAll && (
        <div data-testid="review-details">
          {views.map((v) => {
            const rows = v.columns.filter((c) => c.state !== "unused");
            return (
              <div key={v.dtype} className="mt-2" data-testid={`review-details-${v.dtype}`}>
                <div>{v.file}</div>
                {rows.map((c, i) => (
                  <div key={c.column} className={`px-2 ${i % 2 === 1 ? GREY_ROW : ""}`} data-testid={`review-detail-${v.dtype}-${c.column}`}>
                    "{c.column}" read as {fieldName(c.field)}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function UnsureRow({ view, col, striped, decide, lastReason, setLastReason }) {
  const [editing, setEditing] = useState(false);
  const [field, setField] = useState(col.field || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const held = heldFields(view.columns, col.column);
  const fields = [...view.fields.required, ...view.fields.optional];
  const send = async (decision) => {
    setSaving(true); setError(null);
    try { await decide(view, [decision]); setEditing(false); }
    catch (e) { setError(describeRequestError(e).message); }
    finally { setSaving(false); }
  };
  return (
    <div className={`px-2 ${striped ? GREY_ROW : ""}`} data-testid={`review-unsure-${view.dtype}-${col.column}`}>
      <div className="flex items-center justify-between gap-3">
        <span><span className="mr-3">{DTYPE_SHORT[view.dtype] || view.dtype}</span>"{col.column}" read as {fieldName(col.field)}</span>
        <span className="whitespace-nowrap">
          <button type="button" className={`${smallBtn} mr-1.5`} disabled={saving} data-testid={`review-correct-${view.dtype}-${col.column}`}
            onClick={() => send({ column: col.column, action: "confirm", field: col.field })}>Correct</button>
          <button type="button" className={smallBtn} data-testid={`review-change-${view.dtype}-${col.column}`} onClick={() => setEditing((v) => !v)}>Change</button>
        </span>
      </div>
      {editing && (
        <div className="flex flex-wrap items-center gap-2 pb-1" data-testid={`review-change-editor-${view.dtype}-${col.column}`}>
          <select value={field} onChange={(e) => setField(e.target.value)} data-testid={`review-change-field-${view.dtype}-${col.column}`} className="h-8 rounded bg-white text-sm px-1.5">
            <option value="">Not used</option>
            {fields.map((f) => <option key={f} value={f} disabled={!!held[f]}>{fieldName(f)}{held[f] ? ` (held by ${held[f]})` : ""}</option>)}
          </select>
          <select value={lastReason} onChange={(e) => setLastReason(e.target.value)} data-testid={`review-change-reason-${view.dtype}-${col.column}`} className="h-8 rounded bg-white text-sm px-1.5">
            {REASONS.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
          </select>
          <button type="button" className={smallBtn} disabled={saving} data-testid={`review-change-apply-${view.dtype}-${col.column}`}
            onClick={() => send({ column: col.column, action: "correct", field: field || null, reason: lastReason })}>Apply</button>
          {error && <span className="text-rose-700">{error}</span>}
        </div>
      )}
    </div>
  );
}

function ClaimsSection({ auditId, data, summary, reload }) {
  const [busy, setBusy] = useState(null);
  // A claim with an open Definition check (claim-matching.md section 4.1) is To review whether it is approved or not: it asks here.
  const asks = (c) => definitionOf(c).open;
  // An Other figure is never a task (claim-types-and-correction.md section 4): it is not listed here.
  const open = data.candidates.filter((c) => !isOther(c) && ((c.status === "pending" && !turnoverOf(c).open) || (c.status !== "rejected" && asks(c))));
  const auto = data.candidates.filter((c) => c.auto_accepted && ["approved", "edited"].includes(c.status));
  const groups = [...new Set(open.map((c) => c.group))].sort((a, b) => a - b);
  const act = async (key, fn) => {
    setBusy(key);
    try { await fn(); await reload(); } catch (e) { toast.error(describeRequestError(e).message); } finally { setBusy(null); }
  };
  const answerDefinition = (row, value) => act(row.claim_id, () => answerDefinitionCheck(auditId, row.claim_id, value));
  return (
    <section className={sectionClass} data-testid="review-claims">
      <Heading n="2">Open claims</Heading>
      {open.length === 0 && <p className="text-sm text-slate-600" data-testid="review-claims-none">No claim waits for you.</p>}
      {groups.map((g) => (
        <div key={g} className="mt-2" data-testid={`review-claim-group-${g}`}>
          <div className="flex items-center justify-between">
            <div className="text-xs font-medium text-slate-900">{GROUP_TITLE[g] || "Other"}</div>
            <Button size="sm" variant="outline" className="h-7" disabled={busy !== null} data-testid={`review-approve-all-${g}`}
              onClick={() => act(`g${g}`, async () => { const done = await approveAll(auditId, g); toast.success(approveAllToast(done.approved, done.skipped, done.open_definition)); })}>
              Approve all ({open.filter((c) => c.group === g && c.status === "pending").length})
            </Button>
          </div>
          <table className="w-full text-xs mt-1"><tbody>
            {open.filter((c) => c.group === g).map((c) => (
              <tr key={c.id} className="border-b border-[#F1F5F9] align-top" data-testid="review-claim-row">
                <td className="py-1.5 pr-3 text-slate-900">{typeLabel(c.claim_type)}</td>
                <td className="py-1.5 pr-3 font-mono">{claimValue(c)}</td>
                <td className="py-1.5 pr-3 font-mono text-slate-600">{claimPeriod(c)}</td>
                <td className="py-1.5 pr-3 font-mono text-slate-500">{sourceRef(c.sources?.[0])}</td>
                <td className="py-1.5 whitespace-nowrap">
                  {asks(c) ? (
                    definitionOf(c).views.filter((v) => v.definition_check === "ask").map((v) => (
                      <DefinitionCell key={v.claim_id} row={v} onAnswer={answerDefinition} heading={c.by_period?.length ? v.period : undefined} />
                    ))
                  ) : (
                    <>
                      <Button size="sm" variant="outline" className="h-7 mr-1.5" disabled={busy !== null} data-testid="review-approve"
                        onClick={() => act(c.id, () => updateCandidate(auditId, c.id, { status: "approved" }))}>Approve</Button>
                      <Button size="sm" variant="ghost" className="h-7" disabled={busy !== null} data-testid="review-reject"
                        onClick={() => act(c.id, () => updateCandidate(auditId, c.id, { status: "rejected" }))}>Reject</Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody></table>
        </div>
      ))}
      <Counted testid="review-claims-auto" text={`${summary.claims.auto_accepted} claim${summary.claims.auto_accepted === 1 ? "" : "s"} within tolerance`}>
        <table className="w-full"><tbody>
          {auto.map((c) => (
            <tr key={c.id} className="border-b border-[#F1F5F9]" data-testid="review-auto-claim">
              <td className="py-1 pr-3">{typeLabel(c.claim_type)}</td><td className="py-1 pr-3 font-mono">{claimValue(c)}</td>
              <td className="py-1 pr-3 font-mono text-slate-600">{claimPeriod(c)}</td>
              <td className="py-1"><Button size="sm" variant="ghost" className="h-6" disabled={busy !== null}
                onClick={() => act(c.id, () => updateCandidate(auditId, c.id, { status: "rejected" }))}>Reject</Button></td>
            </tr>
          ))}
        </tbody></table>
      </Counted>
    </section>
  );
}

function TurnoverSection({ auditId, data, reload }) {
  const waiting = data.candidates.filter((c) => c.status === "pending" && turnoverOf(c).open);
  const answer = async (row, payload) => {
    try { await answerTurnover(auditId, row.claim_id, payload); await reload(); } catch (e) { toast.error(describeRequestError(e).message); throw e; }
  };
  return (
    <section className={sectionClass} data-testid="review-turnover">
      <Heading n="3">Revenue / Volume answers</Heading>
      {waiting.length === 0 && <p className="text-sm text-slate-600" data-testid="review-turnover-none">No claim asks Revenue or Volume.</p>}
      {waiting.map((c) => (
        <div key={c.id} className="mt-2 text-xs" data-testid="review-turnover-claim">
          <div className="text-slate-900">{typeLabel(c.claim_type)} · <span className="font-mono">{claimValue(c)}</span> · <span className="font-mono">{claimPeriod(c)}</span></div>
          {turnoverOf(c).views.map((v) => <TurnoverCell key={v.claim_id} row={v} onAnswer={answer} heading={turnoverHeading(v, Boolean(c.by_period?.length))} />)}
        </div>
      ))}
    </section>
  );
}

function TopFiveSection({ auditId, verdict, reload }) {
  const [busy, setBusy] = useState(false);
  const v = verdict.verdict;
  const confirm = (ids) => {
    setBusy(true);
    return putIcInputs(auditId, { top5: ids }).then(reload).catch((e) => toast.error(describeRequestError(e).message)).finally(() => setBusy(false));
  };
  return (
    <section className={sectionClass} data-testid="review-top5">
      <Heading n="4">Top 5 claims</Heading>
      {v.status === "no_verdict" ? <p className="text-sm text-slate-600" data-testid="review-top5-none">{v.message}</p>
        : <TopFive verdict={v} candidates={verdict.candidates || []} onConfirm={confirm} busy={busy} />}
    </section>
  );
}

function ThesisSection({ verdict, save }) {
  return (
    <section className={sectionClass} data-testid="review-thesis">
      <Heading n="5">Deal thesis</Heading>
      <div className="grid gap-3 md:grid-cols-2 text-xs"><ThesisFields verdict={verdict} save={save} /></div>
    </section>
  );
}

function GatesSection({ auditId, verdict, register, extras, audit, reload }) {
  const five = new Set((verdict.verdict.five || []).map((f) => f.claim_id));
  // a row still in Definition check is answered under Open claims first: its label, and so its need for a gate, follow the answer
  const rows = register.filter((r) => five.has(r.claim_id) && r.evidence_label !== "Verified" && r.definition_check !== "ask");
  const { edits, onEdit, clear, saveAll } = useGateEdits({ auditId, rows, prefill: extras.prefill, afterSave: reload });
  const save = (row, edit) => updateClaimInputs(auditId, row.claim_id, edit).then(() => { clear([row.claim_id]); return reload(); })
    .catch((e) => { toast.error(describeRequestError(e).message); throw e; });
  return (
    <section className={sectionClass} data-testid="review-gates">
      <Heading n="6">Gates</Heading>
      {verdict.verdict.top5?.confirmed && rows.length > 0 && (
        <Button size="sm" onClick={saveAll} className="h-8 bg-sky-600 hover:bg-sky-500" data-testid="review-gates-save-all">Save all gates</Button>
      )}
      {!verdict.verdict.top5?.confirmed && <p className="text-sm text-slate-600" data-testid="review-gates-wait">Confirm the top 5 first: a gate is set on each top-5 claim that is not Verified.</p>}
      {verdict.verdict.top5?.confirmed && rows.length === 0 && <p className="text-sm text-slate-600" data-testid="review-gates-none">Every top-5 claim is Verified: no gate is needed.</p>}
      {verdict.verdict.top5?.confirmed && rows.map((row) => (
        <div key={row.claim_id} className="mt-2 text-xs border-t border-[#F1F5F9] pt-2" data-testid="review-gate-row">
          <div className="text-slate-900 mb-1">#{row.rank} {row.claim} <span className="text-slate-500">· {row.evidence_label}</span></div>
          <GateCell row={row} ccy={audit.reporting_currency} onSave={save} prefill={extras.prefill[row.claim_id]} budgets={extras.budgets} edits={edits[row.claim_id]} onEdit={onEdit} />
        </div>
      ))}
    </section>
  );
}

function RatingsSection({ verdict, save }) {
  return (
    <section className={sectionClass} data-testid="review-ratings">
      <Heading n="7">Ratings</Heading>
      <div className="grid gap-3 md:grid-cols-2 text-xs"><RatingFields verdict={verdict} save={save} /></div>
    </section>
  );
}

/** The analyst judgment (claim-review-conclusion.md section 3): the same two fields as the Dashboard, so the memo can be exported from here. */
function JudgmentSection({ verdict, save }) {
  return (
    <section className={sectionClass} data-testid="review-judgment">
      <Heading n="8">{JUDGMENT_HEADING}</Heading>
      <div className="grid gap-3 md:grid-cols-2 text-xs"><JudgmentFields verdict={verdict} save={save} /></div>
    </section>
  );
}

/** Write all narratives and Generate IC memo (on once both ratings are entered). */
function Finish({ auditId, verdict, summary, estimate, reload }) {
  const [writing, setWriting] = useState(null);       // "2 of 3: Data inventory" while it runs
  const [outcome, setOutcome] = useState({});
  const [making, setMaking] = useState(false);
  const ratings = verdict.ic_inputs?.ratings || {};
  const rated = Object.keys(verdict.ratings_for || {}).every((row) => ratings[row]);
  const steps = (estimate?.steps || []).filter((s) => s.available);
  const wroteSome = Object.values(outcome).some((status) => status !== "unavailable");   // after a write the link shows at once

  const writeAll = async () => {
    const results = {};
    for (let i = 0; i < steps.length; i += 1) {
      setWriting(`${i + 1} of ${steps.length}: ${steps[i].label}`);
      try {
        const res = await generateNarrative(auditId, steps[i].step);
        results[steps[i].step] = res.narrative_status;
      } catch (e) {
        results[steps[i].step] = "unavailable";            // the metrics stay; the step says it could not be written
      }
      setOutcome({ ...results });
    }
    setWriting(null);
    await reload();
  };
  const makeMemo = async () => { setMaking(true); try { await downloadMemo(auditId); } finally { setMaking(false); } };
  const blockers = summary.blockers || [];

  return (
    <section className={sectionClass} data-testid="review-finish">
      <div className="flex flex-wrap items-center gap-3">
        <Button data-testid="write-all-narratives" onClick={writeAll} disabled={writing !== null || steps.length === 0} className="gap-2 bg-white text-slate-900 border border-[#D1D5DB] hover:bg-slate-50">
          {writing !== null ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4 text-sky-700" />}
          {writeAllLabel(writing)}
        </Button>
        {(allWritten(estimate) || wroteSome) && (
          <span className="text-xs text-slate-700" data-testid="write-all-done">
            {ALL_WRITTEN_LEAD}
            <Link to={`/audit/${auditId}/dashboard`} data-testid="write-all-link" className="text-sky-700 underline underline-offset-2">{ALL_WRITTEN_LINK}</Link>
          </span>
        )}
      </div>
      <p className="mt-1.5 max-w-2xl text-xs text-slate-500" data-testid="write-all-help">{WRITE_ALL_HELP}</p>
      {Object.entries(outcome).filter(([, status]) => status === "unavailable").map(([step]) => (
        <p key={step} className="mt-1 text-xs text-slate-600" data-testid="write-all-unavailable">Narrative unavailable for {steps.find((s) => s.step === step)?.label}: the computed metrics are unaffected.</p>
      ))}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button data-testid="generate-memo" onClick={makeMemo} disabled={!rated || making} className="gap-2 bg-sky-600 hover:bg-sky-500">
          {making ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}{MEMO_LABEL}
        </Button>
        {!rated && <span className="text-xs text-slate-600" data-testid="memo-waiting">{MEMO_WAITING}</span>}
      </div>
      {blockers.some((b) => b.kind === "revenue_reconciliation") && <p className="mt-2 text-xs text-rose-800" data-testid="memo-blockers">{RECONCILIATION_NOTE}</p>}
    </section>
  );
}
