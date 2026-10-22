/**
 * The console's JSON API, typed for the screens (FR-CONSOLE-45). Every read is a GET under
 * `/api/v1/` and answers a JSON document; every mutation is the enumerated control surface's
 * POST route. The paths mirror `src/aeh/console/api.py` — one table of routes, both sides.
 */

// --- the lifecycle screens' documents (FR-UI-03, #635) -------------------------------------------

export interface SetupStep {
  step_id: string;
  name: string;
  blocking: boolean;
  available: boolean;
  done: boolean;
  note: string;
}

export interface SetupDraft {
  package_id: string;
  version_id: string;
  ready_to_publish: boolean;
  steps: SetupStep[];
}

export interface PackageSetup {
  draft: SetupDraft | null;
  current_version_id: string | null;
}

export interface Student {
  student_ref: string;
  submission_id: string | null;
  full_name: string | null;
}

/** A class's check against the teacher's own list (FR-CONSOLE-69): how many are listed, how
 * many papers are in, and who has none yet — by name. */
export interface ClassSummary {
  listed: number;
  with_paper: number;
  without_paper: string[];
}

export interface ClassRosterEntry {
  cohort_id: string;
  students: Student[];
  summary?: ClassSummary;
  consent_class?: string | null;
  runs?: number;
  papers?: number;
  graded_papers?: number;
  /** A class that never held a paper or a run is deleted outright; any other is kept. */
  deletable?: boolean;
}

export interface ClassRoster {
  cohorts: ClassRosterEntry[];
}

/** The roster editor's fixed copy and choices (FR-CONSOLE-42) — the SPA renders the
 * server's wording, so the consent classes and the paste rule are never restated here. */
export interface RosterEditorDoc {
  student_id_optional: string;
  name_requirement: string;
  consent_classes: { value: string; meaning: string }[];
  consent_default: string | null;
  paste: string;
}

/** The roster file's preview (FR-CONSOLE-63): the rows it holds and every problem row,
 * before anything is written. */
export interface RosterPreviewDoc {
  name: string;
  format_label: string | null;
  rows: { line: number; full_name: string; student_ref: string | null }[];
  problems: { line: number | null; reason: string }[];
  counts: { students: number; problems: number };
  ready: boolean;
}

/** One answer sheet the intake read, as the papers read reports it: the student it was
 * matched to, its paper-check status, and whether it is parked for the operator. */
export interface PaperSheet {
  submission_id: string;
  student_ref: string | null;
  /** The listed name of the student the paper is filed under (FR-CONSOLE-66). */
  full_name?: string | null;
  /** A matched paper, which the teacher may move to another student. */
  matched?: boolean;
  /** A run has graded it: it can be moved, never removed (FR-CONSOLE-67). */
  graded?: boolean;
  status: string;
  parked: boolean;
}

export interface Papers {
  cohort_id: string;
  students: Student[];
  parts: string[];
  /** Whether the class already holds its test paper (the right-test check's reference). */
  test_paper_read?: boolean;
  /** The answer sheets read into the class so far, oldest first. */
  sheets?: PaperSheet[];
  summary?: ClassSummary;
  /** How many of the class's papers a run has graded — the test paper is replaceable at 0. */
  graded_papers?: number;
}

export interface RunStartState {
  run_id: string | null;
  cohort_id: string | null;
  package_version_id: string | null;
  status: string | null;
  /** The settings profile a run started from this console runs under. */
  profile: string | null;
}

export interface MonitorState {
  run_id: string | null;
  status: string | null;
  pause_reason: string | null;
  progress: Record<string, unknown> | null;
}

export interface ReviewItem {
  submission_id: string;
  criterion_id: string;
  kind: string;
  /** The student by name (FR-UI-22) and the grading point by its label. */
  student_ref?: string | null;
  full_name?: string | null;
  label?: string;
}

