/**
 * The sidebar (FR-CONSOLE-47): the wizard's persistent navigation. The wizard home shows
 * only the secondary pages; every other screen adds the compact stepper strip — nine
 * numbered rows with their state badges — so the whole journey stays one click away
 * wherever the teacher is. Every row links; nothing here posts.
 */

import { STAGE_ROUTES, type StageRow } from "./derivation";
import { StageBadge } from "./StateBadge";

const SECONDARY_LINKS: { label: string; path: string }[] = [
  { label: "Classes", path: "/class" },
  { label: "Papers inbox", path: "/papers" },
  { label: "Parked", path: "/parked" },
  { label: "Jobs", path: "/jobs" },
  { label: "Issues", path: "/issues" },
  { label: "Logs", path: "/logs" },
  { label: "Settings", path: "/settings" },
  { label: "Help", path: "/help" },
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
      <ul className="side-links">
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
