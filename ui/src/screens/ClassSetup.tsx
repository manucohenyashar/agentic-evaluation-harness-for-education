import { useState } from "react";
import {
  performAction,
  postRead,
  type ActionResult,
  type ClassRoster as ClassRosterDoc,
  type RosterEditorDoc,
  type RosterPreviewDoc,
} from "../api";
import { outcomeText } from "../components/Confirm";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useToast } from "../state/StateDisplay";
import { useScreenRead } from "../useScreenRead";

/**
 * The class setup screen (FR-UI-03b, FR-CONSOLE-42/53/63): every stored class with its
 * students, read live, and the forms that make one — typed or pasted names (`create class`)
 * or a roster file previewed before anything is written (`roster preview`, then `import
 * roster file`) — plus late students added to an existing class (`add students`). The copy
 * the forms need (the consent classes, the paste rule, the optional-ID statement) is the
 * roster editor read's, so nothing here restates a rule the server owns. The consent class
 * has no default: it can never be changed afterwards, so the teacher chooses it.
 */
export function ClassSetup({ classId }: { classId: string | null }) {
  const read = useScreenRead<ClassRosterDoc>("/api/v1/class-roster");
  const editor = useScreenRead<RosterEditorDoc>("/api/v1/roster-editor");
  const navigate = useNavigate();
  return (
    <ReadScreen title="Set up a class" read={read}>
      {(data) => (
        <>
          {data.cohorts.length === 0 ? (
            <p className="panel">No class exists yet. Make one below.</p>
          ) : (
            data.cohorts.map((cohort) => (
              <section
                key={cohort.cohort_id}
                className="panel"
                aria-label={`Class ${cohort.cohort_id}`}
              >
                <h2>
                  Class {cohort.cohort_id}
                  {cohort.cohort_id === classId && (
                    <span className="badge badge-info"> Selected</span>
                  )}
                </h2>
                <ul className="rows-list">
                  {cohort.students.map((student) => (
                    <li key={student.student_ref}>
                      <span className="step-name">{student.full_name ?? student.student_ref}</span>
                      {student.full_name !== null && (
                        <span className="step-note">{student.student_ref}</span>
                      )}
                      {student.submission_id === null ? (
                        <span className="step-state">no paper yet</span>
                      ) : (
                        <span className="step-state">paper read</span>
                      )}
                    </li>
                  ))}
                </ul>
                {cohort.cohort_id !== classId && (
                  <button
                    type="button"
                    className="button"
                    onClick={() => navigate("/class", { class: cohort.cohort_id, run: null })}
                  >
                    Work with this class
                  </button>
                )}
                <AddStudents classId={cohort.cohort_id} onDone={read.retry} />
                <DeleteClass classId={cohort.cohort_id} onDone={read.retry} />
              </section>
            ))
          )}
          {editor.data === null ? (
            editor.error !== null && (
              <p role="alert" className="screen-alert">
                The class form could not load: {editor.error}
              </p>
            )
          ) : (
            <CreateClass
              editor={editor.data}
              onCreated={(id) => {
                read.retry();
                navigate("/class", { class: id, run: null });
              }}
            />
          )}
        </>
      )}
    </ReadScreen>
  );
}

/** The class name rule `create_cohort` enforces, said before the teacher types (the
 * server still refuses anything else, naming the rule). */
const CLASS_NAME_HINT =
  "Lower-case letters, digits, '-', '_' or '.', up to 64 characters — for example 7b-english.";

