/**
 * The wizard's stage-state derivation (design delta §3.3, FR-CONSOLE-47): every state the
 * stepper shows is read from what the server's reads say, never invented client-side — the
 * package stages take the context read's own wizard rows verbatim, the paper stages count
 * the papers read's roster against the park, and the run stages read the run and jobs
 * records. An unknown enum value renders as the neutral state (`CT-CONSOLE-38`); no count
 * is ever shown that a read did not supply (`CT-UI-08`).
 */

import type { ContextDoc, ImpactDoc, JobsDoc, ParkedDoc, StageState } from "../api";
import type { Papers } from "../api";
import { STAGE_LABELS } from "./vocabulary";

/** The routes the stepper's rows and actions lead to. */
export const WIZARD_ROUTES = {
  class: "/class",
  package: "/package",
  review: "/package/review",
  papers: "/papers",
  run: "/run",
  parked: "/parked",
  results: "/results",
} as const;

/** Where each stage's row leads when it names no more specific action. */
export const STAGE_ROUTES: readonly string[] = [
  WIZARD_ROUTES.class,
  WIZARD_ROUTES.package,
  WIZARD_ROUTES.review,
  WIZARD_ROUTES.review,
  WIZARD_ROUTES.papers,
  WIZARD_ROUTES.run,
  WIZARD_ROUTES.run,
  WIZARD_ROUTES.results,
  WIZARD_ROUTES.results,
];

export interface Selection {
  classId: string | null;
  packageId: string | null;
  runId: string | null;
}

/** The reads the full derivation supplements the context with; each may be absent, and the
 * derivation then degrades to what the context alone says (never to a fabricated state). */
export interface SupplementalReads {
  papers: Papers | null;
  parked: ParkedDoc | null;
  jobs: JobsDoc | null;
  impact: ImpactDoc | null;
}

export interface StageRow {
  /** 1-based stage number, the stepper's row order. */
  index: number;
  label: string;
  state: StageState;
  /** The teacher-facing detail line; empty when the state alone says enough. */
  detail: string;
  /** The next action's label, or null when this stage names no action. */
  action: string | null;
  /** Where the action leads. */
  actionRoute: string | null;
}

/**
 * One ledger entry per class (`ADR-48`): the context read lists a class before it becomes a
 * grading cohort and the cohort after, so the switchers merge the two lists on the id.
 */
export function ledgerEntries(context: ContextDoc): ContextDoc["classes"] {
  const byId = new Map<string, ContextDoc["classes"][number]>();
  for (const entry of context.classes) byId.set(entry.cohort_id, entry);
  for (const entry of context.cohorts) {
    if (!byId.has(entry.cohort_id)) byId.set(entry.cohort_id, entry);
  }
  return [...byId.values()];
}

/** Newest first: a started run sorts ahead by its start time, ties break on the id. */
export function newestRunFirst(runs: ContextDoc["runs"]): ContextDoc["runs"] {
  return [...runs].sort((a, b) => {
    const aAt = a.started_at ?? "";
    const bAt = b.started_at ?? "";
    if (aAt !== bAt) return aAt < bAt ? 1 : -1;
    return a.run_id < b.run_id ? 1 : a.run_id > b.run_id ? -1 : 0;
  });
}

/**
 * The context selection behind one rendered screen: the hash's explicit refs win when they
 * still name something; anything absent or stale falls back to the server data's defaults —
 * a lone class or package selects itself, a selected run names its own package, and the
 * selected class's newest run is the run in focus (CT-UI-07: the hash carries only these
 * opaque refs; nothing else about the selection is stored).
 */
