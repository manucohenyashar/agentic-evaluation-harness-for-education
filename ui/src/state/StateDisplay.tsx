/**
 * The three state tiers rendered (FR-UI-14, design delta §3.3.8): the toast a completed
 * action confirms in, the inline note beside the thing it is about, and the banner a
 * screen-level state persists in. Icon and label carry every state together with the
 * token colour (`CT-UI-10` — never colour alone), and no busy state is ever a spinner in
 * mid-content: content areas show skeletons, jobs show progress bars fed by the counts the
 * server's reads supply (`CT-UI-08`).
 */

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import { failureSentence, type StateMessage } from "./model";

/** The toast's auto-dismiss (§3.3.8: five seconds). One named constant, one meaning. */
const TOAST_AUTO_DISMISS_MS = 5000;

/** One toast raised somewhere in the shell; the host stacks them top-right. */
export interface Toast {
  kind: "success" | "failure";
  text: string;
}

const ToastContext = createContext<(toast: Toast) => void>(() => undefined);

/** Raise a toast: the transient confirmation of a completed action (never the only
 * carrier of an error — a failure that matters also renders in its place). */
export function useToast(): (toast: Toast) => void {
  return useContext(ToastContext);
}

/** The host: stacks the toasts top-right and dismisses each after five seconds. The host is
 * the live region; the outcome banner (FR-UI-24) is the one `status` a screen reader and a
 * test find for an action's outcome, so a toast repeating it is not a second one. */
export function ToastHost({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<{ key: number; toast: Toast }[]>([]);
  const nextKey = useRef(0);
  const raise = useCallback((toast: Toast) => {
    const key = nextKey.current;
    nextKey.current += 1;
    setToasts((current) => [...current, { key, toast }]);
  }, []);
  return (
    <ToastContext.Provider value={raise}>
      {children}
      <div className="toast-host" aria-live="polite">
        {toasts.map(({ key, toast }) => (
          <ToastItem key={key} toast={toast} onDone={() =>
            setToasts((current) => current.filter((entry) => entry.key !== key))
          } />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDone }: { toast: Toast; onDone: () => void }) {
  useEffect(() => {
    const timer = window.setTimeout(onDone, TOAST_AUTO_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [onDone]);
  const Glyph = toast.kind === "success" ? CircleCheck : CircleX;
  return (
    <div className={`toast toast-${toast.kind}`}>
      <Glyph size={16} aria-hidden="true" />
      <span>{toast.text}</span>
    </div>
  );
}

/**
 * The banner (FR-CONSOLE-33's shape): top of the content area, persists until acted on,
 * and always names what failed, why, and the next action as its button. One template, one
 * click: the button is the message's `next_action` re-dispatching the same action.
 */
export function Banner({ message, onAction }: { message: StateMessage; onAction?: () => void }) {
  return (
    <div role="alert" className="banner banner-danger">
      <TriangleAlert size={16} aria-hidden="true" />
      <div className="banner-body">
        <strong>{message.what}</strong>
        {message.why !== "" && <span> — {message.why}</span>}
      </div>
      {message.next_action !== null && onAction !== undefined && (
        <button type="button" className="button" onClick={onAction}>
          {message.next_action}
        </button>
      )}
    </div>
  );
}

/**
 * The inline note: next to the thing it is about, staying until resolved. A field's
 * validation and a per-item status render here, with the failure sentence spoken.
 */
export function InlineNote({ message }: { message: StateMessage }) {
  const Glyph = message.kind === "failure" ? TriangleAlert : CircleCheck;
  return (
    <p role={message.kind === "failure" ? "alert" : "status"} className={`inline-note inline-${message.kind}`}>
      <Glyph size={14} aria-hidden="true" />
      <span>{failureSentence(message)}</span>
    </p>
  );
}

/**
 * The busy placeholder for a content area (§3.3.8): skeleton blocks, never a spinner in
 * mid-content. The text is said for the screen reader, spelled here so the wording is the
 * screens' one "Reading." line.
 */
export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeleton" aria-label="Reading.">
      {Array.from({ length: lines }, (_, index) => (
        <div key={index} className="skeleton-line" aria-hidden="true" />
      ))}
    </div>
  );
}

/**
 * The progress bar on a job: the counts the server's read supplied, nothing derived
 * (`CT-UI-08`). A read that names no total renders the label alone — no fabricated share.
 * The jobs screen is a later story's route (#766); this is the state model's bar it
 * renders, so a job's progress arrives as a labelled bar, never a spinner in mid-content.
 */
export function ProgressBar({ done, total, label }: {
  done: number | null;
  total: number | null;
  label: string;
}) {
  return (
    <div className="progress">
      <progress
        value={done === null || total === null || total === 0 ? undefined : done}
        max={total === null || total === 0 ? undefined : total}
        aria-label={label}
      />
      <span>
        {done !== null && total !== null ? `${done} of ${total} done` : label}
      </span>
    </div>
  );
}
