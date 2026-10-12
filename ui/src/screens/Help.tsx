import { useEffect, useId, useState, type FormEvent } from "react";
import { Screen } from "../components/Screen";
import { askHelp, fetchManuals, type HelpAnswer, type HelpContext, type ManualsIndexDoc } from "../api";

type AskState =
  | { kind: "idle" }
  | { kind: "waiting" }
  | { kind: "answered"; answer: HelpAnswer }
  | { kind: "failed"; message: string };

/**
 * The citation link a grounded answer carries (FR-UI-06): a same-origin link into the
 * server-rendered manuals page, whose fragment is the section anchor the API named. The
 * target page renders each section with that anchor as its element id — the two sides of
 * that convention are declared in `aeh/console/manuals_page.py` and here, and nowhere else.
 */
function citationHref(manualId: string, anchor: string): string {
  return `/manuals/${encodeURIComponent(manualId)}#${anchor}`;
}

function citationLabel(manualId: string, anchor: string): string {
  const section = anchor.replaceAll("-", " ").trim();
  return `${manualId}: ${section}`;
}

/**
 * The grounded Q&A panel (FR-UI-06). The affordance is persistent — it is part of the
 * panel's markup, rendered before any question and still there after the answer (user
 * decision 2): the assistant answers questions and does not operate the system. The
 * panel's only network call is the ask (TC-REQ-129); a not-found answer renders the pointer
 * to the manuals page, and so does a failed ask — the recovery is always the same page.
 *
 * `context` is the asking screen's identity and the object refs it is reading (FR-HELP-06)
 * — the help-everywhere panel passes it, the help centre asks without one. `compact` drops
 * the panel's frame for the side panel, which carries its own.
 */
export function QaPanel({ context, compact = false }: {
  context?: HelpContext;
  compact?: boolean;
}) {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<AskState>({ kind: "idle" });
  const questionId = useId();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const asked = question.trim();
    if (!asked || state.kind === "waiting") {
      return;
    }
    setState({ kind: "waiting" });
    askHelp(asked, context).then(
      (answer) => setState({ kind: "answered", answer }),
      (error: unknown) => setState({
        kind: "failed",
        message: error instanceof Error ? error.message : "the assistant could not answer",
      }),
    );
  };

  return (
    <section className={compact ? "qa-panel qa-panel-compact" : "qa-panel"} aria-label="Ask the assistant">
      <p className="qa-affordance">
        This assistant answers questions; it does not operate the system.
      </p>
      <form className="qa-form" onSubmit={submit}>
        <label htmlFor={questionId}>
          {context === undefined
            ? "Ask the manuals a question"
            : `Ask the manuals a question about this screen`}
        </label>
        <textarea
          id={questionId}
          rows={2}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="e.g. What is the blind sample in the review queue for?"
        />
        <button type="submit" disabled={state.kind === "waiting" || !question.trim()}>
          Ask the assistant
        </button>
      </form>
      <div className="qa-answer" aria-live="polite">
        {state.kind === "waiting" && <p>Waiting for the answer…</p>}
        {state.kind === "failed" && (
          <p role="alert">
            {state.message}. Read the <a href="/manuals">manuals page</a> instead.
          </p>
        )}
        {state.kind === "answered" && (
          <>
            <p className="qa-answer-text">{state.answer.answer}</p>
            {state.answer.citations.length > 0 ? (
              <ul className="qa-citations">
                {state.answer.citations.map((citation, index) => (
                  <li key={`${citation.anchor}-${index}`}>
                    <a href={citationHref(citation.manual_id, citation.anchor)}>
                      {citationLabel(citation.manual_id, citation.anchor)}
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="qa-not-found">
                The manuals do not cover that. Read the{" "}
                <a href="/manuals">manuals page</a>.
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}

/** The manuals index (FR-UI-21): every packaged manual, as the manuals read lists it. */
export function ManualsIndex() {
  const [manuals, setManuals] = useState<ManualsIndexDoc | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchManuals(controller.signal).then(
      (answer) => {
        if (!controller.signal.aborted) {
          setManuals(answer);
          setError(null);
        }
      },
      (failure: unknown) => {
        if (!controller.signal.aborted) {
          setError(failure instanceof Error ? failure.message : String(failure));
        }
      },
    );
    return () => controller.abort();
  }, []);

  if (error !== null) {
    return (
      <p role="alert" className="screen-alert">
        The console could not read the manuals list ({error}). check that the console service
        is running.
      </p>
    );
  }
  if (manuals === null) {
    return <p>Reading.</p>;
  }
  return (
    <section className="manuals-index" aria-label="The manuals">
      <h2>The manuals</h2>
      <ul>
        {manuals.manuals.map((manual) => (
          <li key={manual.manual_id}>
            <a href={`/manuals/${encodeURIComponent(manual.manual_id)}`}>{manual.title}</a>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The whole help destination — the help centre (FR-UI-21): the manuals index, the Q&A
 * panel, and the link to the manuals themselves — the pages the citations open (FR-HELP-01's
 * console page, served same-origin). The level-1 heading is the screen contract every
 * destination carries (`screens.tsx`). The screen reads nothing else of its own
 * (TC-REQ-129), so its degradation (FR-UI-07) rides the shell's context read's failure —
 * a named message and the context read's retry, the same recoverable shape every other
 * screen renders.
 */
export function Help({ failed = false, onRetry }: {
  failed?: boolean;
  onRetry?: () => void;
}) {
  return (
    <Screen title="Manuals & help">
      {failed && (
        <>
          <p role="alert" className="screen-alert">
            The console could not read its state — check that the console service is
            running.
          </p>
          {onRetry && (
            <button type="button" className="button" onClick={onRetry}>
              Try again
            </button>
          )}
        </>
      )}
      <ManualsIndex />
      <QaPanel />
      <p className="qa-manuals-link">
        Or read the <a href="/manuals">manuals page</a> directly.
      </p>
    </Screen>
  );
}
