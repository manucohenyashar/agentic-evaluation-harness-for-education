import { useState } from "react";
import {
  fetchRead,
  fileToBase64,
  type ContextDoc,
  type PackageSetup as PackageSetupDoc,
} from "../api";
import { ActionOutcome, ConfirmDialog, useActionState } from "../components/Confirm";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";
import { useNavigate } from "../navigate";

/**
 * The package setup screen (FR-UI-03a): the M-SETUP draft's steps verbatim, with each
 * blocking gate named as blocking, and the package version the console's run grades. The
 * publish action — the SPA's one enumerated publish control (FR-UI-05) — is offered only
 * when the draft is ready: over a blocked gate it is present but disabled, so the screen
 * never offers a publish the gates refuse (TC-UI-03's blocked world).
 */
export function PackageSetup({ context }: { context: ContextDoc | null }) {
  // Every published test, as the shell's context feed lists them: what a run can grade
  // against, shown whether or not a run exists yet.
  const published = (context?.packages ?? []).filter((p) => p.published_version !== null);
  const navigate = useNavigate();
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
        `${draft.version_id} — in a single step, and records you as ` +
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
          {published.length > 0 && (
            <section className="panel" aria-label="Published tests">
              <h2>Published tests</h2>
              <ul className="rows-list">
                {published.map((p) => (
                  <li key={p.package_id}>
                    <span className="step-name">{p.package_id}</span>
                    <span className="step-note">{p.published_version}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
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
          <section className="panel" aria-label="Make a new package">
            <h2>Make a new package</h2>
            <p>
              <a href="#/package/author" onClick={() => navigate("/package/author")}>
                From your documents
              </a>{" "}
              — upload the test's files and the console drafts the package; or start an
              empty one there and write every question yourself in the editor.
            </p>
          </section>
          <ImportBackup onDone={read.retry} />
        </>
      )}
    </ReadScreen>
  );
}

/**
 * The test's import path (design delta §3.2.3): a backup file (`.aehpkg`) another console
 * exported — the Results screen's "Backup of the test" — is imported through M-PKG's own
 * all-or-nothing import, behind the "export/import package" control's confirmation. A corrupt,
 * altered or already-present test is refused with the reason, and nothing is written.
 */
function ImportBackup({ onDone }: { onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const action = useActionState(onDone);
  const open = async (): Promise<void> => {
    if (file === null) return;
    const content = await fileToBase64(file);
    action.open({
      title: "Import this test",
      description:
        `The test in ${file.name} is added to this console as a published test, exactly as ` +
        "it was exported. A test that is already here is never overwritten.",
      confirm: "Import",
      action: "export/import package",
      body: { content_base64: content, name: file.name },
    });
  };
  return (
    <section className="panel" aria-label="Import a test from its backup file">
      <h2>Import a test from its backup file</h2>
      <div className="settings-form">
        <div className="settings-row">
          <label htmlFor="import-backup">Backup file (.aehpkg)</label>
          <input
            id="import-backup"
            type="file"
            accept=".aehpkg"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </div>
        <div className="settings-actions">
          <button
            type="button"
            className="button"
            disabled={file === null}
            onClick={() => {
              void open();
            }}
          >
            Import the test
          </button>
        </div>
      </div>
      <ActionOutcome outcome={action.outcome} />
      {action.pending !== null && (
        <ConfirmDialog pending={action.pending} onClose={action.close} onDone={action.finish} />
      )}
    </section>
  );
}
