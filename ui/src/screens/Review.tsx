import { useState } from "react";
import {
  performAction,
  type ActionResult,
  type QueueGroup,
  type QueueItem,
  type ReviewQueue as ReviewQueueDoc,
} from "../api";
import { FieldError, FormatLine, useFieldIds } from "../components/Field";
import { BusyButton, DisabledReason, isRefused, plainText, textOutcome, useOutcome } from "../components/Outcome";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useScreenRead } from "../useScreenRead";
import { sharedNames, studentLabel } from "../studentNames";
import { useRunParams } from "../selection";
import { checkField, type FieldSpec } from "../wizard/vocabulary";

/**
 * The review queue (FR-UI-47, the HLD's S9): "I have [ 30 ] minutes" with **Go** rebuilds the
 * queue for that budget through `GET /api/v1/review-queue` (FR-CONSOLE-91 — M-REVIEW ranks and
 * groups; this screen never re-sorts). The header states the four numbers in the HLD's words;
 * groups render above items, each group with three of its papers side by side, the level
 * choices with the current one marked, **Apply to all <n>** (one `review group action`,
 * FR-CONSOLE-92) and **Review one by one**. Each item renders feedback first, then "What the
 * paper shows", then the level choices (the package's own levels, the panel's choices marked),
 * then **Accept / Change / Skip** (`review action`), then "Flagged because: …" (FR-UI-48's
 * order: the words before the mark). No numeric input anywhere (CT-UI-12): the budget is a
 * text field checked against its stated range. The blind sample is never listed here; it is
 * its own screen one click away (inv. 15).
 */

/** The budget field's spec, from the range the read serves (FR-CONSOLE-91: 1…480). */
function budgetSpec(range: [number, number] | undefined): FieldSpec {
  const [min, max] = range ?? [1, 480];
  return { kind: "whole_number", min, max, format: `A whole number from ${min} to ${max} minutes` };
}

/** The header's three sentences (FR-UI-47), with the service's numbers. */
export function queueHeader(doc: ReviewQueueDoc): string {
  const budget = doc.budget_minutes ?? 0;
  const reserved = doc.reserved_for_blind_minutes;
  const shown = doc.shown_total ?? doc.shown.length;
  return (
    `${reserved} of those ${budget} minutes are reserved for the blind sample and spent there. ` +
    `These are the ${shown} highest-value answers of ${doc.flagged_total} flagged, in the other ` +
    `${Math.max(0, budget - reserved)}. ` +
    `The remaining ${doc.residual_provisional} stay provisional and in your queue.`
  );
}

/** The rubric line's slot in a heading: its own name in the package, said once and only when
 * it is not the question's label already. */
function lineName(entry: { question_label: string; criterion_label: string }): string | null {
  return entry.criterion_label !== "" && entry.criterion_label !== entry.question_label
    ? `line ${entry.criterion_label}`
    : null;
}

/** "Q1 · line C1a" — the question, then the rubric line when it says more. */
function whereText(entry: { question_label: string; criterion_label: string }): string {
  const line = lineName(entry);
  return line === null ? entry.question_label : `${entry.question_label} · ${line}`;
}

/**
 * One queue post: busy while in flight, the outcome reported to the banner in the screen's own
 * words — the server's accept/edit sentences carry internal references, so the screen says
 * what happened by the student's name — and the queue re-read after a landed action.
 */
function useQueueAction(onLanded: () => void) {
  const { report, clear } = useOutcome();
  const [busy, setBusy] = useState(false);
  const post = (
    action: string,
    body: Record<string, unknown>,
    said: (result: ActionResult) => string,
    refusedSaid: (result: ActionResult) => string,
  ): void => {
    setBusy(true);
    clear();
    void performAction(action, body)
      .catch((failure: unknown): ActionResult => ({
        action,
        error: failure instanceof Error ? failure.message : String(failure),
      }))
      .then((result) => {
        setBusy(false);
        // The generic action path reports a domain refusal as `dispatched: false` without
        // `refused`, so both count as "not marked".
        const landed = !isRefused(result) && result.dispatched !== false;
        report(landed ? textOutcome(said(result)) : textOutcome(refusedSaid(result), true));
        // A refusal re-reads too: whatever was refused (a stale or already-marked answer)
        // the queue the teacher sees must be the one standing now.
        onLanded();
      });
  };
  return { busy, post };
}

