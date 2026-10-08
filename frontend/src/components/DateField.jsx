import { useEffect, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  MAX_YEAR, MIN_YEAR, WEEKDAYS, YEAR_ERROR, displayDate, monthName, openingView, parseIso, parseYear, shiftMonth, shiftYear, toIso, weeks,
} from "@/lib/datePicker";

const arrow = "h-7 w-7 inline-flex items-center justify-center rounded border border-[#E5E7EB] bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed";

/**
 * A date picker with month and year arrows and a typeable year, in place of the browser's date input
 * (docs/specs/chat-upload.md section 4.1). The value is an ISO date (YYYY-MM-DD) or "". Years run from 2000 to 2100:
 * a year typed outside is rejected with a message and the calendar stays where it was; a value outside is shown empty.
 * `testId` names the trigger button; the parts inside carry `${testId}-month-prev`, `-month-next`, `-year-prev`,
 * `-year-next`, `-year` (the typed year), `-year-error`, `-day-<n>` and `-clear`.
 */
export default function DateField({ value, onChange, testId, className = "", placeholder = "Select a date", clearable = true }) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState(() => openingView(value));
  const [draft, setDraft] = useState(String(view.year));
  const [error, setError] = useState(null);
  const selected = parseIso(value);

  const show = (next) => { setView(next); setDraft(String(next.year)); setError(null); };
  useEffect(() => { if (open) show(openingView(value)); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

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
  const pick = (day) => { onChange(toIso(view.year, view.month, day)); setOpen(false); };
  const id = (part) => `${testId}-${part}`;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" data-testid={testId} aria-label={placeholder}
          className={`mt-1.5 flex h-9 w-full items-center justify-between rounded-md border border-[#E5E7EB] bg-white px-3 text-left font-mono text-sm ${className}`}>
          <span className={selected ? "text-slate-900" : "text-slate-400"}>{displayDate(value) || placeholder}</span>
          <CalendarDays className="h-4 w-4 text-slate-500" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-3 bg-white" align="start" data-testid={id("calendar")}>
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
            {weeks(view).map((week, w) => (
              <tr key={w}>
                {week.map((day, i) => (
                  <td key={i} className="p-0">
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
  );
}
