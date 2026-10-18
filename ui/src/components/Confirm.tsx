import { useCallback, useState } from "react";
import { performAction, type ActionResult } from "../api";

/**
 * The outcome's wording: a refused action is the console's own refusal, prefixed as
 * refused — the console never reports a refused action as done.
 */
export function outcomeText(result: ActionResult): string {
  if (result.error !== undefined && result.error !== "") {
    return `Refused: ${result.error}`;
  }
  if (result.refused === true && result.detail) {
    return `Refused: ${result.detail}`;
  }
  return result.detail || "done — no detail returned";
}

/**
 * One pending action behind a confirmation (FR-UI-05): what the teacher asked for, the
 * control it will run, and the body the confirmation posts — nothing posts until the
 * confirming button is pressed (TC-UI-05: while the dialog is open, and after it is
 * cancelled, the store does not change).
 */
export interface PendingAction {
  /** The dialog's own name — it must say what will happen ("Publish this package"). */
  title: string;
  /** What the action does, in the console's words, as the dialog's first paragraph. */
  description: string;
  /** The button's label for confirming: the action's verb, never a bare "OK". */
  confirm: string;
  /** The enumerated control action, verbatim (`CONTROL_SURFACE_ACTIONS`). */
  action: string;
  body: Record<string, unknown>;
}

/**
 * The confirmation's dialog: a `role=dialog` that names the action, its Cancel button and
 * its confirming button. The result is reported back whatever it was: a refused action is
 * the console's own refusal, shown as it was refused, never reported as done.
 */
export function ConfirmDialog({
  pending,
  onClose,
  onDone,
}: {
  pending: PendingAction;
  onClose: () => void;
  onDone: (result: ActionResult) => void;
}) {
  const [busy, setBusy] = useState(false);

  const run = (): void => {
    setBusy(true);
    performAction(pending.action, pending.body).then(
      (result) => {
        setBusy(false);
        onDone(result);
      },
      (failure: unknown) => {
        setBusy(false);
        onDone({
          action: pending.action,
          error: failure instanceof Error ? failure.message : String(failure),
        });
      },
    );
  };

  return (
    <div role="dialog" aria-modal="true" aria-label={pending.title} className="dialog">
      <h2>{pending.title}</h2>
      <p>{pending.description}</p>
      <div className="dialog-actions">
        <button type="button" className="button" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button type="button" className="button button-primary" onClick={run} disabled={busy}>
          {pending.confirm}
        </button>
      </div>
    </div>
  );
}

/**
 * One screen's action state: the pending confirmation it opened and the outcome of the last
 * one. `open` stages the dialog, `finish` reports the result whatever it was — a refusal is
 * the console's own wording, prefixed as refused, never as done.
 */
export function useActionState(afterDone?: () => void) {
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);

  const open = useCallback((next: PendingAction) => setPending(next), []);
  const close = useCallback(() => setPending(null), []);
  const finish = useCallback(
    (result: ActionResult) => {
      setPending(null);
      setOutcome(outcomeText(result));
      afterDone?.();
    },
    [afterDone],
  );

  return { pending, outcome, open, close, finish };
}

/** The outcome line under the screen's content: what the last confirmed action answered. */
export function ActionOutcome({ outcome }: { outcome: string | null }) {
  if (outcome === null) {
    return null;
  }
  return (
    <p role="status" className="action-outcome">
      {outcome}
    </p>
  );
}
