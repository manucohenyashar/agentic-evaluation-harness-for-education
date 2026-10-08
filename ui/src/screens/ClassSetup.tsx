import { fetchRead, type ClassRoster as ClassRosterDoc } from "../api";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";

/**
 * The class setup screen (FR-UI-03b): every stored cohort with its students, read live —
 * the roster editor's own data, so a change written outside the browser is on the screen
 * after the next reload (TC-UI-C02's out-of-band check). The roster editor itself is the
 * server-rendered console's screen (FR-CONSOLE-42); this screen shows what is stored.
 */
export function ClassSetup() {
  const read = useScreenRead<ClassRosterDoc>("/api/v1/class-roster");
  return (
    <ReadScreen title="Set up a class" read={read}>
      {(data) =>
        data.cohorts.length === 0 ? (
          <p className="panel">No cohort is stored yet.</p>
        ) : (
          data.cohorts.map((cohort) => (
            <section key={cohort.cohort_id} className="panel">
              <h2>Cohort {cohort.cohort_id}</h2>
              <ul className="rows-list">
                {cohort.students.map((student) => (
                  <li key={student.student_ref}>
                    <span className="step-name">{student.student_ref}</span>
                    {student.full_name !== null && (
                      <span className="step-note">{student.full_name}</span>
                    )}
                    {student.submission_id === null && (
                      <span className="step-state">no paper yet</span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))
        )
      }
    </ReadScreen>
  );
}
