import type { ReactNode } from "react";

/**
 * One routed screen's content: the level-1 heading that names it and what the screen shows.
 * The `main` landmark itself belongs to the shell (`App.tsx`), so the hub's cards stay in
 * place beside every screen and every destination keeps its one-click reach (FR-UI-02).
 */
export function Screen({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <>
      <h1>{title}</h1>
      {children}
    </>
  );
}
