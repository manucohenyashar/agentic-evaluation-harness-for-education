/**
 * The context header (FR-CONSOLE-48): the class, package and run switchers ride every
 * screen, each beside its entity's state badge, so the teacher always sees which ledger,
 * package and run the screen is reading. Switching only changes the address (`CT-UI-09`:
 * never a POST on selection change) and the hash carries only the opaque refs
 * (`CT-UI-07`).
 */

import { CircleHelp } from "lucide-react";
import type { ContextDoc } from "../api";
import { runLabel } from "../screens/PastTests";
import { ledgerEntries, newestRunFirst, type Selection } from "./derivation";
import { EntityBadge } from "./StateBadge";
import { packageLabel } from "./vocabulary";

export interface ContextHeaderProps {
  context: ContextDoc | null;
  selection: Selection;
  /** Patches the selection; a null value drops that ref from the address. */
  onSelection: (patch: Partial<Record<"class" | "package" | "run", string | null>>) => void;
  /** Opens the help-everywhere panel (FR-UI-21) over whatever screen is showing. */
  onHelp: () => void;
  /** True while the panel is open — the button then says the panel can be closed. */
  helpOpen?: boolean;
}

interface SwitcherOption {
  value: string;
  label: string;
}

function Switcher({
  id,
  label,
  options,
  value,
  onChange,
  disabled,
}: {
  id: string;
  label: string;
  options: SwitcherOption[];
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  return (
    <>
      <label className="switcher-label" htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className="switcher"
        value={value}
        disabled={disabled || options.length === 0}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.length === 0 ? <option value="">None yet</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </>
  );
}

export function ContextHeader({ context, selection, onSelection, onHelp, helpOpen = false }: ContextHeaderProps) {
  const classes = context === null ? [] : ledgerEntries(context);
  const packages = context?.packages ?? [];
  // FR-CONSOLE-70: the runs of the class in hand, newest first, each named by what the
  // teacher remembers — class, test and date — never "Grading run 3". With no class chosen,
  // every run is offered. Past tests lists them all with their students.
  const runs = newestRunFirst(
    (context?.runs ?? []).filter(
      (run) => selection.classId === null || run.cohort_id === selection.classId,
    ),
  );

  const classOptions: SwitcherOption[] = classes.map((entry) => ({
    value: entry.cohort_id,
    label: entry.label,
  }));
  const packageOptions: SwitcherOption[] = packages.map((entry, index) => ({
    value: entry.package_id,
    label: packageLabel(index, packages.length),
  }));
  const runOptions: SwitcherOption[] = runs.map((entry) => ({
    value: entry.run_id,
    label: runLabel(entry),
  }));

  const selectedClass = classes.find((entry) => entry.cohort_id === selection.classId) ?? null;
  const selectedPackage = packages.find((entry) => entry.package_id === selection.packageId) ?? null;
  const selectedRun = runs.find((entry) => entry.run_id === selection.runId) ?? null;

  return (
    <header className="context-header">
      <a className="context-home" href="#/" aria-label="Wizard home">
        Console
      </a>
      <div className="switchers" role="group" aria-label="What the screen is reading">
        <Switcher
          id="switcher-class"
          label="Class"
          options={classOptions}
          value={selection.classId ?? ""}
          disabled={context === null}
          onChange={(value) => onSelection({ class: value === "" ? null : value })}
        />
        {selectedClass !== null && <EntityBadge state={selectedClass.state} />}
        <Switcher
          id="switcher-package"
          label="Test package"
          options={packageOptions}
          value={selection.packageId ?? ""}
          disabled={context === null}
          onChange={(value) => onSelection({ package: value === "" ? null : value })}
        />
        {selectedPackage !== null && <EntityBadge state={selectedPackage.state} />}
        <Switcher
          id="switcher-run"
          label="Grading run"
          options={runOptions}
          value={selection.runId ?? ""}
          disabled={context === null}
          onChange={(value) => onSelection({ run: value === "" ? null : value })}
        />
        {selectedRun !== null && <EntityBadge state={selectedRun.state} />}
      </div>
      <button
        type="button"
        className="button help-button"
        aria-expanded={helpOpen}
        onClick={onHelp}
      >
        <CircleHelp size={16} aria-hidden="true" />
        {helpOpen ? "Close help" : "Help"}
      </button>
    </header>
  );
}
