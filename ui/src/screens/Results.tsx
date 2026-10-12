import { useMemo, useState } from "react";
import { TriangleAlert } from "lucide-react";
import type { ResultsScreen as ResultsDoc, ResultStudent } from "../api";
import { ActionOutcome, ConfirmDialog, useActionState } from "../components/Confirm";
import { OverrideForm, type OverrideChange } from "../components/Override";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useToast } from "../state/StateDisplay";
import {
  countLevels,
  flagLabel,
  flagTone,
  meanLevelPhrase,
  mostMissed,
  scoreStateLabel,
} from "../state/model";
import { useScreenRead } from "../useScreenRead";

/**
 * The results overview (FR-UI-15): the run's distribution as hand-rolled SVG bars — the
 * declared score levels on the x-axis, the count labelled on each bar, a chart that is a
 * table with bars — beside the per-grading-point stats (the mean score level, the points
 * most papers missed) and the flagged items, each linking to its student. Every count and
 * every level comes from the rows the read served (`CT-UI-08`): the screen aggregates, it
 * never invents. Search, sort and filter by student, score level and flag ride the same
 * served rows.
 *
 * Each student's grade shows beside an editable band control (`FR-CONSOLE-20` invariant
 * 16): the "Change a final grade" disclosure opens the override — band selection plus a
 * required reason — riding the console's existing actions.
 */

function matchesFilters(student: ResultStudent, search: string, level: string, flag: string): boolean {
  if (search !== "") {
    const needle = search.toLowerCase();
    const hay = `${student.student_ref ?? ""} ${student.submission_id}`.toLowerCase();
    if (!hay.includes(needle)) return false;
  }
  if (level !== "" && !student.criteria.some((criterion) => criterion.criterion_band === level)) {
    return false;
  }
  if (flag !== "" && !student.criteria.some((criterion) => criterion.flag === flag)) {
    return false;
  }
  return true;
}

/** The distribution as SVG bars: one rect per declared level, its count labelled on the
 * bar, the level's name under the axis. Hand-rolled, no chart library. */
