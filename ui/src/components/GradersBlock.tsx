import type { EngineFigure, Graders, GradersCriterion } from "../api";

/**
 * The graders measured on System status (FR-UI-46, FR-CONSOLE-88, FR-CALIB-19, FR-STATS-36):
 * the **Jev** block — whether Jev's confident answers are final, and the evidence so far or
 * the figures once there are enough blind answers — with a warning naming any question where
 * Jev's answers agreed less well than the judges' did; then the consistency check of the
 * marked examples and the latest validation checks. Below a minimum no figure is shown, only
 * "too few" with the count (CT-STATS-03). No percentage anywhere.
 */
export function GradersBlock({ graders }: { graders: Graders }) {
  return (
    <>
      <JevBlock graders={graders} />
      <ConsistencyBlock graders={graders} />
      <ValidationChecks graders={graders} />
    </>
  );
}

/** FR-UI-46's opening sentence. */
export function jevFinalSentence(on: boolean): string {
  return `Jev's answers are final when it is confident and one judge agrees (${on ? "on" : "off"}).`;
}

/** FR-UI-46's evidence sentence, before the figures exist. */
export function jevEvidenceSentence(k: number, needed: number): string {
  return `Evidence so far: ${k} of ${needed} blind answers needed.`;
}

function figureText(figure: EngineFigure, minimum: number): string {
  if (figure.status !== "measured" || figure.ordinal_alpha === null) {
    return `too few answers yet (${figure.n} of ${minimum})`;
  }
  return `agreement beyond chance ${figure.ordinal_alpha.toFixed(2)} over ${figure.n} answers`;
}

function measured(criterion: GradersCriterion): boolean {
  return criterion.per_engine.decision.status === "measured";
}

export function JevBlock({ graders }: { graders: Graders }) {
  const shown = graders.criteria.filter(measured);
  const failing = graders.noninferiority_failing;
  return (
    <section className="panel" data-component="jev-block">
      <h2>Jev</h2>
      <p>
        {jevFinalSentence(graders.jev_final_on)}{" "}
        {shown.length === 0 && jevEvidenceSentence(graders.decision_answers, graders.min_per_engine)}
      </p>
      {shown.length > 0 && (
        <ul className="rows-list">
          {shown.map((criterion) => (
            <li key={criterion.criterion_id}>
              <span className="step-name">{criterion.label}</span>
              <span className="step-state">
                {`Jev's answers: ${figureText(criterion.per_engine.decision, graders.min_per_engine)}. ` +
                  `The judges alone: ${figureText(criterion.per_engine.llm_engine_off, graders.min_per_engine)}.`}
              </span>
            </li>
          ))}
        </ul>
      )}
      {failing.length > 0 && (
        <p className="warning" role="alert" data-noninferiority="failing">
          {`Warning: on ${failing.join(", ")}, Jev's answers agreed with your blind marks less ` +
            "well than the judges' answers did. Jev's role has not been changed."}
        </p>
      )}
    </section>
  );
}

function teacherDate(instant: string): string {
  return instant.slice(0, 10);
}

export function ConsistencyBlock({ graders }: { graders: Graders }) {
  const report = graders.consistency_report;
  if (report === null) return null;
  const labels = new Map(graders.criteria.map((item) => [item.criterion_id, item.label]));
  const rows = Object.entries(report.criteria);
  return (
    <section className="panel" data-component="consistency-check">
      <h2>{report.label}</h2>
      {report.outcome === "refused" ? (
        <p>{`On ${teacherDate(report.recorded_at)} your marked examples could not be marked again after the marking models changed.`}</p>
      ) : (
        <>
          <p>{`${report.sentence} Checked on ${teacherDate(report.recorded_at)}.`}</p>
          <ul className="rows-list">
            {rows.map(([criterionId, counts]) => (
              <li key={criterionId}>
                <span className="step-name">{labels.get(criterionId) ?? "A question"}</span>
                <span className="step-state">
                  {`${counts.moved} of ${counts.examples} examples moved to a different level`}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function triggerWords(trigger: string): string {
  return trigger === "package_approval" ? "the test was published" : "the marking models changed";
}

export function ValidationChecks({ graders }: { graders: Graders }) {
  const record = graders.mvvp;
  if (record === null) return null;
  return (
    <section className="panel" data-component="validation-checks">
      <h2>Validation checks</h2>
      <p>
        {record.outcome === "ran"
          ? `Last run on ${teacherDate(record.recorded_at)}, after ${triggerWords(record.trigger)}.`
          : `Not run on ${teacherDate(record.recorded_at)}, after ${triggerWords(record.trigger)}: ` +
            "they would cost more than the run cost limit."}
      </p>
    </section>
  );
}
