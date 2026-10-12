/**
 * The three-tier state model (FR-UI-14, design delta §3.3.8), as pure data: which tier a
 * message renders in, and the one sentence template every failure follows — **what failed ·
 * why (plain language) · one click to retry or fix**. Nothing here touches the DOM or the
 * network, so the model is drivable headless, the way the wizard's derivation is: a caller
 * (a screen, or a test that imports the module alone) classifies an outcome and renders the
 * shape the tier names.
 */

/** The rendering tiers, chosen by what the message is *about*: a completed action confirms
 * in a toast; a field's problem says so inline, next to the thing; a screen-level state is
 * a banner that persists until acted on. */
export type Tier = "toast" | "inline" | "banner";

/** One classified message: the tier it renders in, the three parts of the sentence
 * template, and the retry action the "one click" is. */
export interface StateMessage {
  tier: Tier;
  /** What failed (or what completed) — the subject, in the console's words. */
  what: string;
  /** Why, in plain language. A success message carries none. */
  why: string;
  /** The one click: the retry or fix button's label, or null when nothing to do. */
  next_action: string | null;
  /** Whether the message reports a failure (an error tone) or a completed action. */
  kind: "failure" | "success";
}

/**
 * The failure sentence, from the template's three parts. The parts stay separate in the
 * message so the banner can give the action its own button; this is the spoken form the
 * inline tier and the screen readers get.
 */
export function failureSentence(message: Pick<StateMessage, "what" | "why" | "next_action">): string {
  const what = message.what.trim() || "something went wrong";
  const why = message.why.trim();
  const next = message.next_action?.trim();
  const parts = [what];
  if (why !== "") parts.push(why);
  if (next !== undefined && next !== "") parts.push(`${next} — one click.`);
  return parts.join(" · ");
}

/**
 * A failed read, classified — the banner a screen renders when its document could not be
 * read. The why is the API's own refusal where it named one; the one click is the retry
 * that re-runs the read (`CT-UI-04`).
 */
export function classifyReadFailure(error: string): StateMessage {
  return {
    tier: "banner",
    what: "The console could not read this screen",
    why: error,
    next_action: "Retry",
    kind: "failure",
  };
}

/**
 * A score state's teacher wording (`CT-CONSOLE-31`), mirroring the console's own
 * presentation of the four states M-AGG's schema pins (`CT-AGG-07`); a state this build
 * does not know reads as neutral (CT-CONSOLE-38), never as an error.
 */
export function scoreStateLabel(state: string): string {
  switch (state) {
    case "final":
      return "Final";
    case "provisional_unreviewed":
      return "Not final yet — awaiting teacher review";
    case "ungradeable_by_panel":
      return "The graders refused to grade this criterion — it is recorded as ungradeable, not as awaiting review";
    case "unresolved_selection":
      return "The selection could not be read; it is parked for triage";
    default:
      return "Needs attention";
  }
}

/** A flag's teacher label (FR-UI-15's flagged items); an unknown flag reads as neutral. */
export function flagLabel(flag: string): string {
  switch (flag) {
    case "second_opinion":
      return "Second opinion";
    case "low_confidence":
      return "Low confidence";
    case "not_final":
      return "Not final yet";
    default:
      return "Flagged";
  }
}

/** The tone a flag's badge takes — icon and label carry it with the colour (`CT-UI-10`). */
export function flagTone(flag: string): "warning" | "info" | "neutral" {
  switch (flag) {
    case "second_opinion":
    case "not_final":
      return "warning";
    case "low_confidence":
      return "info";
    default:
      return "neutral";
  }
}

/**
 * One grading point's distribution, counted from the rows a read served (`CT-UI-08`: the
 * SPA aggregates what arrived; it fabricates no count). `levels` is the package's declared
 * order, so a level that no paper reached still takes its place on the axis.
 */
export function countLevels(levels: readonly string[], bands: readonly string[]): number[] {
  const counts = levels.map(() => 0);
  for (const band of bands) {
    const index = levels.indexOf(band);
    if (index >= 0) counts[index] = (counts[index] ?? 0) + 1;
  }
  return counts;
}

/**
 * A grading point's mean score level, in the teacher's words: the declared level nearest
 * the arithmetic mean of the awarded levels' positions. A count that no served row backs
 * is never rendered — an empty cell says so.
 */
export function meanLevelPhrase(levels: readonly string[], counts: readonly number[]): string {
  const total = counts.reduce((sum, count) => sum + count, 0);
  if (total === 0) return "no papers reached a score level";
  const weighted = counts.reduce((sum, count, index) => sum + count * index, 0);
  const mean = weighted / total;
  const nearest = Math.min(levels.length - 1, Math.max(0, Math.round(mean)));
  const name = levels[nearest] ?? "";
  return name === "" ? "no papers reached a score level" : `usually "${name}"`;
}

/**
 * The grading points most papers missed: those whose lowest declared level holds the most
 * papers, among the points that have any papers at the lowest level. Ties stay listed —
 * "most-missed" names a set, not a single winner.
 */
export function mostMissed(
  entries: readonly { label: string; levels: readonly string[]; counts: readonly number[] }[],
): string[] {
  const scored = entries
    .map((entry) => {
      const lowest = entry.counts[0] ?? 0;
      const total = entry.counts.reduce((sum, count) => sum + count, 0);
      return { label: entry.label, lowest, total };
    })
    .filter((entry) => entry.lowest > 0);
  if (scored.length === 0) return [];
  const worst = Math.max(...scored.map((entry) => entry.lowest));
  return scored.filter((entry) => entry.lowest === worst).map((entry) => entry.label);
}
