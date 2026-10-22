import { CircleHelp, Info, TriangleAlert } from "lucide-react";
import type { IssuesDoc } from "../api";
import { ConfirmDialog, useActionState } from "../components/Confirm";
import { Screen } from "../components/Screen";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useScreenRead } from "../useScreenRead";
import { issueSeverityLabel, issueTone } from "../wizard/vocabulary";

/**
 * The issues page (FR-UI-18, design delta §3.3.10): one card per issue this run raised,
 * each saying what happened, what it affects, and the next step — the three sentences the
 * server's issues read already worded (`RS-04`: the console writes the next step, the SPA
 * never invents one). The card's severity is icon + label + colour (CT-UI-10), derived
 * from the server's own source word; where the next step is something the console can do,
 * the card carries that control — confirm-guarded like every post (CT-UI-09).
 */

type Issue = IssuesDoc["issues"][number];

function SeverityBadge({ source }: { source: string }) {
  const tone = issueTone(source);
  const Glyph = tone === "info" ? Info : tone === "warning" ? TriangleAlert : CircleHelp;
  return (
    <span className={`badge badge-${tone}`}>
      <Glyph size={14} aria-hidden="true" />
      <span>{issueSeverityLabel(source)}</span>
    </span>
  );
}

function IssueCard({
  issue,
  onRecover,
}: {
  issue: Issue;
  onRecover: () => void;
}) {
  const navigate = useNavigate();
  return (
    <li className="issue-card">
      <div className="issue-head">
        <SeverityBadge source={issue.source} />
        <span className="issue-source">{issue.source}</span>
      </div>
      <p className="issue-what">{issue.what}</p>
      <p className="issue-affects">{issue.affects}</p>
      <p className="issue-next">
        <span className="wizard-line-label">Next step:</span> {issue.next_step}
      </p>
      {issue.source === "grading step" && (
        <button type="button" className="button" onClick={onRecover}>
          Pick the given-up work back up
        </button>
      )}
      {issue.source === "parked paper" && (
        <button type="button" className="button" onClick={() => navigate("/parked")}>
          Open the parked page
        </button>
      )}
      {issue.source === "grading point" && (
        <button type="button" className="button" onClick={() => navigate("/results")}>
          Review the results
        </button>
      )}
    </li>
  );
}

/**
 * The issues page over the run in focus. Without a selected run there is no read at all —
 * the screen says what to do instead of failing (the shell mounts a read only when its
 * subject exists, `useScreenRead`).
 */
export function Issues({ runId }: { runId: string | null }) {
  const read = useScreenRead<IssuesDoc>(
    runId === null ? null : "/api/v1/issues",
    runId === null ? undefined : { run_id: runId },
  );
  const action = useActionState(read.retry);

  const openRecover = (): void => {
    action.open({
      title: "Pick the given-up work back up",
      description:
        "The console will pick the grading work that gave up back up. This reaches every run " +
        "the console holds, not only this one — anything else waiting to be picked up goes " +
        "too. The outcome line will say what changed.",
      confirm: "Recover",
      action: "recover runs",
      body: {},
    });
  };

  if (runId === null) {
    return (
      <Screen title="Issues">
        <p>Choose a grading run from the switcher above — the issues page reads the run in focus.</p>
      </Screen>
    );
  }

  return (
    <ReadScreen title="Issues" read={read}>
      {(data) => (
        <>
          {data.issues.length === 0 ? (
            <p>Nothing went wrong in this run.</p>
          ) : (
            <ul className="issues-list">
              {data.issues.map((issue) => (
                <IssueCard key={issue.issue_id} issue={issue} onRecover={openRecover} />
              ))}
            </ul>
          )}
          {action.pending !== null && (
            <ConfirmDialog pending={action.pending} onClose={action.close} onDone={action.finish} />
          )}
        </>
      )}
    </ReadScreen>
  );
}
