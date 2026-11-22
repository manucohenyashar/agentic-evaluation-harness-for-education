import { useEffect, useRef, useState } from "react";
import {
  fetchJob,
  fileToBase64,
  type ContextDoc,
  type DifferencesDoc,
  type ExampleDifference,
  type ExampleQuestion,
  type ExamplesDoc,
  type JobDetailDoc,
  type MarkedExample,
  type QuestionsDoc,
} from "../api";
import { ElapsedClock, clockPhase } from "../components/Elapsed";
import { FieldError, FormatLine, useFieldIds } from "../components/Field";
import {
  BusyButton,
  DisabledReason,
  plainText,
  textOutcome,
  useOutcome,
  useReportedAction,
} from "../components/Outcome";
import { ReadScreen } from "../components/ReadScreen";
import { Screen } from "../components/Screen";
import { SeatCard } from "../components/Seat";
import { useNavigate } from "../navigate";
import { useSelection } from "../selection";
import { useScreenRead } from "../useScreenRead";
import { FORMAT_CHOOSE_ONE, FORMAT_FREE_TEXT, packageName } from "../wizard/vocabulary";

/**
 * The marked examples step of package setup (FR-UI-44, FR-UI-45; FR-CONSOLE-87's reads and
 * actions). The teacher uploads unmarked copies, marks each paper on a form that uses the
 * blind sample's seat, then **Check my examples** grades them with the rubric as written —
 * a job, shown with the elapsed clock. Then "Where the system read your rubric differently":
 * each difference side by side, grouped by its cause, and the questions about the rubric.
 * **Skip this step** is on every sub-step until the step is done.
 *
 * Decision D5: the examples never produce a figure. Nothing on this screen counts how often
 * the marks were the same, and no sentence here gives a share of anything — with a dozen
 * papers the teacher chose, that would say nothing; the blind sample is the evidence.
 */

const INTRO =
  "Mark a few papers yourself so the system can check it reads your rubric the way you do.";

/** The statuses in which the examples can still be uploaded, marked and checked. */
const BEFORE_CHECK = new Set(["not_started", "uploaded", "marked"]);

/** A finished job's teacher sentence: the success line (it names any file not used, and
 * why) or the refusal. */
function jobSentence(job: JobDetailDoc): { text: string; failed: boolean } {
  if (job.state === "failed" || job.state === "cancelled") {
    return {
      text: job.error.detail ?? "This could not be done. Nothing was changed; please try again.",
      failed: true,
    };
  }
  return { text: job.progress.current ?? "Done.", failed: false };
}

/**
 * Follows one job (the upload's reading, the check's grading) to its end, then reports its
 * own sentence in the outcome banner — the upload's names any paper refused for having marks
 * on it (FR-SETUP-21) — and re-reads the step.
 */
