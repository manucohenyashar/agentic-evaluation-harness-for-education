import { type BlindSeat, type BlindSeats as BlindSeatsDoc } from "../api";
import { FormatLine, useFieldIds } from "../components/Field";
import { useReportedAction } from "../components/Outcome";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";
import { studentName } from "../studentNames";
import { useRunParams } from "../selection";
import { FORMAT_CHOOSE_ONE } from "../wizard/vocabulary";

/**
 * The blind sample's screen: M-REVIEW's draw for the run, each seat named only by what the
 * flow posed — submission, criterion, evaluation mode — beside that grading point's own
 * declared levels (the generic scale only when the package cannot be read). No
 * system output is carried or shown: no band value, no engine marker, and every select
 * starts unselected (a band must come from the teacher, not from the page). A chosen band
 * posts the enumerated "blind-sample submission" control; the outcome shows in the shell's
 * banner, a refusal as refused.
 */
export function BlindSample() {
  const read = useScreenRead<BlindSeatsDoc>("/api/v1/blind-seats", useRunParams());
  return (
    <ReadScreen title="Blind sample" read={read}>
      {(data) => (
        <>
          <p className="hub-state">
            {data.seats.length === 0
              ? "The draw holds no seat for this run."
              : `${data.seats.length} seat(s) in the draw. Choose the band you judge for each.`}
          </p>
          <ul className="rows-list">
            {data.seats.map((seat) => (
              <SeatRow
                key={`${seat.submission_id}-${seat.criterion_id}`}
                seat={seat}
                runId={data.run_id}
                scale={seat.band_scale ?? data.band_scale}
              />
            ))}
          </ul>
        </>
      )}
    </ReadScreen>
  );
}

/** One seat: who and what it is, and the teacher's own band for it. */
function SeatRow({ seat, runId, scale }: { seat: BlindSeat; runId: string; scale: string[] }) {
  const { busy, run } = useReportedAction();
  const ids = useFieldIds();
  const point = seat.label ?? seat.criterion_id;
  return (
    <li>
      <span className="step-name">{studentName(seat)}</span>
      <span className="step-note">{point}</span>
      {seat.evaluation_mode !== "" && <span className="step-state">{seat.evaluation_mode}</span>}
      <label htmlFor={ids.id}>Your score level</label>
      <select
        {...ids.control}
        name={`seat-band-${seat.criterion_id}`}
        defaultValue=""
        disabled={busy}
        aria-busy={busy || undefined}
        onChange={(event) => {
          if (event.target.value === "") {
            return;
          }
          void run("blind-sample submission", {
            run_id: runId,
            submission_id: seat.submission_id,
            criterion_id: seat.criterion_id,
            band: event.target.value,
            actor: "operator",
          });
        }}
      >
        <option value="">—</option>
        {scale.map((band) => (
          <option key={band} value={band}>
            {band}
          </option>
        ))}
      </select>
      <FormatLine id={ids.formatId} spec={{ kind: "choice", format: FORMAT_CHOOSE_ONE }} />
    </li>
  );
}