export function resolveSelection(
  context: ContextDoc,
  asked: { class?: string; package?: string; run?: string },
): Selection {
  const classes = ledgerEntries(context);
  const findClass = (id: string | undefined) =>
    id === undefined ? null : classes.find((c) => c.cohort_id === id) ?? null;
  const findRun = (id: string | undefined) =>
    id === undefined ? null : context.runs.find((r) => r.run_id === id) ?? null;
  const findPackage = (id: string | undefined) =>
    id === undefined ? null : context.packages.find((p) => p.package_id === id) ?? null;

  let run = findRun(asked.run);
  let cls = findClass(asked.class);
  if (cls === null && run !== null) cls = classes.find((c) => c.cohort_id === run?.cohort_id) ?? null;
  if (run === null && cls !== null) {
    run = newestRunFirst(context.runs.filter((r) => r.cohort_id === cls?.cohort_id))[0] ?? null;
  }

  let pkg = findPackage(asked.package);
  if (pkg === null && run !== null) pkg = findPackage(run.package_id);
  if (pkg === null && context.packages.length === 1) pkg = context.packages[0] ?? null;

  return {
    classId: cls?.cohort_id ?? null,
    packageId: pkg?.package_id ?? null,
    runId: run?.run_id ?? null,
  };
}

function packageOf(context: ContextDoc, packageId: string | null): ContextDoc["packages"][number] | null {
  return packageId === null ? null : context.packages.find((p) => p.package_id === packageId) ?? null;
}

function runOf(context: ContextDoc, runId: string | null): ContextDoc["runs"][number] | null {
  return runId === null ? null : context.runs.find((r) => r.run_id === runId) ?? null;
}

/** The context read's own wizard row for a package stage — the shell renders its state and
 * detail as they arrived, never a client-side copy of the rule. */
function wizardRow(
  pkg: ContextDoc["packages"][number] | null,
  stage: string,
): { state: StageState; detail: string } | null {
  const row = pkg?.wizard.find((r) => r.stage === stage);
  return row === undefined ? null : { state: row.state, detail: row.detail };
}

function parkedFor(parked: ParkedDoc | null, classId: string | null): number {
  if (parked === null) return 0;
  if (classId === null) return parked.counts.total;
  return parked.parked.filter((entry) => entry.cohort_id === classId).length;
}

function gradingJob(jobs: JobsDoc | null, runId: string | null) {
  if (jobs === null || runId === null) return null;
  return jobs.jobs.find((job) => job.kind === "run" && job.job_id === runId) ?? null;
}

function countWord(count: number, singular: string, plural: string): string {
  return count === 1 ? `1 ${singular}` : `${count} ${plural}`;
}

/**
 * The nine stages, derived. `supplemental` may be partial: the package stages need only the
 * context, the paper stages need the papers and park reads, and the run stages read the run
 * (and, for the grading detail, the jobs read). Where a read is absent the derivation says
 * what the context alone establishes and no more.
 */
