import { useEffect, useState } from "react";
import type { AiCallRow, AiCallsDoc, LogsDoc } from "../api";
import { Screen } from "../components/Screen";
import { useScreenRead } from "../useScreenRead";
import { useNavigate } from "../navigate";
import { durationLabel } from "../wizard/vocabulary";

/**
 * The logs page (FR-UI-18, FR-UI-34/35): two tabs. **Run steps** is the run's
 * stage-by-stage records as the server holds them — milestones, per-stage summaries and
 * grouped problems, at stage and grading-point granularity, never a per-student figure
 * (`CT-CONSOLE-09`, `RS-05`). **AI calls** is the journal of the model calls the run made
 * (FR-CONSOLE-78): one row per call, opening to the verbatim question and answer, so a
 * teacher can see how a grade was reached. The tab (and any filters) ride the address,
 * so a link from a student's page opens the right view directly.
 */

/** Which two panels an expanded row shows (FR-UI-35): the grading calls are named for
 * who answered; every other kind takes the general titles. */
const PANEL_TITLES: Record<string, [string, string]> = {
  jev_decision: ["Question sent to Jev", "Jev's answer"],
  ai_judge: ["Question sent to the judge", "The judge's answer"],
};

/** A verbatim payload as the panels show it: the journal's own JSON, pretty-printed. */
function verbatim(payload: unknown): string {
  return typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
}

/** The copy button (FR-UI-35): the panel's text onto the clipboard, with the same
 * refusal sentence the support copy uses when the browser says no. */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState<string | null>(null);
  const refused = "The browser refused the copy — select the text by hand.";
  return (
    <>
      <button
        type="button"
        className="button"
        onClick={() => {
          if (navigator.clipboard === undefined) {
            setCopied(refused);
            return;
          }
          navigator.clipboard.writeText(text).then(
            () => setCopied("Copied."),
            () => setCopied(refused),
          );
        }}
      >
        Copy
      </button>
      {copied !== null && (
        <span role="status" className="step-note"> {copied}</span>
      )}
    </>
  );
}

/** A Jev decision's answer, in teacher words (FR-UI-34): the band it chose (the argmax,
 * the gate's own rule), every band's probability, and the confidence against the
 * threshold the run recorded — "confidence 0.91, needed above 0.80 — accepted". */
function JevAnswer({ item }: { item: AiCallRow }) {
  const response = (item.response ?? {}) as Record<string, unknown>;
  const request = (item.request ?? {}) as Record<string, unknown>;
  const band = response.band as
    | { score?: unknown; probabilities?: unknown; confidence?: unknown }
    | undefined;
  if (band === undefined || !Array.isArray(band.probabilities)) {
    return <p className="ai-call-verbatim">{verbatim(item.response)}</p>;
  }
  const probabilities = band.probabilities as number[];
  const questions = (request.questions ?? {}) as Record<string, unknown>;
  const bandQuestion = questions.band as { criteria?: unknown } | undefined;
  const levels = Array.isArray(bandQuestion?.criteria)
    ? bandQuestion.criteria.map(String)
    : [];
  const peak = Math.max(...probabilities);
  const top = probabilities
    .map((p, index) => (p === peak ? index : -1))
    .filter((index) => index >= 0);
  const chosen: number | null = top.length === 1 ? top[0] ?? null : null;
  const confidence = item.confidence ?? null;
  const accepted = confidence !== null && confidence.threshold !== null
    ? confidence.value > Number(confidence.threshold) && top.length === 1
    : null;
  return (
    <div className="ai-call-jev">
      {chosen !== null && (
        <p>
          Chose: <strong>{levels[chosen] ?? `band ${chosen + 1} of ${probabilities.length}`}</strong>
        </p>
      )}
      <p>
        Chance:{" "}
        {probabilities.map((p, index) => (
          <span key={index}>
            {index > 0 && "; "}
            {levels[index] ?? `band ${index + 1}`} {Math.round(p * 100)}%
          </span>
        ))}
      </p>
      {confidence !== null && (
        <p>
          confidence {confidence.value}
          {confidence.threshold !== null
            ? `, needed above ${confidence.threshold} — ${
                accepted ? "accepted" : "not accepted"
              }`
            : ""}
        </p>
      )}
      <p className="ai-call-verbatim">{verbatim(item.response)}</p>
    </div>
  );
}

/** A tab's read failure, rendered recoverably: the reason and a retry, the same shape
 * every other screen's failed read takes. */
function ReadAlert({ error, retry }: { error: string | null; retry: () => void }) {
  if (error === null) {
    return null;
  }
  return (
    <p role="alert" className="screen-alert">
      The records could not be read ({error}).{" "}
      <button type="button" className="button" onClick={retry}>
        Retry
      </button>
    </p>
  );
}

/** One AI-call row (FR-UI-34/35): kind, student, question, model, time, duration, cost on
 * the closed row; the verbatim question and answer panels on the open one. */
