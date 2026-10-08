import type { ReactNode } from "react";
import { Screen } from "./Screen";
import type { ScreenRead } from "../useScreenRead";

/**
 * The degradation wording (FR-UI-07): what a screen whose read failed tells the teacher.
 * The named refusal the API answered comes first — "the console service is running" names
 * the first thing to check, and no screen over a healthy API renders this (TC-UI-03).
 */
const RECOVERY_TEXT = "check that the console service is running";

/**
 * One destination screen over one read: the level-1 heading, then either the named failure
 * with an explicit retry (CT-UI-04: named, recoverable — the retry re-runs the read) or the
 * screen's own content over the answered document. A read still in flight is said so.
 */
export function ReadScreen<T>({
  title,
  read,
  children,
}: {
  title: string;
  read: ScreenRead<T>;
  children: (data: T) => ReactNode;
}) {
  return (
    <Screen title={title}>
      {read.error !== null ? (
        <>
          <p role="alert" className="screen-alert">
            The console could not read this screen ({read.error}). {RECOVERY_TEXT}.
          </p>
          <button type="button" className="button" onClick={read.retry}>
            Retry
          </button>
        </>
      ) : read.data === null ? (
        <p>Reading.</p>
      ) : (
        children(read.data)
      )}
    </Screen>
  );
}