function useJobWatch(onEnd: () => void) {
  const { report } = useOutcome();
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobDetailDoc | null>(null);
  // Refs, so a re-render never restarts the poll.
  const ended = useRef(onEnd);
  ended.current = onEnd;
  const reported = useRef(report);
  reported.current = report;
  useEffect(() => {
    if (jobId === null) return;
    let stopped = false;
    let timer: number | undefined;
    const poll = (): void => {
      fetchJob(jobId).then(
        (next) => {
          if (stopped) return;
          setJob(next);
          if (next.finished_at !== null || ["succeeded", "failed", "cancelled"].includes(next.state)) {
            const said = jobSentence(next);
            reported.current(textOutcome(plainText(said.text), said.failed));
            setJobId(null);
            ended.current();
            return;
          }
          timer = window.setTimeout(poll, 1000);
        },
        () => {
          if (!stopped) timer = window.setTimeout(poll, 2000);
        },
      );
    };
    poll();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [jobId]);
  return {
    active: jobId !== null,
    job: jobId !== null ? job : null,
    watch: (id: string) => {
      setJob(null);
      setJobId(id);
    },
  };
}

export function MarkedExamples({ context }: { context: ContextDoc | null }) {
  const { packageId } = useSelection();
  const navigate = useNavigate();
  const entry = context?.packages.find((p) => p.package_id === packageId) ?? null;
  const version = entry?.published_version_id ?? null;
  if (context !== null && version === null) {
    return (
      <Screen title="Your marked examples">
        <p className="hub-state">{INTRO}</p>
        <p className="panel">
          Choose a published test first: the examples are checked against a test's rubric as
          it was published.{" "}
          <a href="#/package" onClick={() => navigate("/package")}>
            Go to the test packages
          </a>
        </p>
      </Screen>
    );
  }
  return <ExamplesStep version={version} name={packageName(entry?.package_id)} />;
}

function ExamplesStep({ version, name }: { version: string | null; name: string }) {
  const [polling, setPolling] = useState(false);
  const read = useScreenRead<ExamplesDoc>(
    version === null ? null : "/api/v1/calibration/examples",
    version === null ? undefined : { package_version: version },
    polling ? 2000 : undefined,
  );
  const jobs = useJobWatch(read.retry);
  // A skip before the check stores nothing the read can show on a published test, so this
  // visit remembers it; a skip after the check is the read's own `skipped`.
  const [skippedNow, setSkippedNow] = useState(false);
  // With papers already uploaded, the upload form opens on request, so the marking stays
  // in view.
  const [adding, setAdding] = useState(false);
  const status = read.data?.status ?? null;
  // While a job or the check runs the read is polled, so the clock's state and the step
  // move on.
  useEffect(() => setPolling(status === "checking" || jobs.active), [status, jobs.active]);

  return (
    <ReadScreen title="Your marked examples" read={read}>
      {(doc) => {
        const shown: ExamplesDoc = skippedNow && doc.status !== "answered"
          ? { ...doc, status: "skipped" }
          : doc;
        const done = shown.status === "answered" || shown.status === "skipped";
        const checked = !BEFORE_CHECK.has(doc.status) && doc.status !== "checking";
        const room = doc.limit - doc.examples.length;
        return (
          <>
            <p className="hub-state">{INTRO}</p>
            <p className="examples-test">For {name}.</p>
            <SubSteps doc={doc} />
            {!done && version !== null && (
              <SkipStep
                version={version}
                onDone={() => {
                  setSkippedNow(true);
                  read.retry();
                }}
              />
            )}
            {done && <DoneLine doc={shown} />}
            {!done && BEFORE_CHECK.has(doc.status) && version !== null && (
              <>
                {room > 0 && (doc.examples.length === 0 || adding) && (
                  <UploadExamples
                    doc={doc}
                    version={version}
                    busy={jobs.active}
                    onJob={(jobId) => {
                      setAdding(false);
                      jobs.watch(jobId);
                    }}
                  />
                )}
                {room > 0 && doc.examples.length > 0 && !adding && (
                  <p>
                    <button type="button" className="button" onClick={() => setAdding(true)}>
                      Upload more papers
                    </button>{" "}
                    <span className="step-note">
                      Up to {room} more ({doc.examples.length} of at most {doc.limit} uploaded).
                    </span>
                  </p>
                )}
                {jobs.active && jobs.job?.kind === "examples_upload" && (
                  <p className="hub-state" aria-live="polite">
                    {jobs.job.progress.current ?? "Reading your examples."}
                  </p>
                )}
                {doc.examples.length > 0 && (
                  <MarkExamples doc={doc} version={version} onSaved={read.retry} />
                )}
              </>
            )}
            {!done && version !== null && doc.examples.length > 0 && !checked && (
              <CheckExamples
                doc={doc}
                version={version}
                jobActive={jobs.active}
                starting={jobs.active && jobs.job?.kind === "examples_grade"}
                onJob={jobs.watch}
              />
            )}
            {doc.status === "stopped" && (
              <section className="panel" aria-label="Check my examples">
                <h2>Check my examples</h2>
                <p className="run-clock">
                  <Clock doc={doc} />
                </p>
                <p>
                  The check of your examples stopped before it finished. Your test is marked
                  with your rubric as written; you can skip this step.
                </p>
              </section>
            )}
            {checked && doc.status !== "stopped" && version !== null && (
              <>
                {doc.checking !== null && (
                  <p className="run-clock">
                    Your examples were checked. <Clock doc={doc} />
                  </p>
                )}
                <Differences version={version} />
                <Questions version={version} answeredOrSkipped={done} onDone={read.retry} />
              </>
            )}
          </>
        );
      }}
    </ReadScreen>
  );
}

/** Where the step stands, as its four sub-steps. */
function SubSteps({ doc }: { doc: ExamplesDoc }) {
  const marked = doc.examples.filter((e) => e.marked).length;
  const at = BEFORE_CHECK.has(doc.status)
    ? doc.examples.length === 0
      ? 0
      : 1
    : doc.status === "checking"
      ? 2
      : 3;
  const steps = [
    `Upload unmarked copies (${doc.examples.length} uploaded)`,
    `Mark each paper (${marked} of ${doc.examples.length} marked)`,
    "Check my examples",
    "See where the system read your rubric differently",
  ];
  return (
    <ol className="examples-substeps">
      {steps.map((text, index) => (
        <li key={text} className={index === at ? "examples-substep-current" : undefined}>
          {text}
        </li>
      ))}
    </ol>
  );
}

function DoneLine({ doc }: { doc: ExamplesDoc }) {
  if (doc.status === "skipped") {
    return (
      <p className="panel">
        You skipped this step. Your test is marked with your rubric as written.
      </p>
    );
  }
  return (
    <p className="panel">
      {doc.clarified_rubric?.text ?? "You answered the questions. Thank you."}
    </p>
  );
}

/** **Skip this step**: present on every sub-step until the step is done (FR-UI-44). */
function SkipStep({ version, onDone }: { version: string; onDone: () => void }) {
  const skip = useReportedAction();
  return (
    <p className="examples-skip">
      <BusyButton
        busy={skip.busy}
        onClick={() => {
          void skip.run("examples skip", { package_version: version }, { onDone });
        }}
      >
        Skip this step
      </BusyButton>{" "}
      <span className="step-note">
        It is optional: skipping marks your test with your rubric as written.
      </span>
    </p>
  );
}

/** The upload sub-step: unmarked PDF copies, and — once, at the first upload — whose
 * papers they are (only made-up practice papers go to an online model). */
function UploadExamples({
  doc,
  version,
  busy,
  onJob,
}: {
  doc: ExamplesDoc;
  version: string;
  busy: boolean;
  onJob: (jobId: string) => void;
}) {
  const upload = useReportedAction();
  const [files, setFiles] = useState<File[]>([]);
  const [consent, setConsent] = useState<string | null>(null);
  const room = doc.limit - doc.examples.length;
  const notPdf = files.filter((file) => !/\.pdf$/i.test(file.name));
  const error =
    notPdf.length > 0
      ? `${notPdf.map((f) => f.name).join(", ")} ${notPdf.length === 1 ? "is" : "are"} not a PDF file. Choose PDF files only.`
      : files.length > room
        ? `You chose ${files.length} files; you can add ${room} more (at most ${doc.limit} in all).`
        : null;
  const fileIds = useFieldIds(error);
  const consentIds = useFieldIds();
  const needsConsent = doc.consent.stored === null;
  const reason =
    files.length === 0
      ? "Choose at least one PDF file."
      : error !== null
        ? "Fix the files chosen first."
        : needsConsent && consent === null
          ? "Say whose papers these are."
          : busy
            ? "Wait for the current step to finish."
            : null;

  const send = async (): Promise<void> => {
    const documents = await Promise.all(
      files.map(async (file) => ({ name: file.name, content_base64: await fileToBase64(file) })),
    );
    const body: Record<string, unknown> = { package_version: version, documents };
    if (needsConsent && consent !== null) body.consent = consent;
    void upload.run("examples upload", body, {
      onDone: (result) => {
        setFiles([]);
        if (result.job_id) onJob(result.job_id);
      },
    });
  };

  return (
    <section className="panel" aria-label="Upload unmarked copies">
      <h2>Upload unmarked copies</h2>
      <div className="settings-form">
        <div className={error !== null ? "settings-row settings-row-error" : "settings-row"}>
          <label htmlFor={fileIds.id}>Answer sheets</label>
          <input
            {...fileIds.control}
            type="file"
            accept="application/pdf,.pdf"
            multiple
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
          />
          <FormatLine
            id={fileIds.formatId}
            spec={`${doc.format.replace(/\s*\(at most \d+\)\.?$/, "")}. 1 to ${room} PDF files now (at most ${doc.limit} in all).`}
          />
          <FieldError id={fileIds.errorId} error={error} />
        </div>
        {needsConsent && (
          <div className="settings-row">
            <span id={`${consentIds.id}-label`} className="settings-label">
              Whose papers are these?
            </span>
            <div
              className="choice-list"
              role="radiogroup"
              aria-labelledby={`${consentIds.id}-label`}
              aria-describedby={consentIds.formatId}
            >
              {doc.consent.options.map((option) => (
                <label key={option.value}>
                  <input
                    type="radio"
                    name="examples-consent"
                    value={option.value}
                    checked={consent === option.value}
                    onChange={() => setConsent(option.value)}
                  />
                  {option.meaning[0]?.toUpperCase()}
                  {option.meaning.slice(1)}
                </label>
              ))}
            </div>
            <FormatLine
              id={consentIds.formatId}
              spec={`${FORMAT_CHOOSE_ONE}. Asked once for these examples; on an online model only made-up practice work is sent.`}
            />
          </div>
        )}
        <div className="settings-actions">
          <BusyButton
            className="button button-primary"
            busy={upload.busy}
            disabled={reason !== null}
            onClick={() => {
              void send();
            }}
          >
            Upload the examples
          </BusyButton>
          <DisabledReason reason={reason} />
        </div>
      </div>
    </section>
  );
}

/** The marking sub-step: each paper, whether it has the teacher's marks, and its form. */
function MarkExamples({
  doc,
  version,
  onSaved,
}: {
  doc: ExamplesDoc;
  version: string;
  onSaved: () => void;
}) {
  const firstUnmarked = doc.examples.find((e) => !e.marked)?.document_id ?? null;
  const [open, setOpen] = useState<string | null>(firstUnmarked);
  const current = doc.examples.find((e) => e.document_id === open) ?? null;
  return (
    <section className="panel" aria-label="Mark each paper">
      <h2>Mark each paper</h2>
      <p className="hub-state">
        Read each answer and choose the level you gave it. Your marks stay yours: the system
        never sees them while it marks.
      </p>
      <ul className="rows-list">
        {doc.examples.map((example) => (
          <li key={example.document_id}>
            <span className="step-name">{exampleName(example)}</span>
            <span className="step-state">{example.marked ? "Marked" : "Needs your marks"}</span>
            <button
              type="button"
              className="button"
              aria-expanded={open === example.document_id}
              onClick={() => setOpen(open === example.document_id ? null : example.document_id)}
            >
              {open === example.document_id
                ? "Close the form"
                : example.marked
                  ? "Change my marks"
                  : "Mark this paper"}
            </button>
          </li>
        ))}
      </ul>
      {current !== null && (
        <ExampleForm
          key={current.document_id}
          example={current}
          version={version}
          onSaved={() => {
            const next = doc.examples.find(
              (e) => !e.marked && e.document_id !== current.document_id,
            );
            setOpen(next?.document_id ?? null);
            onSaved();
          }}
        />
      )}
    </section>
  );
}

function exampleName(example: MarkedExample): string {
  return example.file_name || `Example ${example.number}`;
}

/** One paper's form: a seat per part marked by hand, saved together (every part needs a
 * level — FR-SETUP-20's form rule). */
function ExampleForm({
  example,
  version,
  onSaved,
}: {
  example: MarkedExample;
  version: string;
  onSaved: () => void;
}) {
  const save = useReportedAction();
  const [choices, setChoices] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      example.parts
        .filter((part) => part.your_mark !== null)
        .map((part) => [part.criterion_id, part.your_mark as string]),
    ),
  );
  if (example.parts.length === 0) {
    return (
      <p className="hub-state">
        This test has no parts you mark by hand, so there is nothing to enter for this paper.
      </p>
    );
  }
  const left = example.parts.filter((part) => !choices[part.criterion_id]).length;
  return (
    <form
      className="examples-form"
      aria-label={`Your marks for ${exampleName(example)}`}
      onSubmit={(event) => {
        event.preventDefault();
        void save.run(
          "examples mark",
          { package_version: version, document_id: example.document_id, bands: choices },
          { onDone: onSaved },
        );
      }}
    >
      <h3>Your marks for {exampleName(example)}</h3>
      {example.parts.map((part) => (
        <SeatCard
          key={part.criterion_id}
          heading={`${exampleName(example)} — ${part.question}`}
          answer={part.answer}
          name={`example-${example.document_id}-${part.criterion_id}`}
          bands={part.bands}
          chosen={choices[part.criterion_id] ?? null}
          busy={save.busy}
          onChoose={(band) => setChoices({ ...choices, [part.criterion_id]: band })}
          format={`${FORMAT_CHOOSE_ONE}. Saved with the paper's other marks when you press Save.`}
        />
      ))}
      <p className="settings-actions">
        <BusyButton
          type="submit"
          className="button button-primary"
          busy={save.busy}
          disabled={left > 0}
        >
          Save my marks for this paper
        </BusyButton>
        <DisabledReason
          reason={
            left > 0 ? `Choose a level for every part: ${left} still to choose.` : null
          }
        />
      </p>
    </form>
  );
}

