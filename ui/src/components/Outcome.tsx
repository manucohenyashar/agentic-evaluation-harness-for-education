/**
 * Where every action's outcome shows (FR-UI-24/25): one banner fixed at the top of the
 * content area, so the answer to a click is inside the viewport whatever the scroll
 * position the click was made from. It stays until dismissed, until the next action, or
 * until the teacher moves to another screen. Each report also raises a toast, and the
 * pressed control shows a spinner and stays disabled while its request is in flight
 * (`BusyButton`).
 *
 * A refusal reads as three sentences — what happened, why, what to do next — from the
 * server's own `what`/`why`/`next_action`; the shared vocabulary supplies the fallbacks.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { CircleCheck, CircleX, LoaderCircle, X } from "lucide-react";
import { performAction, type ActionResult } from "../api";
import { useToast } from "../state/StateDisplay";
import {
  OUTCOME_DISMISS,
  OUTCOME_DONE_FALLBACK,
  OUTCOME_FALLBACK_NEXT,
  OUTCOME_FALLBACK_WHAT,
  OUTCOME_FALLBACK_WHY,
  OUTCOME_REFUSED_PREFIX,
} from "../wizard/vocabulary";

/** One action's outcome, in the three parts the banner shows. A success carries `what`
 * alone, or with the next step the server named. */
export interface Outcome {
  refused: boolean;
  what: string;
  why: string;
  next: string;
}

/** Whether the console refused (or never reached) the action. */
export function isRefused(result: ActionResult): boolean {
  return (result.error !== undefined && result.error !== "") || result.refused === true;
}

/**
 * The banner's safety net (FR-UI-23): a server sentence that still carries an internal
 * reference — a run id, a `<package>@<hash>` version, a `pkg-…` ref, a file path, an
 * action's internal name quoted back — is said in plain words instead. The screens give
 * their own sentence for the actions they know (`PendingAction.said`); this catches the rest.
 */
export function plainText(text: string): string {
  return text
    .replace(/Nothing was changed: “[^”]*” did not go through\./g, OUTCOME_FALLBACK_WHAT)
    .replace(/\b(?:run-)?[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}\b/gi, "the run")
    .replace(/\b([A-Za-z0-9][\w.-]*)@[0-9a-f]{12}\b/g, (_all, name: string) =>
      name.startsWith("pkg-") ? "this test" : name)
    .replace(/\bpkg-[\w.-]+/g, "this test")
    .replace(/(?:[A-Za-z]:)?[\\/](?:[\w. -]+[\\/])+[\w.-]+/g, "the console's files");
}

/** An action's answer as the banner's three parts. */
export function outcomeOf(result: ActionResult, said?: string): Outcome {
  if (!isRefused(result)) {
    return {
      refused: false,
      what: said ?? plainText(result.detail || OUTCOME_DONE_FALLBACK),
      why: "",
      next: plainText(result.next_action ?? ""),
    };
  }
  return {
    refused: true,
    what: plainText(result.what || OUTCOME_FALLBACK_WHAT),
    why: plainText(result.why || result.error || result.detail || OUTCOME_FALLBACK_WHY),
    next: plainText(result.next_action || OUTCOME_FALLBACK_NEXT),
  };
}

/** A screen's own sentence as an outcome: a success, or a refusal whose sentence is the why. */
export function textOutcome(text: string, refused = false): Outcome {
  return refused
    ? { refused: true, what: OUTCOME_FALLBACK_WHAT, why: text, next: OUTCOME_FALLBACK_NEXT }
    : { refused: false, what: text, why: "", next: "" };
}

/** The banner's sentence as one line — what the outcome paragraph reads. */
export function outcomeSentence(outcome: Outcome): string {
  const parts = outcome.refused
    ? [`${OUTCOME_REFUSED_PREFIX} ${outcome.what}`, outcome.why, outcome.next]
    : [outcome.what, outcome.next];
  return parts.filter((part) => part !== "").join(" ");
}

interface OutcomeApi {
  /** Show `outcome` in the banner; raise its toast unless the screen raises its own. */
  report: (outcome: Outcome, options?: { toast?: boolean }) => void;
  /** Clear the banner — a new action has started. */
  clear: () => void;
  current: Outcome | null;
}

const OutcomeContext = createContext<OutcomeApi>({
  report: () => undefined,
  clear: () => undefined,
  current: null,
});

/** The screen's handle on the banner. */
export function useOutcome(): OutcomeApi {
  return useContext(OutcomeContext);
}

/**
 * Holds the one current outcome for the shell. Sits inside the `ToastHost`. `route` is the
 * screen the teacher stands on: an outcome stays on the screen it was first shown on (an
 * action that moves the teacher to another screen shows its outcome there), and moving on
 * to a different screen afterwards clears it.
 */
