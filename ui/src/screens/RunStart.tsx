import { useEffect, useMemo, useState } from "react";
import { fetchRead, type ContextDoc, type RunStartState as RunStartDoc } from "../api";
import { ActionOutcome, ConfirmDialog, useActionState } from "../components/Confirm";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useScreenRead } from "../useScreenRead";
import { newestRunFirst, type Selection } from "../wizard/derivation";

/**
 * The run-start screen (FR-UI-03d): what would start — the class, the test version and the
 * run's state — beside the start control. Starting is the console's "start run" control
 * behind its confirmation (FR-UI-05), and the confirmation's content is the priced preview
 * read (FR-CONSOLE-43). Two starts are offered:
 *
 * - a **new grading run** for the selected class against a published test version — the
 *   preview and the start both name the class and the version, under the console's own
 *   profile; this is what a fresh data folder needs, where no run exists yet;
 * - a **waiting run** (still pending) restarts under its own frozen configuration
 *   (FR-CONF-15): the run's id, no profile of its own.
 */
/** The preview's estimate in the teacher's words: the orchestrator's own figure, rounded to
 * the cent, or a plain statement that none could be made (never an invented zero). */
function estimateSentence(estimate: string | null): string {
  const value = estimate === null ? NaN : Number(estimate);
  return Number.isNaN(value)
    ? "No cost estimate is available for these settings."
    : `Estimated cost: about $${value.toFixed(2)}.`;
}

export function RunStart({
  context,
  selection,
}: {
  context: ContextDoc | null;
  selection: Selection;
}) {
  const runParams = selection.runId === null ? undefined : { run_id: selection.runId };
  const read = useScreenRead<RunStartDoc>("/api/v1/run-start-state", runParams);
  const action = useActionState(read.retry);
  const navigate = useNavigate();

  // The published test versions a run can grade against, the selected package's first.
  const versions = useMemo(() => {
    const published = (context?.packages ?? []).filter((p) => p.published_version !== null);
    published.sort((a, b) =>
      a.package_id === selection.packageId ? -1 : b.package_id === selection.packageId ? 1 : 0);
    return published.map((p) => p.published_version as string);
  }, [context, selection.packageId]);
  const [version, setVersion] = useState<string>("");
  useEffect(() => {
    if (version === "" || !versions.includes(version)) setVersion(versions[0] ?? "");
  }, [versions, version]);

  const classRuns = useMemo(
    () =>
      newestRunFirst((context?.runs ?? []).filter((r) => r.cohort_id === selection.classId)),
    [context, selection.classId],
  );

  const openStart = async (
    title: string,
    summary: string,
    previewQuery: Record<string, string>,
    body: Record<string, unknown>,
  ): Promise<void> => {
    // The confirmation's content is the API's (FR-CONSOLE-43): the preview read priced on
    // the configuration the start will run under. A refused preview opens the dialog with
    // the refusal named, so the teacher sees why before deciding.
    try {
      const preview = await fetchRead<{ banner: string; estimate: string | null }>(
        "/api/v1/run-start-preview", undefined, previewQuery);
      action.open({
        title,
        description: `${summary} ${estimateSentence(preview.estimate)}`,
        confirm: "Start",
        action: "start run",
        body,
      });
    } catch (failure: unknown) {
      action.open({
        title,
        description: `The console could not price this run (${failure instanceof Error ? failure.message : String(failure)}). Starting it may be refused for the same reason.`,
        confirm: "Start",
        action: "start run",
        body,
      });
    }
  };

  return (
    <ReadScreen title="Start a run" read={read}>
      {(data) => {
        const waiting = data.run_id !== null && data.status === "pending";
        const canStartNew =
          selection.classId !== null && version !== "" && data.profile !== null;
        return (
          <>
            <p className="hub-state">
              {data.run_id === null
                ? "No grading run has started for this class yet."
                : `Run ${data.run_id} — class ${data.cohort_id}, test version ` +
                  `${data.package_version_id}, currently ${data.status ?? "unknown"}.`}
            </p>
            <ActionOutcome outcome={action.outcome} />
            {data.run_id !== null && (
              <button
                type="button"
                className={waiting ? "button button-primary" : "button"}
                onClick={() => {
                  if (data.run_id === null) return;
                  void openStart(
                    "Start this run",
                    "The waiting run starts grading under the settings it was made with.",
                    { run_id: data.run_id },
                    { run_id: data.run_id },
                  );
                }}
              >
                Start the run
              </button>
            )}
            <section className="panel" aria-label="Start a new grading run">
              <h2>Start a new grading run</h2>
              {selection.classId === null ? (
                <p>
                  Choose a class first —{" "}
                  <a href="#/class" onClick={() => navigate("/class")}>
                    set up a class
                  </a>
                  .
                </p>
              ) : versions.length === 0 ? (
                <p>
                  No test is published yet —{" "}
                  <a href="#/package" onClick={() => navigate("/package")}>
                    set up the test
                  </a>{" "}
                  first.
                </p>
              ) : (
                <form
                  className="settings-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!canStartNew || selection.classId === null) return;
                    void openStart(
                      `Grade class ${selection.classId}`,
                      `Every paper read for class ${selection.classId} is graded against ` +
                        `test ${version}, with the models in this console's settings ` +
                        `(${data.profile ?? "none"}). The run keeps going if you close the ` +
                        "browser.",
                      {
                        cohort_id: selection.classId,
                        package_version: version,
                        profile: data.profile ?? "",
                      },
                      {
                        cohort_id: selection.classId,
                        package_version: version,
                        profile: data.profile ?? "",
                      },
                    );
                  }}
                >
                  <div className="settings-row">
                    <span className="step-name">Class</span>
                    <span>{selection.classId}</span>
                  </div>
                  <div className="settings-row">
                    <label htmlFor="run-version">Test version</label>
                    <select
                      id="run-version"
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
                  {classRuns.length > 0 && (
                    <p className="step-note">
                      This class already has {classRuns.length} grading run(s); a new one grades
                      its papers again.
                    </p>
                  )}
                  {data.profile === null && (
                    <p className="settings-error">
                      The console was started without a settings profile, so it cannot start a
                      run. Ask the person who started the console to set one.
                    </p>
                  )}
                  <div className="settings-actions">
                    <button
                      type="submit"
                      className="button button-primary"
                      disabled={!canStartNew}
                    >
                      Start a new grading run
                    </button>
                  </div>
                </form>
              )}
            </section>
            {action.pending !== null && (
              <ConfirmDialog
                pending={action.pending}
                onClose={action.close}
                onDone={(result) => {
                  action.finish(result);
                  if (result.dispatched === true && result.refused !== true) {
                    // The started run, by id: the outcome's own sentence names it ("run <id>
                    // started …"); a restart keeps the run it named. The class rides along,
                    // so the monitor shows exactly this run, never the launch-time one.
                    const started = /^run (\S+) started/.exec(result.detail ?? "")?.[1];
                    const restarted = action.pending?.body["run_id"];
                    navigate("/monitor", {
                      class: selection.classId,
                      run: started ?? (typeof restarted === "string" ? restarted : null),
                    });
                  }
                }}
              />
            )}
          </>
        );
      }}
    </ReadScreen>
  );
}
