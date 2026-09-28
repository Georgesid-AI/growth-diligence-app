import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

/**
 * Hover gloss for a compact notation in a card subtitle (e.g. "IQR 17–58").
 *
 * Deliberately a Tooltip with a slate dotted underline, so it neither looks nor
 * behaves like the sky-underlined source-lineage HoverCard that <Provenance />
 * puts on the numeric figure above it. The two anchor different elements and use
 * different Radix primitives, so they never share hover state.
 *
 * `text` is static copy — never a computed or per-company value.
 */
export function Gloss({ text, id, children }) {
  return (
    <TooltipProvider delayDuration={120}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            tabIndex={0}
            data-testid={id ? `gloss-${id}` : undefined}
            className="cursor-help underline decoration-dotted decoration-slate-500 underline-offset-2 hover:decoration-slate-300"
          >
            {children}
          </span>
        </TooltipTrigger>
        <TooltipContent
          data-testid={id ? `gloss-tip-${id}` : undefined}
          className="border border-[#D1D5DB] bg-white font-sans text-slate-800"
        >
          {text}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
