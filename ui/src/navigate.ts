import { createContext, useContext } from "react";

/** The selection refs a navigation may set (`CT-UI-07`: opaque refs, nothing else); `null`
 * clears one, an absent key keeps what the address already carries. */
export type SelectionPatch = Partial<Record<"class" | "package" | "run", string | null>>;

/**
 * Hash navigation done in the click (`FR-UI-02`): the shell's links set the route through
 * this context — a React discrete event, whose updates flush synchronously, so the
 * destination screen mounts and puts its read on the wire inside the click's own task.
 * The default fragment navigation still runs after it and the shell's `hashchange` listener
 * re-sets the same route (a no-op), so back, reload and a pasted link keep working. A
 * screen that just made something (a class, a run) selects it through the patch.
 */
export const Navigate = createContext<(route: string, patch?: SelectionPatch) => void>(
  () => {},
);

export function useNavigate(): (route: string, patch?: SelectionPatch) => void {
  return useContext(Navigate);
}
