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
