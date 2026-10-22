import { useState } from "react";
import type { ParkedDoc } from "../api";
import { ConfirmDialog, useActionState } from "../components/Confirm";
import { FormatLine, formatIdFor } from "../components/Field";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { sharedNames, studentLabel, studentName } from "../studentNames";
import { useScreenRead } from "../useScreenRead";

/**
 * The parked page (FR-UI-19, live-test blocker B8): every parked paper with its reason in the
 * console's words, the student it matched (or why it could not), and the ways out — each
 * behind its confirmation (CT-UI-09: nothing posts confirm-free):
 *
 * - **This paper belongs to …** — a paper whose student could not be matched is given to the
 *   student on the class list it belongs to (only students with no paper yet are offered),
 *   and goes forward to be graded under them;
 * - **Release to scoring** — the console's own match stands;
 * - **Close as unresolvable** — its criteria are missing, never zero.
 * - **A second paper for one student** (FR-INGEST-41, a rescan) — keep one of the two: remove
 *   this scan, or remove the earlier paper and give this one to the student. It is never
 *   closed, which would grade it INCOMPLETE beside the student's real paper.
 *
 * Students are named the way the teacher knows them: by name, never by an id.
 * Every decision carries the operator's own note (the tick they read, the test the paper
 * belongs to) and is recorded with who decided and when; the card shows the recorded trail.
 * A replacement upload starts on the papers page.
 */

type ParkedEntry = ParkedDoc["parked"][number];
type Resolution = "matched" | "unresolvable" | "assigned" | "remove" | "remove-earlier";

