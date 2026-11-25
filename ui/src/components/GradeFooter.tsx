import { createContext, useContext } from "react";
import type { ContextDoc, RunEntry } from "../api";
import { packageName } from "../wizard/vocabulary";

/**
 * The shell's context read, shared with the screens that need a run's own facts beyond their
 * read (the footer below). Null until the context read has answered.
 */
export const ContextDocContext = createContext<ContextDoc | null>(null);

/** FR-UI-51's line for one run, from the context read (FR-CONSOLE-43's wording). */
export function markedWithLine(run: RunEntry): string | null {
  const provenance = run.provenance;
  if (provenance === undefined || provenance === null) {
    return null;
  }
  const version = provenance.version_label === "" ? "" : ` version ${provenance.version_label}`;
  return (
    `Marked with ${packageName(run.package_id)}${version} · ` +
    `settings ${provenance.settings} · graders ${provenance.graders}`
  );
}

/**
 * Every grade view names what produced it (FR-UI-51, inv. 4, R66): one line below the
 * content, for the run the screen's own read names — not the selection, so Results opened
 * from Past tests names the older run's test, settings and graders.
 */
export function GradeFooter({ runId }: { runId: string | null | undefined }) {
  const context = useContext(ContextDocContext);
  const run = context?.runs.find((entry) => entry.run_id === runId);
  const line = run === undefined ? null : markedWithLine(run);
  if (line === null) {
    return null;
  }
  return (
    <p className="grade-footer" data-grade-footer="">
      {line}
    </p>
  );
}
