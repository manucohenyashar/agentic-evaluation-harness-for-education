import { useState } from "react";
import {
  postRead,
  type ClassRoster as ClassRosterDoc,
  type ClassRosterEntry,
  type RosterEditorDoc,
  type RosterPreviewDoc,
  type Student,
} from "../api";
import { ConfirmDialog, useActionState } from "../components/Confirm";
import { FieldError, FormatLine, useFieldIds } from "../components/Field";
import { BusyButton, DisabledReason, isRefused, useReportedAction } from "../components/Outcome";
import {
  checkField,
  fillFieldFirst,
  fixFieldFirst,
  FORMAT_STUDENT_NAME,
  type FieldSpec,
} from "../wizard/vocabulary";
import { sharedNames, studentLabel, studentName } from "../studentNames";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useScreenRead } from "../useScreenRead";

/**
 * The class setup screen (FR-UI-03b, FR-CONSOLE-42/53/63/64/65/69): every stored class with
 * its students by name — the way the teacher knows them — and the check against their own list
 * (how many are listed, how many papers are in, who has none yet). A misspelt name is
 * corrected in place and a student listed by mistake is taken off the list. Then the forms
 * that make a class — typed or pasted names (`create class`)
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
  // One read as far as the screen is concerned: either read's failure is the screen's named
  // failure, and its retry retries both (CT-UI-04's recovery).
  const both = {
    data: read.data,
    error: read.error ?? editor.error,
    retry: () => {
      read.retry();
      editor.retry();
    },
  };
  return (
    <ReadScreen title="Set up a class" read={both}>
      {(data) => (
        <>
          {data.cohorts.length === 0 ? (
            <p className="panel">No class exists yet. Make one below.</p>
          ) : (
            data.cohorts.map((cohort) => (
              <ClassPanel
                key={cohort.cohort_id}
                cohort={cohort}
                selected={cohort.cohort_id === classId}
                consentMeaning={
                  editor.data?.consent_classes.find((c) => c.value === cohort.consent_class)
                    ?.meaning ?? null
                }
                onChoose={() => navigate("/class", { class: cohort.cohort_id, run: null })}
                onChanged={read.retry}
              />
            ))
          )}
          {editor.data !== null && (
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

/** The class name rule `create_cohort` enforces, said before the teacher types and checked
 * at the field (the server still refuses anything else, naming the rule). */
const CLASS_NAME: FieldSpec = {
  kind: "text",
  format: "Lower-case letters, digits, '-', '_' or '.', up to 64 characters — for example 7b-english",
  pattern: /^[a-z0-9._-]{1,64}$/,
};
const CONSENT_FORMAT: FieldSpec = {
  kind: "choice",
  format: "Choose one. This cannot be changed after the class is made",
};
const SOURCE_FORMAT: FieldSpec = { kind: "choice", format: "Choose how to give the list of students" };
const CLASS_FILE_ACCEPT = ".txt,.csv,.tsv,text/plain,text/csv";
const CLASS_FILE: FieldSpec = {
  kind: "file",
  format: "A class list file (.txt, .csv or .tsv), one student per line",
  accept: CLASS_FILE_ACCEPT,
};
const STUDENTS_TO_ADD: FieldSpec = {
  kind: "text",
  format: "One student's full name per line, as on the class list",
};
const STUDENT_NAME: FieldSpec = { kind: "text", format: FORMAT_STUDENT_NAME, maxLength: 200 };

