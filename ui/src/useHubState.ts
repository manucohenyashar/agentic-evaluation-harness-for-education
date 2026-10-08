import { useCallback, useEffect, useRef, useState } from "react";
import { fetchHubState, type HubState } from "./api";

/** The poll cadence until the first read answers (then the read's own `poll_interval_ms`). */
const FIRST_POLL_FALLBACK_MS = 3000;

export interface HubRead {
  state: HubState | null;
  failed: boolean;
  /** The read's recovery action, run now rather than on the next poll tick (CT-UI-04). */
  retry: () => void;
}

/**
 * The hub's live state (FR-UI-02): read once on mount and re-read on the interval the read
 * itself declares, so a run that changes under an open console shows without a reload. Both
 * outcomes land in state — a failed read is a visible "will keep trying", never an unhandled
 * rejection. No state is kept anywhere but memory (FR-UI-08): a reload refetches, and nothing
 * lands in browser storage.
 */
export function useHubState(): HubRead {
  const [state, setState] = useState<HubState | null>(null);
  const [failed, setFailed] = useState(false);
  const intervalMs = useRef(FIRST_POLL_FALLBACK_MS);

  useEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    let timer: number | undefined;

    const read = (): void => {
      fetchHubState(controller.signal).then(
        (next) => {
          intervalMs.current = next.poll_interval_ms || intervalMs.current;
          setState(next);
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

  // The retry is the same read the poll runs, outside the loop: an immediate refetch, so a
  // failed state's "try again" is a real action, not a wait for the next tick. It shares no
  // controller with the poll — a retry's answer must survive the poll's own abort — and its
  // outcome lands in the same state the poll writes, so whichever answers first wins.
  const retry = useCallback((): void => {
    fetchHubState().then(
      (next) => {
        setState(next);
        setFailed(false);
      },
      () => setFailed(true),
    );
  }, []);

  return { state, failed, retry };
}
