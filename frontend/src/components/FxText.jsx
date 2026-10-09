import { FX_SETTINGS_LABEL } from "@/lib/deckClaims";

/** A figure's text with "FX settings", when the text names it (a missing rate), shown as a link to the audit's FX settings. */
export default function FxText({ text, href, testId }) {
  const at = text.indexOf(FX_SETTINGS_LABEL);
  if (at < 0) return text;
  return (
    <>
      {text.slice(0, at)}
      <a href={href} className="text-sky-700 underline" data-testid={testId}>{FX_SETTINGS_LABEL}</a>
      {text.slice(at + FX_SETTINGS_LABEL.length)}
    </>
  );
}
