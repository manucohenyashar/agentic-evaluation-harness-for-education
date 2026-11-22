import type { CompressionCheck, EngineFigure, Graders, GradersCriterion } from "../api";

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

/** The six protocol steps in the teacher's words, in step order. */
const STEP_NAMES: Record<string, string> = {
  "1": "Agreement with your blind marks",
  "2": "Whether the order of the worked examples changes a mark",
  "3": "Whether the same answer gets the same mark when marked again",
  "4": "Agreement checked for each kind of test separately",
  "5": "Extra checks on markers that always agree with themselves",
  "6": "Whether the marks bunch toward the middle",
};

function anyMeasured(outcome: unknown): boolean {
  if (outcome === null || typeof outcome !== "object") return false;
  return Object.values(outcome as Record<string, unknown>).some(
    (value) =>
      value !== null &&
      typeof value === "object" &&
      ((value as Record<string, unknown>).measured === true ||
        (value as Record<string, unknown>).self_agreement_measured === true),
  );
}

function compressionWords(check: CompressionCheck | null): string {
  if (check === null || check.n === 0 || check.panel_narrower === null) return "not measured yet";
  return check.panel_narrower
    ? `the system's levels are more bunched than yours (${check.n} answers)`
    : `the system's levels are not more bunched than yours (${check.n} answers)`;
}

function stepState(step: string, outcome: unknown): string {
  if (step === "6") return compressionWords(outcome as CompressionCheck | null);
  if (step === "2" || step === "3" || step === "5") {
    return anyMeasured(outcome) ? "measured" : "not measured yet";
  }
  return "recorded";
}

export function ValidationChecks({ graders }: { graders: Graders }) {
  const record = graders.mvvp;
  return (
    <section className="panel" data-component="validation-checks">
      <h2>Validation checks</h2>
      {record === null ? (
        <p>No validation checks have run yet.</p>
      ) : (
        <>
          <p>
            {record.outcome === "ran"
              ? `Last run on ${teacherDate(record.recorded_at)}, after ${triggerWords(record.trigger)}.`
              : `Not run on ${teacherDate(record.recorded_at)}, after ${triggerWords(record.trigger)}: ` +
                "they would cost more than the run cost limit."}
          </p>
          {record.outcome === "ran" && (
            <ul className="rows-list">
              {Object.keys(STEP_NAMES)
                .filter((step) => step in (record.steps ?? {}))
                .map((step) => (
                  <li key={step}>
                    <span className="step-name">{STEP_NAMES[step]}</span>
                    <span className="step-state">{stepState(step, record.steps[step]?.outcome)}</span>
                  </li>
                ))}
            </ul>
          )}
        </>
      )}
      <p>{`On the latest class's blind answers: ${compressionWords(graders.compression)}.`}</p>
    </section>
  );
}