function Clock({ doc }: { doc: ExamplesDoc }) {
  if (doc.checking === null) return null;
  return (
    <ElapsedClock
      startedAt={doc.checking.started_at}
      endedAt={doc.checking.ended_at}
      state={doc.checking.state}
    />
  );
}

/** **Check my examples** (FR-CALIB-17 as a job) with the elapsed clock (FR-UI-29). */
function CheckExamples({
  doc,
  version,
  jobActive,
  starting,
  onJob,
}: {
  doc: ExamplesDoc;
  version: string;
  jobActive: boolean;
  /** The check was asked for and its grading has not reported a state yet. */
  starting: boolean;
  onJob: (jobId: string) => void;
}) {
  const check = useReportedAction();
  const marked = doc.examples.filter((e) => e.marked).length;
  const checking = doc.status === "checking";
  const reason = checking
    ? null
    : marked === 0
      ? "Mark at least one paper first."
      : jobActive
        ? "Wait for the current step to finish."
        : null;
  return (
    <section className="panel" aria-label="Check my examples">
      <h2>Check my examples</h2>
      <p className="hub-state">
        The system marks your examples with your rubric as written, then shows where it read
        a part differently from you. {doc.cost.text}
        {marked < doc.examples.length &&
          ` Papers without your marks are not compared: ${doc.examples.length - marked} still ${doc.examples.length - marked === 1 ? "has" : "have"} none.`}
      </p>
      <p className="settings-actions">
        <BusyButton
          className="button button-primary"
          busy={check.busy || checking}
          disabled={reason !== null}
          onClick={() => {
            void check.run("examples grade", { package_version: version }, {
              onDone: (result) => {
                if (result.job_id) onJob(result.job_id);
              },
            });
          }}
        >
          Check my examples
        </BusyButton>
        <span className="run-clock" aria-live="polite">
          {clockPhase(doc.checking?.state) === null && (checking || starting)
            ? "Starting the check."
            : <Clock doc={doc} />}
        </span>
        <DisabledReason reason={reason} />
      </p>
    </section>
  );
}

