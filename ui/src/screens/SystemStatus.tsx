import { fetchRead, type SystemStatus as StatusDoc } from "../api";
import { ReadScreen } from "../components/ReadScreen";
import { entityStateLabel, versionName } from "../wizard/vocabulary";
import { useScreenRead } from "../useScreenRead";

/**
 * The system status screen (FR-UI-03): the hub's three facts beside the store's own shape —
 * how many cohort ledgers and package files the console serves, and the engine in force.
 */
export function SystemStatus() {
  const read = useScreenRead<StatusDoc>("/api/v1/system-status");
  return (
    <ReadScreen title="System status" read={read}>
      {(data) => (
        <>
          <p className="hub-state">
            {data.run_id === null
              ? "The console serves no run."
              : `The grading run — ${(data.run_status ? entityStateLabel(data.run_status) : "Not known yet")}, test ` +
                `${versionName(data.package_version_id)}.`}
          </p>
          <section className="panel">
            <h2>The store this console serves</h2>
            <ul className="rows-list">
              <li>
                <span className="step-name">Decision engine</span>
                <span className="step-state">{data.engine}</span>
              </li>
              <li>
                <span className="step-name">Cohort ledgers</span>
                <span className="step-state">{data.cohorts}</span>
              </li>
              <li>
                <span className="step-name">Package files</span>
                <span className="step-state">{data.packages}</span>
              </li>
            </ul>
          </section>
        </>
      )}
    </ReadScreen>
  );
}
