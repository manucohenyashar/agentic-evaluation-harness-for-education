import type {
  PackageRecordDoc,
  PriorRecord,
  RecordAdministration,
  ValidityDisagreement,
  ValidityDoc,
  ValidityFigure,
} from "../api";
import { useNavigate } from "../navigate";
import { useScreenRead } from "../useScreenRead";
import { BLIND_SAMPLE_ROUTE } from "./HeldBack";

/**
 * How closely the marking matched the teacher's own blind marks, in teacher words
 * (FR-UI-37/38/43). Every figure is one grading point's — simple checks and overall
 * judgements are never pooled — and always sits beside the number of answers it rests on.
 * A record figure withheld below the minimum reads "too few", never a number. No sentence
 * here says "accuracy" or shows a percentage: agreement beyond chance is not a hit rate.
 */

/** FR-UI-37: a rubric line's scoring model as the teacher reads it. */
export function scoringModelLabel(model: string | null | undefined): string | null {
  if (model === "holistic") return "Marked as an overall judgement";
  if (model === "atomic" || model === "atomic_with_gate") return "Marked as a simple check";
  return null;
}

/** The kind of question a figure is about, plural, for the per-question line. */
function kindWords(model: string): string {
  if (model === "holistic") return "overall judgements";
  if (model === "atomic" || model === "atomic_with_gate") return "simple checks";
  return "marked by judgement";
}

function answers(n: number): string {
  return `${n} answer${n === 1 ? "" : "s"}`;
}

/** One question's line: "Q1 (simple checks): agreement beyond chance 0.00 — 2 answers". A
 * figure the read withholds (a record below the minimum) reads "too few" with its n; one that
 * cannot be worked out from the answers (every answer at one level) says so. */
export function figureLine(figure: ValidityFigure): string {
  const head = `${figure.label} (${kindWords(figure.scoring_model)})`;
  if (figure.kappa !== null && figure.kappa !== undefined) {
    return `${head}: agreement beyond chance ${figure.kappa.toFixed(2)} — ${answers(figure.n)}`;
  }
  if (figure.too_few) {
    return `${head}: too few to rely on yet — ${figure.n} of the ${figure.min_n_for_headline} needed`;
  }
  return `${head}: agreement beyond chance cannot be worked out from these answers — ${answers(figure.n)}`;
}

/** "Too few answers to rely on yet (12 of the 30 needed)." for the question with the fewest
 * answers, or null when every figure has enough. */
export function tooFewSentence(figures: ValidityFigure[]): string | null {
  const few = figures.filter((figure) => figure.too_few);
  if (few.length === 0) return null;
  const least = few.reduce((a, b) => (b.n < a.n ? b : a));
  return `Too few answers to rely on yet (${least.n} of the ${least.min_n_for_headline} needed).`;
}

const DIRECTION_WORDS: Record<string, string> = {
  less_credit: "it gave less credit than you",
  more_credit: "it gave more credit than you",
};

/** The differences in teacher words: "Where it differed, it gave less credit than you on all
 * 3: Ana, Q1 · Ben, Q1 · Chloe, Q3." — grouped by direction when they differ in direction. */