function AiCallRowView({ item }: { item: AiCallRow }) {
  const [asked, answered] = PANEL_TITLES[item.kind] ?? ["What the AI was asked", "What it answered"];
  const head = item.student_name !== null
    ? `${item.student_name} — ${item.question ?? ""}`
    : item.kind_label;
  const requestText = verbatim(item.request);
  return (
    <li className={`ai-call-row ai-call-${item.kind}`}>
      <details>
        <summary>
          <span className="ai-call-kind">{item.kind_label}</span>{" "}
          <strong>{head}</strong>{" "}
          <span className="step-note">
            {item.model ?? "—"} · {item.at ?? "—"} ·{" "}
            {item.latency_ms === null ? "—" : durationLabel(item.latency_ms / 1000)} ·{" "}
            {item.cost === null ? "—" : `$${String(item.cost)}`}
          </span>
        </summary>
        {item.error !== null && item.error !== "" && (
          <p className="criterion-why">This call ended with a problem: {item.error}</p>
        )}
        <section className="ai-call-panel">
          <h4>{asked}</h4>
          <pre className="ai-call-verbatim">{requestText}</pre>
          <CopyButton text={requestText} />
        </section>
        <section className="ai-call-panel">
          <h4>{answered}</h4>
          {item.kind === "jev_decision" ? <JevAnswer item={item} /> : (
            <p className="ai-call-verbatim">{verbatim(item.response)}</p>
          )}
          <CopyButton text={verbatim(item.response)} />
        </section>
      </details>
    </li>
  );
}

/** The AI-calls tab (FR-CONSOLE-78): the run's journaled calls, defaulting to the grading
 * calls, filterable by kind, paginated like the steps tab. The student and question a
 * link arrived with stay applied — this is the "How was this graded?" view. */
function AiCallsTab({ runId, params }: { runId: string | null; params: URLSearchParams | undefined }) {
  const [page, setPage] = useState(1);
  const [kind, setKind] = useState("");
  const student = params?.get("student") ?? undefined;
  const questionId = params?.get("question") ?? params?.get("question_id") ?? undefined;
  useEffect(() => {
    setPage(1);
  }, [runId, student, questionId, kind]);
  const read = useScreenRead<AiCallsDoc>(
    runId === null ? null : "/api/v1/ai-calls",
    runId === null
      ? undefined
      : {
          run_id: runId,
          page: String(page),
          ...(student !== undefined ? { student } : {}),
          ...(questionId !== undefined ? { question_id: questionId } : {}),
          ...(kind !== "" ? { kind } : {}),
        },
  );
  const filtered = (runId !== null && (student !== undefined || questionId !== undefined)) || kind !== "";
  // The note names the student the way the rows do — the listed name, not the ref —
  // taken from the first call once the read answers.
  const shownStudent = student !== undefined
    ? read.data?.items.find((item) => item.student_name !== null)?.student_name ?? student
    : null;
  return (
    <>
      <ReadAlert error={read.error} retry={read.retry} />
      {read.error === null && read.data === null && <p>Reading.</p>}
      {filtered && (
        <p className="step-note">
          {shownStudent !== null ? `Showing the calls for ${shownStudent}` : "Showing filtered calls"}
          {questionId !== undefined ? `, question ${questionId}` : ""}.
        </p>
      )}
      <form className="logs-filter" onSubmit={(event) => event.preventDefault()}>
        <label htmlFor="ai-calls-kind">
          Which calls{" "}
          <select
            id="ai-calls-kind"
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            <option value="">The grading calls</option>
            <option value="jev_decision">Jev decisions</option>
            <option value="ai_judge">AI judge calls</option>
            <option value="all">Every kind</option>
            <option value="page_reading">Page reading</option>
            <option value="package_drafting">Package drafting</option>
            <option value="rubric_setup">Rubric setup</option>
            <option value="answer_extraction">Answer finding</option>
            <option value="feedback_writing">Feedback writing</option>
            <option value="help_question">Help question</option>
            <option value="unlabelled">Other AI call</option>
          </select>
        </label>
      </form>
      {read.data !== null && read.data.items.length === 0 ? (
        <p>No AI call matches this view.</p>
      ) : read.data !== null ? (
        <ul className="ai-calls-list">
          {read.data.items.map((item) => (
            <AiCallRowView key={`${item.call_id ?? ""}-${item.attempt ?? 0}`} item={item} />
          ))}
        </ul>
      ) : null}
      {read.data !== null && (
        <p className="logs-pages">
          {read.data.items.length} call{read.data.items.length === 1 ? "" : "s"} on this page
          of {read.data.total}.
          {read.data.more && (
            <button type="button" className="button" onClick={() => setPage(page + 1)}>
              Show the next page
            </button>
          )}
          {page > 1 && (
            <button type="button" className="button" onClick={() => setPage(1)}>
              Back to the first page
            </button>
          )}
        </p>
      )}
    </>
  );
}

