import { fetchRead, type HelpDoc } from "../api";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";

/**
 * The help screen (FR-UI-03, the manuals list): the manuals this console ships and the
 * assistant's one standing limit — it answers questions about operating the system; it does
 * not operate it (FR-UI-06's answers-only affordance). The grounded Q&A panel is the manuals
 * story's work (#638); this screen's degradation contract holds already (FR-UI-07).
 */
export function Help() {
  const read = useScreenRead<HelpDoc>("/api/v1/help");
  return (
    <ReadScreen title="Manuals & help" read={read}>
      {(data) => (
        <>
          <ul className="rows-list">
            {data.manuals.map((manual) => (
              <li key={manual}>
                <span className="step-name">{manual}</span>
              </li>
            ))}
          </ul>
          <p className="panel">{data.ask}</p>
        </>
      )}
    </ReadScreen>
  );
}
