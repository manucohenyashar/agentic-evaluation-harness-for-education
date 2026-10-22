import { useMemo, useState } from "react";
import { CircleCheck, TriangleAlert } from "lucide-react";
import type { ResultsScreen as ResultsDoc, ResultStudent } from "../api";
import { ConfirmDialog, useActionState } from "../components/Confirm";
import { ElapsedClock } from "../components/Elapsed";
import {
  describedBy,
  errorIdFor,
  FieldError,
  FormatLine,
  formatIdFor,
} from "../components/Field";
import { DisabledReason } from "../components/Outcome";
import {
  NOT_FINAL_REASON_TEXT,
  averageLabel,
  checkField,
  durationLabel,
  fixFieldFirst,
  FORMAT_CHOOSE_ONE,
  type FieldSpec,
} from "../wizard/vocabulary";
import { OverrideForm, type OverrideChange } from "../components/Override";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useToast } from "../state/StateDisplay";
import {
  flagLabel,
  flagTone,
  scoreStateLabel,
} from "../state/model";
import { useScreenRead } from "../useScreenRead";
import { sharedNames, studentLabel } from "../studentNames";
import { useRunParams } from "../selection";

/**
 * The results overview (FR-UI-15, FR-UI-29..33): every student's grade read by question —
 * one cell per question ("Q1 · 2 / 2") and a "Total grade" column — with a bar per
 * question showing the class's average and a grade-count chart, the run's "Time taken"
 * rows, and the not-final banner that explains each reason and approves them all. Every
 * count, mean and timing comes from the rows the read served (`CT-UI-08`): the screen
 * formats, it never invents. Search, sort and filter by student, score level and flag
 * ride the same served rows.
 *
 * Each student's grade shows beside an editable band control (`FR-CONSOLE-20` invariant
 * 16): the "Change a final grade" disclosure opens the override — band selection plus a
 * required reason — riding the console's existing actions.
 */

function matchesFilters(student: ResultStudent, search: string, level: string, flag: string): boolean {
  if (search !== "") {
    const needle = search.toLowerCase();
    // The teacher searches by the name they know the student by.
    const hay = `${student.full_name ?? ""} ${student.student_ref ?? ""}`.toLowerCase();
    if (!hay.includes(needle)) return false;
  }
  if (level !== "" && !student.criteria.some((criterion) => criterion.criterion_band === level)) {
    return false;
  }
  if (flag !== "" && !student.criteria.some((criterion) => criterion.flag === flag)) {
    return false;
  }
  return true;
}

/** One bar in a stat chart, as the served stats name it: a filled share of the row, the
 * label beside it. A chart that is a table with bars, not a pooled histogram. */
function StatBar({ caption, share, label }: { caption: string; share: number; label: string }) {
  const width = `${Math.round(Math.max(0, Math.min(1, share)) * 100)}%`;
  return (
    <li className="stat-bar-row">
      <span className="stat-bar-caption">{caption}</span>
      <span className="stat-bar-track" aria-hidden="true">
        <span className="stat-bar-fill" style={{ width }} />
      </span>
      <span className="stat-bar-label">{label}</span>
    </li>
  );
}

/** A question's class stats (FR-UI-31): one bar per question — the class's average as a
 * share of the question's points, labelled with the design's own line — with full-marks
 * and no-marks counts beneath, from the served stats. */
function QuestionBars({ stats }: { stats: NonNullable<ResultsDoc["question_stats"]> }) {
  return (
    <figure className="question-bars">
      <figcaption className="step-note">
        One bar per question: the class's average against the question's points.
      </figcaption>
      <ul>
        {stats.map((stat) => (
          <li key={stat.question_id} className="question-stat">
            <StatBar
              caption={`${stat.label} — ${averageLabel(stat.mean_points, stat.points_max)}`}
              share={stat.mean_points === null ? 0 : stat.mean_points / stat.points_max}
              label=""
            />
            <p className="stat-note">
              full marks: {stat.full_marks} of {stat.graded}{" "}
              {stat.graded === 1 ? "student" : "students"}; no marks: {stat.zero_marks}
            </p>
          </li>
        ))}
      </ul>
    </figure>
  );
}

