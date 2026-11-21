import { useNavigate } from "../navigate";

/** FR-UI-42's sentence for a mark held back while the blind sample is open. */
export const HELD_BACK_TEXT = "Hidden until you mark your sample or skip it";

/** The blind sample's route: the screen the held-back sentence links to. */
export const BLIND_SAMPLE_ROUTE = "/review/blind";

/**
 * A mark held back while the run's blind sample is open (FR-UI-42, FR-CONSOLE-89): the
 * sentence in place of the level, points or total, and — unless `link` is off — a link to the
 * sample, so the teacher sees why it is hidden and how to bring it back.
 */
export function HeldBack({ link = true }: { link?: boolean }) {
  const navigate = useNavigate();
  return (
    <span className="held-back" data-held-back="">
      {HELD_BACK_TEXT}
      {link && (
        <>
          {" "}
          <a
            href={`#${BLIND_SAMPLE_ROUTE}`}
            onClick={(event) => {
              event.preventDefault();
              navigate(BLIND_SAMPLE_ROUTE);
            }}
          >
            Mark the sample
          </a>
        </>
      )}
    </span>
  );
}

/** Whether anything in a read's document is held back — the draw is open and drew from it. */
export function anyHeldBack(node: unknown): boolean {
  if (Array.isArray(node)) {
    return node.some(anyHeldBack);
  }
  if (node !== null && typeof node === "object") {
    const record = node as Record<string, unknown>;
    return record.hidden_until_blind === true || Object.values(record).some(anyHeldBack);
  }
  return false;
}
