/**
 * The redesign's vocabulary map (design delta §3.3.3, CT-CONSOLE-31): the words the SPA
 * renders are the teacher's words, so every internal name a server read carries is renamed
 * here before it reaches a screen. Nothing outside this module composes a state label — a
 * value the server adds later (CT-CONSOLE-38) falls through to the neutral wording, never
 * an error.
 */

import type { StageState } from "../api";

/** The nine stages, in the wizard's order — the stepper's rows and every NEXT line's subject. */
export const STAGE_LABELS: readonly string[] = [
  "Create the class",
  "Create the test package",
  "Review the draft",
  "Approve the package",
  "Upload the papers",
  "Reading the papers",
  "Start the grading run",
  "Review the results",
  "Export the results",
];

/**
 * An entity state's badge wording. `unknown` is the open arm: a state the server added that
 * this build does not know renders with neutral wording (CT-CONSOLE-38), still labelled.
 */
export function entityStateLabel(state: string): string {
  switch (state) {
    // class ledger states (context read: classes/cohorts)
    case "empty":
      return "No students yet";
    case "roster_only":
      return "Students listed";
    // cohort states
    case "ready":
      return "Ready";
    case "grading":
      return "Grading";
    case "graded":
      return "Graded";
    case "stalled":
      return "Stalled";
    // package states
    case "drafting":
      return "Drafting";
    case "draft_ready":
      return "Draft ready";
    case "published":
      return "Published";
    // run states
    case "pending":
      return "Waiting";
    case "running":
      return "Running";
    case "paused":
      return "Paused";
    case "complete":
      return "Done";
    case "failed":
      return "Failed";
    default:
      return "Needs attention";
  }
}

/** The accessible name of a stage's state — the legend's wording (Done, In progress,
 * Not started, Needs attention, Failed, Queued); an unknown state reads as neutral
 * (CT-CONSOLE-38). */
export function stageStateLabel(state: StageState): string {
  switch (state) {
    case "done":
      return "Done";
    case "in_progress":
      return "In progress";
    case "not_started":
      return "Not started";
    case "failed":
      return "Failed";
    case "needs_attention":
      return "Needs attention";
    case "queued":
      return "Queued";
    default:
      return "Needs attention";
  }
}

/**
 * The tone a state's badge takes, named for the token groups in `tokens.json` (`CT-UI-10`:
 * colour comes from the tokens, and icon + label + colour together carry the state, never
 * colour alone). Unknown states take the neutral tone.
 */
export function stageTone(state: StageState): "success" | "warning" | "danger" | "info" | "neutral" {
  switch (state) {
    case "done":
      return "success";
    case "in_progress":
      return "info";
    case "needs_attention":
      return "warning";
    case "failed":
      return "danger";
    case "queued":
    case "not_started":
      return "neutral";
    default:
      return "neutral";
  }
}

/** A package's switcher line. Package ids are internal (`pkg-…` is never rendered), and no
 * teacher-facing package title exists in the stored data yet — the ordinal names it when
 * there is more than one. Later stories (the package screens) carry the naming actions. */
export function packageLabel(index: number, count: number): string {
  return count > 1 ? `Test package ${index + 1}` : "Test package";
}

/** The tone an entity state's badge takes (the same token groups the stage badges use).
 * Unknown values stay neutral (CT-CONSOLE-38). */
export function entityTone(state: string): "success" | "warning" | "danger" | "info" | "neutral" {
  switch (state) {
    case "roster_only":
    case "ready":
    case "grading":
    case "draft_ready":
    case "running":
      return "info";
    case "graded":
    case "published":
    case "complete":
      return "success";
    case "stalled":
    case "paused":
      return "warning";
    case "failed":
      return "danger";
    default:
      return "neutral";
  }
}

/** How many missing pieces the draft has, in the review walk's own words. */
export function missingPiecesLabel(count: number): string {
  return count === 1 ? "1 missing piece" : `${count} missing pieces`;
}

// --- the secondary pages' vocabulary (FR-UI-18..21) -------------------------------------------------
//
// The jobs table, the issues cards and the settings page render the same rule as the
// stepper: the server's enum words are renamed here before they reach a screen, and a value
// this build does not know falls through to the neutral wording, never an error
// (CT-CONSOLE-38).

/** A job's state, as the jobs table shows it. The server's five words (CT-CONSOLE-37) map
 * to teacher words; anything newer reads as neutral (CT-CONSOLE-38). */
export function jobStateLabel(state: string): string {
  switch (state) {
    case "queued":
      return "Waiting";
    case "running":
      return "Running";
    case "succeeded":
      return "Done";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Stopped";
    default:
      return "Needs attention";
  }
}

/** A job state badge's tone — the same token groups the stage badges use (CT-UI-10). */
export function jobTone(state: string): "success" | "warning" | "danger" | "info" | "neutral" {
  switch (state) {
    case "succeeded":
      return "success";
    case "running":
      return "info";
    case "failed":
      return "danger";
    default:
      return "neutral";
  }
}