export function Review() {
  const runParams = useRunParams();
  const [budget, setBudget] = useState<number | null>(null);
  const read = useScreenRead<ReviewQueueDoc>(
    "/api/v1/review-queue",
    { ...(runParams ?? {}), ...(budget === null ? {} : { budget_minutes: String(budget) }) },
  );
  const navigate = useNavigate();
  return (
    <ReadScreen title="Review queue" read={read}>
      {(data) => {
        const entries = data.entries ?? [];
        const groups = entries.filter((entry): entry is QueueGroup => entry.kind === "group");
        const items = entries.filter((entry): entry is QueueItem => entry.kind === "item");
        // One student appears once per flagged line, so names are told apart across distinct
        // students only — the same student twice is not two people sharing a name.
        const students = new Map<string, QueueItem>();
        for (const entry of [...items, ...groups.flatMap((group) => group.sample)]) {
          students.set(entry.student_ref ?? entry.submission_id, entry);
        }
        const shared = sharedNames([...students.values()]);
        return (
          <>
            <BudgetForm
              key={data.budget_minutes ?? "default"}
              current={data.budget_minutes ?? data.default_budget_minutes ?? 30}
              range={data.budget_range}
              onGo={(minutes) => {
                // Go always rebuilds: the same budget twice re-reads rather than doing nothing.
                if (minutes === budget) {
                  read.retry();
                } else {
                  setBudget(minutes);
                }
              }}
            />
            <p className="hub-state review-header" data-review-header="">
              {queueHeader(data)}
            </p>
            <p className="review-blind-link">
              <a href="#/review/blind" onClick={() => navigate("/review/blind")}>
                Open the blind sample
              </a>{" "}
              <span className="step-note">— it has its own screen and is never listed here.</span>
            </p>
            {entries.length === 0 && (
              <p className="panel">
                {data.flagged_total === 0
                  ? "Nothing is flagged for review."
                  : "No answer fits in this time. Give the queue more minutes and press Go."}
              </p>
            )}
            {groups.length > 0 && (
              <ul className="review-groups">
                {groups.map((group) => (
                  <li key={group.group_signature}>
                    <GroupCard group={group} runId={data.run_id} shared={shared} onLanded={read.retry} />
                  </li>
                ))}
              </ul>
            )}
            {items.length > 0 && (
              <ul className="review-items">
                {items.map((item) => (
                  <li key={`${item.submission_id}-${item.criterion_id}`}>
                    <ItemCard item={item} runId={data.run_id} shared={shared} onLanded={read.retry} />
                  </li>
                ))}
              </ul>
            )}
          </>
        );
      }}
    </ReadScreen>
  );
}

/** "I have [ 30 ] minutes" **Go** — a text field checked against the stated range (no numeric
 * input, CT-UI-12); Go rebuilds the queue for the typed budget. */
function BudgetForm({
  current,
  range,
  onGo,
}: {
  current: number;
  range: [number, number] | undefined;
  onGo: (minutes: number) => void;
}) {
  const [value, setValue] = useState(String(current));
  const [error, setError] = useState<string | null>(null);
  const ids = useFieldIds(error);
  const spec = budgetSpec(range);
  const go = (): void => {
    const said = value.trim();
    const problem = said === "" ? checkField(spec, "x") : checkField(spec, said);
    setError(problem);
    if (problem === null) {
      onGo(Number(said));
    }
  };
  return (
    <form
      className="review-budget"
      onSubmit={(event) => {
        event.preventDefault();
        go();
      }}
    >
      <label htmlFor={ids.id}>I have</label>{" "}
      <input
        {...ids.control}
        type="text"
        name="budget-minutes"
        size={4}
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />{" "}
      <span>minutes</span>{" "}
      <button type="submit" className="button button-primary">
        Go
      </button>
      <FormatLine id={ids.formatId} spec={spec} />
      <FieldError id={ids.errorId} error={error} />
    </form>
  );
}

