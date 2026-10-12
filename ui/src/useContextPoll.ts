import { useCallback, useEffect, useRef, useState } from "react";
import { fetchContext, type ContextDoc } from "./api";

/** The poll cadence: the same 3s fallback the other reads use (the context read declares
 * no interval of its own; the wizard's states change as runs change under the teacher). */
const CONTEXT_POLL_MS = 3000;

export interface ContextRead {
  context: ContextDoc | null;
  failed: boolean;
  /** The read's recovery action, run now rather than on the next poll tick (CT-UI-04). */
  retry: () => void;
}

/**
 * The context header's feed (FR-CONSOLE-48): read once on mount and re-read on a fixed
 * cadence, so the header's badges and the wizard's states follow the stored data without a
 * reload. Both outcomes land in state — a failed read is a visible "will keep trying",
 * never an unhandled rejection. Nothing lands in browser storage (CT-UI-07).
 */
export function useContextPoll(): ContextRead {
  const [context, setContext] = useState<ContextDoc | null>(null);
  const [failed, setFailed] = useState(false);
  const intervalMs = useRef(CONTEXT_POLL_MS);

  useEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    let timer: number | undefined;

    const read = (): void => {
      fetchContext(controller.signal).then(
        (next) => {
          setContext(next);
          setFailed(false);
        },
        () => {
          if (!controller.signal.aborted) {
            setFailed(true);
          }
        },
      ).finally(() => {
        if (!stopped) {
          timer = window.setTimeout(read, intervalMs.current);
        }
      });
    };
    read();

    return () => {
      stopped = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
      controller.abort();
    };
  }, []);

  // The retry is the same read the poll runs, outside the loop, sharing no controller with
  // it — the same shape the hub read's retry used (CT-UI-04's recovery).
  const retry = useCallback((): void => {
    fetchContext().then(
      (next) => {
        setContext(next);
        setFailed(false);
      },
      () => setFailed(true),
    );
  }, []);

  return { context, failed, retry };
}
