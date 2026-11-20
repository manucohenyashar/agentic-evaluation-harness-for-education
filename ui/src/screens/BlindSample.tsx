import { type BlindSeat, type BlindSeats as BlindSeatsDoc } from "../api";
import { FormatLine, useFieldIds } from "../components/Field";
import { useReportedAction } from "../components/Outcome";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";
import { useRunParams } from "../selection";
import { FORMAT_CHOOSE_ONE } from "../wizard/vocabulary";

/**
 * The blind sample's screen (FR-CONSOLE-83): M-REVIEW's seats for the run, each with the
 * student's answer and the question's levels with their descriptions — nothing the system
 * decided about the answer. Choosing a level saves a draft ("blind-sample draft"); nothing
 * counts until **Finish** ("blind-sample finish"). **Skip** ("blind-sample skip") closes the
 * sample with no marks. Every choice starts unselected unless the teacher drafted one.
 */
export function BlindSample() {
  const read = useScreenRead<BlindSeatsDoc>("/api/v1/blind-seats", useRunParams());
  const { busy, run } = useReportedAction();
  return (
    <ReadScreen title="Blind sample" read={read}>
      {(data) => {
        const open = data.state === "open";
        const { marked, total } = data.progress;
        return (
          <>
            <p className="hub-state">
              {total === 0
                ? "There are no answers to mark in this sample."
                : open
                  ? `${marked} of ${total} marked. Choose the level you would give each answer; your marks count when you finish.`
                  : "This sample is closed: it was finished, skipped or its time ran out."}
            </p>
            {open && total > 0 && (
              <p>
                <button
                  type="button"
                  disabled={busy || marked === 0}
                  onClick={() => {
                    const unmarked = total - marked;
                    if (
                      unmarked > 0 &&
                      !window.confirm(
                        `Finish with ${unmarked} answers unmarked? Only the ones you marked will count.`,
                      )
                    ) {
                      return;
                    }
                    void run("blind-sample finish", { run_id: data.run_id }, { onDone: read.retry });
                  }}
                >
                  Finish
                </button>{" "}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    void run("blind-sample skip", { run_id: data.run_id }, { onDone: read.retry });
                  }}
                >
                  Skip the sample
                </button>
              </p>
            )}
            <ul className="rows-list">
              {data.seats.map((seat) => (
                <SeatRow
                  key={seat.seat_id}
                  seat={seat}
                  runId={data.run_id}
                  open={open}
                  onSaved={read.retry}
                />
              ))}
            </ul>
          </>
        );
      }}
    </ReadScreen>
  );
}

/** One seat: whose answer and which question, the answer itself, and the teacher's level. */
function SeatRow({
  seat,
  runId,
  open,
  onSaved,
}: {
  seat: BlindSeat;
  runId: string;
  open: boolean;
  onSaved: () => void;
}) {
  const { busy, run } = useReportedAction();
  const ids = useFieldIds();
  return (
    <li>
      <span className="step-name">{seat.student_name ?? "A student"}</span>
      <span className="step-note">{seat.question}</span>
      <p className="step-note">{seat.answer_text ?? "No answer text could be read for this question."}</p>
      <label htmlFor={ids.id}>Your level</label>
      <select
        {...ids.control}
        name={`seat-band-${seat.seat_id}`}
        defaultValue={seat.draft_band ?? ""}
        disabled={busy || !open}
        aria-busy={busy || undefined}
        onChange={(event) => {
          if (event.target.value === "") {
            return;
          }
          void run(
            "blind-sample draft",
            { run_id: runId, seat_id: seat.seat_id, band: event.target.value },
            { onDone: onSaved },
          );
        }}
      >
        <option value="">—</option>
        {seat.bands.map((band) => (
          <option key={band.name} value={band.name}>
            {band.descriptor ? `${band.name}: ${band.descriptor}` : band.name}
          </option>
        ))}
      </select>
      <FormatLine id={ids.formatId} spec={{ kind: "choice", format: FORMAT_CHOOSE_ONE }} />
    </li>
  );
}