export interface ReviewQueue {
  route: string;
  flagged_total: number;
  shown: ReviewItem[];
  budget_minutes: number | null;
  reserved_for_blind_minutes: number;
  residual_provisional: number;
  queries: string[];
  run_id: string;
}

export interface BlindSeat {
  submission_id: string;
  student_ref: string | null;
  full_name?: string | null;
  criterion_id: string;
  /** The grading point's teacher label (the question it grades). */
  label?: string;
  /** The grading point's own declared levels; null when the package could not be read. */
  band_scale?: string[] | null;
  evaluation_mode: string;
}

export interface BlindSeats {
  run_id: string;
  band_scale: string[];
  seats: BlindSeat[];
}

export interface CriterionBand {
  criterion_id: string;
  criterion_band: string;
}

/** Why a cell is flagged (FR-UI-15), as the read spells it; unknown values render neutral. */
export type FlagKind = "second_opinion" | "low_confidence" | "not_final" | (string & {});

/** One grading point's row in a student's results line — its effective score level (an
 * amended grade shows the amended level), the aggregation's own level beside it, and the
 * routing, state and flag the aggregation wrote. */
export interface ResultCriterion {
  criterion_id: string;
  label: string;
  criterion_band: string;
  stored_band: string;
  routing: string;
  state: string;
  state_reason: string;
  flag: FlagKind | null;
}

export interface ResultStudent {
  submission_id: string;
  student_ref: string | null;
  /** The student's listed name — what the teacher knows them by (FR-CONSOLE-70). */
  full_name?: string | null;
  total: number | null;
  state: string;
  criteria: ResultCriterion[];
}

/** One grading point's declared score levels, in the package's own order (FR-UI-15/17). */
export interface CriterionScale {
  criterion_id: string;
  label: string;
  levels: string[];
}

export interface ResultsScreen {
  run_id: string | null;
  cohort_id: string | null;
  /** The test version the run graded against (absent when no run is shown). */
  package_version_id?: string;
  /** The run's multiple-choice grading points, their options and current key — what the
   * key correction offers. */
  answer_keys?: {
    criterion_id: string;
    label: string;
    options: { option_id: string; label: string }[];
    key: string[];
  }[];
  score_levels: string[];
  scales: CriterionScale[];
  students: ResultStudent[];
}

export interface NarrativeRow {
  level: string;
  question_id: string;
  text: string;
}

/** One grader's verdict for a cell: its teacher label, the score level it chose, and the
 * evidence it cited (`FR-UI-16`'s per-judge outputs and "what the paper shows" quotes). */
export interface GraderVerdict {
  grader: string;
  score_level: string;
  cited: string[];
}

/** One grading point of a student's drill-down: the effective level, the aggregate's own
 * reason text, the declared scale the override offers, and the grader trail behind it. */
export interface CriterionDetail {
  criterion_id: string;
  label: string;
  criterion_band: string;
  stored_band: string;
  routing: string;
  state: string;
  state_reason: string;
  flag: FlagKind | null;
  levels: string[];
  graders: GraderVerdict[];
}

/** One amendment the current grade revision records — who, when, why, and the level the
 * grade moved from and to (FR-UI-17's render-back, RS-09). */
export interface AmendmentEntry {
  criterion_id: string;
  from_band: string;
  to_band: string;
  actor: string;
  reason: string;
  at: string;
}

export interface StudentDetail {
  run_id: string;
  submission_id: string;
  student_ref: string | null;
  full_name?: string | null;
  total: number | null;
  state: string | null;
  narrative: NarrativeRow[];
  criteria: CriterionDetail[];
  amendments: AmendmentEntry[];
}

export interface SystemStatus {
  run_id: string | null;
  run_status: string | null;
  package_version_id: string | null;
  engine: string;
  cohorts: number;
  packages: number;
}

export interface HelpDoc {
  manuals: string[];
  ask: string;
}

