import { useEffect, useRef, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import {
  MAX_YEAR, MIN_YEAR, TYPED_ERROR, WEEKDAYS, YEAR_ERROR, displayDate, monthName, openingView, parseIso, parseTyped, parseYear, pickSide,
  shiftMonth, shiftYear, toIso, weeks,
} from "@/lib/datePicker";

const arrow = "h-7 w-7 inline-flex items-center justify-center rounded border border-[#E5E7EB] bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed";

/**
 * A date field with a typeable text box and a calendar with month and year arrows and a typeable year, in place of the
 * browser's date input (docs/specs/chat-upload.md section 4.1). The value is an ISO date (YYYY-MM-DD) or "". The text
 * box takes 2026-06-30 or 30.06.2026 and no other form; a text that is not a real date inside 2000 to 2100 is rejected
 * with a message and the value stays. Years run from 2000 to 2100: a year typed in the calendar outside is rejected too;
 * a value outside is shown empty. The calendar opens on the side of the field that has room for it (below when it fits),
 * keeps that side while it is open, and always has six rows, so its height never changes.
 * `testId` names the text box; the parts inside carry `${testId}-open` (the calendar button), `-error`, `-month-prev`,
 * `-month-next`, `-year-prev`, `-year-next`, `-year` (the typed year), `-year-error`, `-day-<n>` and `-clear`.
 */
export default function DateField({ value, onChange, testId, className = "", placeholder = "Select a date", clearable = true }) {
  const [open, setOpen] = useState(false);
  const [side, setSide] = useState("bottom");
  const [view, setView] = useState(() => openingView(value));
  const [draft, setDraft] = useState(String(view.year));
  const [error, setError] = useState(null);
  const [typed, setTyped] = useState(null);         // the text being typed in the box; null while the box shows the value
  const [typedError, setTypedError] = useState(null);
  const wrap = useRef(null);
  const selected = parseIso(value);

  const show = (next) => { setView(next); setDraft(String(next.year)); setError(null); };
  useEffect(() => { if (open) show(openingView(value)); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const openCalendar = () => {
    if (open) return;
    if (wrap.current) setSide(pickSide(wrap.current.getBoundingClientRect(), window.innerHeight));
    setOpen(true);
  };
  const move = (next) => { if (next) show(next); };
  const commitYear = () => {
    const year = parseYear(draft);
    if (year == null) {
      setError(YEAR_ERROR);
      setDraft(String(view.year));        // the calendar stays where it was; nothing outside the range is kept
      return;
    }
    show({ ...view, year });
  };
  const pick = (day) => { setTypedError(null); onChange(toIso(view.year, view.month, day)); setOpen(false); };
  const commitTyped = () => {
    if (typed === null) return true;
    const text = typed.trim();
    setTyped(null);
    if (text === "") {
      setTypedError(null);
      if (value && clearable) onChange("");
      return true;
    }
    const iso = parseTyped(text);
    if (!iso) { setTypedError(TYPED_ERROR); return false; }          // the value stays
    setTypedError(null);
    if (iso !== value) onChange(iso);
    return true;
  };
  const id = (part) => `${testId}-${part}`;

  return (
    <>
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <div ref={wrap} className={`mt-1.5 flex h-9 w-full items-center rounded-md border bg-white ${typedError ? "border-rose-400" : "border-[#E5E7EB]"} ${className}`}>
          <input type="text" data-testid={testId} aria-label={placeholder} aria-invalid={typedError ? true : undefined}
            autoComplete="off" placeholder={placeholder} value={typed ?? displayDate(value)}
            onFocus={() => setTyped(selected ? value : "")} onClick={openCalendar}
            onChange={(e) => { setTyped(e.target.value); setTypedError(null); }}
            onBlur={commitTyped}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); if (commitTyped()) setOpen(false); } }}
            className="h-full min-w-0 flex-1 bg-transparent px-3 font-mono text-sm text-slate-900 outline-none placeholder:text-slate-400" />
          <button type="button" data-testid={id("open")} aria-label="Open calendar" onClick={() => (open ? setOpen(false) : openCalendar())}
            className="px-3 text-slate-500 hover:text-slate-800"><CalendarDays className="h-4 w-4" /></button>
        </div>
      </PopoverAnchor>
      <PopoverContent className="w-64 p-3 bg-white" side={side} align="start" avoidCollisions={false} data-testid={id("calendar")}
        onOpenAutoFocus={(e) => e.preventDefault()}
        onInteractOutside={(e) => { if (wrap.current?.contains(e.target)) e.preventDefault(); }}>
        <div className="flex items-center justify-between gap-1 mb-1">
          <button type="button" className={arrow} aria-label="Previous month" data-testid={id("month-prev")}
            disabled={!shiftMonth(view, -1)} onClick={() => move(shiftMonth(view, -1))}><ChevronLeft className="h-4 w-4" /></button>
          <span className="text-sm font-medium text-slate-900" data-testid={id("month")}>{monthName(view.month)}</span>
          <button type="button" className={arrow} aria-label="Next month" data-testid={id("month-next")}
            disabled={!shiftMonth(view, 1)} onClick={() => move(shiftMonth(view, 1))}><ChevronRight className="h-4 w-4" /></button>
        </div>
        <div className="flex items-center justify-between gap-1 mb-2">
          <button type="button" className={arrow} aria-label="Previous year" data-testid={id("year-prev")}
            disabled={!shiftYear(view, -1)} onClick={() => move(shiftYear(view, -1))}><ChevronsLeft className="h-4 w-4" /></button>
          <input type="text" inputMode="numeric" maxLength={4} aria-label="Year" value={draft}
            data-testid={id("year")} onChange={(e) => { setDraft(e.target.value.replace(/\D/g, "")); setError(null); }}
            onBlur={commitYear} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitYear(); } }}
            className="h-7 w-16 rounded border border-[#E5E7EB] text-center font-mono text-sm" />
          <button type="button" className={arrow} aria-label="Next year" data-testid={id("year-next")}
            disabled={!shiftYear(view, 1)} onClick={() => move(shiftYear(view, 1))}><ChevronsRight className="h-4 w-4" /></button>
        </div>
        {/* A line of its own that never changes height: the message goes away on blur, and a grid that moves between a
            click's press and release would swallow the click on a day. */}
        <p className="mb-2 h-4 text-xs leading-4 text-rose-700" role={error ? "alert" : undefined}
          data-testid={error ? id("year-error") : undefined}>{error}</p>
        <table className="w-full text-center text-xs">
          <thead><tr>{WEEKDAYS.map((d) => <th key={d} className="py-1 font-normal text-slate-500">{d}</th>)}</tr></thead>
          <tbody>
            {[...weeks(view), ...Array(6).fill(Array(7).fill(null))].slice(0, 6).map((week, w) => (
              <tr key={w}>
                {week.map((day, i) => (
                  <td key={i} className="h-7 p-0">
                    {day && (
                      <button type="button" data-testid={id(`day-${day}`)} onClick={() => pick(day)}
                        aria-pressed={selected?.year === view.year && selected?.month === view.month && selected?.day === day}
                        className={`h-7 w-7 rounded font-mono ${selected?.year === view.year && selected?.month === view.month && selected?.day === day
                          ? "bg-sky-600 text-white" : "text-slate-800 hover:bg-slate-100"}`}>{day}</button>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-2 flex items-center justify-between text-[10px] text-slate-500">
          <span>{MIN_YEAR}–{MAX_YEAR}</span>
          {clearable && value && (
            <button type="button" className="text-sky-700 underline" data-testid={id("clear")}
              onClick={() => { onChange(""); setOpen(false); }}>Clear</button>
          )}
        </div>
      </PopoverContent>
    </Popover>
    {typedError && <p role="alert" className="mt-1 text-xs text-rose-700" data-testid={id("error")}>{typedError}</p>}
    </>
  );
}