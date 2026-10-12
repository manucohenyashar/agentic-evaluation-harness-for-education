/**
 * The wizard home (FR-CONSOLE-47) — the stepper as hub. Nine stage rows, each one a link to
 * its stage: the row's state badge, the one detail the server's reads back, and the row's
 * next action. Above the rows sit the console's two standing lines: one NEXT (the earliest
 * stage that is not done, and its action) and one IMPACT (what editing the package would
 * touch, sourced from the impact read — never a client-side guess).
 */

import type { StageRow } from "./derivation";
import { STAGE_ROUTES } from "./derivation";
import { StageBadge } from "./StateBadge";
import { stageStateLabel } from "./vocabulary";

export interface WizardHomeProps {
  rows: StageRow[];
  next: string;
  impact: string | null;
  /** Builds a stage link with the current selection threaded through the address. */
  stageHref: (stageRoute: string) => string;
  /** True while the context read keeps failing — the named, recoverable message. */
  failed: boolean;
  retry: () => void;
}

export function WizardHome({ rows, next, impact, stageHref, failed, retry }: WizardHomeProps) {
  return (
    <section className="wizard">
      {failed && (
        <p role="alert" className="hub-alert">
          The console could not read its state. It will keep trying.{" "}
          <button type="button" className="button" onClick={retry}>
            Try again
          </button>
        </p>
      )}
      <p className="wizard-line wizard-next">
        <span className="wizard-line-label">Next:</span> {next}
      </p>
      {impact !== null && (
        <p className="wizard-line wizard-impact">
          <span className="wizard-line-label">Impact:</span> {impact}
        </p>
      )}
      <ol className="steps" aria-label="The nine stages">
        {rows.map((row) => {
          const target = row.actionRoute ?? STAGE_ROUTES[row.index - 1] ?? "/";
          return (
            <li key={row.index} className={`stage stage-${row.state}`}>
              <a
                className="stage-row"
                href={stageHref(target)}
                aria-label={`Stage ${row.index}: ${row.label}, ${stageStateLabel(row.state)}${
                  row.detail === "" ? "" : `. ${row.detail}`
                }`}
              >
                <span className="stage-num" aria-hidden="true">
                  {row.index}
                </span>
                <span className="stage-label">{row.label}</span>
                <StageBadge state={row.state} />
                <span className="stage-detail">{row.detail}</span>
                {row.action !== null && (
                  <span className="stage-action">
                    <span className="visually-hidden">Next action: </span>
                    {row.action}
                  </span>
                )}
              </a>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
