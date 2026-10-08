import { fetchRead, type StudentDetail as DetailDoc } from "../api";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";

/**
 * One student's own screen: their grade record and the narrative M-SYNTH wrote — the
 * student's text the teacher reads, reached one click from the results row (TC-UI-C03's
 * sentinel screen). No editing here: corrections happen on the results screen's band
 * controls, through the controls that own the write.
 */
export function StudentDetail({ submissionId }: { submissionId: string }) {
  const read = useScreenRead<DetailDoc>(
    "/api/v1/results/student-detail",
    { submission_id: submissionId },
  );
  return (
    <ReadScreen title={`Student ${submissionId}`} read={read}>
      {(data) => (
        <>
          <p className="hub-state">
            {data.student_ref ?? data.submission_id} — total {data.total ?? "—"}
            {data.state !== null && data.state !== "" ? `, ${data.state}` : ""}.
          </p>
          {data.narrative.length === 0 ? (
            <p className="panel">The run holds no narrative for this student.</p>
          ) : (
            <ul className="rows-list">
              {data.narrative.map((row) => (
                <li key={`${row.level}-${row.question_id}`}>
                  <span className="step-note">{row.question_id}</span>
                  <p className="narrative-text">{row.text}</p>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </ReadScreen>
  );
}
