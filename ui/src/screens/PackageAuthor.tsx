import { useEffect, useState } from "react";
import {
  fetchAuthoringDraft,
  fetchJob,
  fetchJobs,
  performAction,
  previewDocuments,
  type ActionResult,
  type AuthoringDraftDoc,
  type DraftPlaceholder,
  type JobRecord,
  type PreviewDocument,
} from "../api";
import { ActionOutcome, ConfirmDialog, useActionState } from "../components/Confirm";
import { Screen } from "../components/Screen";
import { useNavigate } from "../navigate";
import { durationLabel, missingPiecesLabel, placeholderLocationLabel } from "../wizard/vocabulary";

/**
 * The authoring screen (FR-UI-11): the teacher's documents go in here, the preview says
 * what the console understood before anything is written, and making the draft runs as a
 * job whose progress, tries and cancel stay on this page (ADR-47's poll cadence). The
 * document bytes themselves travel only inside the one POST read's body and the action's
 * body — never in a URL or a query string (`CT-CONSOLE-34`) — and nothing about them is
 * kept in the browser across a reload (`CT-UI-07`): a reload mid-drafting re-attaches to
 * the job the server still owns.
 */

type Phase = "loading" | "upload" | "drafting" | "report";

/** One picked file, from the picker or a drop, as this session holds it. `reading` and
 * `ready` are both "Reading" on the screen: the bytes are in flight, or they are read
 * and the preview has not answered yet — a file says Understood only once the preview
 * read it (FR-UI-11's per-file status). */
interface PickedFile {
  key: string;
  name: string;
  size: number;
  /** The file's content, base64 — read client-side, sent only in a request body. */
  base64: string | null;
  status: "reading" | "ready" | "understood" | "refused";
  refusal: { detail: string; next_action: string } | null;
}

/** The draft read's own refusal wording for an over-ceiling file (`CT-CONSOLE-36`), with
 * the limit formatted the way the server formats it — the same sentence, not a copy of
 * the number in the bundle. */
function sizeRefusal(ceilingBytes: number): { detail: string; next_action: string } {
  const mb = ceilingBytes / (1024 * 1024);
  return {
    detail: `That file is larger than the ${String(Number(mb.toFixed(2)))} MB limit for one document.`,
    next_action: "Split the document or export fewer pages, then upload it again.",
  };
}

/** One file's per-file status line: Reading while its bytes or its preview are in
 * flight, Understood once the preview read it, Refused with its reason and next step
 * (`CT-CONSOLE-33`) — a refused file never touches the others. */
function FileStatus({ file }: { file: PickedFile }) {
  if (file.status === "refused" && file.refusal !== null) {
    return (
      <span className="upload-state upload-state-refused">
        Refused — {file.refusal.detail} {file.refusal.next_action}
      </span>
    );
  }
  if (file.status === "understood") {
    return <span className="upload-state upload-state-ok">Understood</span>;
  }
  return <span className="upload-state upload-state-reading">Reading…</span>;
}

/** The accepted file's preview outline ("what we understood"): its pages and text blocks
 * in page order, the counts beside them, and every warning the read carried — a page
 * with no text layer is named, never silently dropped (`CT-UI-08`). */
