import { useCallback, useState } from "react";
import { performAction, type ActionResult } from "../api";
import { BusyButton, outcomeOf, outcomeSentence, useOutcome } from "./Outcome";

/**
 * The outcome's wording: a refused action is the console's own refusal, prefixed as
 * refused — the console never reports a refused action as done.
 */
export function outcomeText(result: ActionResult): string {
  return outcomeSentence(outcomeOf(result));
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
  /** The success sentence in the teacher's words, when the server's own would carry
   * internal names (FR-UI-23). */
  said?: string;
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
  const { clear } = useOutcome();

  const run = (): void => {
    setBusy(true);
    clear();
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
        <BusyButton className="button button-primary" onClick={run} busy={busy}>
          {pending.confirm}
        </BusyButton>
      </div>
    </div>
  );
}

/**
 * One screen's action state: the pending confirmation it opened and the outcome of the last
 * one. `open` stages the dialog, `finish` reports the result whatever it was — in the
 * shell's outcome banner (FR-UI-24) with its toast; a refusal is the console's own
 * what / why / next, never reported as done (FR-UI-25).
 */
export function useActionState(afterDone?: () => void) {
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const { report } = useOutcome();

  const open = useCallback((next: PendingAction) => setPending(next), []);
  const close = useCallback(() => setPending(null), []);
  const finish = useCallback(
    (result: ActionResult) => {
      const said = outcomeOf(result, pending?.said);
      setPending(null);
      setOutcome(outcomeSentence(said));
      report(said);
      afterDone?.();
    },
    [afterDone, report, pending],
  );

  return { pending, outcome, open, close, finish };
}