function CreateClass({
  editor,
  onCreated,
}: {
  editor: RosterEditorDoc;
  onCreated: (classId: string) => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [consent, setConsent] = useState<string | null>(editor.consent_default);
  const [source, setSource] = useState<"type" | "file">("type");
  const [paste, setPaste] = useState("");
  const [file, setFile] = useState<{ name: string; content: string } | null>(null);
  const [preview, setPreview] = useState<RosterPreviewDoc | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);

  const chooseFile = (picked: File | undefined): void => {
    setPreview(null);
    setPreviewError(null);
    setFile(null);
    if (picked === undefined) return;
    void picked.text().then((content) => {
      setFile({ name: picked.name, content });
      postRead<RosterPreviewDoc>("/api/v1/roster/preview", { content, name: picked.name }).then(
        setPreview,
        (failure: unknown) =>
          setPreviewError(failure instanceof Error ? failure.message : String(failure)),
      );
    });
  };

  const trimmed = name.trim();
  const ready =
    trimmed !== "" &&
    consent !== null &&
    (source === "type" ? paste.trim() !== "" : preview !== null && preview.ready);

  const create = (): void => {
    if (!ready || consent === null) return;
    setBusy(true);
    setOutcome(null);
    const sent: Promise<ActionResult> =
      source === "type"
        ? performAction("create class", { class_id: trimmed, consent_class: consent, paste })
        : performAction("import roster file", {
            class_id: trimmed,
            consent_class: consent,
            content: file?.content ?? "",
            name: file?.name ?? "",
          });
    sent.then(
      (result) => {
        setBusy(false);
        if (result.dispatched === true && result.refused !== true) {
          toast({ kind: "success", text: `Class ${trimmed} is ready.` });
          setName("");
          setPaste("");
          setFile(null);
          setPreview(null);
          onCreated(trimmed);
        } else {
          setOutcome(outcomeText({ ...result, refused: true }));
        }
      },
      (failure: unknown) => {
        setBusy(false);
        setOutcome(`Refused: ${failure instanceof Error ? failure.message : String(failure)}`);
      },
    );
  };

  return (
    <form
      className="settings-form"
      aria-label="Make a new class"
      onSubmit={(event) => {
        event.preventDefault();
        create();
      }}
    >
      <fieldset>
        <legend>Make a new class</legend>
        <div className="settings-row">
          <label htmlFor="class-name">Class name</label>
          <input
            id="class-name"
            value={name}
            onChange={(event) => setName(event.target.value.toLowerCase())}
            autoComplete="off"
          />
          <p className="step-note">{CLASS_NAME_HINT}</p>
        </div>
        <div className="settings-row" role="radiogroup" aria-label="Whose work is this?">
          <span className="step-name">Whose work is this?</span>
          <div className="choice-list">
          {editor.consent_classes.map((choice) => (
            <label key={choice.value} className="choice">
              <input
                type="radio"
                name="consent"
                value={choice.value}
                checked={consent === choice.value}
                onChange={() => setConsent(choice.value)}
              />{" "}
              {choice.meaning}
            </label>
          ))}
          </div>
          <p className="step-note">This cannot be changed after the class is made.</p>
        </div>
        <div className="settings-row" role="radiogroup" aria-label="How to add the students">
          <span className="step-name">Students</span>
          <div className="choice-list">
          <label className="choice">
            <input
              type="radio"
              name="source"
              checked={source === "type"}
              onChange={() => setSource("type")}
            />{" "}
            Type or paste them
          </label>
          <label className="choice">
            <input
              type="radio"
              name="source"
              checked={source === "file"}
              onChange={() => setSource("file")}
            />{" "}
            Import a class list file
          </label>
          </div>
        </div>
        {source === "type" ? (
          <div className="settings-row">
            <label htmlFor="class-students">One student per line</label>
            <textarea
              id="class-students"
              rows={8}
              value={paste}
              onChange={(event) => setPaste(event.target.value)}
            />
            <p className="step-note">{editor.paste}</p>
            <p className="step-note">{editor.student_id_optional}</p>
          </div>
        ) : (
          <div className="settings-row">
            <label htmlFor="class-file">Class list file</label>
            <input
              id="class-file"
              type="file"
              accept=".txt,.csv,.tsv,text/plain,text/csv"
              onChange={(event) => chooseFile(event.target.files?.[0])}
            />
            {previewError !== null && (
              <p role="alert" className="settings-error">
                The file could not be read: {previewError}
              </p>
            )}
            {preview !== null && <RosterPreview preview={preview} />}
          </div>
        )}
        <div className="settings-actions">
          <button type="submit" className="button button-primary" disabled={!ready || busy}>
            {busy ? "Making the class…" : "Make the class"}
          </button>
        </div>
        {outcome !== null && (
          <p role="status" className="action-outcome">
            {outcome}
          </p>
        )}
      </fieldset>
    </form>
  );
}

/** What the class list file holds before anything is written: every student, and every
 * problem row with its line number, so one pass fixes the whole file. */
