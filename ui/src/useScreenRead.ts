import { useCallback, useLayoutEffect, useState } from "react";
import { fetchRead } from "./api";

export interface ScreenRead<T> {
  /** The read's document, once it has answered. */
  data: T | null;
  /** The named failure the screen renders as a `role=alert` with a retry beside it. */
  error: string | null;
  /** Read again now (the retry button's action). */
  retry: () => void;
}

const POLL_FALLBACK_MS = 3000;

/**
 * One screen's read (FR-UI-03): fetched once on mount, optionally re-read on a poll (the
 * monitor's), with both outcomes in state — a failed read is a named message, never an
 * unhandled rejection. The retry is explicit (CT-UI-04's recovery), and it also fires
 * automatically when the route remounts. Nothing is kept outside this component's memory.
 */
export function useScreenRead<T>(
  path: string,
  params?: Record<string, string>,
  pollMs?: number,
): ScreenRead<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  // A layout effect, not a passive one: it puts the read on the wire inside the task that
  // mounted the screen — a click's synchronous flush — instead of a task after paint. The
  // console's contract is "one click loads the screen" (`spa.wait_for_screen` waits for the
  // read to answer), and a fetch registered a task late can be missed by a network-idle wait
  // that the page already qualified for (CT-UI-04's recovery arms on that wait).
  useLayoutEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    let timer: number | undefined;

    const read = (): void => {
      fetchRead<T>(path, controller.signal, params).then(
        (next) => {
          if (controller.signal.aborted) {
            return;
          }
          setData(next);
          setError(null);
        },
        (failure: unknown) => {
          if (controller.signal.aborted || stopped) {
            return;
          }
          setError(failure instanceof Error ? failure.message : String(failure));
        },
      ).finally(() => {
        if (!stopped && pollMs !== undefined) {
          timer = window.setTimeout(read, pollMs || POLL_FALLBACK_MS);
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
    // `attempt` is in deps: the retry re-runs the effect from scratch. `params` is an object
    // literal at call sites — screens pass stable values per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, attempt, pollMs, params?.run_id, params?.submission_id, params?.cohort_id]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { data, error, retry };
}
