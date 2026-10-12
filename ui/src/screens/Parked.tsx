import type { ParkedDoc } from "../api";
import { ActionOutcome, ConfirmDialog, useActionState } from "../components/Confirm";
import { ReadScreen } from "../components/ReadScreen";
import { useNavigate } from "../navigate";
import { useScreenRead } from "../useScreenRead";

/**
 * The parked page (FR-UI-19): every parked paper with its reason in the console's words,
 * the student it matched (or why it could not), and the resolutions available — the read's
 * own sentences. A paper's two ways out are the operator's two buttons, each behind its
 * confirmation (CT-UI-09: nothing posts confirm-free): release the paper to scoring on the
 * operator's match, or close it as unresolvable — a closed paper's criteria are missing,
 * never zero, and the confirmation says so. A replacement upload starts on the papers page.
 */

type ParkedEntry = ParkedDoc["parked"][number];

function ParkedCard({
  entry,
  onResolve,
}: {
  entry: ParkedEntry;
  onResolve: (entry: ParkedEntry, resolution: "matched" | "unresolvable") => void;
}) {
  const navigate = useNavigate();
  return (
    <li className="parked-card">
      <p className="parked-reason">{entry.reason_label}</p>
      <p className="parked-match">{entry.match_note}</p>
      {entry.resolutions.length > 0 && (
        <ul className="parked-resolutions">
          {entry.resolutions.map((sentence) => (
            <li key={sentence}>{sentence}</li>
          ))}
        </ul>
      )}
      <div className="parked-actions">
        <button type="button" className="button" onClick={() => navigate("/papers")}>
          Upload a replacement
        </button>
        {entry.resolvable && (
          <>
            <button
              type="button"
              className="button"
              onClick={() => onResolve(entry, "matched")}
            >
              Release to scoring
            </button>
            <button
              type="button"
              className="button"
              onClick={() => onResolve(entry, "unresolvable")}
            >
              Close as unresolvable
            </button>
          </>
        )}
      </div>
    </li>
  );
}

export function Parked() {
  const read = useScreenRead<ParkedDoc>("/api/v1/parked");
  const action = useActionState(read.retry);

  const openResolve = (entry: ParkedEntry, resolution: "matched" | "unresolvable"): void => {
    if (resolution === "matched") {
      action.open({
        title: "Release this paper to scoring",
        description:
          "You are saying this paper belongs to the student the console matched it to. " +
          "The paper's pages go forward to be graded.",
        confirm: "Release",
        action: "resolve quarantine item",
        body: { submission_id: entry.submission_id, resolution },
      });
    } else {
      action.open({
        title: "Close this paper as unresolvable",
        description:
          "You are saying this paper cannot be resolved. Its missing pieces stay missing: " +
          "the student's result will show what was never scored, never a made-up mark.",
        confirm: "Close",
        action: "resolve quarantine item",
        body: { submission_id: entry.submission_id, resolution },
      });
    }
  };

  return (
    <ReadScreen title="Parked" read={read}>
      {(data) => (
        <>
          <ActionOutcome outcome={action.outcome} />
          {data.parked.length === 0 ? (
            <p>No papers are parked.</p>
          ) : (
            <>
              <p>
                {data.counts.total} paper{data.counts.total === 1 ? " is" : "s are"} parked.
              </p>
              <ul className="parked-list">
                {data.parked.map((entry) => (
                  <ParkedCard key={entry.submission_id} entry={entry} onResolve={openResolve} />
                ))}
              </ul>
            </>
          )}
          {action.pending !== null && (
            <ConfirmDialog pending={action.pending} onClose={action.close} onDone={action.finish} />
          )}
        </>
      )}
    </ReadScreen>
  );
}
