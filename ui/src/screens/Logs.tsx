import { useEffect, useState } from "react";
import type { LogsDoc } from "../api";
import { Screen } from "../components/Screen";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";

/**
 * The logs page (FR-UI-18): the run's stage-by-stage records as the server holds them —
 * milestones, per-stage summaries and grouped problems, at stage and grading-point
 * granularity, never a per-student figure (CT-CONSOLE-09, RS-05). Each record shows its
 * stage, its time where the record carries one, and its text; a record's detail line opens
 * on demand (a `<details>`, nothing auto-expanded). The page offers a filter box over the
 * stages and texts, and the next page the read admits — the read paginates server-side,
 * so the page's "more" button is the read's own `more_available`.
 */

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

export function Logs({ runId }: { runId: string | null }) {
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

  if (runId === null) {
    return (
      <Screen title="Logs">
        <p>Choose a grading run from the switcher above — the logs page reads the run in focus.</p>
      </Screen>
    );
  }

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

  return (
    <ReadScreen title="Logs" read={read}>
      {(data) => {
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
      }}
    </ReadScreen>
  );
}
