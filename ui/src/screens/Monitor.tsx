import { type MonitorState as MonitorDoc } from "../api";
import { BLIND_SAMPLE_ROUTE } from "../components/HeldBack";
import { BusyButton, useReportedAction } from "../components/Outcome";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { entityStateLabel } from "../wizard/vocabulary";
import { useScreenRead } from "../useScreenRead";
import { useRunParams } from "../selection";

/**
 * The monitor screen (FR-UI-03e): the run's status and pause reason beside M-ORCH's own
 * progress report. It is a live screen: the read is re-run on a poll, so grading that
 * proceeds under an open console shows without a reload. The cadence stays well above the
 * browser's network-idle threshold, so a poll never wedges a navigation wait.
 */
const POLL_MS = 2000;

const PROGRESS_FIELDS: readonly string[] = [
  "done",
  "in_flight",
  "pending",
  "quarantined",
  "escalation_rate_so_far",
  "estimated_completion",
];

function progressLine(progress: Record<string, unknown>): string {
  const facts = PROGRESS_FIELDS.map((field) => {
    const value = progress[field];
    if (value === undefined || value === null || value === "") {
      return null;
    }
    const label = field.replace(/_/g, " ");
    return `${label}: ${String(value)}`;
  }).filter((fact): fact is string => fact !== null);
  return facts.join(", ");
}

/** FR-UI-39's sentence: the sample offered first, with its size and time. */
export function blindFirstSentence(count: number | null | undefined, minutes: number | undefined): string {
  const answers = count === null || count === undefined ? "a few" : String(count);
  const time = minutes === undefined ? "" : ` (about ${minutes} min)`;
  return (
    `Marking finished. Mark ${answers} answers yourself first, without seeing the system's ` +
    `marks${time}, or skip and see the results.`
  );
}

/**
 * The completion banner (FR-UI-39, ADR-58): once the run finishes and its blind sample is
 * open, the sample comes first — **Mark the sample** — with the results as the other,
 * equally available way on: **Skip and see results** skips the sample, then opens Results.
 */
function BlindFirstBanner({ data }: { data: MonitorDoc }) {
  const navigate = useNavigate();
  const { busy, run } = useReportedAction();
  return (
    <div
      className="outcome-banner outcome-done blind-first-banner"
      role="region"
      aria-label="Marking finished"
    >
      <p className="action-outcome">
        <strong className="outcome-what">
          {blindFirstSentence(data.blind_count, data.blind_minutes)}
        </strong>{" "}
        <button
          type="button"
          className="button button-primary"
          onClick={() => navigate(BLIND_SAMPLE_ROUTE)}
        >
          Mark the sample
        </button>{" "}
        <BusyButton
          className="button"
          busy={busy}
          onClick={() => {
            void run("blind-sample skip", { run_id: data.run_id }, {
              onDone: () => navigate("/results"),
            });
          }}
        >
          Skip and see results
        </BusyButton>
      </p>
    </div>
  );
}

export function Monitor() {
  const read = useScreenRead<MonitorDoc>("/api/v1/monitor", useRunParams(), POLL_MS);
  return (
    <ReadScreen title="Monitor run" read={read}>
      {(data) => (
        <>
          {data.status === "complete" && data.blind_sample === "open" && (
            <BlindFirstBanner data={data} />
          )}
          <p className="hub-state">
            {data.run_id === null
              ? "The console serves no run."
              : `The grading run — ${(data.status ? entityStateLabel(data.status) : "Not known yet")}` +
                (data.pause_reason ? ` (paused: ${data.pause_reason})` : "") +
                "."}
          </p>
          {data.progress !== null && (
            <section className="panel">
              <h2>Progress</h2>
              <p>{progressLine(data.progress)}</p>
            </section>
          )}
        </>
      )}
    </ReadScreen>
  );
}
