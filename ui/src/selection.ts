import { createContext, useContext } from "react";
import type { Selection } from "./wizard/derivation";

/**
 * The shell's resolved selection (class, package, run), shared with every screen. The
 * run-bound reads take the selected run as their `run_id`, so a run started from the console
 * — not only the one the console was launched with — is what the monitor, the review queue,
 * the blind sample and the results show (`CT-UI-07`: an opaque ref, nothing else).
 */
export const SelectionContext = createContext<Selection>({
  classId: null,
  packageId: null,
  runId: null,
});

export function useSelection(): Selection {
  return useContext(SelectionContext);
}

/** The run-bound read's query: the selected run, or none (the console's own run then). */
export function useRunParams(): Record<string, string> | undefined {
  const { runId } = useSelection();
  return runId === null ? undefined : { run_id: runId };
}