/** The cause groups' order: the ones that lead somewhere first. */
const CAUSE_ORDER = ["rubric_ambiguity", "model_failure", "teacher_inconsistency"];

/** "Where the system read your rubric differently" (FR-UI-45): each difference side by
 * side, grouped by cause with what happens next, and the fixed sentence. */
function Differences({ version }: { version: string }) {
  const read = useScreenRead<DifferencesDoc>("/api/v1/calibration/differences", {
    package_version: version,
  });
  return (
    <section className="panel" aria-label="Where the system read your rubric differently">
      <h2>Where the system read your rubric differently</h2>
      {read.error !== null ? (
        <p role="alert" className="screen-alert">
          The differences could not be read ({read.error}).{" "}
          <button type="button" className="button" onClick={read.retry}>
            Retry
          </button>
        </p>
      ) : read.data === null ? (
        <p className="hub-state">Reading the differences.</p>
      ) : (
        <>
          <p className="examples-sentence">{read.data.sentence}</p>
          {read.data.groups.length === 0 ? (
            <p className="hub-state">
              The system read every part you marked the way you did. Nothing needs a question.
            </p>
          ) : (
            [...read.data.groups]
              .sort((a, b) => CAUSE_ORDER.indexOf(a.cause) - CAUSE_ORDER.indexOf(b.cause))
              .map((group) => (
                <section key={group.cause} className="examples-cause" aria-label={group.heading}>
                  <h3>{group.heading}</h3>
                  <p className="step-note">{group.next}</p>
                  <ul className="examples-differences">
                    {group.differences.map((difference) => (
                      <li key={`${difference.document_id}-${difference.part}`}>
                        <DifferenceRow difference={difference} />
                      </li>
                    ))}
                  </ul>
                </section>
              ))
          )}
        </>
      )}
    </section>
  );
}