/** The level choices (FR-UI-47): the package's own levels as radios, the current one checked,
 * and beside each the graders who chose it. The marks shown are all inside this control. */
function LevelChoices({
  name,
  legend,
  levels,
  proposed,
  chosen,
  panel,
  busy,
  onChoose,
}: {
  name: string;
  legend: string;
  levels: string[];
  proposed: string;
  chosen: string;
  panel: { grader: string; band: string }[];
  busy: boolean;
  onChoose: (band: string) => void;
}) {
  const ids = useFieldIds();
  const offered = levels.includes(proposed) || proposed === "" ? levels : [...levels, proposed];
  return (
    <fieldset
      className="review-levels"
      data-band-control=""
      aria-describedby={ids.formatId}
      aria-busy={busy || undefined}
    >
      <legend>{legend}</legend>
      {offered.map((level) => {
        const by = panel.filter((choice) => choice.band === level).map((choice) => choice.grader);
        return (
          <label key={level} className="review-level">
            <input
              type="radio"
              name={name}
              value={level}
              checked={chosen === level}
              disabled={busy}
              onChange={() => onChoose(level)}
            />{" "}
            <span className={level === proposed ? "band-value" : undefined}>{level}</span>
            {level === proposed && <span className="band-note"> (proposed)</span>}
            {by.length > 0 && <span className="review-panel"> — chosen by {by.join(", ")}</span>}
          </label>
        );
      })}
      <FormatLine id={ids.formatId} spec="Choose one level" />
    </fieldset>
  );
}

/** One answer (FR-UI-47/48): feedback, quotes, level choices, Accept / Change / Skip, then why
 * it is flagged — in that DOM order. */
function ItemCard({
  item,
  runId,
  shared,
  onLanded,
}: {
  item: QueueItem;
  runId: string;
  shared: Set<string>;
  onLanded: () => void;
}) {
  const [chosen, setChosen] = useState(item.proposed_band);
  const { busy, post } = useQueueAction(onLanded);
  const name = studentLabel(item, shared, "this student");
  const changed = chosen !== item.proposed_band;
  const body = {
    run_id: runId,
    submission_id: item.submission_id,
    criterion_id: item.criterion_id,
    revision: item.revision,
  };
  const refusedSaid = (result: ActionResult): string =>
    result.refresh_required === true
      ? `${name}'s answer changed since the queue was built, so it was not marked. ` +
        "The queue now shows it as it stands."
      : `${name}'s answer could not be marked; it may already be reviewed. The queue now ` +
        "shows what is still waiting.";
  return (
    <article className="criterion-card review-item" data-component="review-item">
      <h2 className="review-item-head">
        {name} <span className="step-note">· {whereText(item)}</span>
      </h2>
      <p className="narrative-text review-feedback">
        {item.narrative !== null && item.narrative.trim() !== ""
          ? item.narrative
          : "No feedback was written for this answer."}
      </p>
      <Quotes quotes={item.quotes} />
      <LevelChoices
        name={`level-${item.submission_id}-${item.criterion_id}`}
        legend="The level"
        levels={item.levels}
        proposed={item.proposed_band}
        chosen={chosen}
        panel={item.panel}
        busy={busy}
        onChoose={setChosen}
      />
      <p className="review-actions">
        <BusyButton
          className="button button-primary"
          busy={busy}
          disabled={changed}
          onClick={() =>
            post("review action", { ...body, decision: "accept" },
              () => `${name}'s answer is marked ${item.proposed_band}, as proposed.`, refusedSaid)
          }
        >
          Accept
        </BusyButton>{" "}
        <BusyButton
          busy={busy}
          disabled={!changed}
          onClick={() =>
            post("review action", { ...body, decision: "edit", new_band: chosen },
              () => `${name}'s answer is marked ${chosen}, changed from ${item.proposed_band}.`,
              refusedSaid)
          }
        >
          Change
        </BusyButton>{" "}
        <BusyButton
          busy={busy}
          onClick={() =>
            post("review action", { ...body, decision: "skip" },
              () => `Skipped for now: ${name}'s answer stays in your queue.`,
              refusedSaid)
          }
        >
          Skip
        </BusyButton>{" "}
        <DisabledReason
          reason={changed
            ? "You chose another level: press Change to mark it, or choose the proposed level to accept."
            : "Choose another level above to change it."}
        />
      </p>
      <p className="review-why">
        Flagged because:{" "}
        {item.why_flagged.length > 0
          ? item.why_flagged.join(", ")
          : "the system could not settle it on its own"}
      </p>
    </article>
  );
}

