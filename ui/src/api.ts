export interface HubState {
  run_id: string | null;
  package_version_id: string | null;
  run_status: string | null;
  engine: string;
  poll_interval_ms: number;
}

export async function fetchHubState(signal?: AbortSignal): Promise<HubState> {
  const response = await fetch("/api/v1/hub", { signal });
  if (!response.ok) {
    throw new Error(`the hub state read failed with status ${response.status}`);
  }
  return (await response.json()) as HubState;
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
