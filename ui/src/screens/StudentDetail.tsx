import { useState } from "react";
import { FileText, TriangleAlert } from "lucide-react";
import type { LogRecord, StudentDetail as DetailDoc } from "../api";
import { ReadScreen } from "../components/ReadScreen";
import { OverrideForm, type OverrideChange } from "../components/Override";
import { useToast } from "../state/StateDisplay";
import { flagLabel, flagTone, scoreStateLabel } from "../state/model";
import { useScreenRead } from "../useScreenRead";

/**
 * One student's drill-down (FR-UI-16, FR-UI-17): the paper's grade per grading point, each
 * with its justification in plain language — the aggregate's own reason text plus the
 * evidence spans the graders cited, rendered as "What the paper shows" quotes — and the
 * feedback narrative M-SYNTH wrote. The engineering trail (each grader's verdict, the run's
 * log) lives in an expandable Details section, never the default view. The override —
 * "Change a final grade", band selection plus a required reason — rides the console's
 * existing amend action, and the ledger's amendment history is rendered back as the one
 * sentence RS-09 spells.
 */
export function StudentDetail({ submissionId }: { submissionId: string }) {
  const read = useScreenRead<DetailDoc>(
    "/api/v1/results/student-detail",
    { submission_id: submissionId },
  );
  const raiseToast = useToast();
  const [showDetails, setShowDetails] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [remount, setRemount] = useState(0);
  // The log panel rides the Details expander: it reads nothing until the teacher opens
  // the trail, and only with the run the drill-down's own read named.
  const data = read.data;
  const logs = useScreenRead<{ run_id: string; records: LogRecord[] }>(
    showDetails && data !== null && data.run_id !== "" ? "/api/v1/logs" : null,
    data === null ? undefined : { run_id: data.run_id },
  );

  const afterOverride = (text: string, changes: OverrideChange[], final: boolean): void => {
    read.retry();
    setRemount((n) => n + 1);
    setOutcome(text);
    if (changes.length > 0) {
      raiseToast({
        kind: "success",
        text: final
          ? "Final grade changed — the history keeps the original."
          : "The review is saved.",
      });
    }
  };

  return (
    <ReadScreen title="Student" read={read}>
      {(doc) => (
        <>
          <p className="hub-state">
            {doc.student_ref ?? doc.submission_id} — total {doc.total ?? "—"}
            {doc.state !== null && doc.state !== ""
              ? `, ${scoreStateLabel(doc.state).toLowerCase()}`
              : ""}
            .
          </p>
          {outcome !== null && <p role="status" className="action-outcome">{outcome}</p>}
          <section className="drilldown">
            <h2>Grades and justifications</h2>
            {doc.criteria.length === 0 ? (
              <p className="panel">The run holds no grading points for this paper.</p>
            ) : (
              <ul className="criterion-cards" key={remount}>
                {doc.criteria.map((criterion) => (
                  <li key={criterion.criterion_id} className="criterion-card">
                    <div className="criterion-head">
                      <strong>{criterion.label}</strong>
                      <span className="band-value">{criterion.criterion_band}</span>
                      {criterion.stored_band !== criterion.criterion_band && (
                        <span className="band-note">
                          (amended from {criterion.stored_band})
                        </span>
                      )}
                      {criterion.flag !== null && (
                        <span className={`badge badge-${flagTone(criterion.flag)}`}>
                          <TriangleAlert aria-hidden="true" size={14} />
                          <span> {flagLabel(criterion.flag)}</span>
                        </span>
                      )}
                    </div>
                    <p className="criterion-state">{scoreStateLabel(criterion.state)}</p>
                    {criterion.state_reason !== "" && (
                      <p className="criterion-why">{criterion.state_reason}</p>
                    )}
                    {criterion.graders.some((grader) => grader.cited.length > 0) && (
                      <div className="evidence">
                        <h4>What the paper shows</h4>
                        <ul>
                          {criterion.graders
                            .flatMap((grader) => grader.cited)
                            .filter((quote, index, all) => all.indexOf(quote) === index)
                            .slice(0, 4)
                            .map((quote, index) => (
                              <li key={index}>
                                <blockquote>“{quote}”</blockquote>
                              </li>
                            ))}
                        </ul>
                      </div>
                    )}
                    <OverrideForm
                      criteria={[{
                        criterion_id: criterion.criterion_id,
                        label: criterion.label,
                        criterion_band: criterion.criterion_band,
                        levels: criterion.levels.length > 0
                          ? criterion.levels
                          : [criterion.criterion_band],
                      }]}
                      final={doc.state === "final"}
                      submissionId={doc.submission_id}
                      runId={doc.run_id}
                      onDone={afterOverride}
                    />
                    <details className="detail-expander">
                      <summary>Details</summary>
                      <div className="detail-body">
                        <h3>The graders' trail</h3>
                        {criterion.graders.length === 0 ? (
                          <p>No grader verdict is recorded for this grading point.</p>
                        ) : (
                          <ul className="grader-list">
                            {criterion.graders.map((grader, index) => (
                              <li key={`${grader.grader}-${index}`}>
                                <strong>{grader.grader}</strong> chose {grader.score_level}.
                                {grader.cited.length > 0 && (
                                  <div className="evidence">
                                    <h4>What the paper shows</h4>
                                    <ul>
                                      {grader.cited.map((quote, quoteIndex) => (
                                        <li key={quoteIndex}>
                                          <blockquote>“{quote}”</blockquote>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                        <h3>The run's log</h3>
                        <p className="log-note">
                          The log is the grading run's own record, at stage and grading-point
                          grain — it never carries a student's data.
                        </p>
                        {logs.error !== null ? (
                          <p role="alert" className="screen-alert">
                            The log could not be read ({logs.error}).{" "}
                            <button type="button" className="button" onClick={logs.retry}>
                              Retry
                            </button>
                          </p>
                        ) : logs.data === null ? (
                          <p>Reading.</p>
                        ) : logs.data.records.length === 0 ? (
                          <p>The run's log holds no records.</p>
                        ) : (
                          <ul className="log-list">
                            {logs.data.records.map((record) => (
                              <li key={record.record_id}>
                                <FileText size={12} aria-hidden="true" />{" "}
                                <strong>{record.stage}</strong> — {record.text}
                                {record.detail !== null && (
                                  <p className="log-detail">{record.detail}</p>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </details>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="narrative">
            <h2>Feedback</h2>
            {doc.narrative.length === 0 ? (
              <p className="panel">The run holds no narrative for this student.</p>
            ) : (
              <ul className="rows-list">
                {doc.narrative.map((row) => (
                  <li key={`${row.level}-${row.question_id}`}>
                    <span className="step-note">{row.question_id}</span>
                    <p className="narrative-text">{row.text}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {doc.amendments.length > 0 && (
            <section className="amendment-history">
              <h2>Grade history</h2>
              <ul>
                {doc.amendments.map((entry, index) => (
                  <li key={index}>
                    Final grade changed from '{entry.from_band}' to '{entry.to_band}' — reason
                    recorded{entry.actor !== "" ? ` by ${entry.actor}` : ""}
                    {entry.reason !== "" ? ` (“${entry.reason}”)` : ""}; the original grade is
                    kept in the history.
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </ReadScreen>
  );
}
