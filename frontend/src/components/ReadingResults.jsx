import { useState } from "react";
import { decideCard, getCell, getDeckPage } from "@/lib/api";
import {
  ACTION_LABELS, HOVERS, NUMERIC, TITLES, WIDTHS, actualPlanLabel, basisLabel, cardTitle, periodLabel, sourceParts, valueText,
} from "@/lib/readingView";
import { PLACEHOLDER } from "@/lib/format";

/**
 * The three result tables across all files and the cards (docs/design/read-check-review.md sections 7.4 and 11.3; docs/design/audit-page-mockup.html).
 * Confirmed starts collapsed behind its count; Rejected and Cannot check show every row. Every heading has a hover text (lib/readingView.js HOVERS).
 * Source is always the last column, the cell or page first, and its link shows the cell or the page. Below 900 px a row is a card (App.css, .reading).
 */

/** The link of a Source: the cell with its neighbours, or the page's lines, shown under the row. */
export function SourceLink({ auditId, source, label }) {
  const [shown, setShown] = useState(null);
  const open = async (e) => {
    e.preventDefault();
    if (shown) { setShown(null); return; }
    try {
      if (source.page) {
        const page = await getDeckPage(auditId, source.deck_id, source.page);
        setShown({ page: page.lines.slice(0, 14) });
      } else if (source.file_hash && source.sheet && source.cell) {
        const first = String(source.cell).split(":")[0];
        setShown({ cells: await getCell(auditId, source.file_hash, source.sheet, first) });
      } else {
        setShown({ none: true });
      }
    } catch (err) {
      setShown({ none: true });
    }
  };
  const { first, rest } = sourceParts(source);
  return (
    <>
      <a href="#source" onClick={open} data-testid="source-link" title="Click to see the cell">
        {label || <><b>{first}</b>{rest ? ` · ${rest}` : ""}</>}
      </a>
      {shown && (
        <div data-testid="source-view" className="source-view">
          {shown.none && <span>Not available for this file.</span>}
          {shown.page && <ul>{shown.page.map((l) => <li key={l.ref}>{l.text}</li>)}</ul>}
          {shown.cells && (
            <table><tbody>{shown.cells.rows.map((r) => (
              <tr key={r.row}>{r.cells.map((c) => <td key={c.ref} className={c.cited ? "cited" : ""} title={c.ref}>{c.text}</td>)}</tr>
            ))}</tbody></table>
          )}
        </div>
      )}
    </>
  );
}

const cellsFor = {
  confirmed: (r, auditId) => [
    <>{r.metric}{r.note === "set by analyst" && (
      <><br /><span className="muted" data-testid="set-by-analyst" title={r.hover}>{r.note}{r.set_at ? `, ${r.set_at}` : ""}</span></>
    )}</>, valueText(r.value, r.unit, r.currency), periodLabel(r.period), r.label || PLACEHOLDER, basisLabel(r.basis), actualPlanLabel(r.actual_plan),
    r.row_role || PLACEHOLDER, <SourceLink key="s" auditId={auditId} source={r.source} />,
  ],
  rejected: (r, auditId) => [
    r.metric,
    <>{valueText(r.value, r.unit, r.currency)}{r.period && <><br /><span className="muted">{periodLabel(r.period)}</span></>}</>,
    <>{valueText(r.cell_value, r.unit, r.currency)}{r.cell_period && <><br /><span className="muted">{periodLabel(r.cell_period)}</span></>}</>,
    r.reason, r.reread,
    r.card_id ? <a key="d" href={`#card-${r.card_id}`}>Decide</a> : r.action,
    <SourceLink key="s" auditId={auditId} source={r.source} />,
  ],
  cannot_check: (r, auditId) => [
    r.metric, valueText(r.value, r.unit, r.currency), periodLabel(r.period), r.label || PLACEHOLDER, r.reason, r.used_in || PLACEHOLDER,
    <SourceLink key="s" auditId={auditId} source={r.source} />,
  ],
};
const NO_WRAP = ["Period", "Re-read", "Action"];