function DifferenceRow({ difference }: { difference: ExampleDifference }) {
  const own = (
    <div className="examples-side">
      <p className="step-name">
        {difference.example} — {difference.part}
      </p>
      <blockquote className="blind-answer">
        {difference.answer.trim() !== "" ? difference.answer : "No answer text could be read."}
      </blockquote>
      <p className="blind-yours">You: {difference.your_mark}</p>
      <p className="blind-system">The system: {difference.system_mark}</p>
      {difference.system_reason !== "" && (
        <p className="blind-descriptor">Its reason: {difference.system_reason}</p>
      )}
    </div>
  );
  if (difference.paired === undefined) {
    return <div className="examples-pair">{own}</div>;
  }
  const paired = difference.paired;
  return (
    <div className="examples-pair">
      {own}
      <div className="examples-side">
        <p className="step-name">
          {paired.example} — {difference.part}
        </p>
        <blockquote className="blind-answer">
          {paired.answer.trim() !== "" ? paired.answer : "No answer text could be read."}
        </blockquote>
        <p className="blind-yours">You: {paired.your_mark ?? "not marked"}</p>
        <p className="blind-system">The system: {difference.system_mark}</p>
      </div>
    </div>
  );
}

/** An option as the teacher reads it. */
function optionLabel(option: string): string {
  if (option === "broaden") return "Broaden the description";
  if (option === "narrow") return "Narrow the description";
  if (option === "keep as is") return "Keep it as it is";
  return option.charAt(0).toUpperCase() + option.slice(1);
}