export type ActionResult = {
  action: string;
  dispatched?: boolean;
  refused?: boolean;
  detail?: string;
  error?: string;
  /** The job id a dispatched background action started (the draft job) — set only when
   * the console dispatched one, so the screen can watch it on the jobs read. */
  job_id?: string;
  /** The next step a refusal or an outcome names (`CT-CONSOLE-33`), when one is set. */
  next_action?: string;
  /** A refusal's first two sentences (FR-UI-25): what happened, and why. */
  what?: string;
  why?: string;
};

/**
 * One read: the document, or the refusal the screen renders as a named, recoverable message
 * (CT-UI-04). The error's text is the API's own refusal where it named one — never a stack.
 */
export async function fetchRead<T>(
  path: string,
  signal?: AbortSignal,
  params?: Record<string, string>,
): Promise<T> {
  const query = params ? `?${new URLSearchParams(params).toString()}` : "";
  const response = await fetch(path + query, { signal });
  if (!response.ok) {
    const refusal = await response.text().catch(() => "");
    let detail = "";
    try {
      detail = String(JSON.parse(refusal).error ?? "");
    } catch {
      detail = "";
    }
    throw new Error(detail || "the console could not read that");
  }
  return (await response.json()) as T;
}

/**
 * One enumerated control: POST to its route with a JSON body. The refusal (a 4xx with the
 * console's own wording) is returned as a result, not thrown — a refused action is an
 * outcome the screen shows, never an unhandled rejection.
 */