function LogRow({ record }: { record: LogsDoc["records"][number] }) {
  return (
    <li className={`log-row log-${record.kind}`}>
      <div className="log-head">
        {record.stage !== null && <span className="log-stage">{record.stage}</span>}
        {record.at !== null && <time className="log-at">{record.at}</time>}
        <span className="visually-hidden">
          {record.kind === "problem" ? "problem" : record.kind === "milestone" ? "milestone" : "summary"}
        </span>
      </div>
      <p className="log-text">{record.text}</p>
      {record.detail !== null && record.detail !== "" && (
        <details className="log-detail">
          <summary>Details</summary>
          <p>{record.detail}</p>
        </details>
      )}
    </li>
  );
}

function matches(record: LogsDoc["records"][number], filter: string): boolean {
  const needle = filter.trim().toLowerCase();
  if (needle === "") {
    return true;
  }
  return (
    (record.stage ?? "").toLowerCase().includes(needle) ||
    record.text.toLowerCase().includes(needle)
  );
}

function RunStepsTab({ runId }: { runId: string | null }) {
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  // A new run in focus starts its own first page — the previous run's page number says
  // nothing about this one's, and neither does its copied note.
  useEffect(() => {
    setPage(1);
    setCopied(null);
  }, [runId]);
  const read = useScreenRead<LogsDoc>(
    runId === null ? null : "/api/v1/logs",
    runId === null ? undefined : { run_id: runId, page: String(page) },
  );

  const copyForSupport = (): void => {
    const records = read.data?.records.filter((record) => matches(record, filter)) ?? [];
    // The copied text is what the screen shows — the same records, nothing more (CT-UI-07:
    // no student names or paper text travel in a support bundle).
    const text = records
      .map((record) =>
        [record.stage ?? "", record.at ?? "", record.text, record.detail ?? ""]
          .filter((line) => line !== "")
          .join(" — "),
      )
      .join("\n");
    const refused = "The browser refused the copy — select the records by hand.";
    if (navigator.clipboard === undefined) {
      setCopied(refused);
      return;
    }
    navigator.clipboard.writeText(text).then(
      () => setCopied("Copied for support."),
      () => setCopied(refused),
    );
  };

  if (read.data === null) {
    return (
      <>
        <ReadAlert error={read.error} retry={read.retry} />
        {read.error === null && <p>Reading.</p>}
      </>
    );
  }
  const data = read.data;
  const shown = data.records.filter((record) => matches(record, filter));
  return (
    <>
      <form className="logs-filter" role="search" onSubmit={(event) => event.preventDefault()}>
        <label htmlFor="logs-filter-box">Filter the records</label>
        <input
          id="logs-filter-box"
          type="search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="e.g. reading"
        />
        {data.records.length > 0 && (
          <button type="button" className="button" onClick={copyForSupport}>
            Copy this page for support
          </button>
        )}
      </form>
      {copied !== null && (
        <p role="status" className="action-outcome">
          {copied}
        </p>
      )}
      {data.records.length === 0 ? (
        <p>The console holds no records for this run yet.</p>
      ) : shown.length === 0 ? (
        <p>No record on this page matches that filter.</p>
      ) : (
        <ol className="logs-list">
          {shown.map((record) => (
            <LogRow key={record.record_id} record={record} />
          ))}
        </ol>
      )}
      <p className="logs-pages">
        {data.page.shown} record{data.page.shown === 1 ? "" : "s"} on this page.
        {data.page.more_available && (
          <button type="button" className="button" onClick={() => setPage(page + 1)}>
            Show the next page
          </button>
        )}
        {page > 1 && (
          <button type="button" className="button" onClick={() => setPage(1)}>
            Back to the first page
          </button>
        )}
      </p>
    </>
  );
}

export function Logs({ runId, params }: { runId: string | null; params?: URLSearchParams }) {
  const navigate = useNavigate();
  const tab = params?.get("tab") === "ai-calls" ? "ai-calls" : "steps";
  if (runId === null) {
    return (
      <Screen title="Logs">
        <p>Choose a grading run from the switcher above — the logs page reads the run in focus.</p>
      </Screen>
    );
  }
  return (
    <Screen title="Logs">
      <nav className="tab-strip" aria-label="The run's logs">
        <a
          href="#/logs?tab=steps"
          aria-current={tab === "steps" ? "page" : undefined}
          onClick={(event) => {
            event.preventDefault();
            navigate("/logs?tab=steps");
          }}
        >
          Run steps
        </a>
        <a
          href="#/logs?tab=ai-calls"
          aria-current={tab === "ai-calls" ? "page" : undefined}
          onClick={(event) => {
            event.preventDefault();
            navigate("/logs?tab=ai-calls");
          }}
        >
          AI calls
        </a>
      </nav>
      {tab === "ai-calls"
        ? <AiCallsTab runId={runId} params={params} />
        : <RunStepsTab runId={runId} />}
    </Screen>
  );
}
