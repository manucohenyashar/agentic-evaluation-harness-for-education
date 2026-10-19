import { useMemo, useState } from "react";
import type { PastTestRun, PastTestsDoc } from "../api";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useScreenRead } from "../useScreenRead";
import { entityStateLabel } from "../wizard/vocabulary";
import { sharedNames, studentLabel } from "../studentNames";

/**
 * Past tests (FR-CONSOLE-70): every grading run the console holds, newest first — its class,
 * the test it graded, when it ran and how it ended — so a teacher asked about a test weeks
 * later finds it without guessing runs one by one. Typing a student's name finds that student
 * in every past test, with their total; each line opens the run's results or the student's own
 * page. Filtering by class narrows the list. Students are named the way the teacher knows them.
 */

/** A date the teacher reads ("14 Mar 2026"), or a dash for a run that never started. */
export function shortDate(at: string | null | undefined): string {
  if (!at) return "—";
  const when = new Date(at);
  if (Number.isNaN(when.getTime())) return at;
  return when.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** One run in words: "7b-english · physics-v2 · 14 Mar 2026". */
export function runLabel(run: {
  cohort_id: string;
  package_version_id: string;
  started_at: string | null;
}): string {
  return `${run.cohort_id} · ${run.package_version_id} · ${shortDate(run.started_at)}`;
}

function matches(text: string | null | undefined, needle: string): boolean {
  return (text ?? "").toLocaleLowerCase().includes(needle);
}

export function PastTests({ classId }: { classId: string | null }) {
  const read = useScreenRead<PastTestsDoc>("/api/v1/past-tests");
  const navigate = useNavigate();
  const [cls, setCls] = useState<string>(classId ?? "");
  const [who, setWho] = useState("");

  return (
    <ReadScreen title="Past tests" read={read}>
      {(doc) => (
        <PastTestsBody
          doc={doc}
          cls={cls}
          setCls={setCls}
          who={who}
          setWho={setWho}
          open={(run: PastTestRun, submissionId?: string) =>
            navigate(submissionId ? `/results/students/${submissionId}` : "/results", {
              class: run.cohort_id,
              run: run.run_id,
            })
          }
        />
      )}
    </ReadScreen>
  );
}

function PastTestsBody({
  doc,
  cls,
  setCls,
  who,
  setWho,
  open,
}: {
  doc: PastTestsDoc;
  cls: string;
  setCls: (value: string) => void;
  who: string;
  setWho: (value: string) => void;
  open: (run: PastTestRun, submissionId?: string) => void;
}) {
  const classes = useMemo(
    () => [...new Set(doc.runs.map((run) => run.cohort_id))].sort(),
    [doc.runs],
  );
  const needle = who.trim().toLocaleLowerCase();
  const runs = doc.runs.filter((run) => cls === "" || run.cohort_id === cls);
  const found = needle === ""
    ? []
    : runs.flatMap((run) =>
        run.students
          .filter((s) => matches(s.full_name, needle))
          .map((student) => ({ run, student })));

  return (
    <>
      <div className="settings-form" role="search" aria-label="Find a past test">
        <div className="settings-row">
          <label htmlFor="past-class">Class</label>
          <select id="past-class" value={cls} onChange={(event) => setCls(event.target.value)}>
            <option value="">Every class</option>
            {classes.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <div className="settings-row">
          <label htmlFor="past-student">Find a student</label>
          <input
            id="past-student"
            type="search"
            value={who}
            placeholder="Type a student's name"
            onChange={(event) => setWho(event.target.value)}
          />
        </div>
      </div>

      {needle !== "" && (
        <section className="panel" aria-label="The student's past tests">
          <h2>“{who.trim()}” in past tests</h2>
          {found.length === 0 ? (
            <p>No graded paper of a student by that name{cls ? ` in ${cls}` : ""}.</p>
          ) : (
            <ul className="rows-list">
              {found.map(({ run, student }) => (
                <li key={`${run.run_id}-${student.submission_id}`}>
                  <a
                    href={`#/results/students/${student.submission_id}`}
                    onClick={(event) => {
                      event.preventDefault();
                      open(run, student.submission_id);
                    }}
                  >
                    {studentLabel(student, sharedNames(run.students))}
                  </a>
                  <span className="step-note">{runLabel(run)}</span>
                  <span className="step-state">Total: {student.total ?? "—"}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {runs.length === 0 ? (
        <p className="panel">
          {doc.runs.length === 0
            ? "No test has been graded yet. Past tests appear here once a grading run starts."
            : "No grading run for this class yet."}
        </p>
      ) : (
        <ul className="rows-list" aria-label="Every grading run, newest first">
          {runs.map((run) => (
            <li key={run.run_id} className="result-row">
              <div className="result-head">
                <a
                  href="#/results"
                  onClick={(event) => {
                    event.preventDefault();
                    open(run);
                  }}
                >
                  Class {run.cohort_id} — test {run.package_version_id}
                </a>
                <span>
                  {shortDate(run.started_at)}
                  {run.completed_at ? ` – ${shortDate(run.completed_at)}` : ""}
                </span>
                <span>{entityStateLabel(run.status)}</span>
                <span>
                  {run.students.length} student{run.students.length === 1 ? "" : "s"} graded
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
      {doc.unreadable_runs > 0 && (
        <p className="step-note">
          The grades of {doc.unreadable_runs} run(s) could not be read; they are listed without
          their students.
        </p>
      )}
    </>
  );
}
