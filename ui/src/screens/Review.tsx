import { fetchRead, type ReviewQueue as ReviewQueueDoc } from "../api";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useScreenRead } from "../useScreenRead";

/**
 * The review queue screen (FR-UI-03f): the teacher's flagged answers before grades are
 * final, through `ConsoleApp.review_queue` — the S9 page's own view. The blind sample is
 * its own screen one click away (`#/review/blind`): the draw shows no system output, only
 * what the flow posed (ADV-15's SPA arm re-checks it).
 */
export function Review() {
  const read = useScreenRead<ReviewQueueDoc>("/api/v1/review-queue");
  const navigate = useNavigate();
  return (
    <ReadScreen title="Review queue" read={read}>
      {(data) => (
        <>
          <p className="hub-state">
            {`Run ${data.run_id} — ` +
              (data.flagged_total === 0
                ? "nothing is flagged for review."
                : `${data.flagged_total} flagged answer(s) await review.`)}
            {data.residual_provisional > 0 &&
              ` ${data.residual_provisional} provisional answer(s) remain outside the queue.`}
          </p>
          <ul className="rows-list">
            {data.shown.map((item) => (
              <li key={`${item.submission_id}-${item.criterion_id}`}>
                <span className="step-name">{item.submission_id}</span>
                <span className="step-note">{item.criterion_id}</span>
                <span className="step-state">{item.kind}</span>
              </li>
            ))}
          </ul>
          <p>
            <a href="#/review/blind" onClick={() => navigate("/review/blind")}>
              Open the blind sample
            </a>
          </p>
        </>
      )}
    </ReadScreen>
  );
}
