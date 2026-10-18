import { useEffect, useMemo, useRef, useState } from "react";
import { fetchJob, type ContextDoc, type JobRecord, type Papers as PapersDoc } from "../api";
import { ReadScreen } from "../components/ReadScreen";
import { Screen } from "../components/Screen";
import { useNavigate } from "../navigate";
import { ProgressBar, useToast } from "../state/StateDisplay";
import { useScreenRead } from "../useScreenRead";
import type { Selection } from "../wizard/derivation";

/**
 * The papers screen (FR-UI-03c, live-test blocker B4): the selected class's students, what
 * has been read for each, and the upload that reads more. The teacher picks the test paper
 * (once per class — every answer sheet is checked against it) and the answer sheets (one PDF
 * per student), sees the list before anything is sent, and confirms. Each file goes up on the
 * upload transport (`FR-CONSOLE-04`, the body is the file itself, never a URL) asking to be
 * read; the console reads it on its own worker with the same checks `aeh ingest` runs, and
 * this screen follows that work's job until it is done. A paper a check refuses is parked
 * for the operator — the Parked page is one link away.
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
    selection.classId === null ? null : "/api/v1/papers",
    selection.classId === null ? undefined : { cohort_id: selection.classId },
  );

  // The published test versions, the selected package's (or this class's last run's) first.
  const versions = useMemo(() => {
    const preferred = new Set<string>();
    const run = (context?.runs ?? []).find((r) => r.run_id === selection.runId);
    if (run !== undefined) preferred.add(run.package_version_id);
    const pkg = (context?.packages ?? []).find((p) => p.package_id === selection.packageId);
    if (pkg?.published_version) preferred.add(pkg.published_version);
    const all = (context?.packages ?? [])
      .map((p) => p.published_version)
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

  if (selection.classId === null) {
    return (
      <Screen title="Load papers">
        <p className="panel">
          Choose a class first —{" "}
          <a href="#/class" onClick={() => navigate("/class")}>
            set up a class
          </a>
          .
        </p>
      </Screen>
    );
  }
  const classId = selection.classId;

  const send = async (needsTestPaper: boolean): Promise<void> => {
    setConfirming(false);
    setProblem(null);
    const queue: { file: File; kind: "assessment" | "sheet" }[] = [];
    if (needsTestPaper && testPaper !== null) queue.push({ file: testPaper, kind: "assessment" });
    for (const file of sheets) queue.push({ file, kind: "sheet" });
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
          setProblem(`${file.name} was not accepted: ${answer.detail ?? "the upload failed."}`);
          break;
        }
        if (answer.job_id) setJobId(answer.job_id);
      } catch (failure: unknown) {
        setProblem(
          `${file.name} could not be sent (${failure instanceof Error ? failure.message : String(failure)}). Check that the console is still running.`,
        );
        break;
      }
    }
    setSending(null);
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
              {versions.length === 0 ? (
                <p>
                  No test is published yet —{" "}
                  <a href="#/package" onClick={() => navigate("/package")}>
                    set up the test
                  </a>{" "}
                  before reading papers.
                </p>
              ) : (
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
                      value={version}
                      onChange={(event) => setVersion(event.target.value)}
                    >
                      {versions.map((v) => (
                        <option key={v} value={v}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="settings-row">
                    <label htmlFor="papers-test">The test paper (PDF)</label>
                    {needsTestPaper ? (
                      <>
                        <input
                          id="papers-test"
                          ref={paperInput}
                          type="file"
                          accept="application/pdf,.pdf"
                          onChange={(event) => setTestPaper(event.target.files?.[0] ?? null)}
                        />
                        <p className="step-note">
                          Needed once for this class: every answer sheet is checked against it.
                        </p>
                      </>
                    ) : (
                      <span>Already in for this class.</span>
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
                      onChange={(event) => setSheets(Array.from(event.target.files ?? []))}
                    />
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
                    <button
                      type="submit"
                      className="button button-primary"
                      disabled={!canSend || busy}
                    >
                      {sending !== null ? `Sending ${sending}…` : "Read the papers"}
                    </button>
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
              <ul className="rows-list">
                {data.students.map((student) => (
                  <li key={student.student_ref}>
                    <span className="step-name">{student.full_name ?? student.student_ref}</span>
                    {student.full_name !== null && (
                      <span className="step-note">{student.student_ref}</span>
                    )}
                    <span className="step-state">
                      {student.submission_id === null ? "no paper yet" : "paper read"}
                    </span>
                  </li>
                ))}
              </ul>
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
              {readySheets.length > 0 && (
                <details className="detail-expander">
                  <summary>Every sheet read so far ({readySheets.length})</summary>
                  <ul className="rows-list">
                    {readySheets.map((sheet) => (
                      <li key={sheet.submission_id}>
                        <span className="step-name">{sheet.student_ref ?? "no name found"}</span>
                        <span className="step-state">
                          {sheetStatusLabel(sheet.status, sheet.parked)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              <p className="step-note">
                {data.parts.length === 0
                  ? "No scans uploaded yet."
                  : `Uploaded files: ${data.parts.join(", ")}.`}
              </p>
            </section>

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
                      void send(needsTestPaper);
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
