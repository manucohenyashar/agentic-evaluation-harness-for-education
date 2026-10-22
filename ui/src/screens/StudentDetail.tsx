import { useState } from "react";
import { FileText, TriangleAlert } from "lucide-react";
import type { CriterionDetail, LogsDoc, StudentDetail as DetailDoc } from "../api";
import { ReadScreen } from "../components/ReadScreen";
import { OverrideForm, type OverrideChange } from "../components/Override";
import { useToast } from "../state/StateDisplay";
import { NOT_FINAL_REASON_TEXT } from "../wizard/vocabulary";
import { flagLabel, flagTone, scoreStateLabel } from "../state/model";
import { useScreenRead } from "../useScreenRead";
import { studentName } from "../studentNames";
import { useRunParams } from "../selection";

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
/** One grading point's card: its band, its justification in plain language, its override,
 * and the engineering trail behind an expander that starts the logs read only when the
 * teacher opens it (`ADR-47`'s no-eager-read rule for the trail). */
function CriterionCard({ criterion, doc, setShowDetails, logs, afterOverride }: {
  criterion: CriterionDetail;
  doc: DetailDoc;
  setShowDetails: (open: boolean) => void;
  logs: { error: string | null; data: LogsDoc | null; retry: () => void };
  afterOverride: (_text: string, changes: OverrideChange[], final: boolean) => void;
}) {
  return (
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
      {/* The expander starts the logs read: the trail is read only once a
          teacher opens an expander, never eagerly behind a closed panel. The
          flag latches: every criterion card carries its own expander over the
          same run's log, so closing one must not pull the read out from under
          another that is still open. */}
      <details
        className="detail-expander"
        onToggle={(event) => {
          if (event.currentTarget.open) {
            setShowDetails(true);
          }
        }}
      >
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
  );
}

export function StudentDetail({ submissionId }: { submissionId: string }) {
  const read = useScreenRead<DetailDoc>(
    "/api/v1/results/student-detail",
    { submission_id: submissionId, ...useRunParams() },
  );
  const raiseToast = useToast();
  const [showDetails, setShowDetails] = useState(false);
  const [remount, setRemount] = useState(0);
  // The log panel rides the Details expander: it reads nothing until the teacher opens
  // the trail, and only with the run the drill-down's own read named.
  const data = read.data;
  const logs = useScreenRead<LogsDoc>(
    showDetails && data !== null && data.run_id !== "" ? "/api/v1/logs" : null,
    data === null ? undefined : { run_id: data.run_id },
  );

  const afterOverride = (_text: string, changes: OverrideChange[], final: boolean): void => {
    read.retry();
    setRemount((n) => n + 1);
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
            {studentName(doc)} — total {doc.total ?? "—"}
            {doc.state !== null && doc.state !== ""
              ? `, ${scoreStateLabel(doc.state).toLowerCase()}`
              : ""}
            .
          </p>
          {doc.total_points != null && doc.total_max != null && (
            <p className="hub-state">
              Total grade {doc.total_points} / {doc.total_max}
              {doc.grade ? ` — ${doc.grade}` : ""}.
            </p>
          )}
          <section className="drilldown">
            <h2>Grades and justifications</h2>
            {doc.criteria.length === 0 ? (
              <p className="panel">The run holds no grading points for this paper.</p>
            ) : (
              <div key={remount}>
                {(doc.questions ?? []).map((question) => (
                  <div key={question.question_id} className="question-group">
                    <h3>
                      {question.label} — {question.points_awarded ?? "—"} /{" "}
                      {question.points_max}
                      {question.state === "not_final" && question.not_final_reason !== null && (
                        <span
                          className="badge badge-warning"
                          title={NOT_FINAL_REASON_TEXT[question.not_final_reason] ??
                            "Please check this answer."}
                        >
                          <TriangleAlert aria-hidden="true" size={12} />
                          <span> Check</span>
                        </span>
                      )}
                    </h3>
                    <ul className="criterion-cards">
                      {doc.criteria
                        .filter((criterion) => criterion.question_id === question.question_id)
                        .map((criterion) => (
                          <CriterionCard
                            key={criterion.criterion_id}
                            criterion={criterion}
                            doc={doc}
                            setShowDetails={setShowDetails}
                            logs={logs}
                            afterOverride={afterOverride}
                          />
                        ))}
                    </ul>
                  </div>
                ))}
                <ul className="criterion-cards">
                  {doc.criteria
                    .filter((criterion) =>
                      !(doc.questions ?? []).some(
                        (question) => question.question_id === criterion.question_id))
                    .map((criterion) => (
                      <CriterionCard
                        key={criterion.criterion_id}
                        criterion={criterion}
                        doc={doc}
                        setShowDetails={setShowDetails}
                        logs={logs}
                        afterOverride={afterOverride}
                      />
                    ))}
                </ul>
              </div>
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
