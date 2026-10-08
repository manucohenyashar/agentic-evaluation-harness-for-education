import { useState } from "react";
import { fetchRead, performAction, type ResultStudent, type ResultsScreen as ResultsDoc } from "../api";
import { ActionOutcome, ConfirmDialog, outcomeText, useActionState } from "../components/Confirm";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useScreenRead } from "../useScreenRead";

/**
 * The results screen (FR-UI-03g): every student's grade record beside the run's per-criterion
 * bands — a band shown is the stored band, displayed as an editable band control (FR-CONSOLE-20
 * invariant 16: no view shows a grade and cannot change it). A finalized row's band edit is the
 * "amend a finalized grade" control; a provisional one's is the "review action" — and the
 * console's refusal is shown as refused, with the select back on the stored band.
 */
function bandOptions(students: ResultStudent[]): string[] {
  const bands = new Set<string>();
  for (const student of students) {
    for (const criterion of student.criteria) {
      if (criterion.criterion_band !== "") {
        bands.add(criterion.criterion_band);
      }
    }
  }
  return [...bands].sort();
}

export function Results() {
  const read = useScreenRead<ResultsDoc>("/api/v1/results/screen");
  const navigate = useNavigate();
  const finalize = useActionState(read.retry);
  const [edit, setEdit] = useState<string | null>(null);
  const [remount, setRemount] = useState<number>(0);

  const afterEdit = (): void => {
    read.retry();
    setRemount((n: number) => n + 1);
  };

  const changeBand = (data: ResultsDoc, student: ResultStudent, criterionId: string, next: string): void => {
    if (data.run_id === null || next === "") {
      return;
    }
    const action = student.state === "final" ? "amend a finalized grade" : "review action";
    const body: Record<string, unknown> =
      student.state === "final"
        ? {
            submission_id: student.submission_id,
            criterion_id: criterionId,
            band: next,
            actor: "operator",
          }
        : {
            run_id: data.run_id,
            submission_id: student.submission_id,
            criterion_id: criterionId,
            new_band: next,
          };
    performAction(action, body).then(
      (result) => {
        setEdit(outcomeText(result));
        afterEdit();
      },
      (failure: unknown) => {
        setEdit(failure instanceof Error ? failure.message : String(failure));
        afterEdit();
      },
    );
  };

  const openFinalize = (data: ResultsDoc): void => {
    if (data.run_id === null || data.students.length === 0) {
      return;
    }
    // The confirmation names what it does out of the API's own document (FR-UI-05): the
    // run it settles and how many of its stored grades are not yet final — a run whose
    // grades are all final settles nothing (FR-CONSOLE-02), and the dialog says that.
    const not_final = data.students.filter((s) => s.state !== "final").length;
    finalize.open({
      title: "Finalize this batch",
      description:
        not_final === 0
          ? `Every stored grade of run ${data.run_id} is already final; finalizing ` +
            "settles nothing — a confirm whose work is done is a no-op (FR-CONSOLE-02). " +
            "Afterward a correction is an amendment, recorded."
          : `Finalizing settles the ${not_final} not-yet-final grade(s) of run ` +
            `${data.run_id} through M-GRADE: the batch's grades stop being provisional. ` +
            "Afterward a correction is an amendment, recorded.",
      confirm: "Finalize",
      action: "finalize batch",
      body: { run_id: data.run_id, actor: "operator" },
    });
  };

  return (
    <ReadScreen title="Results" read={read}>
      {(data) => {
        const options = bandOptions(data.students);
        return (
          <>
            <ActionOutcome outcome={finalize.outcome ?? edit} />
            {data.students.length === 0 ? (
              <p className="panel">The run holds no computed grades.</p>
            ) : (
              <table className="results">
                <thead>
                  <tr>
                    <th>Student</th>
                    <th>Total</th>
                    <th>State</th>
                    <th>Bands</th>
                  </tr>
                </thead>
                <tbody key={remount}>
                  {data.students.map((student) => (
                    <tr key={student.submission_id}>
                      <td>
                        <a
                          href={`#/results/students/${student.submission_id}`}
                          onClick={() => navigate(`/results/students/${student.submission_id}`)}
                        >
                          {student.student_ref ?? student.submission_id}
                        </a>
                      </td>
                      <td>{student.total ?? "—"}</td>
                      <td>{student.state === "" ? "—" : student.state}</td>
                      <td>
                        <ul className="band-list">
                          {student.criteria.map((criterion) => (
                            <li key={criterion.criterion_id}>
                              <label>
                                <span className="step-note">{criterion.criterion_id}</span>
                                <select
                                  name={`criterion-band-${criterion.criterion_id}`}
                                  value={criterion.criterion_band}
                                  onChange={(event) =>
                                    changeBand(
                                      data, student, criterion.criterion_id, event.target.value)
                                  }
                                >
                                  <option value="">—</option>
                                  {options.map((band) => (
                                    <option key={band} value={band}>
                                      {band}
                                    </option>
                                  ))}
                                </select>
                              </label>
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <button
              type="button"
              className="button button-primary"
              onClick={() => openFinalize(data)}
              disabled={data.run_id === null || data.students.length === 0}
            >
              Finalize the batch
            </button>
            {finalize.pending !== null && (
              <ConfirmDialog
                pending={finalize.pending}
                onClose={finalize.close}
                onDone={finalize.finish}
              />
            )}
          </>
        );
      }}
    </ReadScreen>
  );
}