const OWN_WORDS = "__own_words__";

/** The questions (FR-UI-45): "Question 1 of 3", each with its options and two examples. */
function Questions({
  version,
  answeredOrSkipped,
  onDone,
}: {
  version: string;
  answeredOrSkipped: boolean;
  onDone: () => void;
}) {
  const read = useScreenRead<QuestionsDoc>("/api/v1/calibration/questions", {
    package_version: version,
  });
  const send = useReportedAction();
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [words, setWords] = useState<Record<string, string>>({});
  const [inAdvance, setInAdvance] = useState(false);
  const advanceIds = useFieldIds();
  if (read.error !== null) {
    return (
      <p role="alert" className="screen-alert">
        The questions could not be read ({read.error}).{" "}
        <button type="button" className="button" onClick={read.retry}>
          Retry
        </button>
      </p>
    );
  }
  if (read.data === null) {
    return <p className="hub-state">Reading the questions.</p>;
  }
  const doc = read.data;
  if (doc.questions.length === 0) {
    return null;
  }
  const open = doc.status === "open" && !answeredOrSkipped;
  const answers: Record<string, string> = {};
  for (const question of doc.questions) {
    const pick = chosen[question.question_id];
    const text = pick === OWN_WORDS ? (words[question.question_id] ?? "").trim() : pick;
    if (text) answers[question.question_id] = text;
  }
  const left = doc.questions.length - Object.keys(answers).length;
  return (
    <section className="panel" aria-label="Questions about your rubric">
      <h2>Questions about your rubric</h2>
      {!open && (
        <p className="hub-state">
          {doc.status === "skipped"
            ? "You skipped these questions; your rubric is not changed."
            : "You answered these questions."}
        </p>
      )}
      {doc.questions.map((question) => (
        <QuestionCard
          key={question.question_id}
          question={question}
          open={open}
          chosen={chosen[question.question_id] ?? null}
          words={words[question.question_id] ?? ""}
          onChoose={(value) => setChosen({ ...chosen, [question.question_id]: value })}
          onWords={(value) => setWords({ ...words, [question.question_id]: value })}
        />
      ))}
      {open && (
        <div className="examples-answers">
          <div>
            <label className="blind-level">
              <input
                {...advanceIds.control}
                type="checkbox"
                checked={inAdvance}
                onChange={(event) => setInAdvance(event.target.checked)}
              />{" "}
              My students saw this rubric before the test
            </label>
            <FormatLine
              id={advanceIds.formatId}
              spec="Tick it if the rubric was given to students in advance: then it is not changed for this class, and your answers apply to the next one."
            />
          </div>
          <p className="settings-actions">
            <BusyButton
              className="button button-primary"
              busy={send.busy}
              disabled={left > 0}
              onClick={() => {
                void send.run(
                  "examples answer",
                  {
                    package_version: version,
                    answers,
                    rubric_published_in_advance: inAdvance,
                  },
                  {
                    onDone: () => {
                      read.retry();
                      onDone();
                    },
                  },
                );
              }}
            >
              Send my answers
            </BusyButton>
            <DisabledReason
              reason={left > 0 ? `Answer every question: ${left} still to answer.` : null}
            />
          </p>
        </div>
      )}
    </section>
  );
}

