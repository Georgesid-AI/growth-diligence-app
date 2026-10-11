import { useEffect, useState } from "react";
import { NARRATIVE_TIMEOUT_MS, generateNarrative, readNarrative } from "@/lib/api";
import { describeRequestError, logRequestFailure } from "@/lib/requestError";
import { Narrative } from "@/components/Narrative";
import { NarrativeControl } from "@/components/NarrativeControl";

// The narrative steps written from the stored data inventory and data integrity checks (A1, A2). Each has its own button, the
// same helper text and cost note as the growth-engine narrative, and its own saved narrative.
export const STEP_COPY = {
  data_inventory: { title: "Data inventory", actionsTitle: "Data request list (ranked)", ranked: true },
  data_integrity: { title: "Data integrity", actionsTitle: "Next actions (ranked)", ranked: true },
};

/**
 * One step's control and narrative. Opening the audit only reads a narrative someone already wrote (no AI request);
 * the button is the only thing that spends one.
 */
export default function StepNarrative({ auditId, step, ready, onChanged }) {
  const copy = STEP_COPY[step];
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!ready) return undefined;
    let cancelled = false;
    readNarrative(auditId, step)
      .then((res) => { if (!cancelled) setState(res); })
      .catch((e) => {
        if (cancelled) return;
        const failure = describeRequestError(e);
        logRequestFailure(`read ${step} narrative`, failure);
        setState({ narrative_status: "unavailable", reason: `Could not load the saved narrative: ${failure.message}` });
      });
    return () => { cancelled = true; };
  }, [auditId, step, ready]);

  const onGenerate = () => {
    setBusy(true);
    generateNarrative(auditId, step)
      .then((res) => { setState(res); if (onChanged) onChanged(); })
      .catch((e) => {
        const failure = describeRequestError(e, { timeoutMs: NARRATIVE_TIMEOUT_MS });
        logRequestFailure(`generate ${step} narrative`, failure);
        setState({ narrative_status: "unavailable", reason: failure.message });
      })
      .finally(() => setBusy(false));
  };

  return (
    <section data-testid={`step-narrative-${step}`} className="mb-2">
      <h2 className="mb-2 font-heading text-base font-semibold text-slate-900">{copy.title}</h2>
      <NarrativeControl
        step={step}
        label="Write narrative"
        busyLabel="Writing…"
        status={state?.narrative_status}
        generatedAt={state?.generated_at}
        superseded={state?.superseded}
        supersededReason={state?.superseded_reason}
        busy={busy}
        onGenerate={onGenerate}
      />
      <Narrative state={busy ? { loading: true } : state} step={step} title={copy.title} actionsTitle={copy.actionsTitle} ranked={copy.ranked} />
    </section>
  );
}
