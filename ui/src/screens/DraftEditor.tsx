import { useMemo, useState } from "react";
import {
  performAction,
  type AuthoringDraftDoc,
  type DraftCriterion,
  type DraftQuestion,
  type ImpactDoc,
} from "../api";
import { ActionOutcome, ConfirmDialog, useActionState } from "../components/Confirm";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useScreenRead, type ScreenRead } from "../useScreenRead";
import {
  criterionLabel,
  entryFieldLabel,
  questionLabel,
  questionTypeLabel,
} from "../wizard/vocabulary";

/**
 * The editor (FR-UI-13): forms over the draft's structure, working against the
 * enumerated structured-edit surface — one operation at a time, each through `edit
 * draft package`. Every change is staged in the page and shown as a before/after list
 * in the teacher's language before the save is confirmed; the score levels are band
 * selections only, so no numeric entry ever stands on them, and a published package's
 * impact banner comes from the impact read before any edit begins. Validation renders
 * next to the field it is about, in the same vocabulary.
 */

/** One staged change: the enumerated operation and its body, plus the teacher-language
 * line the change list shows before the save. */
interface StagedOp {
  key: number;
  label: string;
  body: Record<string, unknown>;
}

const QUESTION_TYPES = ["mcq", "mixed", "open"] as const;

/** The issues the draft already carries that are about one entry, so each renders next
 * to that entry's own form. */
function issuesFor(
  issues: { field: string; message: string }[],
  kind: string,
  id: string,
): { field: string; message: string }[] {
  const prefix = `${kind} '${id}'`;
  return issues.filter((issue) => issue.field.startsWith(prefix));
}

/** The dedupe key a staged change carries: editing the same field of the same entry
 * twice replaces the earlier staged change rather than stacking two contradictory
 * ones. */
function dedupeKey(body: Record<string, unknown>): string | null {
  const operation = typeof body.operation === "string" ? body.operation : "";
  if (operation === "edit question" || operation === "edit criterion") {
    const field = typeof body.field === "string" ? body.field : "";
    return `${operation}:${String(body.item_id)}:${field}`;
  }
  if (operation === "add option" || operation === "remove option") {
    return `${operation}:${String(body.item_id)}:${String(body.letter)}`;
  }
  return null;
}

// --- the cards' content keys ---------------------------------------------------------------------------

/** A question card's React key: the entry's id **and** the server values the card's
 * form fields initialize from. The card keeps its edits in local state, so keying on
 * the id alone would let a refreshed read arrive with new server values while the form
 * still showed the old ones — and staging from that stale form would silently revert
 * the just-saved change. A changed server value changes the key, which remounts the
 * card on the fresh values. */
function questionCardKey(question: DraftQuestion): string {
  return [
    question.id,
    question.text,
    question.type,
    question.points === null ? "" : String(question.points),
    question.model_answer ?? "",
    question.options.join(","),
  ].join("|");
}

/** The grading-point card's key, for the same reason: its form initializes from the
 * criterion's question, points, key and score levels, so all of them belong in it. */
function criterionCardKey(criterion: DraftCriterion): string {
  return [
    criterion.id,
    criterion.question,
    criterion.points === null ? "" : String(criterion.points),
    criterion.key === undefined || criterion.key === null
      ? "" : JSON.stringify(criterion.key),
    criterion.score_levels.map((band) => `${band.name}:${band.points}`).join(","),
  ].join("|");
}

// --- the question card -------------------------------------------------------------------------------