/** How many students got each grade (FR-UI-31's second chart): one bar per grade name
 * the run's ledger served, counted from the students' own grades. */
function GradeCounts({ students }: { students: ResultStudent[] }) {
  const counts = new Map<string, number>();
  for (const student of students) {
    const grade = student.grade ?? "";
    if (grade !== "") {
      counts.set(grade, (counts.get(grade) ?? 0) + 1);
    }
  }
  const names = [...counts.keys()];
  if (names.length === 0) {
    return null;
  }
  const summary = names.map((name) => `${name}: ${counts.get(name) ?? 0}`).join(", ");
  return (
    <figure className="question-bars">
      <figcaption className="step-note">
        Students per grade. {summary}
      </figcaption>
      <ul>
        {names.map((name) => (
          <StatBar
            key={name}
            caption={name}
            share={(counts.get(name) ?? 0) / Math.max(1, students.length)}
            label={`${counts.get(name) ?? 0}`}
          />
        ))}
      </ul>
    </figure>
  );
}

export function Results() {
  const read = useScreenRead<ResultsDoc>("/api/v1/results/screen", useRunParams());
  const navigate = useNavigate();
  const finalize = useActionState(read.retry);
  const raiseToast = useToast();
  const [remount, setRemount] = useState(0);
  const [search, setSearch] = useState("");
  const [levelFilter, setLevelFilter] = useState("");
  const [flagFilter, setFlagFilter] = useState("");
  const [sort, setSort] = useState("az");

  const data = read.data;

  const flagged = useMemo(() => {
    if (data === null) return [];
    const items: { student: ResultStudent; criterionId: string; label: string; flag: string }[] = [];
    for (const student of data.students) {
      for (const criterion of student.criteria) {
        if (criterion.flag !== null) {
          items.push({
            student,
            criterionId: criterion.criterion_id,
            label: criterion.label,
            flag: criterion.flag,
          });
        }
      }
    }
    return items;
  }, [data]);

  const afterOverride = (_text: string, changes: OverrideChange[], final: boolean): void => {
    read.retry();
    setRemount((n) => n + 1);
    if (changes.length > 0) {
      raiseToast({
        kind: "success",
        text: final
          ? "Final grade changed — the history keeps the original."
          : "The review is saved.",
      });
    }
  };

  const openFinalize = (doc: ResultsDoc): void => {
    if (doc.run_id === null || doc.students.length === 0) {
      return;
    }
    // FR-UI-33's confirmation names what it does out of the API's own document: how many
    // answers were accepted as the AI graded them, and that a later change is recorded.
    const not_final = doc.not_final_questions ?? 0;
    const test = (doc.package_version_id ?? "").split("@")[0] ?? "";
    finalize.open({
      title: "Approve all grades",
      description:
        not_final === 0
          ? `Every grade in these results is already final, so there is nothing left ` +
            "to approve for " +
            `${doc.cohort_id ?? "this class"} — ${test || "this test"}. ` +
            "You can still change a grade afterward; the change is recorded."
          : `Approve all grades for ${doc.cohort_id ?? "this class"} — ` +
            `${test || "this test"}? ${not_final} answers you have not checked will be ` +
            "accepted as the AI graded them. You can still change a grade afterward; " +
            "the change is recorded.",
      confirm: "Approve all",
      action: "finalize batch",
      body: { run_id: doc.run_id, actor: "operator" },
      said: "All grades are final.",
    });
  };

  return (
    <ReadScreen title="Results" read={read}>
      {(doc) => {
        const shared = sharedNames(doc.students);
        const shown = doc.students
          .filter((student) => matchesFilters(student, search, levelFilter, flagFilter))
          .sort((a, b) => {
            const compared = studentLabel(a, shared).localeCompare(
              studentLabel(b, shared), undefined, { sensitivity: "base" });
            return sort === "za" ? -compared : compared;
          });
        const levelsFor = (criterionId: string): string[] =>
          doc.scales.find((scale) => scale.criterion_id === criterionId)?.levels ?? [];
        return (
          <>
            {doc.students.length === 0 ? (
              <p className="panel">The run holds no computed grades.</p>
            ) : (
              <>
                <FinalGradesBanner doc={doc} onApproveAll={() => openFinalize(doc)} />
                <section className="results-overview">
                  <h2>The run</h2>
                  <p className="run-clock">
                    <ElapsedClock
                      startedAt={doc.run?.started_at ?? null}
                      endedAt={doc.run?.ended_at ?? null}
                      state={doc.run?.state ?? null}
                    />
                  </p>
                  <h2>Average by question</h2>
                  {doc.question_stats !== undefined && doc.question_stats.length > 0 && (
                    <QuestionBars stats={doc.question_stats} />
                  )}
                  <h2>Grades</h2>
                  <GradeCounts students={doc.students} />
                  <h2>Time taken</h2>
                  <ul className="time-taken">
                    {(doc.stage_timings ?? []).map((timing) => (
                      <li key={timing.stage}>
                        {timing.label}: {durationLabel(timing.seconds)}
                      </li>
                    ))}
                  </ul>
                  <h2>Flagged</h2>
                  {flagged.length === 0 ? (
                    <p>No grading point is flagged.</p>
                  ) : (
                    <ul className="flagged-list">
                      {flagged.map((item) => (
                        <li key={`${item.student.submission_id}-${item.criterionId}`}>
                          <a
                            href={`#/results/students/${item.student.submission_id}`}
                            onClick={() =>
                              navigate(`/results/students/${item.student.submission_id}`)}
                          >
                            {studentLabel(item.student, shared)}
                          </a>{" "}
                          — {item.label}: {flagLabel(item.flag)}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
                <section className="results-filters">
                  <label>
                    Find a student{" "}
                    <input
                      type="search"
                      name="student-search"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                    />
                  </label>
                  <label>
                    Score level{" "}
                    <select
                      name="level-filter"
                      aria-describedby={formatIdFor("level-filter")}
                      value={levelFilter}
                      onChange={(event) => setLevelFilter(event.target.value)}
                    >
                      <option value="">All levels</option>
                      {doc.score_levels.map((level) => (
                        <option key={level} value={level}>
                          {level}
                        </option>
                      ))}
                    </select>
                    <FormatLine id={formatIdFor("level-filter")} spec="Show only the students at this score level" />
                  </label>
                  <label>
                    Flag{" "}
                    <select
                      name="flag-filter"
                      aria-describedby={formatIdFor("flag-filter")}
                      value={flagFilter}
                      onChange={(event) => setFlagFilter(event.target.value)}
                    >
                      <option value="">All</option>
                      <option value="second_opinion">Second opinion</option>
                      <option value="low_confidence">Low confidence</option>
                      <option value="not_final">Not final yet</option>
                    </select>
                    <FormatLine id={formatIdFor("flag-filter")} spec="Show only the students with this flag" />
                  </label>
                  <label>
                    Sort students{" "}
                    <select
                      name="student-sort"
                      aria-describedby={formatIdFor("student-sort")}
                      value={sort}
                      onChange={(event) => setSort(event.target.value)}
                    >
                      <option value="az">A to Z</option>
                      <option value="za">Z to A</option>
                    </select>
                    <FormatLine id={formatIdFor("student-sort")} spec="The order the students are listed in" />
                  </label>
                </section>
                <ul className="result-list" key={remount}>
                  {shown.map((student) => (
                    <li key={student.submission_id} className="result-row">
                      <div className="result-head">
                        <a
                          href={`#/results/students/${student.submission_id}`}
                          onClick={() => navigate(`/results/students/${student.submission_id}`)}
                        >
                          {studentLabel(student, shared)}
                        </a>
                        {student.total_points != null && student.total_max != null ? (
                          <span className="total-grade">
                            Total grade: {student.total_points} / {student.total_max}
                            {student.grade ? ` — ${student.grade}` : ""}
                          </span>
                        ) : (
                          <span>Total: {student.total ?? "—"}</span>
                        )}
                        <span>{student.state === "" ? "—" : scoreStateLabel(student.state)}</span>
                      </div>
                      <ul className="question-cells">
                        {(student.questions ?? []).map((question) => (
                          <li key={question.question_id} className="question-cell">
                            <span>
                              {question.label} · {question.points_awarded ?? "—"} /{" "}
                              {question.points_max}
                            </span>
                            {question.state === "not_final" && question.not_final_reason !== null && (
                              <span
                                className="badge badge-warning check-badge"
                                title={NOT_FINAL_REASON_TEXT[question.not_final_reason] ??
                                  "Please check this answer."}
                              >
                                <TriangleAlert size={12} aria-hidden="true" />
                                <span> Check</span>
                              </span>
                            )}
                            <details className="question-detail">
                              <summary>How each line was scored</summary>
                              <ul className="band-list">
                                {student.criteria
                                  .filter((criterion) =>
                                    criterion.question_id === question.question_id)
                                  .map((criterion) => (
                                    <li key={criterion.criterion_id}>
                                      <span className="step-note">{criterion.label}</span>{" "}
                                      <span className="band-value">
                                        {criterion.criterion_band}
                                      </span>
                                      {criterion.stored_band !== criterion.criterion_band && (
                                        <span className="band-note">
                                          {" "}(amended from {criterion.stored_band})
                                        </span>
                                      )}
                                      {question.state === "not_final" &&
                                        question.not_final_reason !== null && (
                                        <p className="band-note check-reason">
                                          {NOT_FINAL_REASON_TEXT[question.not_final_reason] ??
                                            "Please check this answer."}
                                        </p>
                                      )}
                                      {criterion.flag !== null && (
                                        <span className={`badge badge-${flagTone(criterion.flag)}`}>
                                          <TriangleAlert size={12} aria-hidden="true" />
                                          <span> {flagLabel(criterion.flag)}</span>
                                        </span>
                                      )}
                                    </li>
                                  ))}
                              </ul>
                            </details>
                          </li>
                        ))}
                      </ul>
                      {/* An unreadable catalog answers no questions: the roll-up is empty,
                          so the served lines still show — the old flat list, degraded but
                          never vanished (FR-CONSOLE-76's contract: the rows are the truth). */}
                      {student.questions !== undefined && student.questions.length > 0 ? null : (
                        <ul className="band-list">
                          {student.criteria.map((criterion) => (
                            <li key={criterion.criterion_id}>
                              <span className="step-note">{criterion.label}</span>{" "}
                              <span className="band-value">{criterion.criterion_band}</span>
                              {criterion.stored_band !== criterion.criterion_band && (
                                <span className="band-note">
                                  {" "}(amended from {criterion.stored_band})
                                </span>
                              )}
                              {criterion.flag !== null && (
                                <span className={`badge badge-${flagTone(criterion.flag)}`}>
                                  <TriangleAlert size={12} aria-hidden="true" />
                                  <span> {flagLabel(criterion.flag)}</span>
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                      <OverrideForm
                        criteria={student.criteria.map((criterion) => ({
                          criterion_id: criterion.criterion_id,
                          label: criterion.label,
                          criterion_band: criterion.criterion_band,
                          levels: levelsFor(criterion.criterion_id).length > 0
                            ? levelsFor(criterion.criterion_id)
                            : [criterion.criterion_band],
                        }))}
                        final={student.state === "final"}
                        submissionId={student.submission_id}
                        runId={doc.run_id}
                        onDone={afterOverride}
                      />
                    </li>
                  ))}
                </ul>
                {shown.length === 0 && <p>No student matches the search or filters.</p>}
              </>
            )}
            {finalize.pending !== null && (
              <ConfirmDialog
                pending={finalize.pending}
                onClose={finalize.close}
                onDone={finalize.finish}
              />
            )}
            {doc.run_id !== null && doc.students.length > 0 && <Downloads key={doc.run_id} doc={doc} />}
            {doc.run_id !== null && <KeyCorrection key={`key-${doc.run_id}`} doc={doc} onDone={read.retry} />}
            {doc.run_id !== null && <ReviewWindow key={`window-${doc.run_id}`} runId={doc.run_id} onDone={read.retry} />}
          </>
        );
      }}
    </ReadScreen>
  );
}

/** The not-final banner (FR-UI-33): the answers that need a check, named in one sentence
 * with the two ways forward — the review filtered to this run, and approving them all —
 * or the state once every grade is final, including the open review window's automatic
 * date. The served count names the answers; the screen never recounts. */
function FinalGradesBanner({ doc, onApproveAll }: {
  doc: ResultsDoc;
  onApproveAll: () => void;
}) {
  const navigate = useNavigate();
  const not_final = doc.not_final_questions ?? 0;
  const window_ends = doc.review_window_ends ?? null;
  return (
    <div className="outcome-banner outcome-done results-banner" role="region" aria-label="The grades' state">
      <p className="action-outcome">
        {not_final > 0 ? (
          <>
            <strong className="outcome-what">
              {not_final} answers need your check before the grades are final.
            </strong>{" "}
            <button
              type="button"
              className="button"
              onClick={() => navigate("/review")}
            >
              Check answers
            </button>{" "}
            <button type="button" className="button button-primary" onClick={onApproveAll}>
              Approve all grades
            </button>
          </>
        ) : window_ends !== null ? (
          <>
            <strong className="outcome-what">
              Grades become final automatically on {window_ends}, when the review window ends.
            </strong>
          </>
        ) : (
          <>
            <CircleCheck size={18} aria-hidden="true" />
            <strong className="outcome-what">All grades are final.</strong>
          </>
        )}
      </p>
    </div>
  );
}

/** A same-origin download link for one export read (FR-CONSOLE-44/58/59): the console
 * answers the file's bytes, and the browser saves them under the name given here. */
function exportHref(path: string, params: Record<string, string>): string {
  return `${path}?${new URLSearchParams(params).toString()}`;
}

/**
 * The exports (design delta §3.2: CSV/PDF existing, workbook and readable test new): the
 * marks as a spreadsheet or a CSV file, one student's report as a PDF, and the test itself
 * as a readable PDF and as a backup file. "Version 1" is every student's marks as first
 * given; a later version holds only the students whose final mark was changed that many
 * times (the export reads one revision, `export_grade_artifacts`).
 */
/** The marks version an export reads: 1 is the marks as first given. */
const MARKS_VERSION: FieldSpec = { kind: "whole_number", min: 1, max: 99 };

function Downloads({ doc }: { doc: ResultsDoc }) {
  const runId = doc.run_id ?? "";
  const [revision, setRevision] = useState("1");
  const shared = sharedNames(doc.students);
  const named = doc.students
    .filter((s) => s.student_ref !== null)
    .sort((a, b) => studentLabel(a, shared).localeCompare(studentLabel(b, shared), undefined, {
      sensitivity: "base",
    }));
  const firstRef = named[0]?.student_ref ?? "";
  const [student, setStudent] = useState(firstRef);
  const revisionError = checkField(MARKS_VERSION, revision);
  const rev = revisionError === null && revision.trim() !== "" ? revision.trim() : "1";
  const version = doc.package_version_id ?? "";
  return (
    <section className="panel" aria-label="Download the results">
      <h2>Download the results</h2>
      <div className="settings-form">
        <div className="settings-row">
          <label htmlFor="export-revision">Marks version</label>
          <input
            id="export-revision"
            aria-describedby={describedBy("export-revision", revisionError)}
            aria-invalid={revisionError !== null || undefined}
            inputMode="numeric"
            placeholder="e.g. 1"
            value={revision}
            onChange={(event) => setRevision(event.target.value)}
          />
          <FormatLine id={formatIdFor("export-revision")} spec={MARKS_VERSION} />
          <FieldError id={errorIdFor("export-revision")} error={revisionError} />
          <p className="step-note">
            1 is every student's marks as first given. 2 lists only the students whose final
            mark was changed, with the changed mark (3 the next change, and so on).
          </p>
        </div>
        <div className="settings-row">
          <label htmlFor="export-student">Student for the report</label>
          <select
            id="export-student"
            aria-describedby={formatIdFor("export-student")}
            value={student}
            onChange={(event) => setStudent(event.target.value)}
          >
            {named.map((s) => (
              <option key={s.submission_id} value={s.student_ref ?? ""}>
                {studentLabel(s, shared)}
              </option>
            ))}
          </select>
          <FormatLine
            id={formatIdFor("export-student")}
            spec="Choose the student whose report to download"
          />
        </div>
      </div>
      {revisionError !== null ? (
        <DisabledReason reason={fixFieldFirst("Marks version")} />
      ) : (
      <ul className="rows-list">
        <li>
          <a
            className="button"
            href={exportHref("/api/v1/results/workbook", { run_id: runId, revision: rev })}
            download={`marks-${runId}-v${rev}.xlsx`}
          >
            Marks spreadsheet (Excel)
          </a>
        </li>
        <li>
          <a
            className="button"
            href={exportHref("/api/v1/results/export", {
              run_id: runId, revision: rev, format: "csv",
            })}
            download={`marks-${runId}-v${rev}.csv`}
          >
            Marks file (CSV)
          </a>
        </li>
        <li>
          <a
            className="button"
            href={exportHref("/api/v1/results/export", {
              run_id: runId, revision: rev, format: "pdf", student_ref: student,
            })}
            download={`report-${student}-v${rev}.pdf`}
          >
            The chosen student&apos;s report (PDF)
          </a>
        </li>
        {version !== "" && (
          <>
            <li>
              <a
                className="button"
                href={exportHref("/api/v1/packages/readable", { package_version: version })}
                download={`test-${version}.pdf`}
              >
                The test and its grading guide (PDF)
              </a>
            </li>
            <li>
              <a
                className="button"
                href={exportHref("/api/v1/packages/readable", {
                  package_version: version, format: "aehpkg",
                })}
                download={`test-${version}.aehpkg`}
              >
                Backup of the test
              </a>
            </li>
          </>
        )}
      </ul>
      )}
    </section>
  );
}

/**
 * The answer-key correction (FR-CONSOLE-30): a multiple-choice key found wrong after the run
 * is corrected here, and M-PKG, M-DET and M-GRADE re-derive that question's marks for the
 * class — the console's "correct an answer key after a run" control, behind its confirmation.
 */
function KeyCorrection({ doc, onDone }: { doc: ResultsDoc; onDone: () => void }) {
  const keys = doc.answer_keys ?? [];
  const [criterion, setCriterion] = useState(keys[0]?.criterion_id ?? "");
  const chosen = keys.find((k) => k.criterion_id === criterion) ?? null;
  const [letter, setLetter] = useState("");
  const action = useActionState(onDone);
  if (keys.length === 0 || doc.run_id === null) return null;
  return (
    <section className="panel" aria-label="Correct an answer key">
      <h2>Correct an answer key</h2>
      <p className="step-note">
        If a multiple-choice answer key was wrong, choose the question and the right answer.
        That question's marks are worked out again for the whole class.
      </p>
      <div className="settings-form">
        <div className="settings-row">
          <label htmlFor="key-question">Question</label>
          <select
            id="key-question"
            aria-describedby={formatIdFor("key-question")}
            value={criterion}
            onChange={(event) => {
              setCriterion(event.target.value);
              setLetter("");
            }}
          >
            {keys.map((k) => (
              <option key={k.criterion_id} value={k.criterion_id}>
                {k.label} (key now: {k.key.join(", ") || "none"})
              </option>
            ))}
          </select>
          <FormatLine id={formatIdFor("key-question")} spec="Choose the question whose key was wrong" />
        </div>
        <div className="settings-row">
          <label htmlFor="key-answer">Right answer</label>
          <select
            id="key-answer"
            aria-describedby={formatIdFor("key-answer")}
            value={letter}
            onChange={(event) => setLetter(event.target.value)}
          >
            <option value="">Choose…</option>
            {(chosen?.options ?? []).map((option) => (
              <option key={option.option_id} value={option.option_id}>
                {option.option_id}
                {option.label !== "" ? ` — ${option.label}` : ""}
              </option>
            ))}
          </select>
          <FormatLine id={formatIdFor("key-answer")} spec={FORMAT_CHOOSE_ONE} />
        </div>
        <div className="settings-actions">
          <button
            type="button"
            className="button"
            disabled={letter === "" || chosen === null || chosen.key.join(",") === letter}
            onClick={() =>
              action.open({
                title: "Correct this answer key",
                description:
                  `The key for ${chosen?.label ?? criterion} becomes ${letter}. Every ` +
                  "student's mark on it is worked out again, and the change is recorded.",
                confirm: "Correct the key",
                action: "correct an answer key after a run",
                body: { run_id: doc.run_id, criterion_id: criterion, answer_key: [letter] },
                said: `The key is corrected, and the marks for ${chosen?.label ?? "that question"} are worked out again.`,
              })
            }
          >
            Correct the key
          </button>
        </div>
      </div>
      {action.pending !== null && (
        <ConfirmDialog pending={action.pending} onClose={action.close} onDone={action.finish} />
      )}
    </section>
  );
}

/**
 * The review window (FR-CONSOLE-22): how many hours the grades stay open for review before
 * finalizing settles them — the "set review window" control, behind its confirmation.
 */
/** The review window's hours, as the form checks them (four digits, as the server takes). */
const REVIEW_HOURS: FieldSpec = { kind: "whole_number", min: 0, max: 9999 };

function ReviewWindow({ runId, onDone }: { runId: string; onDone: () => void }) {
  const [hours, setHours] = useState("");
  const action = useActionState(onDone);
  const hoursError = checkField(REVIEW_HOURS, hours);
  const valid = hoursError === null && hours.trim() !== "";
  return (
    <section className="panel" aria-label="Review window">
      <h2>Review window</h2>
      <p className="step-note">
        Keep the grades open for review for a number of hours before they become final (0
        means they become final as soon as you approve them).
      </p>
      <div className="settings-form">
        <div className="settings-row">
          <label htmlFor="review-hours">Hours</label>
          <input
            id="review-hours"
            aria-describedby={describedBy("review-hours", hoursError)}
            aria-invalid={hoursError !== null || undefined}
            inputMode="numeric"
            placeholder="e.g. 24"
            value={hours}
            onChange={(event) => setHours(event.target.value)}
          />
          <FormatLine id={formatIdFor("review-hours")} spec={REVIEW_HOURS} />
          <FieldError id={errorIdFor("review-hours")} error={hoursError} />
        </div>
        <div className="settings-actions">
          <button
            type="button"
            className="button"
            disabled={!valid}
            onClick={() =>
              action.open({
                title: "Set the review window",
                description: `The grades stay open for review for ${hours} hour(s) before they become final.`,
                confirm: "Set it",
                action: "set review window",
                body: { run_id: runId, review_window_hours: Number(hours) },
                said: `The grades stay open for review for ${hours} hour(s).`,
              })
            }
          >
            Set the review window
          </button>
          <DisabledReason
            reason={
              hoursError !== null ? fixFieldFirst("Hours")
                : hours.trim() === "" ? "Fill in “Hours” first." : null
            }
          />
        </div>
      </div>
      {action.pending !== null && (
        <ConfirmDialog pending={action.pending} onClose={action.close} onDone={action.finish} />
      )}
    </section>
  );
}
