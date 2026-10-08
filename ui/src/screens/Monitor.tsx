import { fetchRead, type MonitorState as MonitorDoc } from "../api";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";

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

export function Monitor() {
  const read = useScreenRead<MonitorDoc>("/api/v1/monitor", undefined, POLL_MS);
  return (
    <ReadScreen title="Monitor run" read={read}>
      {(data) => (
        <>
          <p className="hub-state">
            {data.run_id === null
              ? "The console serves no run."
              : `Run ${data.run_id} — ${data.status ?? "unknown"}` +
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
