import { useEffect, useState } from "react";
import {
  type BlindSeat,
  type BlindSeats as BlindSeatsDoc,
  type ValidityDisagreement,
  type ValidityDoc,
} from "../api";
import { ConfirmDialog, useActionState } from "../components/Confirm";
import { FormatLine, useFieldIds } from "../components/Field";
import { BusyButton, isRefused, useReportedAction } from "../components/Outcome";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useScreenRead } from "../useScreenRead";
import { useRunParams } from "../selection";
import { FORMAT_CHOOSE_ONE } from "../wizard/vocabulary";

/**
 * The blind sample (FR-UI-40/41, FR-CONSOLE-83): M-REVIEW's seats for the run, each with the
 * student's name, the question, the student's answer (and **View the page** for the scan) and
 * the question's levels as choices, each with its description — nothing the system decided
 * about the answer. Choosing a level saves a draft ("blind-sample draft") and the progress
 * line counts it; nothing counts until **Finish** ("blind-sample finish"), which asks first
 * when answers are still unmarked. **Skip** ("blind-sample skip") closes the sample with no
 * marks. Once the sample is finished the screen shows the comparison: each marked answer's
 * level beside the system's, differences first, then **See the results**.
 *
 * There is no link to a student page here: the student page shows the system's mark.
 */
export function BlindSample() {
  const read = useScreenRead<BlindSeatsDoc>("/api/v1/blind-seats", useRunParams());
  const navigate = useNavigate();
  const skip = useReportedAction();
  const finish = useActionState(read.retry);
  return (
    <ReadScreen title="Blind sample" read={read}>
      {(data) => {
        const { marked, total } = data.progress;
        if (data.state !== "open" || total === 0) {
          return <ClosedSample data={data} />;
        }
        const unmarked = total - marked;
        return (
          <>
            <p className="blind-progress" aria-live="polite">
              {marked} of {total} marked
            </p>
            <p className="hub-state">
              Read each answer and choose the level you would give it, without the system's
              mark. Your choices are saved as you go; they count when you finish.
            </p>
            <p className="blind-actions">
              <button
                type="button"
                className="button button-primary"
                disabled={marked === 0 || skip.busy}
                onClick={() =>
                  finish.open({
                    title: "Finish the blind sample",
                    description:
                      unmarked > 0
                        ? `Finish with ${unmarked} ${unmarked === 1 ? "answer" : "answers"} unmarked? Only the ones you marked will count.`
                        : `Finish with all ${total} answers marked? Your marks can't be changed afterwards.`,
                    confirm: "Finish",
                    action: "blind-sample finish",
                    body: { run_id: data.run_id },
                  })
                }
              >
                Finish
              </button>{" "}
              <BusyButton
                className="button"
                busy={skip.busy}
                onClick={() => {
                  void skip.run("blind-sample skip", { run_id: data.run_id }, {
                    onDone: () => navigate("/results"),
                  });
                }}
              >
                Skip and see results
              </BusyButton>
              {marked === 0 && (
                <span className="disabled-reason"> Mark at least one answer to finish.</span>
              )}
            </p>
            <ol className="blind-seats">
              {data.seats.map((seat) => (
                <li key={seat.seat_id}>
                  <BlindSeatCard seat={seat} runId={data.run_id} onSaved={read.retry} />
                </li>
              ))}
            </ol>
            {finish.pending !== null && (
              <ConfirmDialog
                pending={finish.pending}
                onClose={finish.close}
                onDone={finish.finish}
              />
            )}
          </>
        );
      }}
    </ReadScreen>
  );
}

/** The scan's address for one of a seat's pages (served only while the draw is open). */
function pageHref(runId: string, seatId: string, page: number): string {
  return `/blind-page?${new URLSearchParams({
    run_id: runId,
    seat: seatId,
    page: String(page),
  }).toString()}`;
}

