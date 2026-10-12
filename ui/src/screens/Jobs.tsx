import { useEffect, useState } from "react";
import {
  CircleCheck,
  CircleDot,
  CircleHelp,
  CirclePause,
  CircleX,
} from "lucide-react";
import { fetchJob, type JobDetailDoc, type JobRecord, type JobsDoc } from "../api";
import { ActionOutcome, ConfirmDialog, useActionState } from "../components/Confirm";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";
import {
  durationLabel,
  jobCostLabel,
  jobKindLabel,
  jobStateLabel,
  jobTone,
} from "../wizard/vocabulary";

/**
 * The jobs page (FR-UI-19): every job as the jobs read holds it — what it is, its state,
 * its progress in the server's own counts ("12 of 40", never a percentage, never a
 * per-student figure — CT-CONSOLE-09, RS-05), how long it has run and what it has cost.
 * A job's row opens into its measured statistics (the one job's read), and a grading run
 * offers the pause and resume controls behind their confirmations (CT-UI-09). The jobs
 * read mirrors a paused run as `running`, so which runs are paused comes from the context
 * read's own run states, threaded in from the shell — the row never guesses. A state the
 * console does not know renders as the neutral wording (CT-CONSOLE-38).
 */

function JobStateBadge({ state }: { state: string }) {
  const tone = jobTone(state);
  const Glyph =
    tone === "success" ? CircleCheck
    : tone === "info" ? CircleDot
    : tone === "danger" ? CircleX
    : tone === "warning" ? CirclePause
    : CircleHelp;
  return (
    <span className={`badge badge-${tone}`}>
      <Glyph size={14} aria-hidden="true" />
      <span>{jobStateLabel(state)}</span>
    </span>
  );
}

function elapsedLabel(job: JobRecord, now: number): string {
  const started = job.started_at === null ? NaN : Date.parse(job.started_at);
  if (Number.isNaN(started)) {
    return "—";
  }
  const finished = job.finished_at === null ? NaN : Date.parse(job.finished_at);
  const end = Number.isNaN(finished) ? now : finished;
  return durationLabel((end - started) / 1000);
}

function progressLabel(job: JobRecord): string {
  const { done, total, current } = job.progress;
  if (done !== null && total !== null) {
    return `${done} of ${total}`;
  }
  if (current !== null) {
    return current;
  }
  return "—";
}

/** One row's opened body: the one job's read, fetched on demand — a statistic is shown
 * only under the read's own key (CT-UI-08), and a failed read is a named line. */
function JobDetail({ jobId }: { jobId: string }) {
  const [detail, setDetail] = useState<JobDetailDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setError(null);
    fetchJob(jobId, controller.signal).then(
      (answer) => {
        if (!controller.signal.aborted) setDetail(answer);
      },
      (failure: unknown) => {
        if (!controller.signal.aborted) {
          setError(failure instanceof Error ? failure.message : String(failure));
        }
      },
    );
    return () => controller.abort();
  }, [jobId, attempt]);

  if (error !== null) {
    return (
      <p role="alert" className="job-detail-line">
        The console could not read this job's details ({error}).{" "}
        <button type="button" className="button" onClick={() => setAttempt(attempt + 1)}>
          Try again
        </button>
      </p>
    );
  }
  if (detail === null) {
    return <p className="job-detail-line">Reading.</p>;
  }
  const statistics = detail.statistics;
  return (
    <div className="job-detail">
      <p className="job-detail-line">
        Time taken: {durationLabel(statistics.duration_seconds)}.
      </p>
      {statistics.items_graded !== null && (
        <p className="job-detail-line">
          Papers with a grade: {statistics.items_graded}.
        </p>
      )}
      {detail.error.detail !== null && (
        <p className="job-detail-line">
          What went wrong: {detail.error.detail}
          {detail.error.next_action !== null ? ` — ${detail.error.next_action}` : ""}.
        </p>
      )}
    </div>
  );
}

