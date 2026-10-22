/**
 * Every input says what it expects (FR-UI-36): a visible label, a format line directly
 * under the control linked by `aria-describedby`, and — when the entry does not fit — a
 * red refusal at the field restating the format line. The format line and the check read
 * one `FieldSpec`, so the guidance never states a range the check does not enforce.
 */

import { useId, type ReactNode } from "react";
import { formatLine, type FieldSpec } from "../wizard/vocabulary";

/** The attributes a control takes to be linked to its label, format line and refusal. */
export interface ControlProps {
  id: string;
  "aria-describedby": string;
  "aria-invalid"?: boolean;
}

/** The ids one field uses, and the control attributes that link them. */
export function useFieldIds(error: string | null = null): {
  id: string;
  formatId: string;
  errorId: string;
  control: ControlProps;
} {
  const id = useId();
  const formatId = `${id}-format`;
  const errorId = `${id}-error`;
  return {
    id,
    formatId,
    errorId,
    control: {
      id,
      "aria-describedby": error ? `${formatId} ${errorId}` : formatId,
      "aria-invalid": error ? true : undefined,
    },
  };
}

/** The format line: the expected form and its limits, shown before the teacher types. */
export function FormatLine({ id, spec }: { id: string; spec: FieldSpec | string }) {
  return (
    <p id={id} className="field-format">
      {typeof spec === "string" ? spec : formatLine(spec)}
    </p>
  );
}

/** The id of the format line belonging to the control `id`, for controls whose ids are
 * already fixed by the screen (`aria-describedby={formatIdFor(id)}`). */
export function formatIdFor(id: string): string {
  return `${id}-format`;
}

/** The refusal's id for the control `id` (`FieldError id={errorIdFor(id)}`). */
export function errorIdFor(id: string): string {
  return `${id}-error`;
}

/** The control's `aria-describedby`: its format line, and its refusal while it has one. */
export function describedBy(id: string, error: string | null): string {
  return error === null ? formatIdFor(id) : `${formatIdFor(id)} ${errorIdFor(id)}`;
}

/** The refusal at the field, in red beside it. Nothing renders while the entry fits. */
export function FieldError({ id, error }: { id: string; error: string | null }) {
  if (error === null) {
    return null;
  }
  return (
    <p id={id} className="field-invalid" role="alert">
      {error}
    </p>
  );
}

/**
 * One labelled field: the label, the control (rendered by the caller with the linking
 * attributes it is handed), the format line under it and the refusal when there is one.
 */
export function Field({
  label,
  spec,
  error = null,
  className = "field",
  children,
}: {
  label: ReactNode;
  spec: FieldSpec;
  error?: string | null;
  className?: string;
  children: (control: ControlProps) => ReactNode;
}) {
  const ids = useFieldIds(error);
  return (
    <div className={className}>
      <label htmlFor={ids.id}>{label}</label>
      {children(ids.control)}
      <FormatLine id={ids.formatId} spec={spec} />
      <FieldError id={ids.errorId} error={error} />
    </div>
  );
}
