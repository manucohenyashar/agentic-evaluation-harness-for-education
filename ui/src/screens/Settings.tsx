import { useEffect, useState, type FormEvent } from "react";
import { performAction, type ConfigDoc, type SettingRow } from "../api";
import { ConfirmDialog, useActionState } from "../components/Confirm";
import { describedBy, FormatLine, formatIdFor } from "../components/Field";
import { DisabledReason } from "../components/Outcome";
import {
  checkField,
  FORMAT_CHOOSE_ONE,
  pleaseEnter,
  type FieldSpec,
} from "../wizard/vocabulary";
import { ReadScreen } from "../components/ReadScreen";
import { useScreenRead } from "../useScreenRead";

/**
 * The settings page (FR-UI-20, FR-CONF-34/35): the configuration projection rendered —
 * every setting with its teacher label and the value in force, the editable subset as
 * guided forms, everything else read-only, which is the truth. The form posts the
 * enumerated `update configuration` control — never the file — keyed by the row's own
 * setting id, behind its confirmation (CT-UI-09). A secret's row says whether one is
 * configured and never a value (CT-CONF-19), and no key name from the configuration file
 * appears anywhere on the page (CT-CONF-19, CT-CONSOLE-31).
 */

type Edits = Record<string, string>;

/** A setting's one definition (FR-UI-36): the format line shown under its field and the
 * client-side check read the same spec. The write path re-validates every edit against the
 * loader's own rules, and its refusal is the outcome the page shows. */
function settingSpec(row: SettingRow): FieldSpec {
  if (row.type === "choice") {
    return { kind: "choice", format: FORMAT_CHOOSE_ONE };
  }
  if (row.type === "number") {
    if (row.field === "cost_ceiling") {
      return { kind: "decimal", format: "An amount in US dollars, for example 5 or 12.50", min: 0 };
    }
    if (row.field.endsWith("_gate")) {
      return { kind: "decimal", format: "A number from 0 to 1, for example 0.8", min: 0, max: 1 };
    }
    if (row.field === "decision_citation_question_limit") {
      return { kind: "whole_number", min: 1, max: 26 };
    }
    if (row.field === "decision_token_bytes_ratio") {
      return { kind: "whole_number", min: 1, max: 8 };
    }
    return { kind: "decimal", format: "A number, for example 3 or 0.5" };
  }
  if (row.field.endsWith("_model")) {
    return {
      kind: "text",
      format: "One model, written as provider|build",
      pattern: /^[^;|]*\S[^;|]*(\|[^;|]*\S[^;|]*)+$/,
    };
  }
  return { kind: "text", format: "Plain text" };
}

/** An edit's refusal at the field: an unchanged value is never refused, an emptied one is. */
function validateEdit(row: SettingRow, value: string): string | null {
  if (value === row.value) {
    return null;
  }
  const spec = settingSpec(row);
  return value.trim() === "" ? pleaseEnter(spec) : checkField(spec, value);
}

function EditRow({
  row,
  draft,
  error,
  onChange,
}: {
  row: SettingRow;
  draft: string;
  error: string | null;
  onChange: (value: string) => void;
}) {
  const id = `setting-${row.field}`;
  const invalid = error !== null;
  const linked = describedBy(id, error);
  return (
    <div className={`settings-row${invalid ? " settings-row-error" : ""}`}>
      <label htmlFor={id}>{row.label}</label>
      {row.type === "choice" && row.choices.length > 0 ? (
        <select id={id} aria-describedby={linked} value={draft} onChange={(event) => onChange(event.target.value)}>
          {row.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      ) : row.type === "number" ? (
        <input
          id={id}
          type="text"
          inputMode="decimal"
          aria-describedby={linked}
          value={draft}
          aria-invalid={invalid || undefined}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          id={id}
          type="text"
          aria-describedby={linked}
          value={draft}
          aria-invalid={invalid || undefined}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      <FormatLine id={formatIdFor(id)} spec={settingSpec(row)} />
      {error !== null && (
        <p id={`${id}-error`} className="settings-error field-invalid" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function valueLabel(row: SettingRow): string {
  if (row.type === "secret") {
    return row.configured ? "Configured ✓" : "Not configured";
  }
  return row.value === "" ? "—" : row.value;
}

export function Settings() {
  const read = useScreenRead<ConfigDoc>("/api/v1/config");
  const action = useActionState(read.retry);
  const [draft, setDraft] = useState<Edits>({});

  // A fresh read (the retry after a save) resets the draft to what the projection says,
  // so the form never keeps an edit the page no longer shows.
  useEffect(() => {
    setDraft({});
  }, [read.data]);

  return (
    <ReadScreen title="Settings" read={read}>
      {(data) => {
        const editable = data.settings.filter((row) => row.editable);
        const fixed = data.settings.filter((row) => !row.editable);
        const errors = new Map<string, string>(
          editable
            .map((row) => [row.field, validateEdit(row, draft[row.field] ?? row.value)] as const)
            .filter(([, error]) => error !== null) as [string, string][],
        );
        const changed = editable.filter((row) => (draft[row.field] ?? row.value) !== row.value);
        const anyError = errors.size > 0;

        const submit = (event: FormEvent): void => {
          event.preventDefault();
          if (changed.length === 0 || anyError) {
            return;
          }
          const edits: Edits = {};
          for (const row of changed) {
            edits[row.field] = draft[row.field] ?? row.value;
          }
          action.open({
            title: "Change these settings",
            description:
              `You are about to change ${changed.length === 1 ? "1 setting" : `${changed.length} settings`}: ` +
              changed.map((row) => row.label).join(", ") +
              ". The console rechecks every value before it writes anything; a refused value changes nothing.",
            confirm: "Change",
            action: "update configuration",
            body: { edits },
          });
        };

        return (
          <>
            {editable.length === 0 ? (
              <p>No setting can be changed here.</p>
            ) : (
              <form className="settings-form" onSubmit={submit}>
                <fieldset>
                  <legend>Change the settings</legend>
                  {editable.map((row) => (
                    <EditRow
                      key={row.field}
                      row={row}
                      draft={draft[row.field] ?? row.value}
                      error={errors.get(row.field) ?? null}
                      onChange={(value) => setDraft({ ...draft, [row.field]: value })}
                    />
                  ))}
                  <div className="settings-actions">
                    <button
                      type="submit"
                      className="button button-primary"
                      disabled={changed.length === 0 || anyError}
                    >
                      Save the changes
                    </button>
                    <button
                      type="button"
                      className="button"
                      onClick={() => setDraft({})}
                      disabled={changed.length === 0}
                    >
                      Discard the changes
                    </button>
                    <DisabledReason
                      reason={
                        anyError ? "Fix the settings marked in red first."
                          : changed.length === 0 ? "Change a setting first." : null
                      }
                    />
                  </div>
                </fieldset>
              </form>
            )}
            <section className="settings-fixed" aria-label="Everything the console uses">
              <h2>Everything the console uses</h2>
              <dl className="settings-list">
                {fixed.map((row) => (
                  <div className="settings-row" key={row.field}>
                    <dt>{row.label}</dt>
                    <dd>{valueLabel(row)}</dd>
                  </div>
                ))}
              </dl>
            </section>
            {action.pending !== null && (
              <ConfirmDialog pending={action.pending} onClose={action.close} onDone={action.finish} />
            )}
          </>
        );
      }}
    </ReadScreen>
  );
}