export function OutcomeHost({ route, children }: { route: string; children: ReactNode }) {
  const toast = useToast();
  const [current, setCurrent] = useState<Outcome | null>(null);
  const shownOn = useRef<{ outcome: Outcome | null; route: string }>({ outcome: null, route });
  useEffect(() => {
    if (current === null) {
      return;
    }
    if (shownOn.current.outcome !== current) {
      shownOn.current = { outcome: current, route };
    } else if (shownOn.current.route !== route) {
      setCurrent(null);
    }
  }, [current, route]);
  const report = useCallback(
    (outcome: Outcome, options?: { toast?: boolean }) => {
      setCurrent(outcome);
      if (options?.toast !== false) {
        toast({ kind: outcome.refused ? "failure" : "success", text: outcome.what });
      }
    },
    [toast],
  );
  const clear = useCallback(() => setCurrent(null), []);
  const api = useMemo(() => ({ report, clear, current }), [report, clear, current]);
  return <OutcomeContext.Provider value={api}>{children}</OutcomeContext.Provider>;
}

/**
 * The banner itself: directly under the screen's heading, sticky at the top of the
 * viewport, so it is inside the viewport wherever the click was made.
 */
export function OutcomeBanner() {
  const { current, clear } = useOutcome();
  if (current === null) {
    return null;
  }
  const Glyph = current.refused ? CircleX : CircleCheck;
  return (
    <div className={`outcome-banner ${current.refused ? "outcome-refused" : "outcome-done"}`}>
      <Glyph size={18} aria-hidden="true" />
      <p role="status" className="action-outcome">
        {current.refused ? (
          <>
            <strong className="outcome-what">
              {OUTCOME_REFUSED_PREFIX} {current.what}
            </strong>{" "}
            <span className="outcome-why">{current.why}</span>{" "}
            <span className="outcome-next">{current.next}</span>
          </>
        ) : (
          <>
            <strong className="outcome-what">{current.what}</strong>
            {current.next !== "" && (
              <>
                {" "}
                <span className="outcome-next">{current.next}</span>
              </>
            )}
          </>
        )}
      </p>
      <button
        type="button"
        className="outcome-dismiss"
        onClick={clear}
        aria-label={OUTCOME_DISMISS}
        title={OUTCOME_DISMISS}
      >
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

/**
 * The pressed control's state (FR-UI-24(c)): disabled, with a spinner and `aria-busy`,
 * while its request is in flight.
 */
export function BusyButton({
  busy,
  disabled,
  children,
  className = "button",
  type = "button",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { busy: boolean }) {
  return (
    <button
      {...rest}
      type={type}
      className={className}
      disabled={busy || disabled}
      aria-busy={busy || undefined}
    >
      {busy && <LoaderCircle size={14} className="spin" aria-hidden="true" />}
      {children}
    </button>
  );
}

/**
 * One action a screen posts directly (no confirmation dialog): `busy` while in flight, the
 * outcome reported to the banner when it returns, a dropped connection reported as a
 * refusal. `ok` decides success (default: not refused); `said` replaces the success
 * sentence with the screen's own (its toast says the same).
 */
export function useReportedAction() {
  const { report, clear } = useOutcome();
  const [busy, setBusy] = useState(false);
  const run = useCallback(
    (
      action: string,
      body: Record<string, unknown>,
      options: {
        ok?: (result: ActionResult) => boolean;
        said?: (result: ActionResult) => string;
        onDone?: (result: ActionResult) => void;
        toast?: boolean;
      } = {},
    ): Promise<ActionResult> => {
      setBusy(true);
      clear();
      return performAction(action, body)
        .catch(
          (failure: unknown): ActionResult => ({
            action,
            error: failure instanceof Error ? failure.message : String(failure),
          }),
        )
        .then((result) => {
          setBusy(false);
          const ok = options.ok !== undefined ? options.ok(result) : !isRefused(result);
          const outcome = outcomeOf(ok ? result : { ...result, refused: true });
          if (ok && options.said !== undefined) {
            outcome.what = options.said(result);
          }
          report(outcome, { toast: options.toast });
          if (ok) {
            options.onDone?.(result);
          }
          return result;
        });
    },
    [report, clear],
  );
  return { busy, run };
}

/** Why the submit button beside it is disabled, said in words (FR-UI-36). */
export function DisabledReason({ id, reason }: { id?: string; reason: string | null }) {
  if (reason === null || reason === "") {
    return null;
  }
  return (
    <span id={id} className="disabled-reason">
      {reason}
    </span>
  );
}
