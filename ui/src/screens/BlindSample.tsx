import { useState } from "react";
import { fetchRead, performAction, type BlindSeats as BlindSeatsDoc } from "../api";
import { ActionOutcome, outcomeText } from "../components/Confirm";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";

/**
 * The blind sample's screen: M-REVIEW's draw for the run, each seat named only by what the
 * flow posed — submission, criterion, evaluation mode — beside the rubric's band scale. No
 * system output is carried or shown: no band value, no engine marker, and every select
 * starts unselected (a band must come from the teacher, not from the page). A chosen band
 * posts the enumerated "blind-sample submission" control; the console's refusal is shown
 * as refused.
 */
export function BlindSample() {
  const read = useScreenRead<BlindSeatsDoc>("/api/v1/blind-seats");
  const [note, setNote] = useState<string | null>(null);
  return (
    <ReadScreen title="Blind sample" read={read}>
      {(data) => (
        <>
          <ActionOutcome outcome={note} />
          <p className="hub-state">
            {data.seats.length === 0
              ? "The draw holds no seat for this run."
              : `${data.seats.length} seat(s) in the draw. Choose the band you judge for each.`}
          </p>
          <ul className="rows-list">
            {data.seats.map((seat) => (
              <li key={`${seat.submission_id}-${seat.criterion_id}`}>
                <span className="step-name">{seat.student_ref ?? seat.submission_id}</span>
                <span className="step-note">{seat.criterion_id}</span>
                {seat.evaluation_mode !== "" && (
                  <span className="step-state">{seat.evaluation_mode}</span>
                )}
                <select
                  name={`seat-band-${seat.criterion_id}`}
                  defaultValue=""
                  onChange={(event) => {
                    if (event.target.value === "") {
                      return;
                    }
                    performAction("blind-sample submission", {
                      run_id: data.run_id,
                      submission_id: seat.submission_id,
                      criterion_id: seat.criterion_id,
                      band: event.target.value,
                      actor: "operator",
                    }).then(
                      (result) => setNote(outcomeText(result)),
                      (failure: unknown) =>
                        setNote(failure instanceof Error ? failure.message : String(failure)),
                    );
                  }}
                >
                  <option value="">—</option>
                  {data.band_scale.map((band) => (
                    <option key={band} value={band}>
                      {band}
                    </option>
                  ))}
                </select>
              </li>
            ))}
          </ul>
        </>
      )}
    </ReadScreen>
  );
}