export function deriveWizard(
  context: ContextDoc,
  selection: Selection,
  supplemental: Partial<SupplementalReads>,
): StageRow[] {
  const cls = ledgerEntries(context).find((c) => c.cohort_id === selection.classId) ?? null;
  const pkg = packageOf(context, selection.packageId);
  const run = runOf(context, selection.runId);
  const papers = supplemental.papers ?? null;
  const parkedCount = parkedFor(supplemental.parked ?? null, selection.classId);
  const job = gradingJob(supplemental.jobs ?? null, selection.runId);

  const rows: StageRow[] = [];

  // --- stage 1: the class exists and carries a roster ------------------------------------------
  {
    let state: StageState = "not_started";
    let detail = "";
    let action: string | null = "Create the class";
    if (cls !== null) {
      if (cls.students >= 2) {
        state = "done";
        detail = countWord(cls.students, "student", "students") + ".";
        action = null;
      } else if (cls.students === 1) {
        state = "in_progress";
        detail = "1 student is on the list — a class needs at least two.";
        action = "Add students";
      } else {
        state = "not_started";
        detail = "The class has no students yet.";
        action = "Add students";
      }
    }
    rows.push({ index: 1, label: STAGE_LABELS[0] ?? "Create the class", state, detail, action, actionRoute: action === null ? null : WIZARD_ROUTES.class });
  }

  // --- stage 2: the package exists --------------------------------------------------------------
  {
    const row = wizardRow(pkg, "create package");
    let state: StageState;
    let detail: string;
    let action: string | null;
    if (pkg === null) {
      state = "not_started";
      detail = context.packages.length === 0 ? "No test package exists yet." : "Choose a test package.";
      action = "Create the package";
    } else if (row !== null) {
      state = row.state;
      detail = row.detail;
      action = state === "done" ? null : "Open the package";
    } else {
      state = "not_started";
      detail = "";
      action = "Open the package";
    }
    rows.push({ index: 2, label: STAGE_LABELS[1] ?? "Create the test package", state, detail, action, actionRoute: action === null ? null : WIZARD_ROUTES.package });
  }

  // --- stage 3: the draft's review walk ----------------------------------------------------------
  {
    const row = wizardRow(pkg, "review draft");
    let state: StageState = "not_started";
    let detail = "";
    let action: string | null = null;
    if (pkg !== null && row !== null) {
      state = row.state;
      detail = row.detail;
      if (state !== "done" && pkg.draft_missing_pieces !== null) action = "Review the draft";
    }
    rows.push({ index: 3, label: STAGE_LABELS[2] ?? "Review the draft", state, detail, action, actionRoute: action === null ? null : WIZARD_ROUTES.review });
  }

  // --- stage 4: a published version exists --------------------------------------------------------
  {
    const row = wizardRow(pkg, "approve package");
    // The server's own detail names the published version id; the teacher line does not.
    let state: StageState;
    let detail: string;
    let action: string | null = null;
    if (pkg !== null && row !== null) {
      state = row.state;
      detail = pkg.published_version === null ? "Nothing is published yet." : "A published version is ready.";
      if (pkg.draft_missing_pieces === 0) action = "Review and approve";
    } else {
      state = "not_started";
      detail = pkg === null ? "" : "Nothing is published yet.";
    }
    rows.push({ index: 4, label: STAGE_LABELS[3] ?? "Approve the package", state, detail, action, actionRoute: action === null ? null : WIZARD_ROUTES.review });
  }

  // --- stage 5: one paper per roster student, none parked -----------------------------------------
  {
    let state: StageState;
    let detail = "";
    let action: string | null = null;
    let route: string | null = null;
    const roster = papers?.students.length ?? 0;
    const uploaded = papers?.students.filter((s) => s.submission_id !== null).length ?? 0;
    const label = STAGE_LABELS[4] ?? "Upload the papers";
    const push = (): void => {
      rows.push({ index: 5, label, state, detail, action, actionRoute: route });
    };
    if (papers === null || roster === 0) {
      // Without the papers read (or with an empty roster) the context alone decides: a run
      // past the paper stage could only have started on uploaded papers.
      if (run !== null && run.state !== "pending" && run.stage !== "papers") {
        state = "done";
      } else if (cls === null) {
        state = "not_started";
        action = "Choose the class";
        route = WIZARD_ROUTES.class;
      } else if (roster === 0 && papers !== null) {
        state = "not_started";
        detail = "The class has no students yet.";
        action = "Add students";
        route = WIZARD_ROUTES.class;
      } else {
        state = "not_started";
        detail = "No papers are uploaded yet.";
        action = "Upload the papers";
        route = WIZARD_ROUTES.papers;
      }
      push();
    } else if (uploaded >= roster && parkedCount > 0) {
      state = "needs_attention";
      detail = `${countWord(parkedCount, "paper is", "papers are")} parked.`;
      action = "Open the parked page";
      route = WIZARD_ROUTES.parked;
      push();
    } else if (uploaded >= roster) {
      state = "done";
      detail = `${countWord(uploaded, "paper", "papers")} uploaded for ${countWord(roster, "student", "students")}.`;
      push();
    } else if (uploaded === 0) {
      state = "not_started";
      detail = "No papers are uploaded yet.";
      action = "Upload the papers";
      route = WIZARD_ROUTES.papers;
      push();
    } else {
      state = "in_progress";
      detail = `${uploaded} of ${roster} students' papers uploaded.`;
      action = "Upload the papers";
      route = WIZARD_ROUTES.papers;
      push();
    }
  }

  // --- stage 6: reading, with nothing parked -------------------------------------------------------
  {
    let state: StageState;
    let detail = "";
    let action: string | null = null;
    let route: string | null = null;
    if (parkedCount > 0) {
      state = "needs_attention";
      detail = `${countWord(parkedCount, "paper is", "papers are")} parked.`;
      action = "Open the parked page";
      route = WIZARD_ROUTES.parked;
    } else if (run !== null && run.state !== "pending" && run.stage !== "papers") {
      state = "done";
      detail = "Every paper was read; none are parked.";
    } else if (run !== null && run.state === "failed") {
      state = "failed";
      detail = job?.error.detail ?? "The run stopped with a problem.";
    } else if (run !== null && run.state !== "pending") {
      state = "in_progress";
      detail = "Reading is under way.";
    } else {
      state = "not_started";
      if (run !== null) {
        detail = "Reading starts with the grading run.";
        action = "Start the run";
        route = WIZARD_ROUTES.run;
      }
    }
    rows.push({ index: 6, label: STAGE_LABELS[5] ?? "Reading the papers", state, detail, action, actionRoute: route });
  }

  // --- stage 7: the grading run in focus -----------------------------------------------------------
  {
    let state: StageState;
    let detail = "";
    let action: string | null = null;
    if (run === null) {
      state = "not_started";
      detail = "No grading run has started.";
      action = "Start the run";
    } else {
      switch (run.state) {
        case "pending":
          state = "queued";
          detail = "The run is waiting to start.";
          break;
        case "running": {
          state = "in_progress";
          const progress = job?.progress;
          detail =
            progress !== undefined && progress.total !== null
              ? `Grading points: ${progress.done ?? 0} of ${progress.total} done.`
              : "The run is grading.";
          break;
        }
        case "paused":
          state = "in_progress";
          detail = "The run is paused.";
          break;
        case "failed":
          state = "failed";
          detail = job?.error.detail ?? "The run stopped with a problem.";
          break;
        case "complete":
          state = "done";
          detail = "The run finished.";
          break;
        default:
          // A state this build does not know: neutral, never an error (CT-CONSOLE-38).
          state = "needs_attention";
          break;
      }
    }
    rows.push({ index: 7, label: STAGE_LABELS[6] ?? "Start the grading run", state, detail, action, actionRoute: action === null ? null : WIZARD_ROUTES.run });
  }

  // --- stage 8: the review window over the finished run --------------------------------------------
  {
    let state: StageState = "not_started";
    let detail = "";
    let action: string | null = null;
    if (run !== null && run.state === "complete") {
      if (run.stage === "exporting") {
        state = "done";
        detail = "Every grade is final.";
      } else if (run.stage === "reviewing") {
        state = "in_progress";
        detail = "The grades need review before they are final.";
        action = "Review results";
      }
    }
    rows.push({ index: 8, label: STAGE_LABELS[7] ?? "Review the results", state, detail, action, actionRoute: action === null ? null : WIZARD_ROUTES.results });
  }

  // --- stage 9: the export -------------------------------------------------------------------------
  // The done arm needs an export history, which no read carries yet; until one exists the
  // stage reads only what the run's own stage says (never a done the data does not back).
  {
    let state: StageState = "not_started";
    let detail = "";
    let action: string | null = null;
    if (run !== null && run.stage === "exporting") {
      state = "queued";
      detail = "The grades are final — the export can run.";
      action = "Export the results";
    }
    rows.push({ index: 9, label: STAGE_LABELS[8] ?? "Export the results", state, detail, action, actionRoute: action === null ? null : WIZARD_ROUTES.results });
  }

  return rows;
}

/** The stepper's one NEXT line: the earliest stage that is not done, preferring the first
 * one that names an action; a stage whose turn it is but that names no action of its own
 * reads as its name alone. */
export function nextLine(rows: StageRow[]): string {
  const open = rows.filter((row) => row.state !== "done");
  const first = open.find((row) => row.action !== null) ?? open[0];
  if (first === undefined) return "All nine stages are done.";
  const action =
    first.action === null || first.action.toLowerCase() === first.label.toLowerCase()
      ? null
      : first.action;
  return action === null ? `${first.label}.` : `${first.label} — ${action}`;
}

/**
 * The stepper's one IMPACT line, sourced from the impact read (FR-CONSOLE-49): the read's
 * own `regrading` wording, verbatim — what editing the selected package's published version
 * would touch, or its measured "nothing downstream". Null when the read has not landed.
 */
export function impactLine(impact: ImpactDoc | null): string | null {
  return impact === null ? null : impact.regrading.detail;
}
