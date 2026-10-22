import { useEffect, useState } from "react";
import { elapsedLabel } from "../wizard/vocabulary";

/**
 * The elapsed clock (FR-UI-29): a long operation shows "Working — 1 min 12 s" ticking
 * each second from the ledger's `started_at`, and its terminal phrase — "Done in 2 min
 * 14 s" ("Stopped after …" / "Failed after …") — once it ends. The times are the read's
 * own; the component only ticks between them.
 */

/** The operation's phase, from the states the ledger serves. A run still `pending` has
 * no clock yet; `complete` and `failed` are its endings. */
export type ClockPhase = "working" | "done" | "stopped" | "failed";

export function clockPhase(state: string | null | undefined): ClockPhase | null {
  switch (state) {
    case "complete":
      return "done";
    case "failed":
      return "failed";
    case "cancelled":
      return "stopped";
    case "running":
    case "paused":
      return "working";
    default:
      // A state this build does not know: neutral, never an error (CT-CONSOLE-38).
      return null;
  }
}

function secondsBetween(start: string, end: string | null, now: number): number | null {
  const started = Date.parse(start);
  if (Number.isNaN(started)) {
    return null;
  }
  const ended = end === null ? now : Date.parse(end);
  if (Number.isNaN(ended) || ended < started) {
    return null;
  }
  return Math.max(0, (ended - started) / 1000);
}

/** The ticking: re-renders once a second while the operation is still running, so the
 * clock grows without the read's own poll cadence. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) {
      return;
    }
    const tick = (): void => setNow(Date.now());
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

export function ElapsedClock({ startedAt, endedAt, state }: {
  startedAt: string | null;
  endedAt: string | null;
  state: string | null;
}) {
  const phase = clockPhase(state);
  const now = useNow(phase === "working");
  if (phase === null || startedAt === null) {
    return null;
  }
  // A terminal phase with no served end stamp measures nothing: the times are the
  // read's, and a duration to the mount moment would be invented (FR-UI-29).
  if (phase !== "working" && endedAt === null) {
    return null;
  }
  const seconds = secondsBetween(startedAt, phase === "working" ? null : endedAt, now);
  if (seconds === null) {
    return null;
  }
  return <>{elapsedLabel(phase, seconds)}</>;
}
