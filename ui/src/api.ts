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
