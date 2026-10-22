import { useState } from "react";
import { CircleCheck } from "lucide-react";
import {
  performAction,
  type ActionResult,
  type AuthoringDraftDoc,
  type DraftPlaceholder,
  type PackageSummary,
} from "../api";
import { ConfirmDialog, useActionState } from "../components/Confirm";
import { describedBy, errorIdFor, FieldError, FormatLine, formatIdFor } from "../components/Field";
import { BusyButton, DisabledReason, useOutcome } from "../components/Outcome";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";
import { useNavigate } from "../navigate";
import {
  checkField,
  criterionLabel,
  FORMAT_FREE_TEXT,
  type FieldSpec,
  entryFieldLabel,
  missingPiecesLabel,
  placeholderLocationLabel,
  questionLabel,
  questionTypeLabel,
} from "../wizard/vocabulary";

/**
 * The review screen (FR-UI-12, FR-AUTHOR-31): the draft as the teacher reads it — the
 * outline with every missing piece highlighted in place, then the missing pieces asked
 * one plain question at a time ("A few questions before you approve"), the whole package
 * as it would be published (FR-UI-26), and the approve gate. After a successful approve
 * the screen shows FR-CONSOLE-73's banner with the Load papers link, and a reload keeps
 * it (the read serves the approved state). The read re-polls on the shell's cadence, so
 * an answer's effect shows without a reload (`ADR-47`).
 */

/** Where a missing piece stands in the outline: its question's or grading point's index
 * when the location names one, so the highlight lands inside that entry's own card. */
function placeholderEntry(location: string): { kind: string; index: number } | null {
  const match = /^(question|criterion)\[(\d+)\]/.exec(location.trim());
  return match === null ? null : { kind: match[1] ?? "", index: Number(match[2]) };
}

/** One outline card's inline highlight: a missing piece stands here, named by where it
 * is and what to supply — the wording the review walk itself uses. */
function PlaceholderMark({
  placeholder,
  items,
}: {
  placeholder: DraftPlaceholder;
  items: { id: string }[];
}) {
  return (
    <p className="placeholder-mark">
      <span className="placeholder-chip">Missing piece</span>{" "}
      {placeholderLocationLabel(placeholder.location, items)}
      {placeholder.supply ? ` — ${placeholder.supply}` : ""}
    </p>
  );
}

/** The draft outline: the questions and grading points in order, each with its own
 * missing pieces highlighted inline, and the grade table's pieces under it. */
