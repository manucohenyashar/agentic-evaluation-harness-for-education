/**
 * The sidebar (FR-CONSOLE-47): the wizard's persistent navigation. The wizard home shows
 * only the secondary pages; every other screen adds the compact stepper strip — nine
 * numbered rows with their state badges — so the whole journey stays one click away
 * wherever the teacher is. Every row links; nothing here posts.
 */

import { STAGE_ROUTES, type StageRow } from "./derivation";
import { StageBadge } from "./StateBadge";

/** Every lifecycle screen by name, so a teacher never needs the address bar to reach one
 * (FR-UI-02's destinations): the stage strip shows where the journey stands, these go
 * straight to a screen. */
const SCREEN_LINKS: { label: string; path: string }[] = [
  { label: "Set up a class", path: "/class" },
  { label: "Set up a test package", path: "/package" },
  { label: "Load papers", path: "/papers" },
  { label: "Start a run", path: "/run" },
  { label: "Monitor run", path: "/monitor" },
  { label: "Review", path: "/review" },
  { label: "Results", path: "/results" },
  // FR-CONSOLE-70: every test graded before, findable by class or by a student's name.
  { label: "Past tests", path: "/past" },
];

const SECONDARY_LINKS: { label: string; path: string }[] = [
  { label: "Parked", path: "/parked" },
  { label: "Jobs", path: "/jobs" },
  { label: "Issues", path: "/issues" },
  { label: "Logs", path: "/logs" },
  { label: "Settings", path: "/settings" },
  { label: "System status", path: "/status" },
  { label: "Manuals & help", path: "/help" },
];

export interface SidebarProps {
  /** The derived stages, or null while the context read has not landed. */
  rows: StageRow[] | null;
  route: string;
  /** Builds a stage link with the current selection threaded through the address. */
  stageHref: (stageRoute: string) => string;
}

export function Sidebar({ rows, route, stageHref }: SidebarProps) {
  return (
    <nav className="sidebar" aria-label="Console navigation">
      {rows !== null && route !== "/" && (
        <ol className="strip" aria-label="The nine stages">
          {rows.map((row) => {
            const target = row.actionRoute ?? STAGE_ROUTES[row.index - 1] ?? "/";
            return (
              <li key={row.index}>
                <a
                  className="strip-row"
                  href={stageHref(target)}
                  title={`${row.index}. ${row.label}`}
                  aria-label={`Stage ${row.index}: ${row.label}`}
                >
                  <span className="stage-num" aria-hidden="true">
                    {row.index}
                  </span>
                  <StageBadge state={row.state} compact />
                </a>
              </li>
            );
          })}
        </ol>
      )}
      <ul className="side-links" aria-label="Screens">
        {SCREEN_LINKS.map((link) => (
          <li key={link.path}>
            <a href={stageHref(link.path)} aria-current={route === link.path ? "page" : undefined}>
              {link.label}
            </a>
          </li>
        ))}
      </ul>
      <ul className="side-links" aria-label="More">
        {SECONDARY_LINKS.map((link) => (
          <li key={link.path}>
            <a href={stageHref(link.path)} aria-current={route === link.path ? "page" : undefined}>
              {link.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
