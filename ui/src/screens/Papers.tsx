import { fetchRead, type Papers as PapersDoc } from "../api";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";

/**
 * The papers screen (FR-UI-03c): the cohort's students and the scan parts already uploaded,
 * in assembled order, through M-PIPE's `uploaded_parts` — the preflight state. Each student
 * carries their own upload control (`input[type=file]`, labeled for them), so a selection is
 * addressed to that student; sending it is the upload transport's work (FR-CONSOLE-04).
 */
export function Papers() {
  const read = useScreenRead<PapersDoc>("/api/v1/papers");
  return (
    <ReadScreen title="Load papers" read={read}>
      {(data) => (
        <section className="panel">
          <h2>Cohort {data.cohort_id}</h2>
          <p className="hub-state">
            {data.parts.length === 0
              ? "No scans uploaded yet."
              : `Uploaded, in assembled order: ${data.parts.join(", ")}.`}
          </p>
          <ul className="rows-list">
            {data.students.map((student) => (
              <li key={student.student_ref}>
                <label className="upload-row">
                  <span className="step-name">{student.student_ref}</span>
                  {student.submission_id !== null && (
                    <input type="file" name={`scans-${student.submission_id}`} />
                  )}
                  {student.submission_id === null && (
                    <span className="step-state">no paper yet</span>
                  )}
                </label>
              </li>
            ))}
          </ul>
        </section>
      )}
    </ReadScreen>
  );
}
