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

/** A package's switcher option (FR-UI-28): a published package's id is the test's own
 * name, printed on the sheets, so it *is* the option's label — followed by
 * " — version <n>" once the test has more than one version. The ordinal fallback
 * ("Test package 2") applies only to an id matching the internal `pkg-` pattern; a
 * `pkg-…` reference itself is never shown. The switcher's own label stays "Test
 * package" (the Switcher's prop, not this). */
export function packageLabel(
  packageId: string,
  versionCount: number,
  index: number,
  count: number,
): string {
  const id = (packageId ?? "").split("@")[0] ?? "";
  if (id === "" || /^pkg-/.test(id)) {
    return count > 1 ? `Test package ${index + 1}` : "Test package";
  }
  return versionCount > 1 ? `${id} — version ${versionCount}` : id;
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
  if (kind === "paper_intake") {
    return "Reading the papers";
  }
  const spaced = kind.replace(/_/g, " ").trim();
  return spaced === "" ? "Job" : spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** A job's cost as the table shows it: the read's own figure, dollars to the cent, and a
 * plain dash when the job carries none yet — never an invented zero (CT-UI-08). */
export function jobCostLabel(costUsd: number | null): string {
  return costUsd === null ? "—" : `$${costUsd.toFixed(2)}`;
}

/** A duration in teacher words (FR-UI-29): under a minute "45 s", under an hour
 * "2 min 14 s", otherwise "1 h 5 min" — spaces before each unit, no seconds in the
 * hour form. */
export function durationLabel(seconds: number | null): string {
  if (seconds === null) {
    return "—";
  }
  const whole = Math.max(0, Math.round(seconds));
  if (whole < 60) {
    return `${whole} s`;
  }
  const minutes = Math.floor(whole / 60);
  if (minutes < 60) {
    return `${minutes} min ${whole % 60} s`;
  }
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/** Round half-up to `places` decimals, from the unrounded value — JS `toFixed` rounds
 * half-to-even on some values, and the design pins half-up (FR-UI-31's rounding rule).
 * The shift-and-round reads a decimal in the double's favour: the shift's representation
 * error sits at the 16th digit, far from the half-way digit a 1-decimal label needs. */
export function roundHalfUp(value: number, places: number): string {
  const scale = Math.pow(10, places);
  return (Math.round(value * scale) / scale).toFixed(places);
}

/** One question's average line (FR-UI-31): "average 1.8 / 3 (58%)" — the mean to one
 * decimal half-up, the percentage the unrounded mean ÷ max × 100 half-up to a whole
 * number. A question with no marks reads "0.0 / 3 (0%)". */
export function averageLabel(mean: number | null, max: number): string {
  if (mean === null || max <= 0) {
    return `average 0.0 / ${max} (0%)`;
  }
  const percent = Math.max(0, Math.min(100, Math.round(mean / max * 100)));
  return `average ${roundHalfUp(mean, 1)} / ${max} (${percent}%)`;
}

/** One not-final grade's reason, in the design's own words (FR-UI-32): the sentence the
 * Check badge shows on hover and when the cell expands — keyed by the code the results
 * read serves in `not_final_reason`. */
export const NOT_FINAL_REASON_TEXT: Record<string, string> = {
  one_grader_unsure: "The AI grader was not sure. Please check this answer.",
  graders_disagree: "The AI graders gave different marks. Please choose the right one.",
  evidence_not_found: "The grader could not find the answer in the student's writing. Please check the page.",
  quote_not_verified: "The grader quoted words that are not on the page. Please check this answer.",
  more_graders_unavailable: "A second opinion was needed but no other grader is set up. Please check this answer.",
  graders_refused: "The AI could not grade this question for the class. Please grade it yourself.",
};

/** The clock line for a long operation (FR-UI-29): "Working — 1 min 12 s" while it runs,
 * "Done in 2 min 14 s" (or "Stopped after …" / "Failed after …") when it ends. */
export function elapsedLabel(state: "working" | "done" | "stopped" | "failed",
                             seconds: number | null): string {
  const time = durationLabel(seconds);
  switch (state) {
    case "working":
      return `Working — ${time}`;
    case "done":
      return `Done in ${time}`;
    case "stopped":
      return `Stopped after ${time}`;
    case "failed":
      return `Failed after ${time}`;
  }
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

/** The field words a locator's tail can carry, in the teacher's words. `bands` maps to
 * "the score levels" — "band" is an explicitly forbidden term on a teacher surface —
 * and an unknown token stands as it is, renamed as far as the known parts reach. */
const FIELD_TAILS: Record<string, string> = {
  model_answer: "the expected answer",
  options: "the answer options",
  key: "the answer key",
  bands: "the score levels",
  type: "the question type",
  points: "the points",
  question: "the question it grades",
};

function fieldTailLabel(tail: string): string {
  return tail.trim().split(/\s+/).filter((part) => part !== "")
    .map((part) => FIELD_TAILS[part] ?? part).join(" ");
}

/**
 * One entry of the server's own change list or validation list, reworded to the teacher's
 * vocabulary. The server's locators read `question 'Q3' model_answer` — the same words the
 * draft's checks use — and the map's job is exactly what the state badges' is: the
 * internal names go in (the entry's id *and* the field's word after it — a raw
 * `model_answer` or `bands` on the screen is the same leak an id is), the teacher's words
 * come out, and a locator this build does not know still renders, renamed as far as the
 * known parts reach.
 */
export function entryFieldLabel(field: string): string {
  const text = field.trim();
  if (text === "spec") {
    return "the draft";
  }
  if (/^grades\b/.test(text)) {
    const quoted = /^grades\s+'([^']+)'/.exec(text);
    return quoted !== null
      ? `the grade table — ${questionLabel(quoted[1] ?? "")}`
      : "the grade table";
  }
  const entry = /^(question|criterion)\s+'([^']+)'((?:\s+(?:\w+|\[[^\]]*\]))*)$/.exec(text);
  if (entry !== null) {
    const kind = entry[1] ?? "";
    const id = entry[2] ?? "";
    const name = kind === "question" ? questionLabel(id) : criterionLabel(id);
    const tail = fieldTailLabel(entry[3] ?? "");
    return tail === "" ? name : `${name} — ${tail}`;
  }
  const bare = /^(question|criterion)\s+(.*)$/.exec(text);
  if (bare !== null) {
    const name = (bare[1] ?? "") === "question" ? "a question" : "a grading point";
    const tail = fieldTailLabel(bare[2] ?? "");
    return tail === "" ? name : `${name} — ${tail}`;
  }
  return text;
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

