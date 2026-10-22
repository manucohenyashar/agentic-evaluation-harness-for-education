import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchJob,
  type ContextDoc,
  type JobRecord,
  type PaperSheet,
  type Papers as PapersDoc,
  type Student,
} from "../api";
import { ConfirmDialog, useActionState } from "../components/Confirm";
import { ReadScreen } from "../components/ReadScreen";
import { sharedNames, studentLabel } from "../studentNames";
import { useNavigate } from "../navigate";
import { ProgressBar, useToast } from "../state/StateDisplay";
import { useScreenRead } from "../useScreenRead";
import type { Selection } from "../wizard/derivation";
import { FormatLine, formatIdFor } from "../components/Field";
import { BusyButton, DisabledReason, textOutcome, useOutcome } from "../components/Outcome";
import { FORMAT_PDF_PER_STUDENT, OUTCOME_FALLBACK_WHAT, versionName } from "../wizard/vocabulary";

/**
 * The papers screen (FR-UI-03c, live-test blocker B4): the selected class's students, what
 * has been read for each, and the upload that reads more. The teacher picks the test paper
 * (once per class — every answer sheet is checked against it) and the answer sheets (one PDF
 * per student), sees the list before anything is sent, and confirms. Each file goes up on the
 * upload transport (`FR-CONSOLE-04`, the body is the file itself, never a URL) asking to be
 * read; the console reads it on its own worker with the same checks `aeh ingest` runs, and
 * this screen follows that work's job until it is done. A paper a check refuses is parked
 * for the operator — the Parked page is one link away.
 *
 * Every mistake made here has a way back (FR-CONSOLE-66..69): the class check says who has no
 * paper yet, by name; a paper filed under the wrong student is moved to the right one; a paper
 * that should not be here (the wrong file, another class's sheet, the earlier of two scans) is
 * removed so the right scan can be read; and the wrong test paper is replaced while nothing is
 * graded. Students are named the way the teacher knows them — by name, never by an id.
 */

const JOB_POLL_MS = 1500;

/** Where a file goes on the upload transport: its class, its test version and what it is. */
function uploadUrl(classId: string, version: string, kind: "assessment" | "sheet", file: File) {
  const query = new URLSearchParams({
    read: "1",
    cohort_id: classId,
    package_version: version,
    kind,
    filename: file.name,
  });
  return `/api/v1/uploads?${query.toString()}`;
}

/** The teacher's word for one sheet's paper-check status. */
function sheetStatusLabel(status: string, parked: boolean): string {
  if (parked) return `parked (${status.replace(/_/g, " ")})`;
  if (status === "ok") return "read";
  if (status === "low_confidence_ocr") return "read (hard to read)";
  if (status === "reading") return "being read";
  return status.replace(/_/g, " ");
}

