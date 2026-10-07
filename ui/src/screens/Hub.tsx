import type { HubState } from "../api";

/**
 * The home hub's own content (FR-UI-02): what the console is and its live state — the package
 * version in force and the served run's status, read through `/api/v1/hub` and polled by the
 * shell. The destination cards themselves are the shell's navigation (`App.tsx`), so they stay
 * in place beside this screen and every other one.
 */
export function Hub({ state }: { state: HubState | null }) {
  return (
    <>
      <h1>Assessment console</h1>
      <p className="hub-state">
        {state === null
          ? "Reading the console's state."
          : `Package ${state.package_version_id ?? "not chosen"} — last run ${state.run_status ?? "none"}.`}
      </p>
    </>
  );
}