/**
 * One seat (FR-UI-40): whose answer and which question, the answer itself with its scan, and
 * the levels as choices with their descriptions. The seat component is shared by the marked
 * examples step (FR-UI-44), hence its `data-component`.
 */
export function BlindSeatCard({
  seat,
  runId,
  onSaved,
}: {
  seat: BlindSeat;
  runId: string;
  onSaved: () => void;
}) {
  const { busy, run } = useReportedAction();
  const ids = useFieldIds();
  const [chosen, setChosen] = useState<string | null>(seat.draft_band);
  // The read is the truth: a re-read (after a save, or a reload) sets the choice it holds.
  useEffect(() => setChosen(seat.draft_band), [seat.draft_band]);

  const choose = (band: string): void => {
    setChosen(band);
    void run(
      "blind-sample draft",
      { run_id: runId, seat_id: seat.seat_id, band },
      { onDone: onSaved, toast: false },
    ).then((result) => {
      if (isRefused(result)) {
        setChosen(seat.draft_band);
      }
    });
  };

  return (
    <article className="blind-seat" data-component="blind-seat">
      <h2 className="blind-seat-head">
        {seat.student_name ?? "A student"} — {seat.question}
      </h2>
      <blockquote className="blind-answer">
        {seat.answer_text !== null && seat.answer_text.trim() !== ""
          ? seat.answer_text
          : "No answer text could be read for this question; view the page to read it."}
      </blockquote>
      {seat.page_refs.length > 0 && (
        <p className="blind-pages">
          {seat.page_refs.map((page, index) => (
            <span key={page}>
              {index > 0 && " "}
              <a
                className="button"
                href={pageHref(runId, seat.seat_id, page)}
                target="_blank"
                rel="noopener noreferrer"
              >
                {seat.page_refs.length === 1 ? "View the page" : `View the page (page ${page})`}
              </a>
            </span>
          ))}
        </p>
      )}
      <fieldset className="blind-levels" aria-describedby={ids.formatId} aria-busy={busy || undefined}>
        <legend>Your level</legend>
        {seat.bands.map((band) => (
          <label key={band.name} className="blind-level">
            <input
              type="radio"
              name={`seat-band-${seat.seat_id}`}
              value={band.name}
              checked={chosen === band.name}
              disabled={busy}
              onChange={() => choose(band.name)}
            />{" "}
            <strong>{band.name}</strong>
            {band.descriptor ? <span className="blind-descriptor"> — {band.descriptor}</span> : null}
          </label>
        ))}
      </fieldset>
      <FormatLine id={ids.formatId} spec={`${FORMAT_CHOOSE_ONE}. Saved as you choose; you can change it until you finish.`} />
    </article>
  );
}

/** The sample once it is closed: the comparison after Finish (or the review window's end),
 * the skip's sentence after a Skip, or that there was nothing to mark — then the results. */
function ClosedSample({ data }: { data: BlindSeatsDoc }) {
  const navigate = useNavigate();
  const toResults = (
    <p>
      <button type="button" className="button button-primary" onClick={() => navigate("/results")}>
        See the results
      </button>
    </p>
  );
  if (data.state === "skipped") {
    return (
      <>
        <p className="hub-state">
          You skipped the blind sample. Every mark stays as it is; there is no new evidence about
          how accurate the marking is.
        </p>
        {toResults}
      </>
    );
  }
  if (data.state === "finished" || data.state === "closed_by_window") {
    return (
      <>
        <Comparison data={data} />
        {toResults}
      </>
    );
  }
  return (
    <>
      <p className="hub-state">There are no answers to mark in this sample.</p>
      {toResults}
    </>
  );
}

/** One marked answer in the comparison: the teacher's level, the system's, and how they
 * differ. */
interface Compared {
  seat: BlindSeat;
  yours: string;
  /** The system's level, or null when the read pairs none with this answer. */
  system: string | null;
  difference: ValidityDisagreement | null;
}