function DistributionBars({ levels, counts }: { levels: string[]; counts: number[] }) {
  const max = Math.max(1, ...counts);
  const barWidth = 28;
  const gap = 12;
  const height = 130;
  const width = Math.max(levels.length * (barWidth + gap) + gap, 160);
  const plot = 92;
  const summary = levels
    .map((level, index) => `${level}: ${counts[index] ?? 0}`)
    .join(", ");
  return (
    <figure className="distribution">
      <svg
        role="img"
        aria-label={`Papers per score level. ${summary}`}
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
      >
        {levels.map((level, index) => {
          const count = counts[index] ?? 0;
          const barHeight = Math.round((count / max) * plot);
          const x = gap + index * (barWidth + gap);
          const y = plot - barHeight + 4;
          return (
            <g key={level}>
              <text x={x + barWidth / 2} y={y - 4} textAnchor="middle" className="bar-count">
                {count}
              </text>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={Math.max(barHeight, count > 0 ? 2 : 0)}
                className="bar-rect"
              />
              <text x={x + barWidth / 2} y={plot + 24} textAnchor="middle" className="bar-label">
                {level}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption>
        {levels.map((level, index) => (
          <span key={level}>
            {level}: {counts[index] ?? 0}{" "}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

export function Results() {
  const read = useScreenRead<ResultsDoc>("/api/v1/results/screen");
  const navigate = useNavigate();
  const finalize = useActionState(read.retry);
  const raiseToast = useToast();
  const [outcome, setOutcome] = useState<string | null>(null);
  const [remount, setRemount] = useState(0);
  const [search, setSearch] = useState("");
  const [levelFilter, setLevelFilter] = useState("");
  const [flagFilter, setFlagFilter] = useState("");
  const [sort, setSort] = useState("az");

  const data = read.data;

  const counts = useMemo(() => {
    if (data === null) return [];
    const bands = data.students.flatMap((student) =>
      student.criteria.map((criterion) => criterion.criterion_band));
    return countLevels(data.score_levels, bands);
  }, [data]);

  const stats = useMemo(() => {
    if (data === null) return [];
    return data.scales.map((scale) => {
      const bands = data.students.flatMap((student) =>
        student.criteria
          .filter((criterion) => criterion.criterion_id === scale.criterion_id)
          .map((criterion) => criterion.criterion_band));
      return {
        criterion_id: scale.criterion_id,
        label: scale.label,
        levels: scale.levels,
        counts: countLevels(scale.levels, bands),
      };
    });
  }, [data]);

  // The grading points most papers landed at the bottom of (FR-UI-15's most-missed): the
  // set the served counts name, restated beside the per-point stats — never a client-side
  // guess at difficulty, only which served cell counts sit at the lowest declared level.
  const missed = useMemo(() => mostMissed(stats), [stats]);

  const flagged = useMemo(() => {
    if (data === null) return [];
    const items: { student: ResultStudent; criterionId: string; label: string; flag: string }[] = [];
    for (const student of data.students) {
      for (const criterion of student.criteria) {
        if (criterion.flag !== null) {
          items.push({
            student,
            criterionId: criterion.criterion_id,
            label: criterion.label,
            flag: criterion.flag,
          });
        }
      }
    }
    return items;
  }, [data]);

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

  const openFinalize = (doc: ResultsDoc): void => {
    if (doc.run_id === null || doc.students.length === 0) {
      return;
    }
    // The confirmation names what it does out of the API's own document (FR-UI-05): the
    // run it settles and how many of its stored grades are not yet final — a run whose
    // grades are all final settles nothing (FR-CONSOLE-02), and the dialog says that.
    const not_final = doc.students.filter((s) => s.state !== "final").length;
    finalize.open({
      title: "Finalize this batch",
      description:
        not_final === 0
          ? `Every stored grade of run ${doc.run_id} is already final; finalizing ` +
            "settles nothing — a confirm whose work is done is a no-op (FR-CONSOLE-02). " +
            "Afterward a correction is an amendment, recorded."
          : `Finalizing settles the ${not_final} not-yet-final grade(s) of run ` +
            `${doc.run_id}: the batch's grades stop being provisional. ` +
            "Afterward a correction is an amendment, recorded.",
      confirm: "Finalize",
      action: "finalize batch",
      body: { run_id: doc.run_id, actor: "operator" },
    });
  };

  return (
    <ReadScreen title="Results" read={read}>
      {(doc) => {
        const shown = doc.students
          .filter((student) => matchesFilters(student, search, levelFilter, flagFilter))
          .sort((a, b) => {
            const refA = a.student_ref ?? a.submission_id;
            const refB = b.student_ref ?? b.submission_id;
            const compared = refA.localeCompare(refB);
            return sort === "za" ? -compared : compared;
          });
        const levelsFor = (criterionId: string): string[] =>
          doc.scales.find((scale) => scale.criterion_id === criterionId)?.levels ?? [];
        return (
          <>
            <ActionOutcome outcome={outcome ?? finalize.outcome} />
            {doc.students.length === 0 ? (
              <p className="panel">The run holds no computed grades.</p>
            ) : (
              <>
                <section className="results-overview">
                  <h2>Distribution</h2>
                  <DistributionBars levels={doc.score_levels} counts={counts} />
                  <h2>Per grading point</h2>
                  <ul className="point-stats">
                    {stats.map((stat) => (
                      <li key={stat.criterion_id}>
                        <strong>{stat.label}</strong> — {meanLevelPhrase(stat.levels, stat.counts)}
                        {" "}({stat.levels.map((level, index) =>
                          `${level}: ${stat.counts[index] ?? 0}`).join(", ")})
                      </li>
                    ))}
                  </ul>
                  {missed.length > 0 && (
                    <p className="point-stats-missed">
                      Most missed: {missed.join(", ")} — where most papers landed on the
                      lowest declared score level.
                    </p>
                  )}
                  <h2>Flagged</h2>
                  {flagged.length === 0 ? (
                    <p>No grading point is flagged.</p>
                  ) : (
                    <ul className="flagged-list">
                      {flagged.map((item) => (
                        <li key={`${item.student.submission_id}-${item.criterionId}`}>
                          <a
                            href={`#/results/students/${item.student.submission_id}`}
                            onClick={() =>
                              navigate(`/results/students/${item.student.submission_id}`)}
                          >
                            {item.student.student_ref ?? item.student.submission_id}
                          </a>{" "}
                          — {item.label}: {flagLabel(item.flag)}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
                <section className="results-filters">
                  <label>
                    Find a student{" "}
                    <input
                      type="search"
                      name="student-search"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                    />
                  </label>
                  <label>
                    Score level{" "}
                    <select
                      name="level-filter"
                      value={levelFilter}
                      onChange={(event) => setLevelFilter(event.target.value)}
                    >
                      <option value="">All levels</option>
                      {doc.score_levels.map((level) => (
                        <option key={level} value={level}>
                          {level}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Flag{" "}
                    <select
                      name="flag-filter"
                      value={flagFilter}
                      onChange={(event) => setFlagFilter(event.target.value)}
                    >
                      <option value="">All</option>
                      <option value="second_opinion">Second opinion</option>
                      <option value="low_confidence">Low confidence</option>
                      <option value="not_final">Not final yet</option>
                    </select>
                  </label>
                  <label>
                    Sort students{" "}
                    <select
                      name="student-sort"
                      value={sort}
                      onChange={(event) => setSort(event.target.value)}
                    >
                      <option value="az">A to Z</option>
                      <option value="za">Z to A</option>
                    </select>
                  </label>
                </section>
                <ul className="result-list" key={remount}>
                  {shown.map((student) => (
                    <li key={student.submission_id} className="result-row">
                      <div className="result-head">
                        <a
                          href={`#/results/students/${student.submission_id}`}
                          onClick={() => navigate(`/results/students/${student.submission_id}`)}
                        >
                          {student.student_ref ?? student.submission_id}
                        </a>
                        <span>Total: {student.total ?? "—"}</span>
                        <span>{student.state === "" ? "—" : scoreStateLabel(student.state)}</span>
                      </div>
                      <ul className="band-list">
                        {student.criteria.map((criterion) => (
                          <li key={criterion.criterion_id}>
                            <span className="step-note">{criterion.label}</span>{" "}
                            <span className="band-value">{criterion.criterion_band}</span>
                            {criterion.stored_band !== criterion.criterion_band && (
                              <span className="band-note">
                                {" "}(amended from {criterion.stored_band})
                              </span>
                            )}
                            {criterion.flag !== null && (
                              <span className={`badge badge-${flagTone(criterion.flag)}`}>
                                <TriangleAlert size={12} aria-hidden="true" />
                                <span> {flagLabel(criterion.flag)}</span>
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                      <OverrideForm
                        criteria={student.criteria.map((criterion) => ({
                          criterion_id: criterion.criterion_id,
                          label: criterion.label,
                          criterion_band: criterion.criterion_band,
                          levels: levelsFor(criterion.criterion_id).length > 0
                            ? levelsFor(criterion.criterion_id)
                            : [criterion.criterion_band],
                        }))}
                        final={student.state === "final"}
                        submissionId={student.submission_id}
                        runId={doc.run_id}
                        onDone={afterOverride}
                      />
                    </li>
                  ))}
                </ul>
                {shown.length === 0 && <p>No student matches the search or filters.</p>}
              </>
            )}
            <button
              type="button"
              className="button button-primary"
              onClick={() => openFinalize(doc)}
              disabled={doc.run_id === null || doc.students.length === 0}
            >
              Finalize the batch
            </button>
            {finalize.pending !== null && (
              <ConfirmDialog
                pending={finalize.pending}
                onClose={finalize.close}
                onDone={finalize.finish}
              />
            )}
          </>
        );
      }}
    </ReadScreen>
  );
}