/** "What the paper shows": the quotes the graders cited. */
function Quotes({ quotes, limit = 4 }: { quotes: string[]; limit?: number }) {
  return (
    <div className="evidence">
      <h4>What the paper shows</h4>
      {quotes.length === 0 ? (
        <p className="step-note">The graders quoted nothing from the paper.</p>
      ) : (
        <ul>
          {quotes.slice(0, limit).map((quote, index) => (
            <li key={index}>
              <blockquote>“{quote}”</blockquote>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** One group (FR-UI-47): the pattern, three papers side by side, the level choices with the
 * current one marked, **Apply to all <n>** (one `review group action`) and **Review one by
 * one** (the members, each to its own student page). */
function GroupCard({
  group,
  runId,
  shared,
  onLanded,
}: {
  group: QueueGroup;
  runId: string;
  shared: Set<string>;
  onLanded: () => void;
}) {
  const navigate = useNavigate();
  const [chosen, setChosen] = useState(group.proposed_band);
  const [oneByOne, setOneByOne] = useState(false);
  const { busy, post } = useQueueAction(onLanded);
  const memberNames = sharedNames(group.members);
  return (
    <article className="criterion-card review-group" data-component="review-group">
      <h2 className="review-item-head">
        {group.size} students · {group.question_label}
        {lineName(group) !== null && ` · ${lineName(group)}`} — all show the same pattern
      </h2>
      <p className="review-pattern">{group.pattern}</p>
      <ul className="review-sample">
        {group.sample.map((member) => (
          <li key={member.submission_id} className="review-paper">
            <strong>{studentLabel(member, shared, "A student")}</strong>
            {member.quotes.length > 0 ? (
              <blockquote>“{member.quotes[0]}”</blockquote>
            ) : (
              <p className="step-note">No words quoted from this paper.</p>
            )}
          </li>
        ))}
      </ul>
      <LevelChoices
        name={`group-level-${group.group_signature}`}
        legend={`The level for all ${group.size}`}
        levels={group.levels}
        proposed={group.proposed_band}
        chosen={chosen}
        panel={[]}
        busy={busy}
        onChoose={setChosen}
      />
      <p className="review-actions">
        <BusyButton
          className="button button-primary"
          busy={busy}
          onClick={() =>
            post(
              "review group action",
              { run_id: runId, group_signature: group.group_signature, band: chosen },
              (result) => plainText(result.detail ?? "") ||
                `${group.size} answers marked ${chosen} as one decision.`,
              (result) => plainText(result.detail || result.error || "") ||
                "Nothing was marked. The queue now shows what is still waiting.",
            )
          }
        >
          Apply to all {group.size}
        </BusyButton>{" "}
        <button
          type="button"
          className="button"
          aria-expanded={oneByOne}
          onClick={() => setOneByOne((open) => !open)}
        >
          Review one by one
        </button>
      </p>
      {oneByOne && (
        <ul className="rows-list review-members">
          {group.members.map((member) => (
            <li key={member.submission_id}>
              <a
                className="step-name"
                href={`#/results/students/${member.submission_id}`}
                onClick={() => navigate(`/results/students/${member.submission_id}`)}
              >
                {studentLabel(member, memberNames, "A student")}
              </a>
            </li>
          ))}
        </ul>
      )}
      <p className="review-why">
        Flagged because:{" "}
        {group.why_flagged.length > 0
          ? group.why_flagged.join(", ")
          : "the system could not settle these on its own"}
      </p>
    </article>
  );
}
