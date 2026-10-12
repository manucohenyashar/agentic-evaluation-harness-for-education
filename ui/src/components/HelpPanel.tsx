import { useEffect, useState } from "react";
import { BookOpen, CircleHelp } from "lucide-react";
import { fetchManual, fetchManuals, type ManualsIndexDoc } from "../api";
import { QaPanel } from "../screens/Help";
import type { HelpContext } from "../api";

/**
 * The help-everywhere side panel (FR-UI-21, design delta §3.3.11): it opens over any
 * screen and carries the manuals index, the current screen's own manual section where the
 * console's operating manual names one, and the grounded Q&A box — the ask tagged with the
 * asking screen's identity and the object refs it is reading (`FR-HELP-06`, and nothing
 * more than that travels: `CT-UI-07`). Nothing here posts and nothing is stored; the panel
 * is presentational state of the shell.
 */

/** The console's own operating manual — where a screen's "how do I use this" section lives. */
const OPERATING_MANUAL = "console-operating-tutorial";

/** Which section of the operating manual names each screen. A screen the manual does not
 * name shows no section link — nothing is fabricated to fill the slot. */
const SCREEN_SECTIONS: Array<[route: string, keyword: string]> = [
  ["/", "the page map"],
  ["/class", "set up the test"],
  ["/package", "set up the test"],
  ["/package/review", "set up the test"],
  ["/papers", "load the student papers"],
  ["/parked", "load the student papers"],
  ["/run", "start the run, and watch it"],
  ["/jobs", "start the run, and watch it"],
  ["/issues", "when something goes wrong"],
  ["/logs", "when something goes wrong"],
  ["/results", "morning review"],
  ["/settings", "changing something"],
];

/** The screen id the ask's context carries: the route as a slug, with the parameterized
 * routes collapsed to their page. Whitespace-free, as `aeh/help/context.py` requires. */
function screenIdOf(route: string): string {
  if (route.startsWith("/results/students/")) {
    return "results";
  }
  if (route === "/review/blind") {
    return "review";
  }
  const id = route.replace(/^\//, "").replace(/\//g, "-");
  return id === "" ? "wizard-home" : id;
}

function sectionFor(route: string): string | null {
  for (const [prefix, keyword] of SCREEN_SECTIONS) {
    if (route === prefix || route.startsWith(`${prefix}/`)) {
      return keyword;
    }
  }
  return null;
}

interface ScreenSection {
  manualId: string;
  manualTitle: string;
  anchor: string;
  heading: string;
}

export function HelpPanel({
  route,
  refs,
  onClose,
}: {
  route: string;
  refs: string[];
  onClose: () => void;
}) {
  const [manuals, setManuals] = useState<ManualsIndexDoc | null>(null);
  const [manualsError, setManualsError] = useState<string | null>(null);
  const [section, setSection] = useState<ScreenSection | null>(null);
  const [sectionError, setSectionError] = useState<string | null>(null);

  const screenId = screenIdOf(route);
  const context: HelpContext = {
    screen: screenId,
    refs: refs.filter((ref) => ref.trim() !== "" && !/\s/.test(ref)),
  };

  useEffect(() => {
    const controller = new AbortController();
    fetchManuals(controller.signal).then(
      (answer) => {
        if (controller.signal.aborted) return;
        setManuals(answer);
        setManualsError(null);
      },
      (failure: unknown) => {
        if (controller.signal.aborted) return;
        setManuals(null);
        setManualsError(failure instanceof Error ? failure.message : String(failure));
      },
    );
    const keyword = sectionFor(route);
    if (keyword !== null) {
      fetchManual(OPERATING_MANUAL, controller.signal).then(
        (manual) => {
          if (controller.signal.aborted) return;
          const heading = manual.toc.find((entry) =>
            entry.heading.toLowerCase().includes(keyword),
          );
          setSection(
            heading === undefined
              ? null
              : {
                  manualId: manual.manual_id,
                  manualTitle: manual.title,
                  anchor: heading.anchor,
                  heading: heading.heading,
                },
          );
          setSectionError(null);
        },
        (failure: unknown) => {
          // A failed read is named, not silent — "no section" and "could not read" must
          // not look the same (CT-UI-04).
          if (!controller.signal.aborted) {
            setSection(null);
            setSectionError(failure instanceof Error ? failure.message : String(failure));
          }
        },
      );
    } else {
      setSection(null);
      setSectionError(null);
    }
    return () => controller.abort();
    // `route` is the dependency: the section follows the screen the panel sits over.
  }, [route]);

  return (
    <aside className="help-panel" aria-label="Help">
      <div className="help-panel-head">
        <h2>
          <CircleHelp size={18} aria-hidden="true" /> Help
        </h2>
        <button type="button" className="button" onClick={onClose}>
          Close
        </button>
      </div>
      {section !== null && (
        <p className="help-panel-section">
          <BookOpen size={14} aria-hidden="true" /> This screen's manual section:{" "}
          <a href={`/manuals/${encodeURIComponent(section.manualId)}#${section.anchor}`}>
            {section.heading}
          </a>
          <span className="help-panel-manual-title"> — in {section.manualTitle}</span>
        </p>
      )}
      {section === null && sectionError !== null && (
        <p role="alert" className="help-panel-section">
          The console could not read this screen's manual section ({sectionError}).
        </p>
      )}
      <nav className="help-panel-manuals" aria-label="The manuals">
        <h3>The manuals</h3>
        {manualsError !== null && (
          <p role="alert">The console could not read the manuals list ({manualsError}).</p>
        )}
        {manuals !== null && (
          <ul>
            {manuals.manuals.map((manual) => (
              <li key={manual.manual_id}>
                <a href={`/manuals/${encodeURIComponent(manual.manual_id)}`}>{manual.title}</a>
              </li>
            ))}
          </ul>
        )}
      </nav>
      <QaPanel context={context} compact />
    </aside>
  );
}