/*
 * The outcome banner's words (FR-UI-24/25): a refusal reads as three sentences — what
 * happened, why, and what to do next. The server sends all three (`what`/`why`/
 * `next_action`); these are the fallbacks for a refusal that arrived without them (a
 * dropped connection, an older answer).
 */
export const OUTCOME_REFUSED_PREFIX = "Refused:";
export const OUTCOME_FALLBACK_WHAT = "Nothing was changed.";
export const OUTCOME_FALLBACK_WHY = "The console could not do it.";
export const OUTCOME_FALLBACK_NEXT = "Check what is named here, then try again.";
export const OUTCOME_DONE_FALLBACK = "Done.";
export const OUTCOME_DISMISS = "Dismiss";
export const OUTCOME_WORKING = "Working…";

/**
 * One input's expected answer (FR-UI-36): the single definition the field's format line
 * and its check both read, so the guidance can never state a range the check does not
 * enforce. `whole_number` mirrors the gap questions' `answer_kind` (FR-AUTHOR-31); the
 * other kinds carry their format line in words.
 */
export type FieldSpec =
  | { kind: "whole_number"; min: number; max: number; format?: string }
  | { kind: "decimal"; format: string; min?: number; max?: number }
  | { kind: "text"; format: string; minLength?: number; maxLength?: number; pattern?: RegExp }
  | { kind: "file"; format: string; accept: string }
  | { kind: "choice"; format: string };

/** The format line shown under a field, before the teacher types (no closing period). */
export function formatLine(spec: FieldSpec): string {
  if (spec.kind === "whole_number") {
    return spec.format ?? `A whole number from ${spec.min} to ${spec.max}`;
  }
  return spec.format;
}

/** The refusal shown at the field: "Please enter " + the format line, as one sentence.
 * A whole number's refusal is the canonical range sentence (FR-AUTHOR-31: the field-level
 * refusal restates the range), not the format hint's tail — a hint like "A whole number
 * from 1 to 8. The test is out of 8 points." refuses as "Please enter a whole number
 * from 1 to 8." */
