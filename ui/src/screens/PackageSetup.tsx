import { fetchRead, type PackageSetup as PackageSetupDoc } from "../api";
import { ActionOutcome, ConfirmDialog, useActionState } from "../components/Confirm";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";

/**
 * The package setup screen (FR-UI-03a): the M-SETUP draft's steps verbatim, with each
 * blocking gate named as blocking, and the package version the console's run grades. The
 * publish action — the SPA's one enumerated publish control (FR-UI-05) — is offered only
 * when the draft is ready: over a blocked gate it is present but disabled, so the screen
 * never offers a publish the gates refuse (TC-UI-03's blocked world).
 */
export function PackageSetup() {
  const read = useScreenRead<PackageSetupDoc>("/api/v1/package-setup");
  const action = useActionState(read.retry);

  const openPublish = (): void => {
    if (read.data === null || read.data.draft === null) {
      return;
    }
    // The confirmation names what it does out of the API's own document (FR-UI-05):
    // the draft and the version the flip locks, and the body posts the draft's package
    // id — the offer and the action work on the same package, never the fallback's.
    const draft = read.data.draft;
    action.open({
      title: "Publish this package",
      description:
        `Publishing locks the draft of package ${draft.package_id} — version ` +
        `${draft.version_id} — through M-PKG's one-transaction flip and records you as ` +
        "the approver. The run then grades against this version.",
      confirm: "Publish",
      action: "publish package",
      body: { actor: "operator", package_id: draft.package_id },
    });
  };

  return (
    <ReadScreen title="Set up a test package" read={read}>
      {(data) => (
        <>
          <p className="hub-state">
            {data.current_version_id
              ? `The run grades against package version ${data.current_version_id}.`
              : "No run names a package version yet."}
          </p>
          <ActionOutcome outcome={action.outcome} />
          {data.draft === null ? (
            <p className="panel">
              No package's setup holds a draft right now. Every stored package is published.
            </p>
          ) : (
            <section className="panel">
              <h2>
                Draft {data.draft.package_id} — version {data.draft.version_id}
              </h2>
              <ul className="steps">
                {data.draft.steps.map((step) => (
                  <li key={step.step_id} className={step.blocking ? "step step-blocking" : "step"}>
                    <span className="step-name">{step.name}</span>
                    {step.blocking && <span className="badge">Blocking</span>}
                    <span className="step-state">
                      {step.done ? "done" : step.available ? "waiting on you" : "not available"}
                    </span>
                    {step.note !== "" && <span className="step-note">{step.note}</span>}
                  </li>
                ))}
              </ul>
              {data.draft.ready_to_publish ? (
                <button
                  type="button"
                  className="button button-primary"
                  onClick={openPublish}
                >
                  Publish the draft version
                </button>
              ) : (
                <button type="button" className="button" disabled>
                  Publish the draft version
                </button>
              )}
            </section>
          )}
          {action.pending !== null && (
            <ConfirmDialog pending={action.pending} onClose={action.close} onDone={action.finish} />
          )}
        </>
      )}
    </ReadScreen>
  );
}