function JobRow({
  job,
  now,
  paused,
  onPause,
  onResume,
}: {
  job: JobRecord;
  now: number;
  paused: boolean;
  onPause: (job: JobRecord) => void;
  onResume: (job: JobRecord) => void;
}) {
  const [open, setOpen] = useState(false);
  // The jobs read mirrors a paused run's job as `running`, so the row's own state cannot
  // tell pause from go — the context read's run state can, and it arrives as `paused`.
  const canPause = job.kind === "run" && job.state === "running" && !paused;
  const canResume = job.kind === "run" && paused;
  return (
    <>
      <tr className="job-row">
        <th scope="row">{jobKindLabel(job.kind)}</th>
        <td>
          <JobStateBadge state={job.state} />
        </td>
        <td>{progressLabel(job)}</td>
        <td>{elapsedLabel(job, now)}</td>
        <td>{jobCostLabel(job.cost_usd)}</td>
        <td className="job-row-actions">
          {canPause && (
            <button type="button" className="button" onClick={() => onPause(job)}>
              Pause the run
            </button>
          )}
          {canResume && (
            <button type="button" className="button" onClick={() => onResume(job)}>
              Resume the run
            </button>
          )}
          <button
            type="button"
            className="button"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            {job.state === "failed" && !open ? "What went wrong" : open ? "Hide details" : "Details"}
          </button>
        </td>
      </tr>
      {open && (
        <tr className="job-detail-row">
          <td colSpan={6}>
            <JobDetail jobId={job.job_id} />
          </td>
        </tr>
      )}
    </>
  );
}

/** The run ids the context read says are paused — the one state the jobs read cannot
 * carry, since it mirrors a paused run's job as `running`. */
export function Jobs({ pausedRunIds }: { pausedRunIds: string[] }) {
  // The table re-reads on the shell's cadence; `now` marks the render so a running job's
  // elapsed time advances with each poll without its own timer.
  const [now, setNow] = useState(() => Date.now());
  const read = useScreenRead<JobsDoc>("/api/v1/jobs", undefined, 3000);
  useEffect(() => {
    if (read.data !== null) {
      setNow(Date.now());
    }
  }, [read.data]);
  const action = useActionState(read.retry);

  const openPause = (job: JobRecord): void => {
    action.open({
      title: "Pause this run",
      description:
        "The console will pause the grading run as soon as the grading point it is on " +
        "finishes. Nothing is lost; while it is paused, this page's row offers Resume.",
      confirm: "Pause",
      action: "pause/resume",
      body: { run_id: job.job_id, state: "paused" },
    });
  };

  const openResume = (job: JobRecord): void => {
    action.open({
      title: "Resume this run",
      description:
        "The console will let the grading run continue from the grading point it paused on.",
      confirm: "Resume",
      action: "pause/resume",
      body: { run_id: job.job_id, state: "running" },
    });
  };

  return (
    <ReadScreen title="Jobs" read={read}>
      {(data) => (
        <>
          <ActionOutcome outcome={action.outcome} />
          {data.jobs.length === 0 ? (
            <p>No jobs have run yet.</p>
          ) : (
            <table className="results jobs-table">
              <caption className="visually-hidden">The console's jobs</caption>
              <thead>
                <tr>
                  <th scope="col">What</th>
                  <th scope="col">State</th>
                  <th scope="col">Progress</th>
                  <th scope="col">Elapsed</th>
                  <th scope="col">Cost, US dollars</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.jobs.map((job) => (
                  <JobRow
                    key={job.job_id}
                    job={job}
                    now={now}
                    paused={pausedRunIds.includes(job.job_id)}
                    onPause={openPause}
                    onResume={openResume}
                  />
                ))}
              </tbody>
            </table>
          )}
          {action.pending !== null && (
            <ConfirmDialog pending={action.pending} onClose={action.close} onDone={action.finish} />
          )}
        </>
      )}
    </ReadScreen>
  );
}
