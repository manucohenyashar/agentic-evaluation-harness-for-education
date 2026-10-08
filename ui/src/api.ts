/**
 * The console's JSON API, typed for the screens (FR-CONSOLE-45). Every read is a GET under
 * `/api/v1/` and answers a JSON document; every mutation is the enumerated control surface's
 * POST route. The paths mirror `src/aeh/console/api.py` — one table of routes, both sides.
 */

export interface HubState {
  run_id: string | null;
  package_version_id: string | null;
  run_status: string | null;
  engine: string;
  poll_interval_ms: number;
}

export async function fetchHubState(signal?: AbortSignal): Promise<HubState> {
  return fetchRead<HubState>("/api/v1/hub", signal);
}

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

export interface ClassRoster {
  cohorts: { cohort_id: string; students: Student[] }[];
}

export interface Papers {
  cohort_id: string;
  students: Student[];
  parts: string[];
}

export interface RunStartState {
  run_id: string | null;
  cohort_id: string | null;
  package_version_id: string | null;
  status: string | null;
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
  criterion_id: string;
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

export interface ResultStudent {
  submission_id: string;
  student_ref: string | null;
  total: number | null;
  state: string;
  criteria: CriterionBand[];
}

export interface ResultsScreen {
  run_id: string | null;
  cohort_id: string | null;
  students: ResultStudent[];
}

export interface NarrativeRow {
  level: string;
  question_id: string;
  text: string;
}

export interface StudentDetail {
  run_id: string;
  submission_id: string;
  student_ref: string | null;
  total: number | null;
  state: string | null;
  narrative: NarrativeRow[];
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
    throw new Error(detail || `the read failed with status ${response.status}`);
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
    payload = { action, error: `the action answered status ${response.status}` };
  }
  if (!response.ok && payload.error === undefined) {
    payload.error = payload.detail ?? `the action answered status ${response.status}`;
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
 */
export async function askHelp(question: string, signal?: AbortSignal): Promise<HelpAnswer> {
  const response = await fetch(`/api/v1/help/ask?q=${encodeURIComponent(question)}`, { signal });
  if (!response.ok) {
    throw new Error(`the assistant could not answer (status ${response.status})`);
  }
  return (await response.json()) as HelpAnswer;
}