function DraftOutline({ draft }: { draft: NonNullable<AuthoringDraftDoc["draft"]> }) {
  return (
    <div className="outline">
      <h2>The draft</h2>
      {draft.items.map((question, index) => (
        <div key={question.id} className="outline-entry">
          <h3>{questionLabel(question.id)}</h3>
          <p className="outline-text">
            {question.text === "" ? "(no question text yet)" : question.text}
          </p>
          <p className="outline-meta">
            {questionTypeLabel(question.type)}
            {question.points !== null ? `, ${question.points} point(s)` : ""}
          </p>
          {question.options.length > 0 && (
            <ul className="outline-options">
              {question.options.map((letter) => (
                <li key={letter}>
                  {letter}. {question.option_labels?.[letter] ?? ""}
                </li>
              ))}
            </ul>
          )}
          {question.model_answer !== null && question.model_answer !== "" && (
            <p className="outline-answer">
              Expected answer: {question.model_answer}
            </p>
          )}
          {draft.placeholders
            .map((placeholder, order) => ({ placeholder, order }))
            .filter(({ placeholder }) => {
              const entry = placeholderEntry(placeholder.location);
              return entry !== null && entry.kind === "question" &&
                entry.index === index;
            })
            .map(({ placeholder, order }) => (
              <PlaceholderMark key={order} placeholder={placeholder} items={draft.items} />
            ))}
        </div>
      ))}
      {draft.criteria.map((criterion, index) => (
        <div key={criterion.id} className="outline-entry">
          <h3>{criterionLabel(criterion.id)}</h3>
          <p className="outline-meta">
            Grades {criterion.question === "" ? "no question yet" : questionLabel(criterion.question)}
            {criterion.points !== null ? `, ${criterion.points} point(s)` : ""}
          </p>
          {criterion.key !== undefined && criterion.key !== null && (
            <p className="outline-meta">
              Answer key: {Array.isArray(criterion.key) ? criterion.key.join(", ") : criterion.key}
            </p>
          )}
          {criterion.score_levels.length > 0 && (
            <ul className="outline-options">
              {criterion.score_levels.map((band) => (
                <li key={band.name}>
                  {band.name} ({band.points} point(s)){band.descriptor !== "" ? ` — ${band.descriptor}` : ""}
                </li>
              ))}
            </ul>
          )}
          {draft.placeholders
            .map((placeholder, order) => ({ placeholder, order }))
            .filter(({ placeholder }) => {
              const entry = placeholderEntry(placeholder.location);
              return entry !== null && entry.kind === "criterion" &&
                entry.index === index;
            })
            .map(({ placeholder, order }) => (
              <PlaceholderMark key={order} placeholder={placeholder} items={draft.items} />
            ))}
        </div>
      ))}
      {draft.placeholders
        .map((placeholder, order) => ({ placeholder, order }))
        .filter(({ placeholder }) => placeholderEntry(placeholder.location) === null)
        .map(({ placeholder, order }) => (
          <PlaceholderMark key={order} placeholder={placeholder} items={draft.items} />
        ))}
      {draft.issues.length > 0 && (
        <div className="outline-issues">
          <h3>Things to check</h3>
          <ul>
            {draft.issues.map((issue, index) => (
              <li key={index}>
                {entryFieldLabel(issue.field)} — {issue.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** The current question's answer form (FR-AUTHOR-31): one question at a time, the send
 * goes through the enumerated review control, and the read's next poll asks the next
 * question. The field's refusal is checked before anything is sent, and the typed value
 * stays while the refusal stands. */
function AnswerForm({
  placeholder,
  draft,
  onDone,
}: {
  placeholder: DraftPlaceholder;
  draft: NonNullable<AuthoringDraftDoc["draft"]>;
  onDone: (result: ActionResult) => void;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const { clear } = useOutcome();
  const spec = answerSpec(placeholder);
  const error = checkField(spec, value);
  const id = "answer-value";
  const send = (): void => {
    setBusy(true);
    clear();
    performAction("answer authoring review", {
      package_id: draft.package_id,
      item_id: placeholder.item_id,
      value,
    }).then(
      (result) => {
        setBusy(false);
        onDone(result);
      },
      (failure: unknown) => {
        setBusy(false);
        onDone({
          action: "answer authoring review",
          error: failure instanceof Error ? failure.message : String(failure),
        });
      },
    );
  };
  const label = placeholder.question
    ? placeholder.question
    : `Your answer for ${placeholderLocationLabel(placeholder.location, draft.items)}`;
  const reason =
    value.trim() === "" ? "Type your answer first."
      : error !== null ? "Fix your answer first." : null;
  const control = {
    id,
    "aria-describedby": describedBy(id, error),
    "aria-invalid": error !== null || undefined,
    value,
    onChange: (event: { target: { value: string } }) => setValue(event.target.value),
  };
  return (
    <div className="answer-form">
      <label htmlFor={id}>{label}</label>
      {!placeholder.question && placeholder.supply !== "" && (
        <p className="answer-supply">{placeholder.supply}</p>
      )}
      {spec.kind === "whole_number" ? (
        <input {...control} type="text" inputMode="numeric" placeholder="e.g. 6" />
      ) : (
        <textarea {...control} />
      )}
      <FormatLine id={formatIdFor(id)} spec={spec} />
      <FieldError id={errorIdFor(id)} error={error} />
      <p>
        <BusyButton
          className="button button-primary"
          disabled={reason !== null}
          busy={busy}
          onClick={send}
        >
          Send the answer
        </BusyButton>
        <DisabledReason reason={busy ? null : reason} />
      </p>
    </div>
  );
}

/** The answer's one definition (FR-UI-36, FR-AUTHOR-31): the kind and limits the read
 * serves beside the gap, so the format line and the field's check say the same range the
 * server re-checks. A gap the read gives no kind for is free text. */
function answerSpec(placeholder: DraftPlaceholder): FieldSpec {
  const hint = (placeholder.answer_hint ?? "").replace(/\.\s*$/, "");
  if (
    placeholder.answer_kind === "whole_number" &&
    typeof placeholder.answer_min === "number" &&
    typeof placeholder.answer_max === "number"
  ) {
    return {
      kind: "whole_number",
      min: placeholder.answer_min,
      max: placeholder.answer_max,
      format: hint || undefined,
    };
  }
  if (placeholder.answer_kind === "yes_no") {
    return { kind: "text", format: hint || "Yes or no", pattern: /^(yes|no)$/i };
  }
  return {
    kind: "text",
    format: hint || FORMAT_FREE_TEXT,
    minLength: placeholder.answer_min ?? undefined,
    maxLength: placeholder.answer_max ?? undefined,
  };
}

/** One summary value, as the read serves it: the display text and, when the teacher
 * supplied it at review, the "your answer" marker (FR-UI-26). A score-levels array reads
 * as one line ("full loop (2), broken loop (0)"); an unanswered value's text is the
 * served "Not answered yet". */
function SummaryValue({ piece }: { piece: { value: unknown; source: string | null } }) {
  const value = piece.value;
  const text = value === null || value === undefined ? "Not answered yet"
    : Array.isArray(value)
      ? (value.every((entry) => typeof entry === "string")
        ? (value as string[]).join(", ")
        : asScoreLevels(value))
      : typeof value === "object" ? "Not answered yet"
      : String(value);
  return (
    <>
      {text}
      {piece.source === "your answer" && <span className="summary-source"> (your answer)</span>}
    </>
  );
}

/** The whole package (FR-CONSOLE-72, FR-UI-26): the summary the read serves, above the
 * Approve button and in its reading order — Test, Approved by, the grade table, the
 * questions with their points and the total, and how each question is scored. Every
 * value's source travels with it; an unanswered piece reads "Not answered yet" in place. */
function PackageSummaryView({ summary }: { summary: PackageSummary }) {
  const passRow = summary.grades.rows.find(
    (row) => row.grade.trim().toLowerCase() === "pass" && row.answered,
  );
  return (
    <section aria-label="The whole package" className="summary-section">
      <h2>The whole package</h2>
      <p className="summary-line">
        <strong>Test</strong> <SummaryValue piece={summary.test} />
      </p>
      <p className="summary-line">
        <strong>Approved by</strong> <SummaryValue piece={summary.approver} />
      </p>
      {passRow ? (
        <p className="summary-line">
          <strong>Passing score</strong> {String(passRow.lowest_total)} of {summary.grades.max}
          {passRow.source === "your answer" && <span className="summary-source"> (your answer)</span>}
        </p>
      ) : summary.grades.rows.length > 0 ? (
        <div className="summary-line">
          <strong>The grades</strong>
          <ul className="summary-grades">
            {summary.grades.rows.map((row) => (
              <li key={row.grade}>
                {row.grade}: {row.answered ? `${String(row.lowest_total)} of ${summary.grades.max}` : "Not answered yet"}
                {row.source === "your answer" && <span className="summary-source"> (your answer)</span>}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="summary-line">
          <strong>The grades</strong> {summary.grades.value ?? "Not answered yet"}
        </p>
      )}
      <div className="summary-line">
        <strong>Questions</strong>
        <ul className="summary-questions">
          {summary.questions.map((question) => (
            <li key={question.number}>
              {question.number}. <SummaryValue piece={question.text} /> —{" "}
              <SummaryValue piece={question.points} />
              {question.points.answered ? " point(s)" : ""},{" "}
              <SummaryValue piece={question.type} />
              {question.correct_option !== undefined && question.correct_option.answered && (
                <>
                  {" "}
                  — correct answer <SummaryValue piece={question.correct_option} />
                </>
              )}
            </li>
          ))}
        </ul>
        <p>
          {summary.points_complete
            ? `${summary.total_points} points in total`
            : "Not answered yet — the total waits on a question's points"}
        </p>
      </div>
      <div className="summary-line">
        <strong>How each question is scored</strong>
        <ul className="summary-scoring">
          {summary.questions.map((question) => (
            <li key={question.number}>
              {question.number}.{" "}
              {question.rubric.length === 0
                ? "No grading point yet"
                : question.rubric.map((line, index) => (
                    <span key={line.criterion_id}>
                      {index > 0 && "; "}
                      {line.correct_option !== undefined && (
                        <SummaryValue piece={line.correct_option} />
                      )}
                      {line.levels !== undefined && (
                        <SummaryValue piece={line.levels} />
                      )}
                    </span>
                  ))}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/** Score levels as the summary carries them — `[{name, points, descriptor}]` — read as
 * one line: "full loop (2), broken loop (0)". A non-array reads as its served text. */
function asScoreLevels(value: unknown): string {
  if (!Array.isArray(value)) {
    return typeof value === "string" ? value : "";
  }
  return value
    .map((band: { name?: unknown; points?: unknown }) =>
      `${String(band.name ?? "")}${band.points !== null && band.points !== undefined ? ` (${String(band.points)})` : ""}`)
    .join(", ");
}

/** The gaps in one queue (FR-AUTHOR-31): the placeholder gaps, then the question-points
 * gaps the read serves beside them — same shape, same answer action. A gap whose question
 * waits on another answer first (FR-AUTHOR-32: a grade floor needs the questions' points)
 * counts toward the total but takes no turn until its wait clears. */
function questionQueue(draft: NonNullable<AuthoringDraftDoc["draft"]>): DraftPlaceholder[] {
  return [...draft.placeholders, ...(draft.points_questions ?? [])];
}

export function ReviewDraft({ packageId }: { packageId: string | null }) {
  const navigate = useNavigate();
  const action = useActionState();
  const read = useScreenRead<AuthoringDraftDoc>(
    "/api/v1/authoring/draft",
    packageId ? { package_id: packageId } : undefined,
    3000,
  );

  const approve = (draftPackageId: string): void => {
    action.open({
      title: "Approve and build the package",
      description:
        "The console will build the package from the draft as it stands and record the " +
        "approval. A built package never changes afterwards.",
      confirm: "Approve the package",
      action: "approve draft package",
      body: { package_id: draftPackageId },
    });
  };

  return (
    <ReadScreen title="Review the draft" read={read}>
      {(data) => {
        const draft = data.draft;
        if (draft === null) {
          return (
            <p>
              No draft stands here yet. Make one from your documents on the{" "}
              <a href="#/package/author" onClick={() => navigate("/package/author")}>
                authoring screen
              </a>
              .
            </p>
          );
        }
        const gaps = questionQueue(draft);
        const answerable = gaps.filter((gap) => (gap.waiting_on?.length ?? 0) === 0);
        const waiting = gaps.filter((gap) => (gap.waiting_on?.length ?? 0) > 0);
        const current: DraftPlaceholder | null = answerable.length > 0
          ? answerable[0] ?? null
          : null;
        const published = draft.published ?? null;
        return (
          <>
            {published !== null && (
              <div className="outcome-banner outcome-done">
                <CircleCheck size={18} aria-hidden="true" />
                <p role="status" className="action-outcome">
                  <strong className="outcome-what">{published.detail}</strong>
                </p>
              </div>
            )}
            <DraftOutline draft={draft} />
            <section aria-label="Questions to answer" className="gaps-section">
              <h2>A few questions before you approve</h2>
              {current === null && gaps.length === 0 ? (
                <p>None — the draft is ready to approve.</p>
              ) : current === null ? (
                <>
                  {/* Every standing question waits on another answer first: each names
                      itself in its own served words and opens once its wait clears (the
                      read's next poll). No input here — the answer's range is not known
                      yet, which the question's own hint says. */}
                  {waiting.map((gap) => (
                    <div key={gap.item_id} className="answer-form">
                      <label>{gap.question}</label>
                      <p className="answer-supply">{gap.answer_hint}</p>
                    </div>
                  ))}
                </>
              ) : (
                <>
                  <p>
                    Question {answerable.indexOf(current) + 1} of {answerable.length}.
                  </p>
                  <AnswerForm
                    key={current.item_id}
                    placeholder={current}
                    draft={draft}
                    onDone={(result) => {
                      action.finish(result);
                      // The answer either landed (the read's next poll asks the next
                      // question) or was not accepted (the console's own wording says
                      // so) — either way the form closes.
                    }}
                  />
                </>
              )}
            </section>
            {draft.summary !== undefined && <PackageSummaryView summary={draft.summary} />}
            <section aria-label="Approval" className="approve-section">
              <h2>Approve the package</h2>
              {published !== null ? (
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => navigate(published.next.route)}
                >
                  {published.next.label}
                </button>
              ) : gaps.length > 0 ? (
                <>
                  <button type="button" className="button button-primary" disabled>
                    Approve the package
                  </button>
                  <DisabledReason
                    reason={`The package cannot be approved yet. ${missingPiecesLabel(gaps.length)} still stand in the draft. Answer them under A few questions above, then approve.`}
                  />
                </>
              ) : (
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => approve(draft.package_id)}
                >
                  Approve the package
                </button>
              )}
            </section>
            <section aria-label="Start again" className="redraft-section">
              <h2>Not what you meant?</h2>
              <p>
                You can make the draft again from your documents. The answers you
                already gave are kept where the content still matches, and you will be
                asked to confirm the kept ones.
              </p>
              <button
                type="button"
                className="button"
                onClick={() => navigate("/package/author")}
              >
                Re-draft from my documents
              </button>{" "}
              <a
                href="#/package/edit"
                onClick={() => navigate("/package/edit")}
                className="stage-action"
              >
                Edit the draft instead
              </a>
            </section>
            {action.pending !== null && (
              <ConfirmDialog
                pending={action.pending}
                onClose={action.close}
                onDone={action.finish}
              />
            )}
          </>
        );
      }}
    </ReadScreen>
  );
}