/** A job's kind, as the jobs table's first column names it. A kind this build does not
 * know renders as the server's own word, spaced — a name, not a state. */
export function jobKindLabel(kind: string): string {
  if (kind === "run") {
    return "Grading run";
  }
  const spaced = kind.replace(/_/g, " ").trim();
  return spaced === "" ? "Job" : spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** A job's cost as the table shows it: the read's own figure, dollars to the cent, and a
 * plain dash when the job carries none yet — never an invented zero (CT-UI-08). */
export function jobCostLabel(costUsd: number | null): string {
  return costUsd === null ? "—" : `$${costUsd.toFixed(2)}`;
}

/** A duration in seconds as the jobs table shows it, in whole clock units. */
export function durationLabel(seconds: number | null): string {
  if (seconds === null) {
    return "—";
  }
  const whole = Math.max(0, Math.round(seconds));
  if (whole < 60) {
    return `${whole}s`;
  }
  const minutes = Math.floor(whole / 60);
  if (minutes < 60) {
    return `${minutes}m ${whole % 60}s`;
  }
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** An issue card's severity tone, derived from the server's own source word (FR-UI-18's
 * icon+label+colour severity, sourced honestly): a second-opinion note informs, every
 * other known source warns, and an unknown source stays neutral (CT-CONSOLE-38). */
export function issueTone(source: string): "success" | "warning" | "danger" | "info" | "neutral" {
  switch (source) {
    case "second opinion":
      return "info";
    case "grading step":
    case "parked paper":
    case "grading point":
      return "warning";
    default:
      return "neutral";
  }
}

/** An issue card's severity label — the words beside the icon (CT-UI-10: never colour
 * alone). An unknown source reads as neutral (CT-CONSOLE-38). */
export function issueSeverityLabel(source: string): string {
  return issueTone(source) === "info" ? "Information" : "Needs attention";
}

// --- the authoring screens' vocabulary (FR-UI-11..13, #764) -----------------------------------------
//
// The draft's own entry ids (`Q3`, `C2`) and the structure read's dotted locations are
// internal names, so they are renamed here before they reach a screen — the same rule the
// state badges follow, and the one the vocabulary scan (CT-CONSOLE-31) enforces on every
// teacher surface: no raw entry id, no TOML path, ever.

/** A draft question's id, as the teacher reads it: "Q3" becomes "Question 3"; anything
 * else is already a name and stands as it is. */
export function questionLabel(id: string): string {
  const numbered = /^Q(\d+)$/.exec(id.trim());
  return numbered ? `Question ${numbered[1]}` : id.trim();
}

/** A grading point's id, the same rule: "C2" becomes "Grading point 2". */
export function criterionLabel(id: string): string {
  const numbered = /^C(\d+)$/.exec(id.trim());
  return numbered ? `Grading point ${numbered[1]}` : id.trim();
}

/** A question's type, as the editor's form names it. */
export function questionTypeLabel(type: string): string {
  switch (type) {
    case "mcq":
      return "Multiple choice";
    case "mixed":
      return "Choice and written";
    case "open":
      return "Written answer";
    default:
      return "Written answer";
  }
}

/**
 * One entry of the server's own change list or validation list, reworded to the teacher's
 * vocabulary. The server's locators read `question 'Q3' options` — the same words the
 * draft's checks use — and the map's job is exactly what the state badges' is: the
 * internal name goes in, the teacher's words come out, and a locator this build does not
 * know still renders, renamed as far as the known parts reach.
 */
export function entryFieldLabel(field: string): string {
  return field.replace(
    /(question|criterion)\s+'([^']+)'/g,
    (_all, kind: string, id: string) =>
      kind === "question" ? questionLabel(id) : criterionLabel(id),
  ).trim();
}

/** Where in the draft a missing piece stands, from the structure read's dotted location:
 * the segment naming the entry becomes the entry's label, and the field it stands at
 * becomes the field's teacher name. */
export function placeholderLocationLabel(location: string, items: { id: string }[]): string {
  const match = /^(question|criterion)\[(\d+)\](?:\.(.*))?$/.exec(location.trim());
  if (match !== null) {
    const entry = items[Number(match[2])];
    const name = entry !== undefined
      ? (match[1] === "question" ? questionLabel(entry.id) : criterionLabel(entry.id))
      : (match[1] === "question" ? "a question" : "a grading point");
    const field = placeholderFieldLabel(match[3] ?? "");
    return field === "" ? name : `${name} — ${field}`;
  }
  if (location.trim().startsWith("grades")) {
    return "The grade table";
  }
  return "In the draft";
}

/** The field a missing piece stands at, in the same words the answer form uses. */
function placeholderFieldLabel(field: string): string {
  switch (field) {
    case "model_answer":
      return "the expected answer";
    case "options":
      return "the answer options";
    case "key":
      return "the answer key";
    case "bands":
      return "the score levels";
    case "type":
      return "the question type";
    default:
      return "";
  }
}
