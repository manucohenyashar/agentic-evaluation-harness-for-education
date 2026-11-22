import type { ReactNode } from "react";
import type { BlindBand } from "../api";
import { FormatLine, useFieldIds } from "./Field";

/**
 * The seat (FR-UI-40): one answer to mark without the system's mark — whose answer and which
 * question, the answer itself (with whatever links to its scan the caller adds), and the
 * question's levels as choices, each with its description. Shared by the blind sample and
 * the marked examples step (FR-UI-44), hence one `data-component` for both. The seat holds
 * no state of its own: the caller owns the choice and what choosing does (a draft saved at
 * once on the blind sample; a form saved per paper on the examples step).
 */
export function SeatCard({
  heading,
  answer,
  pages,
  name,
  bands,
  chosen,
  busy = false,
  onChoose,
  format,
}: {
  heading: string;
  answer: string | null;
  pages?: ReactNode;
  /** The radio group's name — unique on the page. */
  name: string;
  bands: BlindBand[];
  chosen: string | null;
  busy?: boolean;
  onChoose: (band: string) => void;
  /** The format line under the levels: how to choose and when it is saved. */
  format: string;
}) {
  const ids = useFieldIds();
  return (
    <article className="blind-seat" data-component="blind-seat">
      <h2 className="blind-seat-head">{heading}</h2>
      <blockquote className="blind-answer">
        {answer !== null && answer.trim() !== ""
          ? answer
          : "No answer text could be read for this question; view the page to read it."}
      </blockquote>
      {pages}
      <fieldset className="blind-levels" aria-describedby={ids.formatId} aria-busy={busy || undefined}>
        <legend>Your level</legend>
        {bands.map((band) => (
          <label key={band.name} className="blind-level">
            <input
              type="radio"
              name={name}
              value={band.name}
              checked={chosen === band.name}
              disabled={busy}
              onChange={() => onChoose(band.name)}
            />{" "}
            <strong>{band.name}</strong>
            {band.descriptor ? <span className="blind-descriptor"> — {band.descriptor}</span> : null}
          </label>
        ))}
      </fieldset>
      <FormatLine id={ids.formatId} spec={format} />
    </article>
  );
}
