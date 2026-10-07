import { useState, type FormEvent } from "react";
import { Screen } from "../components/Screen";
import { askHelp, type HelpAnswer } from "../api";

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
 * The manuals & help screen's Q&A panel (FR-UI-06). The affordance is persistent — it is
 * part of the panel's markup, rendered before any question and still there after the answer
 * (user decision 2): the assistant answers questions and does not operate the system. The
 * panel's only network call is the ask (TC-REQ-129); a not-found answer renders the pointer
 * to the manuals page, and so does a failed ask — the recovery is always the same page.
 */
export function QaPanel() {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<AskState>({ kind: "idle" });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const asked = question.trim();
    if (!asked || state.kind === "waiting") {
      return;
    }
    setState({ kind: "waiting" });
    askHelp(asked).then(
      (answer) => setState({ kind: "answered", answer }),
      (error: unknown) => setState({
        kind: "failed",
        message: error instanceof Error ? error.message : "the assistant could not answer",
      }),
    );
  };

  return (
    <section className="qa-panel" aria-label="Ask the assistant">
      <p className="qa-affordance">
        This assistant answers questions; it does not operate the system.
      </p>
      <form className="qa-form" onSubmit={submit}>
        <label htmlFor="qa-question">Ask the manuals a question</label>
        <textarea
          id="qa-question"
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

/**
 * The whole help destination: the Q&A panel beside the link to the manuals themselves —
 * the pages the citations open (FR-HELP-01's console page, served same-origin). The level-1
 * heading is the screen contract every destination carries (`screens.tsx`).
 */
export function Help() {
  return (
    <Screen title="Manuals & help">
      <QaPanel />
      <p className="qa-manuals-link">
        Or read the <a href="/manuals">manuals page</a> directly.
      </p>
    </Screen>
  );
}
