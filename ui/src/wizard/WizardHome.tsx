/**
 * The wizard home (FR-CONSOLE-47) — the stepper as hub. Nine stage rows, each one a link to
 * its stage: the row's state badge, the one detail the server's reads back, and the row's
 * next action. Above the rows sit the console's two standing lines: one NEXT (the earliest
 * stage that is not done, and its action) and one IMPACT (what editing the package would
 * touch, sourced from the impact read — never a client-side guess).
 */

import { useScreenRead } from "../useScreenRead";
import type { StageRow } from "./derivation";
import { STAGE_ROUTES } from "./derivation";
import { StageBadge } from "./StateBadge";
import { OutcomeBanner } from "../components/Outcome";
import { stageStateLabel, versionName } from "./vocabulary";

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

/** The hub read (FR-UI-02): the console's package version, its run's status and the decision
 * engine in force — the live facts the destinations carry. */
interface HubDoc {
  package_version_id: string | null;
  run_status: string | null;
  engine: string;
  poll_interval_ms: number;
}

/** Every destination, once, with the live fact that belongs to it (FR-UI-02): the links work
 * whatever the reads answer; a fact shows only once the hub read has supplied it. */
function Destinations({ stageHref }: { stageHref: (route: string) => string }) {
  const hub = useScreenRead<HubDoc>("/api/v1/hub", undefined, 5000).data;
  const fact = (text: string | null): string => (text === null ? "" : ` — ${text}`);
  const links: { label: string; route: string; fact: string }[] = [
    { label: "Set up a class", route: "/class", fact: "" },
    {
      label: "Set up a test package",
      route: "/package",
      fact: fact(hub === null ? null : `test: ${versionName(hub.package_version_id)}`),
    },
    { label: "Load papers", route: "/papers", fact: "" },
    {
      label: "Start a run",
      route: "/run",
      fact: fact(hub === null ? null : `last run: ${hub.run_status ?? "none yet"}`),
    },
    { label: "Monitor run", route: "/monitor", fact: "" },
    { label: "Review", route: "/review", fact: "" },
    { label: "Results", route: "/results", fact: "" },
    {
      label: "System status",
      route: "/status",
      fact: fact(hub === null ? null : `decision engine: ${hub.engine}`),
    },
    { label: "Manuals & help", route: "/help", fact: "" },
  ];
  return (
    <nav className="panel" aria-label="Destinations">
      <h2>Go to</h2>
      <ul className="rows-list">
        {links.map((link) => (
          <li key={link.route}>
            <a href={stageHref(link.route)}>
              {link.label}
              {link.fact}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function WizardHome({ rows, next, impact, stageHref, failed, retry }: WizardHomeProps) {
  return (
    <section className="wizard">
      <h1>Your grading day</h1>
      <OutcomeBanner />
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
      <Destinations stageHref={stageHref} />
    </section>
  );
}
