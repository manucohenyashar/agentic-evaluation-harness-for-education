import { useState } from "react";
import {
  performAction,
  type ActionResult,
  type AuthoringDraftDoc,
  type DraftPlaceholder,
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
 * The review screen (FR-UI-12): the draft as the teacher reads it — the outline with
 * every missing piece highlighted in place, the list of what each one needs, and the
 * answer form that takes them one at a time through the enumerated review control.
 * Approval stays blocked, with the count, while any piece stands. The read re-polls on
 * the shell's cadence, so an answer's effect shows without a reload (`ADR-47`).
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
      {placeholder.reason ? ` (${placeholder.reason})` : ""}
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

/** One missing piece's answer form: one at a time — the piece the teacher opened takes
 * its answer, the send goes through the enumerated review control, and the read's next
 * poll shows what the answer changed. */
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

export function ReviewDraft({ packageId }: { packageId: string | null }) {
  const navigate = useNavigate();
  const action = useActionState();
  const [openItem, setOpenItem] = useState<string | null>(null);
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
        const missing = draft.missing_pieces;
        return (
          <>
            <DraftOutline draft={draft} />
            <section aria-label="Missing pieces" className="missing-section">
              <h2>Missing pieces</h2>
              {missing === 0 ? (
                <p>None — the draft is ready to approve.</p>
              ) : (
                <>
                  <p>
                    {missingPiecesLabel(missing)} stand in the draft. Answer them one at
                    a time below; approval waits until every one is answered.
                  </p>
                  <ul className="placeholder-list">
                    {draft.placeholders.map((placeholder, index) => (
                      <li key={index} className="placeholder-row">
                        <span>
                          {placeholderLocationLabel(placeholder.location, draft.items)}
                          {placeholder.reason ? ` — ${placeholder.reason}` : ""}
                        </span>{" "}
                        <button
                          type="button"
                          className="button"
                          aria-pressed={openItem === placeholder.item_id}
                          onClick={() =>
                            setOpenItem(
                              openItem === placeholder.item_id ? null : placeholder.item_id,
                            )
                          }
                        >
                          {openItem === placeholder.item_id ? "Close" : "Answer"}
                        </button>
                        {openItem === placeholder.item_id && (
                          <AnswerForm
                            placeholder={placeholder}
                            draft={draft}
                            onDone={(result) => {
                              action.finish(result);
                              // The answer either landed (the read's next poll shows
                              // the piece gone) or was not accepted (the console's own
                              // wording says so) — either way the form closes.
                              setOpenItem(null);
                            }}
                          />
                        )}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
            <section aria-label="Approval" className="approve-section">
              <h2>Approve the package</h2>
              {missing > 0 ? (
                <p className="refusal-shape">
                  <strong>The package cannot be approved yet.</strong>{" "}
                  {missingPiecesLabel(missing)} still stand in the draft.{" "}
                  Answer them under Missing pieces above, then approve.
                </p>
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
