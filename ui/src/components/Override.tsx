import { useState } from "react";
import { performAction } from "../api";
import { InlineNote } from "../state/StateDisplay";

/**
 * The override (FR-UI-17, RS-09): "Change a final grade" opens a band selection — the same
 * declared bands, no numeric entry (`FR-CONSOLE-07`) — plus a **required** reason field.
 * The form refuses to post without the reason, and it rides the console's existing amend
 * action (`amend a finalized grade`) for a finalized grade — ONE post carrying every
 * changed grading point, because M-GRADE writes one revision from the whole edit map and
 * sequential single-criterion posts would each drop the previous one's edits — and the
 * review action for a not-yet-final one. There is no second write path to the grade
 * history. The render-back is the ledger's own sentence: what changed, that a reason was
 * recorded, and that the original grade is kept in the history.
 *
 * The form stays rendered inside a collapsed disclosure so a band shown is always beside an
 * editable band control (`FR-CONSOLE-20` invariant 16) without the form being the default
 * view.
 */

/** The criteria row shape the form reads — the fields both screens' rows carry. */
export type OverrideCriterion = {
  criterion_id: string;
  label: string;
  criterion_band: string;
  levels?: string[];
};

export interface OverrideChange {
  criterion_id: string;
  from_band: string;
  to_band: string;
}

/** The amend's render-back, from the values the form itself showed — both are the
 * declared levels the reads served, and the reason is the one the teacher typed. */
export function amendmentRenderBack(change: OverrideChange): string {
  return (
    `Final grade changed from '${change.from_band}' to '${change.to_band}' — ` +
    "reason recorded; the original grade is kept in the history."
  );
}

export function OverrideForm({
  criteria,
  final,
  submissionId,
  runId,
  onDone,
}: {
  criteria: OverrideCriterion[];
  /** Whether this student's grade is finalized — the amend action's own precondition. */
  final: boolean;
  submissionId: string;
  runId: string | null;
  onDone: (outcome: string, changes: OverrideChange[], final: boolean) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(criteria.map((criterion) => [criterion.criterion_id, criterion.criterion_band])),
  );
  const [reason, setReason] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async (): Promise<void> => {
    const changes: OverrideChange[] = criteria
      .map((criterion) => ({
        criterion_id: criterion.criterion_id,
        from_band: criterion.criterion_band,
        to_band: values[criterion.criterion_id] ?? criterion.criterion_band,
      }))
      .filter((change) => change.to_band !== change.from_band && change.to_band !== "");
    if (changes.length === 0) {
      setNote("No grade is changed — nothing to save.");
      return;
    }
    if (final && reason.trim() === "") {
      // The refusal the design mandates: no override of a finalized grade without its
      // reason (RS-09). Nothing is posted, and the form stays open with the field in it.
      setNote("A reason is required to change a final grade — say why the grade is changing.");
      return;
    }
    setBusy(true);
    setNote(null);
    let outcome = "";
    let failure: string | null = null;
    if (final) {
      // ONE amend post carries every changed grading point: M-GRADE writes one revision
      // holding the whole edit map, and the console's amend effect records every entry in
      // it. Sequential per-criterion posts would each build the next revision from only
      // that call's edit and silently drop the one before.
      try {
        const result = await performAction("amend a finalized grade", {
          run_id: runId,
          submission_id: submissionId,
          changes: changes.map((change) => ({
            criterion_id: change.criterion_id,
            band: change.to_band,
          })),
          actor: "operator",
          reason: reason.trim(),
        });
        if (result.error !== undefined && result.error !== "") {
          failure = result.error;
        } else if (result.refused === true) {
          failure = result.detail ?? "the console refused it";
        } else {
          outcome = changes.map(amendmentRenderBack).join(" ");
        }
      } catch (error: unknown) {
        failure = error instanceof Error ? error.message : String(error);
      }
    } else {
      // A not-yet-final grade rides the review action, one queue item per grading point —
      // each resolution is its own decision, so one post per changed point is the queue's
      // own grain, not a second write path.
      for (const change of changes) {
        try {
          const result = await performAction("review action", {
            run_id: runId,
            submission_id: submissionId,
            criterion_id: change.criterion_id,
            new_band: change.to_band,
          });
          if (result.error !== undefined && result.error !== "") {
            failure = result.error;
            break;
          }
          if (result.refused === true) {
            failure = result.detail ?? "the console refused it";
            break;
          }
          outcome = result.detail || "The review action is done.";
        } catch (error: unknown) {
          failure = error instanceof Error ? error.message : String(error);
          break;
        }
      }
    }
    setBusy(false);
    if (failure !== null) {
      setNote(`Refused: ${failure}`);
      onDone(`Refused: ${failure}`, [], final);
      return;
    }
    setNote(null);
    setReason("");
    onDone(outcome, changes, final);
  };

  return (
    <details className="override">
      <summary>{final ? "Change a final grade" : "Change the grade"}</summary>
      <div className="override-body">
        {criteria.map((criterion) => (
          <label key={criterion.criterion_id} className="override-field">
            <span>{criterion.label}</span>
            <select
              name={`criterion-band-${criterion.criterion_id}`}
              value={values[criterion.criterion_id] ?? criterion.criterion_band}
              onChange={(event) =>
                setValues((current) => ({
                  ...current,
                  [criterion.criterion_id]: event.target.value,
                }))
              }
            >
              {(criterion.levels ?? [criterion.criterion_band]).map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
          </label>
        ))}
        <label className="override-field">
          <span>{final ? "Reason (required)" : "Reason"}</span>
          <textarea
            name="override-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={2}
          />
        </label>
        {note !== null && <InlineNote message={{ tier: "inline", what: note, why: "", next_action: null, kind: "failure" }} />}
        <button type="button" className="button button-primary" onClick={save} disabled={busy}>
          Save
        </button>
      </div>
    </details>
  );
}