function RosterPreview({ preview }: { preview: RosterPreviewDoc }) {
  return (
    <div className="roster-preview" aria-label="What the file holds">
      <p className="step-note">
        {preview.counts.students} student(s) found
        {preview.format_label !== null ? ` (${preview.format_label})` : ""}.
      </p>
      {preview.problems.length > 0 && (
        <ul className="rows-list">
          {preview.problems.map((problem, index) => (
            <li key={index} className="settings-error">
              {problem.line !== null ? `Line ${problem.line}: ` : ""}
              {problem.reason}
            </li>
          ))}
        </ul>
      )}
      {preview.rows.length > 0 && (
        <ul className="rows-list">
          {preview.rows.map((row) => (
            <li key={row.line}>
              <span className="step-name">{row.full_name}</span>
              {row.student_ref !== null && <span className="step-note">{row.student_ref}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Late students for an existing class (`add students`, FR-CONSOLE-42): the same paste rule
 * as a new class, appended to its list. */
function AddStudents({ classId, onDone }: { classId: string; onDone: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [paste, setPaste] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);

  if (!open) {
    return (
      <button type="button" className="button" onClick={() => setOpen(true)}>
        Add students
      </button>
    );
  }
  const add = (): void => {
    setBusy(true);
    setOutcome(null);
    performAction("add students", { cohort_id: classId, paste }).then(
      (result) => {
        setBusy(false);
        if (result.dispatched === true && result.refused !== true && result.error === undefined) {
          toast({ kind: "success", text: `Students added to ${classId}.` });
          setPaste("");
          setOpen(false);
          onDone();
        } else {
          setOutcome(outcomeText({ ...result, refused: true }));
        }
      },
      (failure: unknown) => {
        setBusy(false);
        setOutcome(`Refused: ${failure instanceof Error ? failure.message : String(failure)}`);
      },
    );
  };
  return (
    <div className="settings-row">
      <label htmlFor={`add-${classId}`}>Students to add, one per line</label>
      <textarea
        id={`add-${classId}`}
        rows={4}
        value={paste}
        onChange={(event) => setPaste(event.target.value)}
      />
      <div className="settings-actions">
        <button
          type="button"
          className="button button-primary"
          disabled={busy || paste.trim() === ""}
          onClick={add}
        >
          Add them
        </button>
        <button type="button" className="button" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
      </div>
      {outcome !== null && (
        <p role="status" className="action-outcome">
          {outcome}
        </p>
      )}
    </div>
  );
}

/** Deleting a class (`purge cohort`): its students, papers and marks are removed for good.
 * The store refuses while the class's evidence has not been saved for validation, and the
 * refusal is shown as refused. The teacher types the class name to confirm — a purge cannot
 * be undone, so one click is not enough. */
function DeleteClass({ classId, onDone }: { classId: string; onDone: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);
  if (!open) {
    return (
      <button type="button" className="button" onClick={() => setOpen(true)}>
        Delete this class…
      </button>
    );
  }
  const purge = (): void => {
    setBusy(true);
    performAction("purge cohort", { cohort_id: classId }).then(
      (result) => {
        setBusy(false);
        if (result.dispatched === true && result.refused !== true && result.error === undefined) {
          toast({ kind: "success", text: `Class ${classId} was deleted.` });
          setOpen(false);
          onDone();
        } else {
          setOutcome(outcomeText({ ...result, refused: true }));
        }
      },
      (failure: unknown) => {
        setBusy(false);
        setOutcome(`Refused: ${failure instanceof Error ? failure.message : String(failure)}`);
      },
    );
  };
  return (
    <div className="settings-row" role="group" aria-label={`Delete class ${classId}`}>
      <p className="settings-error">
        Deleting removes this class's students, papers and marks for good. It cannot be undone.
        Type the class name to confirm.
      </p>
      <label htmlFor={`purge-${classId}`}>Class name</label>
      <input
        id={`purge-${classId}`}
        value={typed}
        autoComplete="off"
        onChange={(event) => setTyped(event.target.value)}
      />
      <div className="settings-actions">
        <button
          type="button"
          className="button"
          disabled={busy || typed !== classId}
          onClick={purge}
        >
          Delete the class
        </button>
        <button type="button" className="button" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
      </div>
      {outcome !== null && (
        <p role="status" className="action-outcome">
          {outcome}
        </p>
      )}
    </div>
  );
}