function QuestionCard({
  question,
  index,
  count,
  issues,
  onStage,
  onApplyNow,
  onDelete,
}: {
  question: DraftQuestion;
  index: number;
  count: number;
  issues: { field: string; message: string }[];
  onStage: (label: string, body: Record<string, unknown>) => void;
  onApplyNow: (body: Record<string, unknown>) => void;
  onDelete: (label: string, body: Record<string, unknown>) => void;
}) {
  const name = questionLabel(question.id);
  const [text, setText] = useState(question.text);
  const [type, setType] = useState(
    QUESTION_TYPES.includes(question.type as (typeof QUESTION_TYPES)[number])
      ? question.type
      : "open",
  );
  const [points, setPoints] = useState(question.points === null ? "" : String(question.points));
  const [answer, setAnswer] = useState(question.model_answer ?? "");
  const [newLetter, setNewLetter] = useState("");
  const [newLabel, setNewLabel] = useState("");

  const changed =
    text !== question.text ||
    type !== question.type ||
    (points !== "" && Number(points) !== question.points) ||
    answer !== (question.model_answer ?? "");

  const save = (): void => {
    if (text !== question.text) {
      onStage(
        `${name} — the question text: "${question.text}" becomes "${text}"`,
        { operation: "edit question", item_id: question.id, field: "text", value: text },
      );
    }
    if (type !== question.type) {
      onStage(
        `${name} — the question type: ${questionTypeLabel(question.type)} becomes ${questionTypeLabel(type)}`,
        { operation: "edit question", item_id: question.id, field: "type", value: type },
      );
    }
    if (points !== "" && Number(points) !== question.points) {
      onStage(
        `${name} — the points: ${question.points ?? "none"} becomes ${Number(points)}`,
        {
          operation: "edit question", item_id: question.id,
          field: "points", value: Number(points),
        },
      );
    }
    if (answer !== (question.model_answer ?? "")) {
      onStage(
        `${name} — the expected answer: "${question.model_answer ?? "(none)"}" becomes "${answer}"`,
        {
          operation: "edit question", item_id: question.id,
          field: "model_answer", value: answer,
        },
      );
    }
    setText(question.text);
    setType(QUESTION_TYPES.includes(question.type as (typeof QUESTION_TYPES)[number])
      ? question.type : "open");
    setPoints(question.points === null ? "" : String(question.points));
    setAnswer(question.model_answer ?? "");
  };

  const addOption = (): void => {
    const letter = newLetter.trim().toUpperCase();
    onStage(
      `${name} — added option ${letter}: "${newLabel.trim()}"`,
      { operation: "add option", item_id: question.id, letter, label: newLabel.trim() },
    );
    setNewLetter("");
    setNewLabel("");
  };

  return (
    <div className="editor-card">
      <h3>{name}</h3>
      {issues.map((issue, i) => (
        <p key={i} className="field-error">
          {entryFieldLabel(issue.field)} — {issue.message}
        </p>
      ))}
      <label htmlFor={`q-text-${index}`}>The question</label>
      <textarea
        id={`q-text-${index}`}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <label htmlFor={`q-type-${index}`}>The question type</label>
      <select
        id={`q-type-${index}`}
        value={type}
        onChange={(event) => setType(event.target.value)}
      >
        {QUESTION_TYPES.map((value) => (
          <option key={value} value={value}>
            {questionTypeLabel(value)}
          </option>
        ))}
      </select>
      <label htmlFor={`q-points-${index}`}>The points</label>
      <input
        id={`q-points-${index}`}
        type="number"
        min={0}
        value={points}
        onChange={(event) => setPoints(event.target.value)}
      />
      <label htmlFor={`q-answer-${index}`}>The expected answer</label>
      <textarea
        id={`q-answer-${index}`}
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
      />
      {changed && (
        <p>
          <button type="button" className="button" onClick={save}>
            Stage the changes to this question
          </button>
        </p>
      )}
      {(question.options.length > 0 || question.type === "mcq" || question.type === "mixed") && (
        <div className="editor-options">
          <h4>The answer options</h4>
          <ul>
            {question.options.map((letter) => (
              <li key={letter}>
                {letter}. {question.option_labels?.[letter] ?? ""}{" "}
                <button
                  type="button"
                  className="button"
                  onClick={() =>
                    onStage(
                      `${name} — removed option ${letter}`,
                      { operation: "remove option", item_id: question.id, letter },
                    )
                  }
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
          <label htmlFor={`q-newletter-${index}`}>New option's letter</label>{" "}
          <input
            id={`q-newletter-${index}`}
            type="text"
            maxLength={1}
            size={2}
            value={newLetter}
            onChange={(event) => setNewLetter(event.target.value)}
          />{" "}
          <label htmlFor={`q-newlabel-${index}`}>What the option says</label>{" "}
          <input
            id={`q-newlabel-${index}`}
            type="text"
            value={newLabel}
            onChange={(event) => setNewLabel(event.target.value)}
          />{" "}
          <button
            type="button"
            className="button"
            disabled={newLetter.trim() === "" || newLabel.trim() === ""}
            onClick={addOption}
          >
            Add the option
          </button>
        </div>
      )}
      <p className="editor-card-actions">
        <button
          type="button"
          className="button"
          disabled={index === 0}
          onClick={() =>
            onApplyNow({
              operation: "move question", item_id: question.id, position: index,
            })
          }
        >
          Move up
        </button>{" "}
        <button
          type="button"
          className="button"
          disabled={index === count - 1}
          onClick={() =>
            onApplyNow({
              operation: "move question", item_id: question.id, position: index + 2,
            })
          }
        >
          Move down
        </button>{" "}
        <button
          type="button"
          className="button"
          onClick={() =>
            onDelete(
              `${name} — removed, with the grading points that grade it`,
              { operation: "delete question", item_id: question.id },
            )
          }
        >
          Remove this question
        </button>
      </p>
    </div>
  );
}

// --- the grading-point card ---------------------------------------------------------------------------

function CriterionCard({
  criterion,
  index,
  count,
  items,
  criteria,
  issues,
  onStage,
  onApplyNow,
  onDelete,
}: {
  criterion: DraftCriterion;
  index: number;
  count: number;
  items: DraftQuestion[];
  criteria: DraftCriterion[];
  issues: { field: string; message: string }[];
  onStage: (label: string, body: Record<string, unknown>) => void;
  onApplyNow: (body: Record<string, unknown>) => void;
  onDelete: (label: string, body: Record<string, unknown>) => void;
}) {
  const name = criterionLabel(criterion.id);
  const owner = items.find((question) => question.id === criterion.question);
  const [questionId, setQuestionId] = useState(criterion.question);
  const [points, setPoints] = useState(criterion.points === null ? "" : String(criterion.points));
  const [copyFrom, setCopyFrom] = useState("");

  const saveQuestion = (): void => {
    if (questionId !== criterion.question) {
      onStage(
        `${name} — now grades ${questionLabel(questionId)}`,
        {
          operation: "edit criterion", item_id: criterion.id,
          field: "question", value: questionId,
        },
      );
      setQuestionId(criterion.question);
    }
  };

  const setKey = (letters: string[]): void => {
    onStage(
      `${name} — the answer key: ${letters.join(", ")}`,
      { operation: "edit criterion", item_id: criterion.id, field: "key", value: letters },
    );
  };

  // The score levels are band selections only (`FR-UI-13`: no numeric entry, ever):
  // the teacher picks a set the draft already carries, and the set travels to the
  // server exactly as the read showed it.
  const useLevelsFrom = (): void => {
    const source = criteria.find((entry) => entry.id === copyFrom);
    if (source === undefined) {
      return;
    }
    onStage(
      `${name} — the score levels become the levels of ${criterionLabel(source.id)}`,
      {
        operation: "edit criterion", item_id: criterion.id, field: "bands",
        value: source.score_levels.map((band) => ({
          name: band.name, points: band.points, descriptor: band.descriptor,
        })),
      },
    );
    setCopyFrom("");
  };

  const savePoints = (): void => {
    if (points !== "" && Number(points) !== criterion.points) {
      onStage(
        `${name} — the points: ${criterion.points ?? "none"} becomes ${Number(points)}`,
        {
          operation: "edit criterion", item_id: criterion.id,
          field: "points", value: Number(points),
        },
      );
      setPoints(criterion.points === null ? "" : String(criterion.points));
    }
  };

  const chosenKey = criterion.key === undefined || criterion.key === null
    ? []
    : Array.isArray(criterion.key) ? criterion.key : [String(criterion.key)];

  return (
    <div className="editor-card">
      <h3>{name}</h3>
      {issues.map((issue, i) => (
        <p key={i} className="field-error">
          {entryFieldLabel(issue.field)} — {issue.message}
        </p>
      ))}
      <label htmlFor={`c-question-${index}`}>The question it grades</label>{" "}
      <select
        id={`c-question-${index}`}
        value={questionId}
        onChange={(event) => setQuestionId(event.target.value)}
      >
        {items.map((question) => (
          <option key={question.id} value={question.id}>
            {questionLabel(question.id)}
          </option>
        ))}
      </select>{" "}
      {questionId !== criterion.question && (
        <button type="button" className="button" onClick={saveQuestion}>
          Stage the change
        </button>
      )}
      <div className="editor-options">
        <h4>The points it carries</h4>
        <label htmlFor={`c-points-${index}`}>The points</label>{" "}
        <input
          id={`c-points-${index}`}
          type="number"
          min={0}
          value={points}
          onChange={(event) => setPoints(event.target.value)}
        />{" "}
        {points !== "" && Number(points) !== criterion.points && (
          <button type="button" className="button" onClick={savePoints}>
            Stage the change
          </button>
        )}
      </div>
      {owner !== undefined && owner.options.length > 0 && (
        <div className="editor-options">
          <h4>The answer key</h4>
          <p className="editor-card-note">
            Choose the option(s) the correct answer is. Setting a key replaces the score
            levels; a graded point's score levels replace the key.
          </p>
          {chosenKey.length > 0 && (
            <p className="editor-card-note">Chosen now: {chosenKey.join(", ")}</p>
          )}
          {owner.options.map((letter) => (
            <p key={letter}>
              <label>
                <input
                  type="checkbox"
                  checked={chosenKey.includes(letter)}
                  onChange={(event) => {
                    const next = event.target.checked
                      ? [...chosenKey.filter((item) => item !== letter), letter].sort()
                      : chosenKey.filter((item) => item !== letter);
                    if (next.length > 0) {
                      setKey(next);
                    }
                  }}
                />{" "}
                {letter}. {owner.option_labels?.[letter] ?? ""}
              </label>
            </p>
          ))}
        </div>
      )}
      <div className="editor-options">
        <h4>The score levels</h4>
        <ul>
          {criterion.score_levels.map((band) => (
            <li key={band.name}>
              {band.name} — {band.points} point(s)
              {band.descriptor !== "" ? ` — ${band.descriptor}` : ""}
            </li>
          ))}
        </ul>
        <p className="editor-card-note">
          The score levels are chosen, never typed: pick a set the draft already
          carries. To add a brand-new level, answer the draft's missing pieces on the
          review screen.
        </p>
        <label htmlFor={`c-bands-${index}`}>Use the score levels of</label>{" "}
        <select
          id={`c-bands-${index}`}
          value={copyFrom}
          onChange={(event) => setCopyFrom(event.target.value)}
        >
          <option value="">(choose a grading point)</option>
          {criteria
            .filter((entry) => entry.id !== criterion.id && entry.score_levels.length > 0)
            .map((entry) => (
              <option key={entry.id} value={entry.id}>
                {criterionLabel(entry.id)}
              </option>
            ))}
        </select>{" "}
        <button
          type="button"
          className="button"
          disabled={copyFrom === ""}
          onClick={useLevelsFrom}
        >
          Stage the change
        </button>
      </div>
      <p className="editor-card-actions">
        <button
          type="button"
          className="button"
          disabled={index === 0}
          onClick={() =>
            onApplyNow({
              operation: "move criterion", item_id: criterion.id, position: index,
            })
          }
        >
          Move up
        </button>{" "}
        <button
          type="button"
          className="button"
          disabled={index === count - 1}
          onClick={() =>
            onApplyNow({
              operation: "move criterion", item_id: criterion.id, position: index + 2,
            })
          }
        >
          Move down
        </button>{" "}
        <button
          type="button"
          className="button"
          onClick={() =>
            onDelete(
              `${name} — removed`,
              { operation: "delete criterion", item_id: criterion.id },
            )
          }
        >
          Remove this grading point
        </button>
      </p>
    </div>
  );
}

// --- the add form -------------------------------------------------------------------------------------

/** A new question's form: staged as one "add question" operation, with its options
 * when the teacher wrote any. */
function AddQuestionForm({
  onStage,
}: {
  onStage: (label: string, body: Record<string, unknown>) => void;
}) {
  const [text, setText] = useState("");
  const [type, setType] = useState("open");
  const [points, setPoints] = useState("");
  const [answer, setAnswer] = useState("");
  const [labels, setLabels] = useState<string[]>(["", "", "", ""]);
  const LETTERS = ["A", "B", "C", "D"];
  const options = labels
    .map((label, index) => [LETTERS[index] ?? "", label] as const)
    .filter(([, label]) => label.trim() !== "");
  const add = (): void => {
    onStage(
      `Added a question: "${text.trim()}"`,
      {
        operation: "add question",
        text: text.trim(),
        type,
        ...(points !== "" ? { points: Number(points) } : {}),
        ...(options.length > 0
          ? { options: Object.fromEntries(options.map(([letter, label]) => [letter, label.trim()])) }
          : {}),
        ...(answer.trim() !== "" ? { model_answer: answer.trim() } : {}),
      },
    );
    setText("");
    setType("open");
    setPoints("");
    setAnswer("");
    setLabels(["", "", "", ""]);
  };
  return (
    <div className="editor-card">
      <h3>Add a question</h3>
      <label htmlFor="add-q-text">The question</label>
      <textarea
        id="add-q-text"
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <label htmlFor="add-q-type">The question type</label>
      <select id="add-q-type" value={type} onChange={(event) => setType(event.target.value)}>
        {QUESTION_TYPES.map((value) => (
          <option key={value} value={value}>
            {questionTypeLabel(value)}
          </option>
        ))}
      </select>
      <label htmlFor="add-q-points">The points</label>
      <input
        id="add-q-points"
        type="number"
        min={0}
        value={points}
        onChange={(event) => setPoints(event.target.value)}
      />
      <label htmlFor="add-q-answer">The expected answer</label>
      <textarea
        id="add-q-answer"
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
      />
      {type !== "open" && (
        <div className="editor-options">
          <h4>The answer options</h4>
          {LETTERS.map((letter, index) => (
            <p key={letter}>
              <label htmlFor={`add-q-opt-${letter}`}>{letter}</label>{" "}
              <input
                id={`add-q-opt-${letter}`}
                type="text"
                value={labels[index] ?? ""}
                onChange={(event) => setLabels(labels.map((item, i) =>
                  i === index ? event.target.value : item))}
              />
            </p>
          ))}
        </div>
      )}
      <p>
        <button
          type="button"
          className="button"
          disabled={text.trim() === ""}
          onClick={add}
        >
          Stage the new question
        </button>
      </p>
    </div>
  );
}

/** A new grading point's form. A grading point grades one question by one of two
 * shapes, and the server's `add criterion` takes exactly those two: by the question's
 * answer key (the chosen options, with the points a right answer carries) or by a set
 * of score levels the draft already carries — copied, never typed, because the score
 * levels are band selections only (`FR-UI-13`: no numeric entry stands on them). When
 * the question carries no options and the draft carries no score levels, neither shape
 * can stand, and the form says where score levels come from rather than taking a
 * grading point it could not grade with. */
function AddCriterionForm({
  items,
  criteria,
  onStage,
}: {
  items: DraftQuestion[];
  criteria: DraftCriterion[];
  onStage: (label: string, body: Record<string, unknown>) => void;
}) {
  const [questionId, setQuestionId] = useState(items[0]?.id ?? "");
  const [points, setPoints] = useState("");
  const [copyFrom, setCopyFrom] = useState("");
  const [keyLetters, setKeyLetters] = useState<string[]>([]);
  const owner = items.find((question) => question.id === questionId);
  const withLevels = criteria.filter((entry) => entry.score_levels.length > 0);
  const keyPossible = owner !== undefined && owner.options.length > 0;

  const addByKey = (): void => {
    if (owner === undefined || keyLetters.length === 0) return;
    const letters = [...keyLetters].sort();
    onStage(
      `Added a grading point for ${questionLabel(questionId)} — graded by its ` +
        `answer key: ${letters.join(", ")}`,
      {
        operation: "add criterion",
        question: questionId,
        key: letters,
        ...(points !== "" ? { points: Number(points) } : {}),
      },
    );
    setKeyLetters([]);
    setPoints("");
  };

  const addWithLevels = (): void => {
    const source = withLevels.find((entry) => entry.id === copyFrom);
    if (source === undefined) return;
    onStage(
      `Added a grading point for ${questionLabel(questionId)} — graded by the score ` +
        `levels of ${criterionLabel(source.id)}`,
      {
        operation: "add criterion",
        question: questionId,
        bands: source.score_levels.map((band) => ({
          name: band.name, points: band.points, descriptor: band.descriptor,
        })),
      },
    );
    setCopyFrom("");
  };

  if (items.length === 0) {
    return (
      <div className="editor-card">
        <h3>Add a grading point</h3>
        <p className="editor-card-note">
          A grading point grades one of the questions. Add a question first.
        </p>
      </div>
    );
  }
  return (
    <div className="editor-card">
      <h3>Add a grading point</h3>
      <label htmlFor="add-c-question">The question it grades</label>{" "}
      <select
        id="add-c-question"
        value={questionId}
        onChange={(event) => setQuestionId(event.target.value)}
      >
        {items.map((question) => (
          <option key={question.id} value={question.id}>
            {questionLabel(question.id)}
          </option>
        ))}
      </select>
      {keyPossible && owner !== undefined && (
        <div className="editor-options">
          <h4>Grade it by its answer key</h4>
          {owner.options.map((letter) => (
            <p key={letter}>
              <label>
                <input
                  type="checkbox"
                  checked={keyLetters.includes(letter)}
                  onChange={(event) =>
                    setKeyLetters(event.target.checked
                      ? [...keyLetters, letter]
                      : keyLetters.filter((item) => item !== letter))}
                />{" "}
                {letter}. {owner.option_labels?.[letter] ?? ""}
              </label>
            </p>
          ))}
          <label htmlFor="add-c-points">The points a right answer carries</label>{" "}
          <input
            id="add-c-points"
            type="number"
            min={0}
            value={points}
            onChange={(event) => setPoints(event.target.value)}
          />{" "}
          <button
            type="button"
            className="button"
            disabled={keyLetters.length === 0}
            onClick={addByKey}
          >
            Stage the grading point
          </button>
        </div>
      )}
      {withLevels.length > 0 && (
        <div className="editor-options">
          <h4>Or grade it by score levels</h4>
          <label htmlFor="add-c-bands">Use the score levels of</label>{" "}
          <select
            id="add-c-bands"
            value={copyFrom}
            onChange={(event) => setCopyFrom(event.target.value)}
          >
            <option value="">(choose a grading point)</option>
            {withLevels.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {criterionLabel(entry.id)}
              </option>
            ))}
          </select>{" "}
          <button
            type="button"
            className="button"
            disabled={copyFrom === ""}
            onClick={addWithLevels}
          >
            Stage the grading point
          </button>
        </div>
      )}
      {!keyPossible && withLevels.length === 0 && (
        <p className="editor-card-note">
          A written question is graded by score levels, and this draft carries none to
          copy. Score levels come from your documents: start the draft from your files
          on the authoring screen, or give the question answer choices and grade it by
          its key.
        </p>
      )}
    </div>
  );
}

/** The save's confirm: the staged changes listed before/after, in the teacher's
 * language, and nothing posted until the confirming button is pressed. The apply
 * itself sends the staged operations one at a time, so this dialog only decides. */
function SaveConfirmDialog({
  staged,
  onClose,
  onConfirm,
}: {
  staged: StagedOp[];
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <div role="dialog" aria-modal="true" aria-label="Save your changes" className="dialog">
      <h2>Save your changes</h2>
      <p>
        The console will apply these changes to the draft, in the order listed. The
        draft is re-validated after the save; anything it still refuses comes back
        named.
      </p>
      <ul className="change-list">
        {staged.map((op) => (
          <li key={op.key}>{op.label}</li>
        ))}
      </ul>
      <div className="dialog-actions">
        <button type="button" className="button" onClick={onClose}>
          Cancel
        </button>
        <button type="button" className="button button-primary" onClick={onConfirm}>
          Save the changes
        </button>
      </div>
    </div>
  );
}

export function DraftEditor({
  packageId,
  publishedVersion,
  impact,
}: {
  packageId: string | null;
  publishedVersion: string | null;
  impact: ScreenRead<ImpactDoc>;
}) {
  const navigate = useNavigate();
  const action = useActionState();
  const read = useScreenRead<AuthoringDraftDoc>(
    "/api/v1/authoring/draft",
    packageId ? { package_id: packageId } : undefined,
  );
  const [staged, setStaged] = useState<StagedOp[]>([]);
  const [nextKey, setNextKey] = useState(1);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState<string[] | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [deletePending, setDeletePending] = useState<StagedOp | null>(null);

  // Staging a change replaces an earlier staged change to the same field of the same
  // entry — the list never shows two contradictory intentions for one spot.
  const stage = (label: string, body: Record<string, unknown>): void => {
    const key = dedupeKey(body);
    setStaged((current) => [
      ...current.filter((op) => key === null || dedupeKey(op.body) !== key),
      { key: nextKey, label, body },
    ]);
    setNextKey((n) => n + 1);
  };

  // One immediate, non-staged operation — a move — applied at once through the same
  // enumerated surface, and the read re-run so the outline moves with it. A dropped
  // connection is caught here, not left as an unhandled rejection with the saving state
  // stuck on: the change was not sent, and the screen says so.
  const applyNow = async (body: Record<string, unknown>): Promise<void> => {
    const draftId = read.data?.draft?.package_id ?? "";
    setApplying(true);
    try {
      const result = await performAction("edit draft package", {
        package_id: draftId, ...body,
      });
      action.finish(result);
      if (result.refused !== true && result.error === undefined) {
        read.retry();
      }
    } catch (failure: unknown) {
      action.finish({
        action: "edit draft package",
        error: `the console could not be reached (${
          failure instanceof Error ? failure.message : String(failure)
        }); the change was not sent. Check that the console service is running.`,
      });
    } finally {
      setApplying(false);
    }
  };

  const saveAll = async (): Promise<void> => {
    const ops = staged;
    const draftId = read.data?.draft?.package_id ?? "";
    setSaveOpen(false);
    setApplying(true);
    const lines: string[] = [];
    let stopped = false;
    try {
      for (const op of ops) {
        const result = await performAction("edit draft package", {
          package_id: draftId, ...op.body,
        });
        if (result.refused === true || result.error !== undefined) {
          lines.push(
            `Refused: ${result.error ?? result.detail ?? "the console gave no reason."} — ` +
              "the changes after this one were not sent.",
          );
          stopped = true;
          break;
        }
        lines.push(result.detail ?? "done.");
      }
    } catch (failure: unknown) {
      lines.push(
        `The console could not be reached (${
          failure instanceof Error ? failure.message : String(failure)
        }) — the changes after this one were not sent. Check that the console service ` +
          "is running, then save again.",
      );
      stopped = true;
    } finally {
      setApplying(false);
    }
    setApplied(lines);
    // A save that was refused or interrupted part-way keeps the changes it never
    // sent, so the teacher can correct and save again; a complete save clears the list.
    if (!stopped) {
      setStaged([]);
    }
    read.retry();
  };

  const draft = read.data?.draft ?? null;
  const generalIssues = useMemo(
    () =>
      (draft?.issues ?? []).filter(
        (issue) =>
          !draft?.items.some((question) =>
            issue.field.startsWith(`question '${question.id}'`)) &&
          !draft?.criteria.some((criterion) =>
            issue.field.startsWith(`criterion '${criterion.id}'`)),
      ),
    [draft],
  );

  return (
    <ReadScreen title="Edit the package" read={read}>
      {() => {
        if (draft === null) {
          return (
            <p>
              No draft stands here yet. Make one from your documents, or start an empty
              one, on the{" "}
              <a href="#/package/author" onClick={() => navigate("/package/author")}>
                authoring screen
              </a>
              .
            </p>
          );
        }
        return (
          <>
            {publishedVersion !== null && (
              <div role="alert" className="impact-banner">
                {impact.data !== null ? (
                  <p>
                    This package version is published: {impact.data.runs} grading run(s)
                    have used it and {impact.data.students} students were graded under
                    it. {impact.data.regrading.detail}
                  </p>
                ) : impact.error !== null ? (
                  <p>
                    The impact read did not answer ({impact.error}). Check that the
                    console service is running.
                  </p>
                ) : (
                  <p>Reading the published version's impact.</p>
                )}
                <p>
                  Editing the draft does not change the published version — a built
                  package is never changed. Approving this edited draft will not publish
                  it over the published version: the console will ask for the edits to go
                  out as a new draft under a new package name instead. The published
                  version stays exactly as it is, and the runs already graded under it
                  stay graded under it.
                </p>
                {impact.data !== null && impact.data.run_records.length > 0 && (
                  <div>
                    <h3>The runs already graded under it</h3>
                    <ul className="change-list">
                      {impact.data.run_records.map((record) => (
                        <li key={record.run_id}>
                          {record.run_id} — {record.state} (cohort {record.cohort_id})
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {generalIssues.length > 0 && (
              <div className="outline-issues">
                <h2>Things to check</h2>
                <ul>
                  {generalIssues.map((issue, index) => (
                    <li key={index}>
                      {entryFieldLabel(issue.field)} — {issue.message}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <section aria-label="Questions" className="editor-section">
              <h2>Questions</h2>
              {draft.items.map((question, index) => (
                <QuestionCard
                  key={questionCardKey(question)}
                  question={question}
                  index={index}
                  count={draft.items.length}
                  issues={issuesFor(draft.issues, "question", question.id)}
                  onStage={stage}
                  onApplyNow={(body) => void applyNow(body)}
                  onDelete={(label, body) =>
                    setDeletePending({ key: 0, label, body })}
                />
              ))}
              <AddQuestionForm onStage={stage} />
            </section>
            <section aria-label="Grading points" className="editor-section">
              <h2>Grading points</h2>
              {draft.criteria.length === 0 && (
                <p>No grading points stand in the draft yet.</p>
              )}
              {draft.criteria.map((criterion, index) => (
                <CriterionCard
                  key={criterionCardKey(criterion)}
                  criterion={criterion}
                  index={index}
                  count={draft.criteria.length}
                  items={draft.items}
                  criteria={draft.criteria}
                  issues={issuesFor(draft.issues, "criterion", criterion.id)}
                  onStage={stage}
                  onApplyNow={(body) => void applyNow(body)}
                  onDelete={(label, body) =>
                    setDeletePending({ key: 0, label, body })}
                />
              ))}
              <AddCriterionForm
                items={draft.items}
                criteria={draft.criteria}
                onStage={stage}
              />
            </section>
            <section aria-label="The grade table" className="editor-section">
              <h2>The grade table</h2>
              <p className="editor-card-note">
                The grade table stands as the draft carries it. Its missing pieces are
                answered on the review screen.
              </p>
            </section>
            <section aria-label="Your changes" className="pending-section">
              <h2>Your changes</h2>
              {staged.length === 0 && applied === null && <p>Nothing changed yet.</p>}
              {staged.length > 0 && (
                <>
                  <ul className="change-list">
                    {staged.map((op) => (
                      <li key={op.key}>{op.label}</li>
                    ))}
                  </ul>
                  <p>
                    <button
                      type="button"
                      className="button button-primary"
                      disabled={applying}
                      onClick={() => setSaveOpen(true)}
                    >
                      Review changes ({staged.length})
                    </button>
                  </p>
                </>
              )}
              {applied !== null && (
                <div className="change-list change-list-applied">
                  <h3>What the last save changed</h3>
                  <ul>
                    {applied.map((line, index) => (
                      <li key={index}>{line}</li>
                    ))}
                  </ul>
                </div>
              )}
              {applying && <p>Saving.</p>}
            </section>
            {saveOpen && (
              <SaveConfirmDialog
                staged={staged}
                onClose={() => setSaveOpen(false)}
                onConfirm={() => void saveAll()}
              />
            )}
            {deletePending !== null && (
              <ConfirmDialog
                pending={{
                  title: "Remove it from the draft",
                  description: `${deletePending.label}. The draft on disk keeps everything else.`,
                  confirm: "Remove",
                  action: "edit draft package",
                  body: deletePending.body,
                }}
                onClose={() => setDeletePending(null)}
                onDone={(result) => {
                  setDeletePending(null);
                  action.finish(result);
                  if (result.refused !== true && result.error === undefined) {
                    read.retry();
                  }
                }}
              />
            )}
            <p className="editor-footer">
              <a href="#/package/review" onClick={() => navigate("/package/review")}>
                Back to the review
              </a>{" "}·{" "}
              <button type="button" className="button" onClick={() => navigate("/")}>
                Back to the wizard
              </button>
            </p>
          </>
        );
      }}
    </ReadScreen>
  );
}