export function pleaseEnter(spec: FieldSpec): string {
  const line = (spec.kind === "whole_number"
    ? `A whole number from ${spec.min} to ${spec.max}`
    : formatLine(spec)
  ).replace(/\.\s*$/, "");
  return `Please enter ${line.charAt(0).toLowerCase()}${line.slice(1)}.`;
}

/**
 * Whether `value` fits `spec`: `null` when it does, the field's refusal when it does not.
 * An empty value is left to the submit button's own "fill this in" reason, so a field the
 * teacher has not touched yet shows no red.
 */
export function checkField(spec: FieldSpec, value: string): string | null {
  const said = value.trim();
  if (said === "") {
    return null;
  }
  switch (spec.kind) {
    case "whole_number": {
      if (!/^-?\d+$/.test(said)) return pleaseEnter(spec);
      const number = Number(said);
      return number < spec.min || number > spec.max ? pleaseEnter(spec) : null;
    }
    case "decimal": {
      if (!/^-?(\d+(\.\d*)?|\.\d+)$/.test(said)) return pleaseEnter(spec);
      const number = Number(said);
      if (spec.min !== undefined && number < spec.min) return pleaseEnter(spec);
      if (spec.max !== undefined && number > spec.max) return pleaseEnter(spec);
      return null;
    }
    case "text":
      if (spec.minLength !== undefined && said.length < spec.minLength) return pleaseEnter(spec);
      if (spec.maxLength !== undefined && said.length > spec.maxLength) return pleaseEnter(spec);
      if (spec.pattern !== undefined && !spec.pattern.test(said)) return pleaseEnter(spec);
      return null;
    default:
      return null;
  }
}

/** Why a submit button is disabled while its field refuses — said beside the button. */
export function fixFieldFirst(label: string): string {
  return `Fix “${label}” first.`;
}

/** Why a submit button is disabled while a field it needs is still empty. */
export function fillFieldFirst(label: string): string {
  return `Fill in “${label}” first.`;
}

/* The format lines the screens share (FR-UI-36's examples), one wording each. */
export const FORMAT_FULL_NAME = "Your full name, as students know you";
export const FORMAT_STUDENT_NAME = "The student's full name, as it appears on the class list";
export const FORMAT_PDF_PER_STUDENT = "A PDF file, one per student";
export const FORMAT_CHOOSE_ONE = "Choose one from the list";
export const FORMAT_FREE_TEXT = "Plain text, in your own words";
export const FORMAT_QUESTION_TEXT = "The question as students read it on the test";
export const FORMAT_EXPECTED_ANSWER = "The answer you expect, in plain words";
export const FORMAT_OPTION_LETTER = "One letter, for example E";
export const FORMAT_OPTION_WORDS = "The option's words, as printed on the test";
export const FORMAT_GRADED_QUESTION = "Choose the question this grading point marks";
export const FORMAT_REUSE_LEVELS = "Choose a grading point whose score levels to reuse";
export const FORMAT_KEY_OPTIONS = "Tick every option that is a correct answer";
/**
 * A package version's teacher name (FR-UI-23: the `<package>@<hash>` form is internal and
 * never shown): the label the context read serves for it when it knows the version
 * (FR-CONSOLE-74, "ENG7-READ-01 version 1"), otherwise the test's name alone.
 */
export function versionName(
  versionId: string | null | undefined,
  known?: { published_version_id: string | null; published_version: string | null }[],
): string {
  if (!versionId) {
    return "no test yet";
  }
  const label = known?.find((entry) => entry.published_version_id === versionId)?.published_version;
  if (label) {
    return label;
  }
  return packageName(versionId.split("@")[0] ?? "");
}

/** A package's teacher name: a published package's id is the test's own name; an internal
 * `pkg-…` reference is never shown. */
export function packageName(packageId: string | null | undefined): string {
  const id = (packageId ?? "").split("@")[0] ?? "";
  return id === "" || id.startsWith("pkg-") ? "this test" : id;
}

/** A question's or grading point's points, as the editor checks them — the edit
 * surface's own rule: any number of points, 0 or more. */
export const QUESTION_POINTS: FieldSpec = {
  kind: "decimal",
  format: "A number of points, 0 or more, for example 2 or 2.5",
  min: 0,
};
