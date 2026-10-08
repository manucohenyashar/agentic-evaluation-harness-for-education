import { fetchRead, type RunStartState as RunStartDoc } from "../api";
import { ActionOutcome, ConfirmDialog, useActionState } from "../components/Confirm";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";

/**
 * The run-start screen (FR-UI-03d): what would start — the cohort, the package version and
 * the run's state — beside the start control. Starting is the console's "start run" control
 * behind its confirmation (FR-UI-05); a run already composed restarts under its own frozen
 * configuration (FR-CONF-15), which is what the confirmation posts: the run's id, no
 * profile of its own.
 */
export function RunStart() {
  const read = useScreenRead<RunStartDoc>("/api/v1/run-start-state");
  const action = useActionState(read.retry);

  const openStart = async (): Promise<void> => {
    if (read.data === null || read.data.run_id === null) {
      return;
    }
    // The confirmation's content is the API's (FR-CONSOLE-43): the preview read priced on
    // the run's own frozen configuration — the banner the started run would show and the
    // estimate behind the confirmation. A refused preview opens the dialog as the named
    // refusal with the confirm withheld; nothing composes today's environment over the run.
    try {
      const preview = await fetchRead<{ banner: string; estimate: string | null }>(
        "/api/v1/run-start-preview", undefined, { run_id: read.data.run_id });
      action.open({
        title: "Start this run",
        description: preview.banner + (preview.estimate ? `\n${preview.estimate}` : ""),
        confirm: "Start",
        action: "start run",
        body: { run_id: read.data.run_id },
      });
    } catch (failure: unknown) {
      action.open({
        title: "Start this run",
        description: `The console could not read the run's preview (${failure instanceof Error ? failure.message : String(failure)}). Check that the console service is running.`,
        confirm: "Start",
        action: "start run",
        body: { run_id: read.data.run_id },
      });
    }
  };

  return (
    <ReadScreen title="Start a run" read={read}>
      {(data) => (
        <>
          <p className="hub-state">
            {data.run_id === null
              ? "The console serves no run: there is nothing to start here."
              : `Run ${data.run_id} — cohort ${data.cohort_id}, package version ` +
                `${data.package_version_id}, currently ${data.status ?? "unknown"}.`}
          </p>
          <ActionOutcome outcome={action.outcome} />
          <button
            type="button"
            className="button button-primary"
            onClick={() => { void openStart(); }}
            disabled={data.run_id === null}
          >
            Start the run
          </button>
          {action.pending !== null && (
            <ConfirmDialog pending={action.pending} onClose={action.close} onDone={action.finish} />
          )}
        </>
      )}
    </ReadScreen>
  );
}