function directionSentence(difference: ValidityDisagreement): string {
  if (difference.direction === "more_credit") return "The system gave more credit than you.";
  if (difference.direction === "less_credit") return "The system gave less credit than you.";
  return "The system gave a different level.";
}

/**
 * The comparison (FR-UI-41): each answer the teacher marked, "You: <level>" beside "The
 * system: <level>", the differences first, each saying whether the system gave more or less
 * credit. The teacher's levels are the seats' own marks; the system's come from the validity
 * read's `compared` (FR-CONSOLE-80), every mark paired with the system's level. An answer
 * the read pairs nothing with is shown as not compared, never as agreeing. The comparison renders only once the read says the sample is `recorded`; before that
 * an empty list would read as "everything matched".
 */
function Comparison({ data }: { data: BlindSeatsDoc }) {
  const validity = useScreenRead<ValidityDoc>("/api/v1/results/validity", { run_id: data.run_id });
  const marked = data.seats.filter((seat) => seat.draft_band !== null && seat.draft_band !== "");
  if (validity.error !== null) {
    return (
      <p role="alert" className="screen-alert">
        The comparison with the system's marks could not be read ({validity.error}).{" "}
        <button type="button" className="button" onClick={validity.retry}>
          Retry
        </button>
      </p>
    );
  }
  if (validity.data === null) {
    return <p className="hub-state">Reading the comparison.</p>;
  }
  if (marked.length === 0) {
    return <p className="hub-state">The sample is closed and none of its answers were marked.</p>;
  }
  if (validity.data.state !== "recorded") {
    return (
      <p className="hub-state">
        Your marks are recorded. The comparison with the system's marks is not ready yet; it
        appears here once it is worked out.
      </p>
    );
  }
  const paired = validity.data.compared ?? [];
  const rows: Compared[] = marked.map((seat) => {
    // The system's level for this answer: the one pairing for this student and grading point.
    // None (or two students sharing a name) leaves it unknown — never assumed to agree.
    const matches = paired.filter(
      (item) => item.criterion_id === seat.criterion_id && item.student === seat.student_name,
    );
    const pair = matches.length === 1 ? (matches[0] ?? null) : null;
    const yours = seat.draft_band ?? "";
    const system = pair?.system_band ?? null;
    const difference = pair !== null && system !== yours ? pair : null;
    return { seat, yours, system, difference };
  });
  // Differences first, then the answers the system's level is unknown for, then agreements.
  const rank = (row: Compared): number => (row.difference !== null ? 0 : row.system === null ? 1 : 2);
  rows.sort((a, b) => rank(a) - rank(b));
  const differing = rows.filter((row) => row.difference !== null).length;
  const unknown = rows.filter((row) => row.system === null).length;
  const known = rows.length - unknown;
  return (
    <section className="blind-comparison" aria-label="Your marks beside the system's">
      <h2>Your marks beside the system's</h2>
      <p className="hub-state">
        {differing === 0
          ? known === rows.length
            ? `The system gave the same level as you on all ${rows.length} answers you marked.`
            : `The system gave the same level as you on ${known} of the ${rows.length} answers you marked.`
          : `The system gave a different level on ${differing} of the ${rows.length} answers you marked.`}
        {unknown > 0 &&
          ` For ${unknown} of them the system's level could not be read, so they are not compared.`}
      </p>
      <ul className="rows-list">
        {rows.map((row) => (
          <li
            key={row.seat.seat_id}
            className={row.difference !== null ? "blind-compared blind-differs" : "blind-compared"}
          >
            <span className="step-name">
              {row.seat.student_name ?? "A student"} — {row.seat.question}
            </span>
            <span className="blind-yours">You: {row.yours}</span>
            <span className="blind-system">
              The system: {row.system ?? "its level could not be read"}
            </span>
            {row.difference !== null && (
              <span className="blind-direction">{directionSentence(row.difference)}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
