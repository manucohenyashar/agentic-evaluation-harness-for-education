/**
 * The shell's supplemental reads: the three reads the wizard's paper and run stages count
 * — the selected class's papers, the park, the jobs — plus, when the selected package has
 * a published version, the impact read. They live in the shell, not on the wizard home, so
 * the compact strip on every secondary page derives from the same answered reads the home
 * does: no stage state is ever rendered from the absence of a read. A read whose subject
 * does not exist (no class chosen, no published version) makes no request at all.
 */

import type { ContextDoc, ImpactDoc, JobsDoc, ParkedDoc, Papers as PapersDoc } from "../api";
import { useScreenRead, type ScreenRead } from "../useScreenRead";

/** The supplemental reads re-poll on the same cadence as the context read. */
const POLL_MS = 3000;

export interface WizardReads {
  papers: ScreenRead<PapersDoc>;
  parked: ScreenRead<ParkedDoc>;
  jobs: ScreenRead<JobsDoc>;
  impact: ScreenRead<ImpactDoc>;
  /** The selected package's published version, or null while none is selected. */
  publishedVersion: string | null;
}

export function useWizardReads(
  context: ContextDoc | null,
  selection: { classId: string | null; packageId: string | null },
): WizardReads {
  const classId = selection.classId;
  const papers = useScreenRead<PapersDoc>(
    classId === null ? null : "/api/v1/papers",
    classId === null ? undefined : { cohort_id: classId },
    POLL_MS,
  );
  const parked = useScreenRead<ParkedDoc>("/api/v1/parked", undefined, POLL_MS);
  const jobs = useScreenRead<JobsDoc>("/api/v1/jobs", undefined, POLL_MS);
  const publishedVersion =
    context?.packages.find((entry) => entry.package_id === selection.packageId)
      ?.published_version_id ?? null;
  const impact = useScreenRead<ImpactDoc>(
    publishedVersion === null ? null : "/api/v1/impact",
    publishedVersion === null ? undefined : { package_version: publishedVersion },
    POLL_MS,
  );
  return { papers, parked, jobs, impact, publishedVersion };
}