export async function performAction(
  action: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<ActionResult> {
  const slug = action.toLowerCase().replace(/\//g, "-").replace(/ /g, "-");
  const response = await fetch(`/api/v1/actions/${slug}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  let payload: ActionResult = { action };
  try {
    payload = (await response.json()) as ActionResult;
  } catch {
    payload = { action, error: "the action did not go through" };
  }
  if (!response.ok && payload.error === undefined) {
    payload.error = payload.detail ?? "the action did not go through";
  }
  return payload;
}

export interface HelpCitation {
  manual_id: string;
  anchor: string;
}

export interface HelpAnswer {
  answer: string;
  citations: HelpCitation[];
}

/**
 * One grounded ask (FR-UI-06): the only `M-HELP` call the SPA makes (TC-REQ-129) — the
 * citations come back inside the answer, so the panel never needs the manuals reads.
 * The manuals pages the citations point at are the console's own server-rendered pages
 * (`/manuals`), same origin, no API call.
 *
 * The ask may carry the asking screen's context (`FR-HELP-06`): the screen's identity and
 * the object refs it is reading — nothing else (`CT-UI-07`), and exactly the shape
 * `aeh/help/context.py` parses server-side. An ask without one is the plain manuals ask.
 */
export interface HelpContext {
  screen: string;
  refs: string[];
}

export async function askHelp(
  question: string,
  context?: HelpContext,
  signal?: AbortSignal,
): Promise<HelpAnswer> {
  const params = new URLSearchParams({ q: question });
  if (context !== undefined) {
    params.set("context", JSON.stringify(context));
  }
  const response = await fetch(`/api/v1/help/ask?${params.toString()}`, { signal });
  if (!response.ok) {
    throw new Error("the assistant could not answer just now");
  }
  return (await response.json()) as HelpAnswer;
}

// --- the wizard shell's reads (the redesign surface, FR-CONSOLE-47..52) ---------------------------
//
// Every state value below travels exactly as a server read spells it (`CT-CONSOLE-38`: the
// enums are additive; a value the SPA does not know renders as a neutral state, never an
// error), so the types keep an open string arm beside the declared values.

/** The stepper's state-badge values (`§3.3.4`'s legend, as the context read declares them). */
export type StageState =
  | "done"
  | "in_progress"
  | "not_started"
  | "needs_attention"
  | "failed"
  | "queued"
  | (string & {});

/** One class ledger (`ADR-48`): a class and a grading cohort are one ledger in two states,
 * so the switcher and the wizard treat them as one list. */
export interface ClassEntry {
  cohort_id: string;
  label: string;
  students: number;
  state: string;
  runs: number;
}

/** One wizard row the server derives for a package's stages — the shell renders the
 * server's state and detail, never a client-side copy of the rule. */
export interface PackageWizardRow {
  stage: string;
  state: StageState;
  detail: string;
}

export interface PackageEntry {
  package_id: string;
  state: string;
  /** The teacher label, "ENG7-READ-01 version 1" (FR-CONSOLE-74). */
  published_version: string | null;
  /** The version id the reads and actions take. */
  published_version_id: string | null;
  version_count: number;
  draft_missing_pieces: number | null;
  wizard: PackageWizardRow[];
}

export interface RunEntry {
  run_id: string;
  cohort_id: string;
  package_id: string;
  package_version_id: string;
  state: string;
  stage: string;
  started_at: string | null;
  completed_at: string | null;
}

/** The context header's feed (FR-CONSOLE-48): empty collections when nothing is stored. */
export interface ContextDoc {
  classes: ClassEntry[];
  cohorts: ClassEntry[];
  packages: PackageEntry[];
  runs: RunEntry[];
}

export async function fetchContext(signal?: AbortSignal): Promise<ContextDoc> {
  return fetchRead<ContextDoc>("/api/v1/context", signal);
}

/** What editing a package version would touch (FR-CONSOLE-49) — the wizard's IMPACT line,
 * and the editor's banner's list of the runs already graded under it. */
export interface ImpactDoc {
  /** The teacher label; `package_version_id` is the id (FR-CONSOLE-74). */
  package_version: string;
  package_version_id: string;
  runs: number;
  students: number;
  run_records: { run_id: string; cohort_id: string; state: string }[];
  regrading: { triggered: boolean; detail: string };
}

export async function fetchImpact(
  packageVersion: string,
  signal?: AbortSignal,
): Promise<ImpactDoc> {
  return fetchRead<ImpactDoc>("/api/v1/impact", signal, { package_version: packageVersion });
}

/** The park, under its teacher name (FR-CONSOLE-47) — the parked count the stepper names. */
export interface ParkedDoc {
  parked: {
    submission_id: string;
    cohort_id: string;
    reason: string;
    reason_label: string;
    matched_student: string | null;
    /** The matched student's listed name. */
    matched_name?: string | null;
    match_note: string;
    resolutions: string[];
    resolvable: boolean;
    /** The paper's student was not matched, but its pages were read: it can be given to
     * one of the class's students who has no paper yet. */
    assignable?: boolean;
    students_without_paper?: { student_ref: string; full_name: string | null }[];
    /** A second paper for a student who already has one (FR-INGEST-41): the student, and
     * their earlier paper — whether a run graded it (then it stays). */
    duplicate_of?: {
      student_ref: string;
      full_name: string | null;
      submission_id: string | null;
      graded: boolean;
    } | null;
    /** The operator decisions recorded for this paper, oldest first. */
    decisions?: {
      resolution: string;
      actor: string;
      student_ref: string | null;
      full_name?: string | null;
      note: string | null;
      decided_at: string;
    }[];
  }[];
  counts: { total: number; by_reason: Record<string, number> };
}

export async function fetchParked(signal?: AbortSignal): Promise<ParkedDoc> {
  return fetchRead<ParkedDoc>("/api/v1/parked", signal);
}

/** The jobs read's records (`CT-CONSOLE-37`'s field set) — the grading-point progress the
 * stepper's grading row renders. */
export interface JobRecord {
  job_id: string;
  kind: string;
  state: string;
  /** The authoring job's stage word ("reading documents", "drafting", "writing draft") —
   * set only while an authoring job reports stage-level progress (FR-AUTHOR-30). */
  stage?: string | null;
  /** The tries the current step item spent and the budget it had — the draft job's
   * per-item retry state, shown as "attempt x of y". */
  attempt?: number | null;
  attempts?: number | null;
  progress: { done: number | null; total: number | null; current: string | null };
  started_at: string | null;
  finished_at: string | null;
  cost_usd: number | null;
  error: { detail: string | null; next_action: string | null };
}

export interface JobsDoc {
  jobs: JobRecord[];
}

export async function fetchJobs(signal?: AbortSignal): Promise<JobsDoc> {
  return fetchRead<JobsDoc>("/api/v1/jobs", signal);
}

/**
 * The secondary pages' read payloads (FR-UI-18..21, this issue's pages). Each screen renders
 * what its read carried; a screen never invents a count or a state (CT-UI-08), and a next
 * step arrives already worded. `projected` is the read's own observability block (seam 4);
 * the screens do not shape it.
 */

/** The issues read (`GET /api/v1/issues?run_id=...`): the run's issues as the server's own
 * teacher sentences — every card's what / affects / next step arrives already worded. */
export interface IssuesDoc {
  run_id: string | null;
  issues: Array<{
    issue_id: string;
    source: string;
    what: string;
    affects: string;
    next_step: string;
  }>;
  projected: Record<string, unknown>;
}

/** The logs read (`GET /api/v1/logs?run_id=...&page=...`): one page of the run's records,
 * each already typed (milestone / summary / problem) and worded. */
export interface LogsDoc {
  run_id: string | null;
  records: Array<{
    record_id: string;
    kind: string;
    stage: string | null;
    at: string | null;
    text: string;
    detail: string | null;
  }>;
  page: { size: number; shown: number; more_available: boolean };
  projected: Record<string, unknown>;
}

/** One settings row: the projection's `SettingView`, as the read carries it. */
export interface SettingRow {
  field: string;
  label: string;
  value: string;
  type: string;
  editable: boolean;
  choices: string[];
  configured: boolean | null;
}

/** The configuration read (`GET /api/v1/config`): the settings rows in projection form —
 * each row's `field` names the write path's own setting id (an `EDITABLE_SETTINGS` value),
 * so the settings page posts its `update configuration` edits keyed by what it rendered. */
export interface ConfigDoc {
  settings: SettingRow[];
  projected: Record<string, unknown>;
}

export async function fetchIssues(runId: string, signal?: AbortSignal): Promise<IssuesDoc> {
  return fetchRead<IssuesDoc>("/api/v1/issues", signal, { run_id: runId });
}

export async function fetchLogs(
  runId: string,
  page: number,
  signal?: AbortSignal,
): Promise<LogsDoc> {
  return fetchRead<LogsDoc>("/api/v1/logs", signal, { run_id: runId, page: String(page) });
}

export async function fetchConfig(signal?: AbortSignal): Promise<ConfigDoc> {
  return fetchRead<ConfigDoc>("/api/v1/config", signal);
}

/** The one job's extended read (`GET /api/v1/jobs/{job_id}`): the record plus its measured
 * statistics — a statistic is shown only under the read's own key (CT-UI-08). */
export type JobDetailDoc = JobRecord & {
  statistics: { duration_seconds: number | null; items_graded: number | null };
};

export async function fetchJob(jobId: string, signal?: AbortSignal): Promise<JobDetailDoc> {
  return fetchRead<JobDetailDoc>(`/api/v1/jobs/${encodeURIComponent(jobId)}`, signal);
}

/** The manuals index (`GET /api/v1/manuals`) — the help panel's and help centre's list. */
export interface ManualsIndexDoc {
  manuals: Array<{ manual_id: string; title: string }>;
  projected?: Record<string, unknown>;
}

/** One manual (`GET /api/v1/manuals/{manual_id}`): the table of contents the help panel
 * matches the current screen against for its "this screen's manual section" link. */
export interface ManualDoc {
  manual_id: string;
  title: string;
  toc: Array<{ anchor: string; heading: string }>;
}

export async function fetchManuals(signal?: AbortSignal): Promise<ManualsIndexDoc> {
  return fetchRead<ManualsIndexDoc>("/api/v1/manuals", signal);
}

export async function fetchManual(manualId: string, signal?: AbortSignal): Promise<ManualDoc> {
  return fetchRead<ManualDoc>(`/api/v1/manuals/${encodeURIComponent(manualId)}`, signal);
}

// --- the authoring screens' reads (FR-UI-11..13, #764) --------------------------------------------

/**
 * The one POST read the SPA makes: the authoring preview. Its body carries the uploaded
 * documents themselves, because document content can never travel in a URL or a query
 * string (`CT-CONSOLE-34`), and the read writes nothing anywhere. A refusal (a body the
 * read cannot use) comes back as a thrown named message, the same shape `fetchRead`
 * renders.
 */
export async function postRead<T>(
  path: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    const refusal = await response.text().catch(() => "");
    let detail = "";
    try {
      detail = String(JSON.parse(refusal).error ?? "");
    } catch {
      detail = "";
    }
    throw new Error(detail || "the console could not read that");
  }
  return (await response.json()) as T;
}

/** One uploaded document, as the preview read answers it: accepted documents carry their
 * blocks, counts and warnings; refused ones carry the refusal with its next step. */
export interface PreviewDocument {
  name: string;
  accepted: boolean;
  pages?: number;
  blocks?: Array<{ kind: string; ordinal: number; page: number; text: string }>;
  stats?: {
    page_count: number;
    block_count: number;
    word_count: number;
    table_count: number;
    image_count: number;
  };
  warnings?: Array<{ code: string; message: string }>;
  refusal?: { detail: string; next_action: string };
}

export interface PreviewDoc {
  documents: PreviewDocument[];
  projected: { received: number; accepted: number; refused: number; blocks: number };
}

export async function previewDocuments(
  documents: Array<{ name: string; content_base64: string }>,
  signal?: AbortSignal,
): Promise<PreviewDoc> {
  return postRead<PreviewDoc>("/api/v1/authoring/preview", { documents }, signal);
}

/** One missing piece in the draft, as the draft read carries it: the item's id, its
 * location through the structure, the reason it stands, and what to supply. */
export interface DraftPlaceholder {
  item_id: string;
  location: string;
  reason: string;
  supply: string;
  /** The teacher's side of the gap (FR-AUTHOR-31): the plain question, the form of the
   * answer in words, and the answer's kind with its limits — the one definition the
   * field's format line and its check read. */
  question?: string;
  answer_hint?: string;
  answer_kind?: string;
  answer_min?: number | null;
  answer_max?: number | null;
  /** The item ids this question waits on before its own range is known (FR-AUTHOR-32:
   * a grade floor needs the questions' points first) — empty when it can be answered. */
  waiting_on?: string[];
}

/** One value in the package summary, as the read serves it (FR-CONSOLE-72): the display
 * text, whether it is answered at all, and where it came from — the teacher's own answer
 * or the documents. An unanswered value's text is the served "Not answered yet". */
export interface SummaryPiece {
  value: unknown;
  answered: boolean;
  source: string | null;
}

/** One question in the summary, in paper order, with its rubric lines under it. */
export interface SummaryQuestion {
  number: string;
  text: SummaryPiece;
  points: SummaryPiece;
  type: SummaryPiece;
  rubric: Array<{
    criterion_id: string;
    part_of?: string | null;
    correct_option?: SummaryPiece;
    levels?: SummaryPiece;
    points?: number | null;
  }>;
  expected_answer?: SummaryPiece;
  correct_option?: SummaryPiece;
}

/** The grade table in the summary: each grade and the lowest total that earns it, with
 * the test's maximum. A whole-table placeholder arrives with no rows and its own piece. */
export interface SummaryGrades {
  rows: Array<{ grade: string; lowest_total: unknown; answered: boolean; source: string | null }>;
  answered: boolean;
  max: number;
  value?: string;
  source?: string | null;
}

/** The package summary itself (FR-CONSOLE-72, `aeh.console.package_summary`): the whole
 * draft as it would be published, with the approve screen's reading order riding the
 * fields — test, approver, grade table, questions with their rubric, total points. */
export interface PackageSummary {
  test: SummaryPiece;
  approver: SummaryPiece;
  questions: SummaryQuestion[];
  total_points: number;
  points_complete: boolean;
  grades: SummaryGrades;
  unanswered: number;
}

/** One question in the draft, as the structure read projects it. `options` is the letters
 * the read has always answered; the labels ride the additive `option_labels` map beside
 * them. A question whose options stand as a placeholder sentinel arrives with an empty
 * letters list. */
export interface DraftQuestion {
  id: string;
  type: string;
  points: number | null;
  text: string;
  options: string[];
  option_labels?: Record<string, string>;
  model_answer: string | null;
}

/** One grading point in the draft, with its score levels as the read carries them. */
export interface DraftCriterion {
  id: string;
  question: string;
  points: number | null;
  score_method: string | null;
  component_of: string | null;
  score_levels: Array<{ name: string; points: number | null; descriptor: string }>;
  key?: string | string[] | null;
}

/** One validation issue the draft already carries, as the read projects it. */
export interface DraftIssueRow {
  field: string;
  message: string;
}

/** The draft-structure read (`GET /api/v1/authoring/draft`): the draft as structure —
 * never as TOML text (`ADR-45`). `draft` is null when no readable draft stands; the
 * upload ceiling rides every answer (`CT-CONSOLE-36`), so the screens enforce the same
 * bound client-side with the same teacher sentence. */
export interface AuthoringDraftDoc {
  draft: {
    package_id: string;
    file_name: string;
    package: string | null;
    approved_by: string | null;
    items: DraftQuestion[];
    criteria: DraftCriterion[];
    grades: unknown;
    placeholders: DraftPlaceholder[];
    /** Question-points gaps (FR-AUTHOR-32): a report-only gap stands in no sentinel, so
     * the points questions ride beside `placeholders`, same shape, same answer action. */
    points_questions?: DraftPlaceholder[];
    issues: DraftIssueRow[];
    missing_pieces: number;
    /** FR-CONSOLE-72: the package as it would be published, answers merged in. */
    summary?: PackageSummary;
    /** FR-UI-27: the served approved state — the FR-CONSOLE-73 sentence with the Load
     * papers link, present exactly when the draft stands approved and unchanged. */
    published?: { detail: string; next: { label: string; route: string } };
  } | null;
  doc_max_bytes: number;
  projected: { items: number; criteria: number; placeholders: number; issues: number };
}

export async function fetchAuthoringDraft(
  signal?: AbortSignal,
  packageId?: string | null,
): Promise<AuthoringDraftDoc> {
  const params = packageId ? { package_id: packageId } : undefined;
  return fetchRead<AuthoringDraftDoc>("/api/v1/authoring/draft", signal, params);
}

/** A chosen file's bytes as base64, for an action body: file content never travels in a URL
 * or a query string (`CT-CONSOLE-34`), only inside the request body. */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result ?? "");
      resolve(result.slice(result.indexOf(",") + 1));
    };
    reader.onerror = () => reject(reader.error ?? new Error("the file could not be read"));
    reader.readAsDataURL(file);
  });
}

/** Past tests (FR-CONSOLE-70): every grading run, newest first, with its class, test version,
 * dates and graded students by name. */
export interface PastTestStudent {
  submission_id: string;
  student_ref: string | null;
  full_name: string | null;
  total: number | null;
  state: string;
}

export interface PastTestRun {
  run_id: string;
  cohort_id: string;
  package_id: string;
  package_version_id: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  students: PastTestStudent[];
}

export interface PastTestsDoc {
  runs: PastTestRun[];
  unreadable_runs: number;
}