function PreviewOutline({ document: doc }: { document: PreviewDocument }) {
  return (
    <div className="preview-file">
      <h3>{doc.name}</h3>
      <p className="preview-counts">
        {doc.stats?.page_count ?? 0} page(s), {doc.stats?.block_count ?? 0} text blocks,{" "}
        {doc.stats?.word_count ?? 0} words, {doc.stats?.table_count ?? 0} tables,{" "}
        {doc.stats?.image_count ?? 0} pictures.
      </p>
      {(doc.warnings ?? []).map((warning, index) => (
        <p key={index} className="preview-warning">
          {warning.message}
        </p>
      ))}
      {(doc.blocks ?? []).length > 0 && (
        <ol className="preview-blocks">
          {(doc.blocks ?? []).map((block) => (
            <li key={block.ordinal}>
              <span className="preview-page">Page {block.page}</span> {block.text}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** The drafting view (FR-UI-11's progress job): the stage, the done/total counts, the
 * tries on the current item, the elapsed time and the cancel control — all from the one
 * job's read, polled on the shell's cadence. Nothing is invented while a count is not
 * known yet (`CT-UI-08`). */
function DraftingView({
  job,
  now,
  onCancel,
  onRestart,
}: {
  job: JobRecord;
  now: number;
  onCancel: () => void;
  onRestart: () => void;
}) {
  const stage = job.stage ?? null;
  const { done, total, current } = job.progress;
  const started = job.started_at === null ? NaN : Date.parse(job.started_at);
  const finished = job.finished_at === null ? NaN : Date.parse(job.finished_at);
  const end = Number.isNaN(finished) ? now : finished;
  return (
    <section aria-label="Drafting progress" className="drafting-progress">
      <h2>Drafting the test</h2>
      {job.state === "failed" ? (
        <>
          <p role="alert" className="screen-alert">
            The draft stopped: {job.error.detail ?? "the console gave no reason."}
            {job.error.next_action !== null ? ` ${job.error.next_action}` : ""}
          </p>
          <button type="button" className="button" onClick={onRestart}>
            Start again from your files
          </button>
        </>
      ) : (
        <>
          <p className="drafting-line">
            {stage === null ? "" : `${stage.charAt(0).toUpperCase()}${stage.slice(1)} — `}
            {done !== null && total !== null ? `${done} of ${total}` : current ?? "Working"}
            {job.attempt !== null && job.attempt !== undefined &&
              job.attempts !== null && job.attempts !== undefined && (
                <> — attempt {job.attempt} of {job.attempts}</>
              )}
            {" — "}
            {Number.isNaN(started) ? "—" : durationLabel((end - started) / 1000)} so far.
          </p>
          <button type="button" className="button" onClick={onCancel}>
            Stop the draft
          </button>
        </>
      )}
    </section>
  );
}

/** The report view: the draft's own sections, from the draft read — what was found, the
 * missing pieces marked in it, and one primary action on to the review screen. A count
 * is never invented (`CT-UI-08`): everything here is the read's own figure. */
function ReportView({
  draft,
  onContinue,
  warnings,
}: {
  draft: NonNullable<AuthoringDraftDoc["draft"]>;
  onContinue: () => void;
  warnings: string[];
}) {
  return (
    <section aria-label="What we understood" className="report-view">
      <h2>What we understood</h2>
      {warnings.length > 0 && (
        <div className="report-warnings">
          <h3>Things we noticed while reading</h3>
          {warnings.map((warning, index) => (
            <p key={index} className="preview-warning">
              {warning}
            </p>
          ))}
        </div>
      )}
      <h3>What the draft carries</h3>
      <p>
        {draft.items.length} question(s) and {draft.criteria.length} grading point(s)
        {typeof draft.grades === "object" && draft.grades !== null
          ? ", and the grade table"
          : "" /* a placeholder stands where the table would be — not claimed as a table */}.
      </p>
      <h3>Missing pieces</h3>
      {draft.missing_pieces === 0 ? (
        <p>None — the draft is ready to review and approve.</p>
      ) : (
        <>
          <p>
            {missingPiecesLabel(draft.missing_pieces)}, marked in the draft. Each one is
            a spot the console could not read on its own; the review screen asks you
            about them one at a time.
          </p>
          <ul className="placeholder-list">
            {draft.placeholders.map((placeholder: DraftPlaceholder) => (
              <li key={placeholder.location}>
                {placeholderLocationLabel(placeholder.location, draft.items)}
                {placeholder.reason ? ` — ${placeholder.reason}` : ""}
              </li>
            ))}
          </ul>
        </>
      )}
      <button type="button" className="button button-primary" onClick={onContinue}>
        Continue to review
      </button>
    </section>
  );
}

export function PackageAuthor({ packageId }: { packageId: string | null }) {
  const navigate = useNavigate();
  const action = useActionState();

  const [phase, setPhase] = useState<Phase>("loading");
  const [ceiling, setCeiling] = useState<number | null>(null);
  const [existing, setExisting] = useState<AuthoringDraftDoc["draft"]>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [files, setFiles] = useState<PickedFile[]>([]);
  const [preview, setPreview] = useState<PreviewDocument[] | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [scratchTitle, setScratchTitle] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [mounted, setMounted] = useState(0);
  const [loadFailed, setLoadFailed] = useState(false);

  // First load: the draft read answers the upload ceiling (`CT-CONSOLE-36`) and whether a
  // draft already stands; the jobs read says whether a draft job of this console is still
  // on the wire, so a reload mid-drafting re-attaches to the server's job rather than
  // restarting from the browser's memory (`CT-UI-07`: the browser owns nothing).
  useEffect(() => {
    const controller = new AbortController();
    let alive = true;
    Promise.all([
      fetchAuthoringDraft(controller.signal, packageId),
      fetchJobs(controller.signal),
    ]).then(
      ([draftDoc, jobsDoc]) => {
        if (!alive || controller.signal.aborted) return;
        setLoadFailed(false);
        setCeiling(draftDoc.doc_max_bytes);
        setExisting(draftDoc.draft);
        const authoring = jobsDoc.jobs.filter((entry) =>
          entry.kind === "authoring_draft" || entry.kind.startsWith("authoring"),
        );
        const running = authoring.find(
          (entry) => entry.state === "queued" || entry.state === "running",
        );
        if (running !== undefined) {
          setJobId(running.job_id);
          setJob(running);
          setPhase("drafting");
          return;
        }
        if (draftDoc.draft !== null &&
            authoring.some((entry) => entry.state === "succeeded")) {
          setPhase("report");
          return;
        }
        setPhase("upload");
      },
      (failure: unknown) => {
        if (!alive || controller.signal.aborted) return;
        // A failed first read is the named refusal with the retry, like every screen.
        action.finish({
          action: "read",
          error: `the console could not read this screen (${
            failure instanceof Error ? failure.message : String(failure)
          }); check that the console service is running.`,
        });
        setLoadFailed(true);
        setPhase("upload");
      },
    );
    return () => {
      alive = false;
      controller.abort();
    };
    // The retry re-runs the whole first load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [packageId, mounted]);

  // The drafting job's poll (`ADR-47`): the one job's read every three seconds, until the
  // job leaves the wire.
  useEffect(() => {
    if (phase !== "drafting" || jobId === null) {
      return;
    }
    const controller = new AbortController();
    let stopped = false;
    let timer: number | undefined;
    const poll = (): void => {
      fetchJob(jobId, controller.signal).then(
        (detail) => {
          if (controller.signal.aborted) return;
          setJob(detail);
          setNow(Date.now());
          if (detail.state === "succeeded" || detail.state === "cancelled" ||
              detail.state === "failed") {
            stopped = true;
            if (detail.state === "succeeded") {
              // The draft stands: re-read it, then show the report's sections.
              fetchAuthoringDraft(controller.signal, packageId).then(
                (draftDoc) => {
                  if (controller.signal.aborted) return;
                  setExisting(draftDoc.draft);
                  setPhase("report");
                },
                () => setPhase("upload"),
              );
            } else if (detail.state === "failed") {
              setPhase("drafting"); // the failed view renders from the job record
            } else {
              setPhase("upload");
            }
            return;
          }
          timer = window.setTimeout(poll, 3000);
        },
        () => {
          if (!controller.signal.aborted && !stopped) {
            timer = window.setTimeout(poll, 3000);
          }
        },
      );
    };
    poll();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
      controller.abort();
    };
  }, [phase, jobId, packageId]);

  const accept = (list: FileList | null): void => {
    if (list === null) return;
    const next: PickedFile[] = [];
    let index = 0;
    for (const file of Array.from(list)) {
      const key = `${file.name}-${file.size}-${file.lastModified}-${index}`;
      index += 1;
      const entry: PickedFile = {
        key, name: file.name, size: file.size, base64: null,
        status: "reading", refusal: null,
      };
      if (ceiling !== null && file.size > ceiling) {
        entry.status = "refused";
        entry.refusal = sizeRefusal(ceiling);
      } else if (file.size === 0) {
        entry.status = "refused";
        entry.refusal = {
          detail: "That file is empty.",
          next_action: "Upload the file again.",
        };
      } else {
        const reader = new FileReader();
        reader.onload = () => {
          const result = typeof reader.result === "string" ? reader.result : "";
          const base64 = result.slice(result.indexOf(",") + 1);
          // The bytes are in: the file stays "Reading" until the preview answers.
          setFiles((current) => current.map((item) =>
            item.key === key ? { ...item, base64, status: "ready" } : item));
        };
        reader.onerror = () => {
          setFiles((current) => current.map((item) =>
            item.key === key
              ? {
                  ...item, status: "refused",
                  refusal: {
                    detail: "That file could not be read from your computer.",
                    next_action: "Check the file opens on your computer, then upload it again.",
                  },
                }
              : item));
        };
        reader.readAsDataURL(file);
      }
      next.push(entry);
    }
    setFiles((current) => [...current, ...next]);
    setPreview(null);
    setPreviewError(null);
  };

  const removeFile = (key: string): void => {
    setFiles((current) => current.filter((item) => item.key !== key));
    setPreview(null);
    setPreviewError(null);
  };

  const runPreview = (): void => {
    const ready = files.filter(
      (file) => file.base64 !== null && file.status !== "refused",
    );
    setPreviewBusy(true);
    setPreviewError(null);
    previewDocuments(
      ready.map((file) => ({ name: file.name, content_base64: file.base64 ?? "" })),
    ).then(
      (answer) => {
        setPreviewBusy(false);
        setPreview(answer.documents);
        // The per-file statuses follow the preview: a file the read took is Understood,
        // one it refused carries the read's own reason and next step. The answers come
        // back in the order the request named the files, so they bind by position —
        // two files that happen to share a name must never share one answer.
        setFiles((current) => current.map((file) => {
          const sentIndex = ready.findIndex((sent) => sent.key === file.key);
          if (file.status === "refused" || sentIndex === -1) {
            return file;
          }
          const answered = answer.documents[sentIndex];
          if (answered === undefined) {
            return file;
          }
          return answered.accepted
            ? { ...file, status: "understood" }
            : { ...file, status: "refused", refusal: answered.refusal ?? null };
        }));
      },
      (failure: unknown) => {
        setPreviewBusy(false);
        setPreviewError(failure instanceof Error ? failure.message : String(failure));
      },
    );
  };

  const startDraft = (): void => {
    const ready = files.filter(
      (file) => file.base64 !== null &&
        (file.status === "ready" || file.status === "understood"),
    );
    const replace = existing !== null;
    action.open({
      title: replace ? "Make the draft again" : "Make the draft",
      description:
        `The console will read your ${ready.length} file(s) and write a first draft of ` +
        "the test package. This can take a few minutes; you can stop it while it runs." +
        (replace
          ? " Your files are read again and the draft is written from the start; " +
            "answers you already gave are kept where the content still matches, and " +
            "you will be asked to confirm the kept ones."
          : ""),
      confirm: replace ? "Make the draft again" : "Make the draft",
      action: "draft package from documents",
      body: {
        documents: ready.map((file) => ({
          name: file.name, content_base64: file.base64,
        })),
        ...(replace ? { replace: true } : {}),
      },
    });
  };

  const startFromScratch = (): void => {
    action.open({
      title: "Start an empty draft",
      description:
        "The console will write an empty draft named from the title you typed — no " +
        "questions and no grading points yet. The editor is where you add them.",
      confirm: "Start the empty draft",
      action: "draft package from scratch",
      body: { title: scratchTitle },
    });
  };

  const cancelDraft = (): void => {
    if (jobId === null) return;
    action.open({
      title: "Stop this draft",
      description:
        "The draft stops at its next step. The files it has written stay exactly as " +
        "the last completed step left them.",
      confirm: "Stop the draft",
      action: "cancel job",
      body: { job_id: jobId },
    });
  };

  // A confirmed action's aftermath: a dispatched draft job moves the screen to its
  // progress view; a dispatched from-scratch start moves on to the editor.
  const afterAction = (result: ActionResult): void => {
    if (result.refused === true || result.error !== undefined) {
      return;
    }
    if (typeof result.job_id === "string" && result.job_id !== "") {
      setJobId(result.job_id);
      setJob(null);
      setPhase("drafting");
      return;
    }
    if (result.dispatched === true && result.action === "draft package from scratch") {
      navigate("/package/edit");
    }
  };

  if (phase === "loading") {
    return (
      <Screen title="Author the package">
        <p>Reading.</p>
      </Screen>
    );
  }

  const acceptedFiles = files.filter(
    (file) => file.base64 !== null &&
      (file.status === "ready" || file.status === "understood"),
  );
  const refusedFiles = files.filter((file) => file.status === "refused");
  const readingFiles = files.filter((file) => file.status === "reading");
  // The report's "things we noticed while reading" is the preview's own warnings when
  // this session ran one; after a reload straight into the report the session holds no
  // reading, so the section stands down rather than claiming either way.
  const reportWarnings = (preview ?? [])
    .filter((doc) => doc.accepted)
    .flatMap((doc) => (doc.warnings ?? []).map((warning) => warning.message));

  return (
    <Screen title="Author the package">
      <ActionOutcome outcome={action.outcome} />
      {phase === "drafting" && job !== null && (
        <>
          <DraftingView
            job={job}
            now={now}
            onCancel={cancelDraft}
            onRestart={() => setPhase("upload")}
          />
          {action.pending !== null && (
            <ConfirmDialog
              pending={action.pending}
              onClose={action.close}
              onDone={(result) => {
                action.finish(result);
              }}
            />
          )}
        </>
      )}
      {phase === "drafting" && job === null && <p>Reading.</p>}
      {phase === "report" && existing !== null && (
        <ReportView
          draft={existing}
          warnings={reportWarnings}
          onContinue={() => navigate("/package/review")}
        />
      )}
      {phase === "upload" && (
        <>
          {loadFailed && (
            <p>
              The screen could not read the draft's state, so the upload limit is not
              known yet.{" "}
              <button
                type="button"
                className="button"
                onClick={() => {
                  setLoadFailed(false);
                  setMounted((value) => value + 1);
                }}
              >
                Try again
              </button>
            </p>
          )}
          {existing !== null && (
            <section aria-label="An existing draft" className="editor-note">
              <p>
                A draft already stands. You can look at it on the review screen, or make
                it again from your documents — the answers you already gave are kept
                where the content still matches.
              </p>
              <button
                type="button"
                className="button"
                onClick={() => navigate("/package/review")}
              >
                Open the review
              </button>
            </section>
          )}
          <section aria-label="Upload documents" className="upload-section">
            <h2>Your documents</h2>
            <div
              className={dragOver ? "dropzone dropzone-active" : "dropzone"}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragOver(false);
                accept(event.dataTransfer.files);
              }}
            >
              <p>Drag your test files here, or choose them below.</p>
              <label>
                <input
                  type="file"
                  multiple
                  accept=".docx,.txt,.pdf"
                  aria-label="Choose files to upload"
                  onChange={(event) => {
                    accept(event.target.files);
                    event.target.value = "";
                  }}
                />
              </label>
            </div>
            {files.length > 0 && (
              <ul className="upload-list">
                {files.map((file) => (
                  <li key={file.key} className="upload-file">
                    <span className="upload-name">{file.name}</span>{" "}
                    <FileStatus file={file} />{" "}
                    <button
                      type="button"
                      className="button"
                      onClick={() => removeFile(file.key)}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {refusedFiles.length > 0 && (
              <p className="preview-warning">
                The refused files above are left out; the rest are unaffected. Remove a
                refused file, fix what its next step names, and upload it again.
              </p>
            )}
            <p>
              <button
                type="button"
                className="button"
                disabled={readingFiles.length > 0 || acceptedFiles.length === 0 ||
                  previewBusy}
                onClick={runPreview}
              >
                {previewBusy ? "Reading…" : "Show what we understood"}
              </button>{" "}
              <button
                type="button"
                className="button button-primary"
                disabled={readingFiles.length > 0 || acceptedFiles.length === 0 ||
                  previewBusy}
                onClick={startDraft}
              >
                {existing !== null ? "Make the draft again" : "Make the draft"}
              </button>
            </p>
            {previewError !== null && (
              <p role="alert" className="screen-alert">
                The preview could not run ({previewError}). Check that the console
                service is running.
              </p>
            )}
          </section>
          {preview !== null && (
            <section aria-label="What we understood" className="preview-section">
              <h2>What we understood</h2>
              <p>
                {preview.filter((doc) => doc.accepted).length} file(s) read,{" "}
                {preview.filter((doc) => !doc.accepted).length} refused.
              </p>
              {preview.filter((doc) => doc.accepted).map((doc) => (
                <PreviewOutline key={doc.name} document={doc} />
              ))}
            </section>
          )}
          <section aria-label="Start from an empty draft" className="scratch-section">
            <h2>Or start from an empty draft</h2>
            <p>
              No documents needed: you write every question and grading point yourself in
              the editor.
            </p>
            <label htmlFor="scratch-title">The package's name</label>{" "}
            <input
              id="scratch-title"
              type="text"
              value={scratchTitle}
              onChange={(event) => setScratchTitle(event.target.value)}
            />{" "}
            <button
              type="button"
              className="button"
              disabled={scratchTitle.trim() === ""}
              onClick={startFromScratch}
            >
              Start the empty draft
            </button>
          </section>
          {action.pending !== null && (
            <ConfirmDialog
              pending={action.pending}
              onClose={action.close}
              onDone={(result) => {
                action.finish(result);
                afterAction(result);
              }}
            />
          )}
        </>
      )}
    </Screen>
  );
}
