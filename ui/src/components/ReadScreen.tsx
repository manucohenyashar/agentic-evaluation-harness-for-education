import type { ReactNode } from "react";
import { Screen } from "./Screen";
import { Banner, Skeleton } from "../state/StateDisplay";
import { classifyReadFailure } from "../state/model";
import type { ScreenRead } from "../useScreenRead";

/**
 * The degradation wording (FR-UI-07): what a screen whose read failed tells the teacher.
 * The named refusal the API answered comes first — "the console service is running" names
 * the first thing to check, and no screen over a healthy API renders this (TC-UI-03).
 */
const RECOVERY_TEXT = "check that the console service is running";

/**
 * One destination screen over one read: the level-1 heading, then either the named failure
 * as a banner (FR-UI-14's screen tier: what failed, why, and the retry as its one click —
 * CT-UI-04's named, recoverable shape) or the screen's own content over the answered
 * document. A read still in flight is a skeleton placeholder, never a spinner in
 * mid-content (§3.3.8).
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
          <Banner
            message={{
              ...classifyReadFailure(read.error),
              why: `${read.error}. ${RECOVERY_TEXT}.`,
            }}
            onAction={read.retry}
          />
          <button type="button" className="button" onClick={read.retry}>
            Retry
          </button>
        </>
      ) : read.data === null ? (
        <Skeleton />
      ) : (
        children(read.data)
      )}
    </Screen>
  );
}