export function ResultTable({ kind, rows, auditId }) {
  const heads = Object.keys(HOVERS[kind]);
  return (
    <table className="rows" data-testid={`table-${kind}`}>
      <colgroup>{WIDTHS[kind].map((w, i) => <col key={i} style={{ width: `${w}%` }} />)}</colgroup>
      <thead>
        <tr>{heads.map((h) => <th key={h} title={HOVERS[kind][h]} className={NUMERIC[kind].includes(h) ? "num" : ""}>{h}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((r, n) => (
          <tr key={`${r.key}-${n}`} data-testid={`row-${kind}`}>
            {cellsFor[kind](r, auditId).map((c, i) => (
              <td key={heads[i]} data-h={heads[i]}
                className={[NUMERIC[kind].includes(heads[i]) ? "num" : "", NO_WRAP.includes(heads[i]) ? "nw" : "", heads[i] === "Source" ? "src" : ""].join(" ").trim()}>{c}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Card({ card, auditId, onDecided }) {
  const [typing, setTyping] = useState(false);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState(null);
  const send = async (action, value) => {
    try {
      await decideCard(auditId, card.id, { action, ...(value !== undefined ? { value } : {}) });
      onDecided();
    } catch (e) {
      setError(e.response?.data?.detail || "The decision could not be saved.");
    }
  };
  const side = (s) => {
    const parts = [s.value !== null && s.value !== undefined ? valueText(s.value, s.unit, s.currency) : null, s.period ? periodLabel(s.period) : null].filter(Boolean);
    return (
      <div>
        <b>{s.label}</b>
        {parts.join(", ")}{parts.length && s.evidence ? " — " : ""}{s.evidence ? `"${s.evidence}"` : ""}
      </div>
    );
  };
  return (
    <div className="card" id={`card-${card.id}`} data-testid={`card-${card.kind}`}>
      <h3>{cardTitle(card)}</h3>
      <div className="two">{card.reader && side(card.reader)}{card.other && side(card.other)}</div>
      <p className="muted"><SourceLink auditId={auditId} source={card.source} /></p>
      <div className="actions">
        {card.actions.filter((a) => a !== "type_value").map((a) => (
          <button key={a} type="button" className="btn quiet" data-testid={`card-${a}`} onClick={() => send(a)}>{ACTION_LABELS[a]}</button>
        ))}
        {card.actions.includes("type_value") && !typing && (
          <button type="button" className="btn quiet" data-testid="card-type_value" onClick={() => setTyping(true)}>{ACTION_LABELS.type_value}</button>
        )}
        {typing && (
          <span>
            <input type="number" step="any" value={typed} onChange={(e) => setTyped(e.target.value)} data-testid="card-typed" aria-label="Value" />
            <button type="button" className="btn quiet" data-testid="card-typed-save" disabled={typed === ""} onClick={() => send("type_value", Number(typed))}>Save</button>
          </span>
        )}
      </div>
      {error && <p className="bad" role="alert">{String(error)}</p>}
    </div>
  );
}

export default function ReadingResults({ data, auditId, confirmedOpen, setConfirmedOpen, onChanged }) {
  const open = data.cards.filter((c) => c.status === "open");
  const section = (kind, tone, children) => (
    <>
      <h2 className={tone} data-testid={`heading-${kind}`}>{TITLES[kind]} <span className="n">· {data.counts[kind]}</span></h2>
      {children}
    </>
  );
  return (
    <section className="results" data-testid="reading-results">
      {section("confirmed", "ok", (
        <details open={confirmedOpen} data-testid="confirmed-details">
          <summary onClick={(e) => { e.preventDefault(); setConfirmedOpen(!confirmedOpen); }}>{confirmedOpen ? "Hide" : "Show"}</summary>
          {data.tables.confirmed.length > 0 && <ResultTable kind="confirmed" rows={data.tables.confirmed} auditId={auditId} />}
        </details>
      ))}
      {section("rejected", "bad", data.tables.rejected.length > 0 && <ResultTable kind="rejected" rows={data.tables.rejected} auditId={auditId} />)}
      {open.map((c) => <Card key={c.id} card={c} auditId={auditId} onDecided={onChanged} />)}
      {section("cannot_check", "warn", data.tables.cannot_check.length > 0 && <ResultTable kind="cannot_check" rows={data.tables.cannot_check} auditId={auditId} />)}
    </section>
  );
}