function CreateClass({
  editor,
  onCreated,
}: {
  editor: RosterEditorDoc;
  onCreated: (classId: string) => void;
}) {
  const [name, setName] = useState("");
  const [consent, setConsent] = useState<string | null>(editor.consent_default);
  const [source, setSource] = useState<"type" | "file">("type");
  const [paste, setPaste] = useState("");
  const [file, setFile] = useState<{ name: string; content: string } | null>(null);
  const [preview, setPreview] = useState<RosterPreviewDoc | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const { busy, run } = useReportedAction();
  const nameError = checkField(CLASS_NAME, name);
  const nameIds = useFieldIds(nameError);
  const consentIds = useFieldIds();
  const sourceIds = useFieldIds();
  const pasteIds = useFieldIds();
  const fileIds = useFieldIds();
  const pasteSpec: FieldSpec = { kind: "text", format: editor.paste.replace(/\.\s*$/, "") };

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
  const reason =
    trimmed === ""
      ? fillFieldFirst("Class name")
      : nameError !== null
        ? fixFieldFirst("Class name")
        : consent === null
          ? fillFieldFirst("Whose work is this?")
          : source === "type"
            ? paste.trim() === "" ? fillFieldFirst("One student per line") : null
            : preview === null || !preview.ready
              ? fillFieldFirst("Class list file")
              : null;
  const ready = reason === null;

  const create = (): void => {
    if (!ready || consent === null) return;
    const body =
      source === "type"
        ? { class_id: trimmed, consent_class: consent, paste }
        : {
            class_id: trimmed,
            consent_class: consent,
            content: file?.content ?? "",
            name: file?.name ?? "",
          };
    void run(source === "type" ? "create class" : "import roster file", body, {
      ok: (result) => result.dispatched === true && !isRefused(result),
      said: () => `Class ${trimmed} is ready.`,
      onDone: () => {
        setName("");
        setPaste("");
        setFile(null);
        setPreview(null);
        onCreated(trimmed);
      },
    });
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
          <label htmlFor={nameIds.id}>Class name</label>
          <input
            {...nameIds.control}
            value={name}
            placeholder="e.g. 7b-english"
            onChange={(event) => setName(event.target.value.toLowerCase())}
            autoComplete="off"
          />
          <FormatLine id={nameIds.formatId} spec={CLASS_NAME} />
          <FieldError id={nameIds.errorId} error={nameError} />
        </div>
        <div className="settings-row" role="radiogroup" aria-labelledby={consentIds.id}>
          <span id={consentIds.id} className="step-name">Whose work is this?</span>
          <div className="choice-list">
          {editor.consent_classes.map((choice) => (
            <label key={choice.value} className="choice">
              <input
                type="radio"
                name="consent"
                value={choice.value}
                checked={consent === choice.value}
                aria-describedby={consentIds.formatId}
                onChange={() => setConsent(choice.value)}
              />{" "}
              {choice.meaning}
            </label>
          ))}
          </div>
          <FormatLine id={consentIds.formatId} spec={CONSENT_FORMAT} />
        </div>
        <div className="settings-row" role="radiogroup" aria-labelledby={sourceIds.id}>
          <span id={sourceIds.id} className="step-name">Students</span>
          <div className="choice-list">
          <label className="choice">
            <input
              type="radio"
              name="source"
              checked={source === "type"}
              aria-describedby={sourceIds.formatId}
              onChange={() => setSource("type")}
            />{" "}
            Type or paste them
          </label>
          <label className="choice">
            <input
              type="radio"
              name="source"
              checked={source === "file"}
              aria-describedby={sourceIds.formatId}
              onChange={() => setSource("file")}
            />{" "}
            Import a class list file
          </label>
          </div>
          <FormatLine id={sourceIds.formatId} spec={SOURCE_FORMAT} />
        </div>
        {source === "type" ? (
          <div className="settings-row">
            <label htmlFor={pasteIds.id}>One student per line</label>
            <textarea
              {...pasteIds.control}
              rows={8}
              value={paste}
              onChange={(event) => setPaste(event.target.value)}
            />
            <FormatLine id={pasteIds.formatId} spec={pasteSpec} />
            <p className="step-note">{editor.student_id_optional}</p>
          </div>
        ) : (
          <div className="settings-row">
            <label htmlFor={fileIds.id}>Class list file</label>
            <input
              {...fileIds.control}
              type="file"
              accept={CLASS_FILE_ACCEPT}
              onChange={(event) => chooseFile(event.target.files?.[0])}
            />
            <FormatLine id={fileIds.formatId} spec={CLASS_FILE} />
            {previewError !== null && (
              <p role="alert" className="settings-error">
                The file could not be read: {previewError}
              </p>
            )}
            {preview !== null && <RosterPreview preview={preview} />}
          </div>
        )}
        <div className="settings-actions">
          <BusyButton type="submit" className="button button-primary" disabled={!ready} busy={busy}>
            {busy ? "Making the class…" : "Make the class"}
          </BusyButton>
          <DisabledReason reason={busy ? null : reason} />
        </div>
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
  const [open, setOpen] = useState(false);
  const [paste, setPaste] = useState("");
  const { busy, run } = useReportedAction();
  const ids = useFieldIds();

  if (!open) {
    return (
      <button type="button" className="button" onClick={() => setOpen(true)}>
        Add students
      </button>
    );
  }
  const add = (): void => {
    void run("add students", { cohort_id: classId, paste }, {
      ok: (result) => result.dispatched === true && !isRefused(result),
      said: () => `Students added to ${classId}.`,
      onDone: () => {
        setPaste("");
        setOpen(false);
        onDone();
      },
    });
  };
  const label = "Students to add, one per line";
  return (
    <div className="settings-row">
      <label htmlFor={ids.id}>{label}</label>
      <textarea
        {...ids.control}
        rows={4}
        value={paste}
        onChange={(event) => setPaste(event.target.value)}
      />
      <FormatLine id={ids.formatId} spec={STUDENTS_TO_ADD} />
      <div className="settings-actions">
        <BusyButton
          className="button button-primary"
          disabled={paste.trim() === ""}
          busy={busy}
          onClick={add}
        >
          Add them
        </BusyButton>
        <button type="button" className="button" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
        <DisabledReason reason={!busy && paste.trim() === "" ? fillFieldFirst(label) : null} />
      </div>
    </div>
  );
}

/** Deleting a class (`purge cohort`): its students, papers and marks are removed for good.
 * The store refuses while the class's evidence has not been saved for validation, and the
 * refusal is shown as refused. The teacher types the class name to confirm — a purge cannot
 * be undone, so one click is not enough. */
function DeleteClass({
  classId,
  deletable,
  runs,
  onDone,
}: {
  classId: string;
  deletable: boolean;
  runs: number;
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const { busy, run } = useReportedAction();
  const ids = useFieldIds();
  if (!deletable) {
    // FR-CONSOLE-69: said before the teacher asks, so a delete is never a dead end.
    return (
      <p className="step-note refusal-shape">
        <strong>This class cannot be deleted.</strong>{" "}
        {runs > 0
          ? "It has been graded, and its results stay under Past tests. " +
            "To start again, make a new class below."
          : "It holds papers. Remove its papers on the Load papers screen, then delete it."}
      </p>
    );
  }
  if (!open) {
    return (
      <button type="button" className="button" onClick={() => setOpen(true)}>
        Delete this class…
      </button>
    );
  }
  const purge = (): void => {
    void run("purge cohort", { cohort_id: classId }, {
      ok: (result) => result.dispatched === true && !isRefused(result),
      said: () => `Class ${classId} was deleted.`,
      onDone: () => {
        setOpen(false);
        onDone();
      },
    });
  };
  const confirmSpec: FieldSpec = {
    kind: "text",
    format: `The class name exactly as it is written: ${classId}`,
  };
  return (
    <div className="settings-row" role="group" aria-label={`Delete class ${classId}`}>
      <p className="settings-error">
        Deleting removes this class and its list of students for good. It cannot be undone.
        Type the class name to confirm.
      </p>
      <label htmlFor={ids.id}>Class name</label>
      <input
        {...ids.control}
        value={typed}
        autoComplete="off"
        onChange={(event) => setTyped(event.target.value)}
      />
      <FormatLine id={ids.formatId} spec={confirmSpec} />
      <div className="settings-actions">
        <BusyButton
          className="button"
          disabled={typed !== classId}
          busy={busy}
          onClick={purge}
        >
          Delete the class
        </BusyButton>
        <button type="button" className="button" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
        <DisabledReason
          reason={!busy && typed !== classId ? `Type “${classId}” above to confirm.` : null}
        />
      </div>
    </div>
  );
}


/** One class: its students by name, the check against the teacher's own list, and the
 * corrections — rename, remove, add, delete. */
function ClassPanel({
  cohort,
  selected,
  consentMeaning,
  onChoose,
  onChanged,
}: {
  cohort: ClassRosterEntry;
  selected: boolean;
  consentMeaning: string | null;
  onChoose: () => void;
  onChanged: () => void;
}) {
  const action = useActionState(onChanged);
  const shared = sharedNames(cohort.students);
  const students = [...cohort.students].sort((a, b) =>
    studentName(a).localeCompare(studentName(b), undefined, { sensitivity: "base" }));
  const summary = cohort.summary;
  return (
    <section className="panel" aria-label={`Class ${cohort.cohort_id}`}>
      <h2>
        Class {cohort.cohort_id}
        {selected && <span className="badge badge-info"> Selected</span>}
      </h2>
      {summary !== undefined && (
        <p className="hub-state" aria-label="Class check">
          {summary.listed} student{summary.listed === 1 ? "" : "s"} on the list ·{" "}
          {summary.with_paper} paper{summary.with_paper === 1 ? "" : "s"} read
          {summary.without_paper.length > 0
            ? ` · no paper yet: ${summary.without_paper.join(", ")}`
            : summary.listed > 0
              ? " · every student has a paper"
              : ""}
        </p>
      )}
      {consentMeaning !== null && (
        <p className="step-note">Whose work this is: {consentMeaning}</p>
      )}
      <ul className="rows-list" aria-label="Students">
        {students.map((student) => (
          <StudentRow
            key={student.student_ref}
            classId={cohort.cohort_id}
            student={student}
            label={studentLabel(student, shared)}
            onRemove={() =>
              action.open({
                title: "Take this student off the list",
                description:
                  `${studentLabel(student, shared)} will no longer be on the list of class ` +
                  `${cohort.cohort_id}. A student whose paper is already in cannot be taken ` +
                  "off: move or remove the paper first.",
                confirm: "Take off the list",
                action: "remove student",
                body: { cohort_id: cohort.cohort_id, student_ref: student.student_ref },
              })
            }
            onRenamed={onChanged}
          />
        ))}
      </ul>
      {!selected && (
        <button type="button" className="button" onClick={onChoose}>
          Work with this class
        </button>
      )}
      <AddStudents classId={cohort.cohort_id} onDone={onChanged} />
      <DeleteClass
        classId={cohort.cohort_id}
        deletable={cohort.deletable ?? true}
        runs={cohort.runs ?? 0}
        onDone={onChanged}
      />
      {action.pending !== null && (
        <ConfirmDialog pending={action.pending} onClose={action.close} onDone={action.finish} />
      )}
    </section>
  );
}

/** One student on the list: their name first, whether their paper is in, and the two
 * corrections a list needs — fix the spelling, or take a mistaken entry off. */
function StudentRow({
  classId,
  student,
  label,
  onRemove,
  onRenamed,
}: {
  classId: string;
  student: Student;
  label: string;
  onRemove: () => void;
  onRenamed: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(student.full_name ?? "");
  const { busy, run } = useReportedAction();
  const nameError = checkField(STUDENT_NAME, name);
  const ids = useFieldIds(nameError);
  const save = (): void => {
    void run(
      "rename student",
      { cohort_id: classId, student_ref: student.student_ref, full_name: name },
      {
        ok: (result) => result.dispatched === true && !isRefused(result),
        said: (result) => result.detail || "Name corrected.",
        onDone: () => {
          setEditing(false);
          onRenamed();
        },
      },
    );
  };
  if (editing) {
    const reason =
      name.trim() === "" ? fillFieldFirst("Correct the name")
        : nameError !== null ? fixFieldFirst("Correct the name") : null;
    return (
      <li>
        <label htmlFor={ids.id} className="step-name">
          Correct the name
        </label>
        <input {...ids.control} value={name} onChange={(event) => setName(event.target.value)} />
        <FormatLine id={ids.formatId} spec={STUDENT_NAME} />
        <FieldError id={ids.errorId} error={nameError} />
        <BusyButton
          className="button button-primary"
          disabled={reason !== null}
          busy={busy}
          onClick={save}
        >
          Save
        </BusyButton>
        <button type="button" className="button" disabled={busy} onClick={() => setEditing(false)}>
          Cancel
        </button>
        <DisabledReason reason={busy ? null : reason} />
      </li>
    );
  }
  return (
    <li>
      <span className="step-name">{label}</span>
      <span className="step-state">
        {student.submission_id === null ? "no paper yet" : "paper read"}
      </span>
      <button
        type="button"
        className="button button-small"
        aria-label={`Correct the name of ${label}`}
        onClick={() => setEditing(true)}
      >
        Correct name
      </button>
      {student.submission_id === null && (
        <button
          type="button"
          className="button button-small"
          aria-label={`Take ${label} off the list`}
          onClick={onRemove}
        >
          Take off list
        </button>
      )}
    </li>
  );
}
