import { useState } from "react";
import type { WholeGradeDoc, WholeGradeStudent } from "../api";
import { FormatLine, formatIdFor } from "../components/Field";
import { GradeFooter } from "../components/GradeFooter";
import { HeldBack } from "../components/HeldBack";
import { BusyButton, useReportedAction } from "../components/Outcome";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useRunParams } from "../selection";
import { sharedNames, studentLabel } from "../studentNames";
import { useScreenRead } from "../useScreenRead";

/**
 * The whole-grade sample (FR-UI-49, the HLD's S10; FR-CONSOLE-93): a few students' grades
 * drawn from the papers the system accepted on its own, shown end to end as each student will
 * receive them — the feedback first, then the total and grade, then every question's points
 * with each line's level. One question is asked, with its three answers and Skip's cost in the
 * same view, above the grades (R62, FR-CONSOLE-06): **Yes, they do** and **Skip** each record
 * one answer (`whole-grade confirm` / `whole-grade skip`, no label — the sample is a check,
 * not evidence); **Open a student** opens the chosen student's own page.
 */

/** FR-UI-49's question and Skip's cost, verbatim. */
export const WHOLE_GRADE_QUESTION = "Do these look like grades you would have given?";
export const WHOLE_GRADE_SKIP_COST =
  "Skipping means nobody has read a whole paper's result end to end; the grades are " +
  "delivered either way.";

function StudentGrade({ student, name }: { student: WholeGradeStudent; name: string }) {
  const questionLabel = new Map(student.questions.map((q) => [q.question_id, q.label]));
  return (
    <li className="whole-grade-student panel">
      <h2>{name}</h2>
      {/* The feedback before the mark (inv. 10). */}
      {student.narrative.length > 0 && (
        <ul className="rows-list whole-grade-feedback">
          {student.narrative.map((row) => (
            <li key={`${row.level}-${row.question_id}`}>
              {row.level !== "l2_test" && questionLabel.has(row.question_id) && (
                <span className="step-note">{questionLabel.get(row.question_id)}</span>
              )}
              <p className="narrative-text">
                {row.hidden_until_blind === true ? <HeldBack link={false} /> : row.text}
              </p>
            </li>
          ))}
        </ul>
      )}
      <p className="total-grade">
        {student.hidden_until_blind === true ? (
          <>
            Total grade: <HeldBack link={false} />
          </>
        ) : student.total_points != null && student.total_max != null ? (
          <>
            Total grade: {student.total_points} / {student.total_max}
            {student.grade ? ` — ${student.grade}` : ""}
          </>
        ) : (
          <>Total: {student.total ?? "—"}{student.grade ? ` — ${student.grade}` : ""}</>
        )}
      </p>
      <ul className="question-cells">
        {student.questions.map((question) => (
          <li key={question.question_id} className="question-cell">
            <span>
              {question.label} ·{" "}
              {question.hidden_until_blind === true ? (
                <HeldBack link={false} />
              ) : (
                <>
                  {question.points_awarded ?? "—"} / {question.points_max}
                </>
              )}
            </span>
            <ul className="band-list">
              {question.lines.map((line) => (
                <li key={line.criterion_id}>
                  <span className="step-note">{line.label}</span>{" "}
                  {line.hidden_until_blind === true ? (
                    <HeldBack link={false} />
                  ) : (
                    <span className="band-control" data-band-control="">
                      <span className="band-value">{line.level}</span>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </li>
  );
}

export function WholeGradeSample() {
  const read = useScreenRead<WholeGradeDoc>("/api/v1/results/whole-grade-sample", useRunParams());
  const navigate = useNavigate();
  const answer = useReportedAction();
  const [chosen, setChosen] = useState("");
  return (
    <ReadScreen title="Whole-grade sample" read={read}>
      {(doc) => {
        const shared = sharedNames(doc.students);
        const open = chosen !== "" ? chosen : (doc.students[0]?.submission_id ?? "");
        return (
          <>
            {doc.short_sample_note !== null && (
              <p className="hub-state">{doc.short_sample_note}</p>
            )}
            {doc.students.length === 0 ? (
              <p>
                <button type="button" className="button" onClick={() => navigate("/results")}>
                  See the results
                </button>
              </p>
            ) : (
              <>
                <section className="panel whole-grade-ask" aria-label="The whole-grade question">
                  <p className="hub-state">
                    <strong>{WHOLE_GRADE_QUESTION}</strong>{" "}
                    <span className="step-note">
                      {doc.students.length} {doc.students.length === 1 ? "student" : "students"},{" "}
                      {doc.population_note}.
                    </span>
                  </p>
                  <div className="whole-grade-actions">
                    <BusyButton
                      className="button button-primary"
                      busy={answer.busy}
                      onClick={() => {
                        void answer.run("whole-grade confirm", { run_id: doc.run_id });
                      }}
                    >
                      Yes, they do
                    </BusyButton>
                    <label htmlFor="whole-grade-student" className="visually-hidden">
                      Student to open
                    </label>
                    <select
                      id="whole-grade-student"
                      aria-describedby={formatIdFor("whole-grade-student")}
                      value={open}
                      onChange={(event) => setChosen(event.target.value)}
                    >
                      {doc.students.map((student) => (
                        <option key={student.submission_id} value={student.submission_id}>
                          {studentLabel(student, shared)}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="button"
                      onClick={() => navigate(`/results/students/${open}`)}
                    >
                      Open a student
                    </button>
                    <BusyButton
                      className="button"
                      busy={answer.busy}
                      onClick={() => {
                        void answer.run("whole-grade skip", { run_id: doc.run_id });
                      }}
                    >
                      Skip
                    </BusyButton>
                  </div>
                  <FormatLine
                    id={formatIdFor("whole-grade-student")}
                    spec="Choose the student whose page Open a student shows"
                  />
                  <p className="step-note whole-grade-skip-cost">{WHOLE_GRADE_SKIP_COST}</p>
                </section>
                <ul className="whole-grade-list">
                  {doc.students.map((student) => (
                    <StudentGrade
                      key={student.submission_id}
                      student={student}
                      name={studentLabel(student, shared)}
                    />
                  ))}
                </ul>
              </>
            )}
            {/* FR-UI-51: one line below the content naming what produced these grades. */}
            <GradeFooter runId={doc.run_id} />
          </>
        );
      }}
    </ReadScreen>
  );
}
