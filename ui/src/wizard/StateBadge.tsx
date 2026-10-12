/**
 * The state badges (FR-CONSOLE-47's legend): an icon, a label and a token-driven colour
 * together carry each state (`CT-UI-10` — never colour alone), so a screen reader gets the
 * label and a colour-blind teacher gets the glyph. Colours come only from `tokens.json`
 * through the design tokens the stylesheet already applies (`CT-UI-04`).
 */

import { CircleCheck, CircleDot, CirclePause, CircleX, Circle, TriangleAlert } from "lucide-react";
import type { StageState } from "../api";
import { entityStateLabel, entityTone, stageStateLabel, stageTone } from "./vocabulary";

type Tone = "success" | "warning" | "danger" | "info" | "neutral";

function glyphFor(state: StageState) {
  switch (state) {
    case "done":
      return CircleCheck;
    case "in_progress":
      return CircleDot;
    case "failed":
      return CircleX;
    case "needs_attention":
      return TriangleAlert;
    case "queued":
      return CirclePause;
    default:
      return Circle;
  }
}

/** A stage's badge: the legend's glyph as an icon with its label spelled out beside it
 * (icon + label + colour carry the state together, `CT-UI-10`). `compact` drops the label
 * for the sidebar strip and keeps it for the screen reader. */
export function StageBadge({ state, compact = false }: { state: StageState; compact?: boolean }) {
  const Glyph = glyphFor(state);
  const tone = stageTone(state);
  const label = stageStateLabel(state);
  return (
    <span className={`badge badge-${tone}`}>
      <Glyph size={14} aria-hidden="true" />
      {compact ? <span className="visually-hidden">{label}</span> : <span>{label}</span>}
    </span>
  );
}

/** A class, cohort, package or run state, as the header's switchers show it — icon, label
 * and colour together (CT-UI-10); the tone's glyph stands for the state the way the stage
 * badges' glyphs do. */
export function EntityBadge({ state }: { state: string }) {
  const tone = entityTone(state);
  const Glyph = glyphFor(
    tone === "success" ? "done"
      : tone === "info" ? "in_progress"
      : tone === "warning" ? "needs_attention"
      : tone === "danger" ? "failed"
      : "not_started",
  );
  return (
    <span className={`badge badge-${tone}`}>
      <Glyph size={14} aria-hidden="true" />
      <span>{entityStateLabel(state)}</span>
    </span>
  );
}
