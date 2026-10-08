import { createContext, useContext } from "react";

/**
 * Hash navigation done in the click (`FR-UI-02`): the shell's links set the route through
 * this context — a React discrete event, whose updates flush synchronously, so the
 * destination screen mounts and puts its read on the wire inside the click's own task.
 * The default fragment navigation still runs after it and the shell's `hashchange` listener
 * re-sets the same route (a no-op), so back, reload and a pasted link keep working.
 */
export const Navigate = createContext<(route: string) => void>(() => {});

export function useNavigate(): (route: string) => void {
  return useContext(Navigate);
}