function ParkedCard({
  entry,
  onResolve,
}: {
  entry: ParkedEntry;
  onResolve: (entry: ParkedEntry, resolution: Resolution, studentRef: string, note: string) => void;
}) {
  const navigate = useNavigate();
  const [student, setStudent] = useState("");
  const [note, setNote] = useState("");
  const choices = entry.students_without_paper ?? [];
  const shared = sharedNames(choices);
  const duplicate = entry.duplicate_of ?? null;
  const earlierPresent = duplicate !== null && duplicate.submission_id !== null;
  const noteId = `note-${entry.submission_id}`;
  const studentId = `student-${entry.submission_id}`;
  return (
    <li className="parked-card">
      <p className="parked-reason">{entry.reason_label}</p>
      <p className="parked-match">{entry.match_note}</p>
      {entry.resolutions.length > 0 && (
        <ul className="parked-resolutions">
          {entry.resolutions.map((sentence) => (
            <li key={sentence}>{sentence}</li>
          ))}
        </ul>
      )}
      {entry.resolvable && (
        <div className="settings-form">
          {entry.assignable === true && (
            <div className="settings-row">
              <label htmlFor={studentId}>This paper belongs to</label>
              <select
                id={studentId}
                aria-describedby={formatIdFor(studentId)}
                value={student}
                onChange={(event) => setStudent(event.target.value)}
              >
                <option value="">Choose the student…</option>
                {choices.map((choice) => (
                  <option key={choice.student_ref} value={choice.student_ref}>
                    {studentLabel(choice, shared)}
                  </option>
                ))}
              </select>
              <FormatLine
                id={formatIdFor(studentId)}
                spec="Choose the student whose paper this is"
              />
              {choices.length === 0 && (
                <p className="step-note">
                  Every student on the list already has a paper. Add the student on the
                  Classes screen first, or close this paper.
                </p>
              )}
            </div>
          )}
          <div className="settings-row">
            <label htmlFor={noteId}>Your note (optional)</label>
            <input
              id={noteId}
              aria-describedby={formatIdFor(noteId)}
              value={note}
              placeholder="For example: Q1 is C — the second tick was crossed out"
              onChange={(event) => setNote(event.target.value)}
            />
            <FormatLine
              id={formatIdFor(noteId)}
              spec="Optional: a sentence on what you decided and why, kept with the paper"
            />
          </div>
        </div>
      )}
      <div className="parked-actions">
        <button type="button" className="button" onClick={() => navigate("/papers")}>
          Upload a replacement
        </button>
        {duplicate !== null && earlierPresent && (
          <>
            <button
              type="button"
              className="button"
              onClick={() => onResolve(entry, "remove", "", note)}
            >
              Keep the earlier paper (remove this scan)
            </button>
            {!duplicate.graded && (
              <button
                type="button"
                className="button button-primary"
                onClick={() => onResolve(entry, "remove-earlier", "", note)}
              >
                Use this scan instead
              </button>
            )}
          </>
        )}
        {entry.resolvable && (
          <>
            {entry.assignable === true && (
              <button
                type="button"
                className="button button-primary"
                disabled={student === ""}
                onClick={() => onResolve(entry, "assigned", student, note)}
              >
                Give it to this student
              </button>
            )}
            {duplicate === null && (
              <>
                <button
                  type="button"
                  className="button"
                  onClick={() => onResolve(entry, "matched", "", note)}
                >
                  Release to scoring
                </button>
                <button
                  type="button"
                  className="button"
                  onClick={() => onResolve(entry, "unresolvable", "", note)}
                >
                  Close as unresolvable
                </button>
              </>
            )}
          </>
        )}
      </div>
      {(entry.decisions ?? []).length > 0 && (
        <ul className="rows-list" aria-label="Decisions recorded">
          {(entry.decisions ?? []).map((decision) => (
            <li key={decision.decided_at}>
              <span className="step-name">{decisionLabel(decision.resolution)}</span>
              {decision.student_ref !== null && (
                <span className="step-note">to {studentName(decision)}</span>
              )}
              {decision.note !== null && <span className="step-note">“{decision.note}”</span>}
              <span className="step-state">
                {decision.actor}, {new Date(decision.decided_at).toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function decisionLabel(resolution: string): string {
  switch (resolution) {
    case "assigned":
      return "Given to a student";
    case "matched":
      return "Released";
    case "unresolvable":
      return "Closed";
    default:
      return "Decided";
  }
}

export function Parked() {
  const read = useScreenRead<ParkedDoc>("/api/v1/parked");
  const action = useActionState(read.retry);

  const openResolve = (
    entry: ParkedEntry,
    resolution: Resolution,
    studentRef: string,
    note: string,
  ): void => {
    const body: Record<string, unknown> = {
      submission_id: entry.submission_id,
      resolution,
      note,
    };
    if (resolution === "assigned") {
      const chosen = (entry.students_without_paper ?? []).find(
        (choice) => choice.student_ref === studentRef,
      );
      body.student_ref = studentRef;
      action.open({
        title: "Give this paper to a student",
        description:
          `You are saying this paper belongs to ${chosen ? studentName(chosen) : "this student"}. It goes ` +
          "forward to be graded as theirs, and your decision is recorded.",
        confirm: "Give it",
        action: "resolve quarantine item",
        body,
      });
    } else if (resolution === "remove") {
      const who = entry.duplicate_of ? studentName(entry.duplicate_of) : "the student";
      action.open({
        title: "Keep the earlier paper",
        description:
          `This scan is removed and ${who}'s earlier paper stays theirs. Nothing else changes.`,
        confirm: "Remove this scan",
        action: "remove paper",
        body: { cohort_id: entry.cohort_id, submission_id: entry.submission_id },
      });
      return;
    } else if (resolution === "remove-earlier") {
      const who = entry.duplicate_of ? studentName(entry.duplicate_of) : "the student";
      action.open({
        title: "Use this scan instead",
        description:
          `${who}'s earlier paper is removed. Then choose ${who} under "This paper belongs ` +
          "to\" on this card to give this scan to them.",
        confirm: "Remove the earlier paper",
        action: "remove paper",
        body: {
          cohort_id: entry.cohort_id,
          submission_id: entry.duplicate_of?.submission_id ?? "",
        },
      });
      return;
    } else if (resolution === "matched") {
      action.open({
        title: "Release this paper to scoring",
        description:
          "You are saying this paper belongs to the student the console matched it to. " +
          "The paper's pages go forward to be graded, and your decision is recorded.",
        confirm: "Release",
        action: "resolve quarantine item",
        body,
      });
    } else {
      action.open({
        title: "Close this paper as unresolvable",
        description:
          "You are saying this paper cannot be resolved. Its missing pieces stay missing: " +
          "the student's result will show what was never scored, never a made-up mark.",
        confirm: "Close",
        action: "resolve quarantine item",
        body,
      });
    }
  };

  return (
    <ReadScreen title="Parked" read={read}>
      {(data) => (
        <>
          {data.parked.length === 0 ? (
            <p>No papers are parked.</p>
          ) : (
            <>
              <p>
                {data.counts.total} paper{data.counts.total === 1 ? " is" : "s are"} parked.
              </p>
              <ul className="parked-list">
                {data.parked.map((entry) => (
                  <ParkedCard key={entry.submission_id} entry={entry} onResolve={openResolve} />
                ))}
              </ul>
            </>
          )}
          {action.pending !== null && (
            <ConfirmDialog pending={action.pending} onClose={action.close} onDone={action.finish} />
          )}
        </>
      )}
    </ReadScreen>
  );
}