function QuestionCard({
  question,
  open,
  chosen,
  words,
  onChoose,
  onWords,
}: {
  question: ExampleQuestion;
  open: boolean;
  chosen: string | null;
  words: string;
  onChoose: (value: string) => void;
  onWords: (value: string) => void;
}) {
  const choiceIds = useFieldIds();
  const wordsIds = useFieldIds();
  return (
    <article className="examples-question">
      <h3>{question.heading}</h3>
      <p>{question.text}</p>
      {question.descriptor !== "" && (
        <p className="blind-descriptor">
          The description of “{question.level}” now: {question.descriptor}
        </p>
      )}
      <div className="examples-pair">
        {question.examples.map((example) => (
          <div key={example.example} className="examples-side">
            <p className="step-name">{example.example}</p>
            <blockquote className="blind-answer">
              {example.answer.trim() !== "" ? example.answer : "No answer text could be read."}
            </blockquote>
            <p className="blind-yours">You: {example.your_mark}</p>
            <p className="blind-system">The system: {example.system_mark}</p>
          </div>
        ))}
      </div>
      {open && (
        <fieldset className="blind-levels" aria-describedby={choiceIds.formatId}>
          <legend>Your answer</legend>
          {[...question.options, OWN_WORDS].map((option) => (
            <label key={option} className="blind-level">
              <input
                type="radio"
                name={`question-${question.question_id}`}
                value={option}
                checked={chosen === option}
                onChange={() => onChoose(option)}
              />{" "}
              {option === OWN_WORDS ? "In my own words" : optionLabel(option)}
            </label>
          ))}
          <FormatLine id={choiceIds.formatId} spec={FORMAT_CHOOSE_ONE} />
          {chosen === OWN_WORDS && (
            <div className="settings-row">
              <label htmlFor={wordsIds.id}>How you meant it</label>
              <textarea
                {...wordsIds.control}
                rows={2}
                maxLength={500}
                value={words}
                onChange={(event) => onWords(event.target.value)}
              />
              <FormatLine id={wordsIds.formatId} spec={`${FORMAT_FREE_TEXT}, up to 500 characters`} />
            </div>
          )}
        </fieldset>
      )}
    </article>
  );
}
