import type { BoundaryFields } from "./api";

/**
 * Ranges (FR-UI-50, R58): a student whose unreviewed lines could move their grade reads
 * "<low>–<high> (<grade_low>–<grade_high>) until <k> answers are checked" instead of a point;
 * with no boundary table the range reads in points (the delta's OQ-8 wording). The range and
 * the letters are the served stored values (FR-CONSOLE-94) — the screen formats, it never
 * recomputes.
 */

/** A score as the teacher reads it: whole numbers bare, otherwise one decimal. */
export function scoreText(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 10) / 10);
}

/** The line state of an answer the teacher has not checked yet. */
export const UNCHECKED_STATE = "provisional_unreviewed";

/** How many of a student's lines are still waiting for the teacher's check. */
export function uncheckedCount(lines: { state: string; hidden_until_blind?: boolean }[]): number {
  return lines.filter((line) => line.state === UNCHECKED_STATE && line.hidden_until_blind !== true)
    .length;
}

/** The range sentence, or null when the student's grade cannot move (then the grade shows). */
export function rangeText(fields: BoundaryFields, unchecked: number): string | null {
  const low = fields.score_low;
  const high = fields.score_high;
  if (!fields.boundary_at_risk || low === null || low === undefined
      || high === null || high === undefined) {
    return null;
  }
  const until = unchecked > 0
    ? `until ${unchecked} ${unchecked === 1 ? "answer is" : "answers are"} checked`
    : "until the answers are checked";
  const span = `${scoreText(low)}–${scoreText(high)}`;
  if (fields.grade_low && fields.grade_high) {
    return `${span} (${fields.grade_low}–${fields.grade_high}) ${until}`;
  }
  return `${span} points ${until}`;
}