export function differencesSentence(differences: ValidityDisagreement[]): string {
  const groups = new Map<string, ValidityDisagreement[]>();
  for (const item of differences) {
    const key = item.direction ?? "different";
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  const order = ["less_credit", "more_credit", "different"];
  const parts = order
    .filter((key) => groups.has(key))
    .map((key) => {
      const items = groups.get(key) ?? [];
      const words = DIRECTION_WORDS[key] ?? "it gave a different level";
      const count =
        groups.size === 1 ? (items.length === 1 ? "on 1" : `on all ${items.length}`) : `on ${items.length}`;
      const where = items.map((item) => `${item.student}, ${item.question}`).join(" · ");
      return `${words} ${count}: ${where}`;
    });
  return `Where it differed, ${parts.join("; ")}.`;
}

function absenceWords(item: RecordAdministration): string {
  if (item.absence_reason === "skipped") return "the blind sample was skipped";
  if (item.absence_reason !== undefined) return "no answers were marked in the blind sample";
  const count = item.blind_count ?? 0;
  return `${count} blind answer${count === 1 ? "" : "s"}`;
}

/** The figures of a record (a test version's, or the earlier classes'): "<k> of 30 blind
 * answers collected; too few to rely on yet" while below the minimum, else per question. */
function RecordFigures({
  blindLabels,
  minimum,
  criteria,
}: {
  blindLabels: number;
  minimum: number;
  criteria: ValidityFigure[];
}) {
  if (blindLabels < minimum) {
    return (
      <p className="record-headline">
        {blindLabels} of {minimum} blind answers collected; too few to rely on yet
      </p>
    );
  }
  if (criteria.length === 0) {
    return <p className="record-headline">{blindLabels} blind answers collected</p>;
  }
  // A record keeps one figure per grading point and marking setup (a new backend or grader
  // panel starts its own figure, never pooled); when a question has more than one, each is
  // numbered so two lines for the same question never read as a contradiction.
  const total = new Map<string, number>();
  for (const figure of criteria) {
    total.set(figure.criterion_id, (total.get(figure.criterion_id) ?? 0) + 1);
  }
  const seen = new Map<string, number>();
  return (
    <ul className="record-figures">
      {criteria.map((figure, index) => {
        const nth = (seen.get(figure.criterion_id) ?? 0) + 1;
        seen.set(figure.criterion_id, nth);
        const setup = (total.get(figure.criterion_id) ?? 1) > 1 ? ` (marking setup ${nth})` : "";
        return <li key={`${figure.criterion_id}-${index}`}>{figureLine(figure)}{setup}</li>;
      })}
    </ul>
  );
}

/** The earlier classes' record, on its own labelled line — never in this class's place
 * (FR-CONSOLE-24). */
function PriorRecordLine({ prior }: { prior: PriorRecord }) {
  return (
    <div className="prior-record" aria-label={prior.label}>
      <p>
        <strong>{prior.label}</strong> ({prior.population})
      </p>
      <RecordFigures
        blindLabels={prior.blind_labels}
        minimum={prior.min_n_for_headline}
        criteria={prior.criteria}
      />
    </div>
  );
}

/**
 * The results agreement block (FR-UI-38): headed "How closely the marking matched yours",
 * the matched sentence over the answers the teacher marked blind, each question's agreement
 * beyond chance with its n, the "too few" sentence, and the differences by student name with
 * **Review these** (the comparison). A skipped sample says there is no new evidence; one not
 * yet marked links to it. The earlier classes' record follows on a separate labelled line.
 */
export function AgreementBlock({ runId }: { runId: string }) {
  const read = useScreenRead<ValidityDoc>("/api/v1/results/validity", { run_id: runId });
  const navigate = useNavigate();
  const openSample = (): void => navigate(BLIND_SAMPLE_ROUTE, { run: runId });
  const heading = <h2>How closely the marking matched yours</h2>;
  if (read.error !== null) {
    return (
      <section className="panel agreement-block" aria-label="How closely the marking matched yours">
        {heading}
        <p role="alert" className="screen-alert">
          This could not be read ({read.error}).{" "}
          <button type="button" className="button" onClick={read.retry}>
            Retry
          </button>
        </p>
      </section>
    );
  }
  const doc = read.data;
  if (doc === null) {
    return (
      <section className="panel agreement-block" aria-label="How closely the marking matched yours">
        {heading}
        <p className="hub-state">Reading how closely the marking matched yours.</p>
      </section>
    );
  }
  const prior = doc.prior_record ?? null;
  let body;
  if (doc.state === "skipped") {
    body = (
      <p>You skipped the blind sample for this class, so there is no new evidence about accuracy.</p>
    );
  } else if (doc.state !== "recorded") {
    body = (
      <p>
        {doc.state === "in_progress"
          ? "Your blind sample for this class is not finished yet. "
          : "You have not marked a blind sample for this class yet. "}
        <a
          href={`#${BLIND_SAMPLE_ROUTE}`}
          onClick={(event) => {
            event.preventDefault();
            openSample();
          }}
        >
          Mark the sample
        </a>
      </p>
    );
  } else {
    const figures = doc.criteria ?? [];
    const n = figures.reduce((sum, figure) => sum + figure.n, 0);
    const matched = figures.reduce((sum, figure) => sum + (figure.matched ?? 0), 0);
    const tooFew = tooFewSentence(figures);
    const differences = doc.disagreements;
    body =
      n === 0 ? (
        <p>No answer in the blind sample was marked, so there is nothing to compare yet.</p>
      ) : (
        <>
          <p className="agreement-matched">
            On the {n === 1 ? "1 answer" : `${n} answers`} you marked without seeing the
            system's marks, it gave the same level on {matched}.
          </p>
          <ul className="agreement-figures">
            {figures.map((figure) => (
              <li key={figure.criterion_id}>{figureLine(figure)}</li>
            ))}
          </ul>
          {tooFew !== null && <p className="agreement-too-few">{tooFew}</p>}
          {differences.length > 0 && (
            <p className="agreement-differences">
              {differencesSentence(differences)}{" "}
              <button type="button" className="button" onClick={openSample}>
                Review these
              </button>
            </p>
          )}
        </>
      );
  }
  return (
    <section className="panel agreement-block" aria-label="How closely the marking matched yours">
      {heading}
      {body}
      {prior !== null && <PriorRecordLine prior={prior} />}
    </section>
  );
}

/**
 * The test's record (FR-UI-43): "How well this test has been marked so far" — the blind
 * answers collected across every class that took this version, per-question agreement once
 * there are enough, then each class's contribution with its date.
 */
export function PackageRecord({ versionId, name }: { versionId: string; name?: string }) {
  const read = useScreenRead<PackageRecordDoc>("/api/v1/packages/record", {
    package_version_id: versionId,
  });
  return (
    <section className="panel package-record" aria-label="How well this test has been marked so far">
      <h2>How well this test has been marked so far</h2>
      {read.error !== null ? (
        <p role="alert" className="screen-alert">
          The record of {name ?? "this test"} could not be read ({read.error}).{" "}
          <button type="button" className="button" onClick={read.retry}>
            Retry
          </button>
        </p>
      ) : read.data === null ? (
        <p className="hub-state">Reading the record of {name ?? "this test"}.</p>
      ) : (
        <>
          <p className="step-note">{read.data.version_label}</p>
          <RecordFigures
            blindLabels={read.data.blind_labels}
            minimum={read.data.min_n_for_headline}
            criteria={read.data.criteria}
          />
          {read.data.administrations.length === 0 ? (
            <p>No class has taken this version of the test yet.</p>
          ) : (
            <ul className="rows-list record-classes" aria-label="Each class's contribution">
              {read.data.administrations.map((item, index) => (
                <li key={`${item.class_name}-${index}`}>
                  <span className="step-name">{item.class_name}</span>
                  <span className="step-note">{item.date ?? "—"}</span>
                  <span>{absenceWords(item)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