export function Papers({
  context,
  selection,
}: {
  context: ContextDoc | null;
  selection: Selection;
}) {
  const navigate = useNavigate();
  const toast = useToast();
  const read = useScreenRead<PapersDoc>(
    "/api/v1/papers",
    selection.classId === null ? undefined : { cohort_id: selection.classId },
  );
  const fix = useActionState(read.retry);
  const { report, clear } = useOutcome();

  // The published test versions, the selected package's (or this class's last run's) first.
  const versions = useMemo(() => {
    const preferred = new Set<string>();
    const run = (context?.runs ?? []).find((r) => r.run_id === selection.runId);
    if (run !== undefined) preferred.add(run.package_version_id);
    const pkg = (context?.packages ?? []).find((p) => p.package_id === selection.packageId);
    if (pkg?.published_version_id) preferred.add(pkg.published_version_id);
    const all = (context?.packages ?? [])
      .map((p) => p.published_version_id)
      .filter((v): v is string => v !== null);
    return [...preferred, ...all.filter((v) => !preferred.has(v))];
  }, [context, selection.runId, selection.packageId]);
  const [version, setVersion] = useState("");
  useEffect(() => {
    if (version === "" || !versions.includes(version)) setVersion(versions[0] ?? "");
  }, [versions, version]);

  const [testPaper, setTestPaper] = useState<File | null>(null);
  const [sheets, setSheets] = useState<File[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [sending, setSending] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const sheetInput = useRef<HTMLInputElement | null>(null);

  // A switch from one class to ANOTHER drops what was chosen and followed for the first, so
  // nothing is sent to the wrong class. The selection resolving for the first time (none ->
  // the class the screen already shows) is not a switch and keeps the work in hand.
  const shownClass = useRef<string | null>(selection.classId);
  useEffect(() => {
    const previous = shownClass.current;
    shownClass.current = selection.classId;
    if (previous === null || previous === selection.classId) return;
    setTestPaper(null);
    setSheets([]);
    setJobId(null);
    setJob(null);
    setProblem(null);
  }, [selection.classId]);
  const paperInput = useRef<HTMLInputElement | null>(null);

  // Follow the reading job until it settles, re-reading the class as each file lands.
  useEffect(() => {
    if (jobId === null) return;
    let stopped = false;
    let timer: number | undefined;
    const poll = (): void => {
      fetchJob(jobId).then(
        (next) => {
          if (stopped) return;
          setJob(next);
          read.retry();
          if (next.state === "queued" || next.state === "running") {
            timer = window.setTimeout(poll, JOB_POLL_MS);
          } else {
            toast({
              kind: next.state === "succeeded" ? "success" : "failure",
              text: next.progress.current ?? "The papers were read.",
            });
          }
        },
        () => {
          if (!stopped) timer = window.setTimeout(poll, JOB_POLL_MS);
        },
      );
    };
    poll();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
    // `read.retry` and `toast` are stable; the job id alone restarts the follow.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  // With no class chosen the server's own default class answers (the run's, else the first);
  // the uploads always go to the class the screen actually shows.
  const send = async (classId: string, needsTestPaper: boolean): Promise<void> => {
    setConfirming(false);
    setProblem(null);
    clear();
    const queue: { file: File; kind: "assessment" | "sheet" }[] = [];
    if (needsTestPaper && testPaper !== null) queue.push({ file: testPaper, kind: "assessment" });
    for (const file of sheets) queue.push({ file, kind: "sheet" });
    let failed: string | null = null;
    let sent = 0;
    for (const { file, kind } of queue) {
      setSending(file.name);
      try {
        const response = await fetch(uploadUrl(classId, version, kind, file), {
          method: "POST",
          headers: { "Content-Type": "application/pdf" },
          body: file,
        });
        const answer = (await response.json().catch(() => ({}))) as {
          dispatched?: boolean;
          detail?: string;
          job_id?: string;
        };
        if (!response.ok || answer.dispatched !== true) {
          const said = `${file.name} was not accepted: ${answer.detail ?? "the upload failed."}`;
          setProblem(said);
          failed = said;
          break;
        }
        if (answer.job_id) setJobId(answer.job_id);
        sent += 1;
      } catch (failure: unknown) {
        const said =
          `${file.name} could not be sent (${failure instanceof Error ? failure.message : String(failure)}). Check that the console is still running.`;
        setProblem(said);
        failed = said;
        break;
      }
    }
    setSending(null);
    report(
      failed !== null
        ? {
            ...textOutcome(failed, true),
            what: sent === 0 ? OUTCOME_FALLBACK_WHAT : `Only ${sent} of ${queue.length} files were sent.`,
            next: "Check the file named here, then send it again.",
          }
        : textOutcome(
            `${queue.length === 1 ? "1 file was" : `${queue.length} files were`} sent. ` +
              "Reading the papers has started.",
          ),
    );
    setTestPaper(null);
    setSheets([]);
    if (paperInput.current) paperInput.current.value = "";
    if (sheetInput.current) sheetInput.current.value = "";
  };

  return (
    <ReadScreen title="Load papers" read={read}>
      {(data) => {
        const needsTestPaper = data.test_paper_read !== true;
        const readySheets = data.sheets ?? [];
        const parkedCount = readySheets.filter((s) => s.parked).length;
        const canSend =
          version !== "" &&
          sending === null &&
          (sheets.length > 0 || (needsTestPaper && testPaper !== null)) &&
          (!needsTestPaper || testPaper !== null);
        const busy = job !== null && (job.state === "queued" || job.state === "running");
        return (
          <>
            <section className="panel" aria-label="Read papers">
              <h2>Class {data.cohort_id}</h2>
              {versions.length === 0 && (
                <p>
                  No test is published yet —{" "}
                  <a href="#/package" onClick={() => navigate("/package")}>
                    set up the test
                  </a>{" "}
                  before reading papers.
                </p>
              )}
              {(
                <form
                  className="settings-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (canSend) setConfirming(true);
                  }}
                >
                  <div className="settings-row">
                    <label htmlFor="papers-version">Test these papers answer</label>
                    <select
                      id="papers-version"
                      aria-describedby={formatIdFor("papers-version")}
                      value={version}
                      onChange={(event) => setVersion(event.target.value)}
                    >
                      {versions.map((v) => (
                        <option key={v} value={v}>
                          {versionName(v, context?.packages)}
                        </option>
                      ))}
                    </select>
                    <FormatLine
                      id={formatIdFor("papers-version")}
                      spec="Choose the published test the students sat"
                    />
                  </div>
                  <div className="settings-row">
                    <label htmlFor="papers-test">The test paper (PDF)</label>
                    {needsTestPaper ? (
                      <>
                        <input
                          id="papers-test"
                          aria-describedby={formatIdFor("papers-test")}
                          ref={paperInput}
                          type="file"
                          accept="application/pdf,.pdf"
                          onChange={(event) => setTestPaper(event.target.files?.[0] ?? null)}
                        />
                        <FormatLine
                          id={formatIdFor("papers-test")}
                          spec="One PDF file of the blank test paper"
                        />
                        <p className="step-note">
                          Needed once for this class: every answer sheet is checked against it.
                        </p>
                      </>
                    ) : (
                      <span>
                        Already in for this class.{" "}
                        {(data.graded_papers ?? 0) === 0 ? (
                          <button
                            type="button"
                            className="button button-small"
                            onClick={() =>
                              fix.open({
                                title: "Replace the test paper",
                                description:
                                  "The test paper read for this class is removed, so the right " +
                                  "one is read with your next upload. The answer sheets already " +
                                  "read were checked against the wrong test paper, so they are " +
                                  "removed too and read again when you upload them. Nothing " +
                                  "has been graded yet, so no mark is lost.",
                                confirm: "Replace the test paper",
                                action: "replace test paper",
                                body: { cohort_id: data.cohort_id, with_sheets: true },
                              })
                            }
                          >
                            Wrong test paper? Replace it
                          </button>
                        ) : (
                          <span className="step-note">
                            Papers here are already graded against it, so it stays.
                          </span>
                        )}
                      </span>
                    )}
                  </div>
                  <div className="settings-row">
                    <label htmlFor="papers-sheets">Answer sheets (one PDF per student)</label>
                    <input
                      id="papers-sheets"
                      ref={sheetInput}
                      type="file"
                      accept="application/pdf,.pdf"
                      multiple
                      aria-describedby={formatIdFor("papers-sheets")}
                      onChange={(event) => setSheets(Array.from(event.target.files ?? []))}
                    />
                    <FormatLine id={formatIdFor("papers-sheets")} spec={FORMAT_PDF_PER_STUDENT} />
                  </div>
                  {(testPaper !== null || sheets.length > 0) && (
                    <ul className="rows-list" aria-label="Files to read">
                      {testPaper !== null && needsTestPaper && (
                        <li>
                          <span className="step-name">{testPaper.name}</span>
                          <span className="step-note">test paper</span>
                        </li>
                      )}
                      {sheets.map((file, index) => (
                        <li key={`${index}-${file.name}`}>
                          <span className="step-name">{file.name}</span>
                          <span className="step-note">
                            answer sheet, {Math.max(1, Math.round(file.size / 1024))} KB
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="settings-actions">
                    <BusyButton
                      type="submit"
                      className="button button-primary"
                      disabled={!canSend || busy}
                      busy={sending !== null}
                    >
                      {sending !== null ? `Sending ${sending}…` : "Read the papers"}
                    </BusyButton>
                    <DisabledReason
                      reason={
                        sending !== null || canSend ? null
                          : busy ? "Wait until the papers already sent have been read."
                            : version === "" ? "Publish a test first."
                              : needsTestPaper && testPaper === null
                                ? "Choose the test paper first."
                                : "Choose the answer sheets first."
                      }
                    />
                  </div>
                  {problem !== null && (
                    <p role="alert" className="settings-error">
                      {problem}
                    </p>
                  )}
                </form>
              )}
              {job !== null && (
                <div className="drafting-progress" aria-label="Reading progress">
                  <ProgressBar
                    done={job.progress.done ?? 0}
                    total={job.progress.total ?? 0}
                    label="Papers read"
                  />
                  <p className="drafting-line">{job.progress.current ?? ""}</p>
                  {job.state === "failed" && (
                    <p role="alert" className="screen-alert">
                      {job.error.detail ?? "The papers could not be read."}{" "}
                      {job.error.next_action ?? ""}
                    </p>
                  )}
                </div>
              )}
            </section>

            <section className="panel" aria-label="Students">
              <h2>Students</h2>
              <ClassCheck data={data} />
              <SheetList
                data={data}
                onMove={(sheet, student, shared) =>
                  fix.open({
                    title: "Give this paper to another student",
                    description:
                      `This paper is now filed under ${studentLabel(sheet, shared)}. It will ` +
                      `belong to ${studentLabel(student, shared)} instead; any marks it already ` +
                      "has move with it, and the change is recorded.",
                    confirm: "Move the paper",
                    action: "move paper to student",
                    body: {
                      cohort_id: data.cohort_id,
                      submission_id: sheet.submission_id,
                      student_ref: student.student_ref,
                      actor: "teacher",
                    },
                  })
                }
                onRemove={(sheet, shared) =>
                  fix.open({
                    title: "Remove this paper",
                    description:
                      `The paper filed under ${studentLabel(sheet, shared, "no student")} is ` +
                      "removed from this class, with everything read from it. Upload the right " +
                      "scan afterwards and it is read again.",
                    confirm: "Remove the paper",
                    action: "remove paper",
                    body: { cohort_id: data.cohort_id, submission_id: sheet.submission_id },
                  })
                }
              />
              {parkedCount > 0 && (
                <p>
                  {parkedCount === 1 ? "1 paper is" : `${parkedCount} papers are`} parked for a
                  check —{" "}
                  <a href="#/parked" onClick={() => navigate("/parked")}>
                    open the parked papers
                  </a>
                  .
                </p>
              )}
              <p className="step-note">
                {data.parts.length === 0
                  ? "No scans uploaded yet."
                  : `Uploaded files: ${data.parts.join(", ")}.`}
              </p>
            </section>
            {fix.pending !== null && (
              <ConfirmDialog pending={fix.pending} onClose={fix.close} onDone={fix.finish} />
            )}

            {confirming && (
              <div role="dialog" aria-modal="true" aria-label="Read these papers" className="dialog">
                <h2>Read these papers</h2>
                <p>
                  {needsTestPaper ? "The test paper and " : ""}
                  {sheets.length} answer sheet(s) will be sent to the page reader set in this
                  console's settings and checked against test {version}. A paper that fails a
                  check is parked for you to look at; a paper already read is skipped.
                </p>
                <div className="dialog-actions">
                  <button type="button" className="button" onClick={() => setConfirming(false)}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="button button-primary"
                    onClick={() => {
                      void send(data.cohort_id, needsTestPaper);
                    }}
                  >
                    Read them
                  </button>
                </div>
              </div>
            )}
          </>
        );
      }}
    </ReadScreen>
  );
}

/** The check a teacher makes against their own class list (FR-CONSOLE-69): who is listed,
 * whose paper is in, and — by name — who has none yet. */
function ClassCheck({ data }: { data: PapersDoc }) {
  const summary = data.summary;
  if (summary === undefined) return null;
  return (
    <p className="hub-state" aria-label="Class check">
      {summary.with_paper} of {summary.listed} student{summary.listed === 1 ? "" : "s"} have a
      paper read.
      {summary.without_paper.length > 0
        ? ` No paper yet: ${summary.without_paper.join(", ")}.`
        : " Every student on the list has a paper."}
    </p>
  );
}

/** Every student with their paper, by name, and every paper with the two corrections it can
 * take: give it to the right student, or remove it so the right scan can be read. */
function SheetList({
  data,
  onMove,
  onRemove,
}: {
  data: PapersDoc;
  onMove: (sheet: PaperSheet, student: Student, shared: Set<string>) => void;
  onRemove: (sheet: PaperSheet, shared: Set<string>) => void;
}) {
  const shared = sharedNames(data.students);
  const sheets = data.sheets ?? [];
  const bySubmission = new Map(sheets.map((sheet) => [sheet.submission_id, sheet]));
  const students = [...data.students].sort((a, b) =>
    studentLabel(a, shared).localeCompare(studentLabel(b, shared), undefined, {
      sensitivity: "base",
    }));
  const withoutPaper = data.students.filter((student) => student.submission_id === null);
  const loose = sheets.filter(
    (sheet) => !data.students.some((student) => student.submission_id === sheet.submission_id),
  );
  return (
    <>
      <ul className="rows-list" aria-label="Students and their papers">
        {students.map((student) => {
          const sheet =
            student.submission_id === null ? undefined : bySubmission.get(student.submission_id);
          return (
            <li key={student.student_ref}>
              <span className="step-name">{studentLabel(student, shared)}</span>
              <span className="step-state">
                {sheet === undefined
                  ? "no paper yet"
                  : sheetStatusLabel(sheet.status, sheet.parked)}
              </span>
              {sheet !== undefined && (
                <SheetFixes
                  sheet={sheet}
                  shared={shared}
                  choices={withoutPaper}
                  onMove={onMove}
                  onRemove={onRemove}
                />
              )}
            </li>
          );
        })}
      </ul>
      {loose.length > 0 && (
        <details className="detail-expander" open>
          <summary>Papers not filed under a student ({loose.length})</summary>
          <ul className="rows-list">
            {loose.map((sheet) => (
              <li key={sheet.submission_id}>
                <span className="step-name">
                  {studentLabel(sheet, shared, "No student matched")}
                </span>
                <span className="step-state">{sheetStatusLabel(sheet.status, sheet.parked)}</span>
                {!sheet.graded && (
                  <button
                    type="button"
                    className="button button-small"
                    onClick={() => onRemove(sheet, shared)}
                  >
                    Remove this paper
                  </button>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

function SheetFixes({
  sheet,
  shared,
  choices,
  onMove,
  onRemove,
}: {
  sheet: PaperSheet;
  shared: Set<string>;
  choices: Student[];
  onMove: (sheet: PaperSheet, student: Student, shared: Set<string>) => void;
  onRemove: (sheet: PaperSheet, shared: Set<string>) => void;
}) {
  const [target, setTarget] = useState("");
  const selectId = `move-${sheet.submission_id}`;
  const chosen = choices.find((student) => student.student_ref === target);
  return (
    <span className="sheet-fixes">
      {sheet.matched === true && choices.length > 0 && (
        <>
          <label htmlFor={selectId}>Not theirs? Give the paper to</label>
          <select
            id={selectId}
            aria-describedby={formatIdFor(selectId)}
            value={target}
            onChange={(event) => setTarget(event.target.value)}
          >
            <option value="">Not theirs? Give it to…</option>
            {choices.map((student) => (
              <option key={student.student_ref} value={student.student_ref}>
                {studentLabel(student, shared)}
              </option>
            ))}
          </select>
          <FormatLine id={formatIdFor(selectId)} spec="Choose the student this paper belongs to" />
          <button
            type="button"
            className="button button-small"
            disabled={chosen === undefined}
            onClick={() => chosen !== undefined && onMove(sheet, chosen, shared)}
          >
            Move
          </button>
        </>
      )}
      {sheet.graded !== true && (
        <button type="button" className="button button-small" onClick={() => onRemove(sheet, shared)}>
          Remove paper
        </button>
      )}
    </span>
  );
}
