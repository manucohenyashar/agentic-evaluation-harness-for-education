import tokens from "./tokens.json";

/**
 * NFR-UI-02: `tokens.json` is the single source of truth. The stylesheet never hard-codes a
 * color, size, spacing, radius or shadow — it reads the custom properties this module sets.
 * `kebab` turns each token's camelCase name into its CSS spelling (`accentInk` ->
 * `--color-accent-ink`), so a token's variable name is decided by its JSON name alone.
 */
const KEBAB = /(^|[a-z0-9])([A-Z])/g;

function kebab(name: string): string {
  return name.replace(KEBAB, (_all, head: string, tail: string) => `${head}-${tail.toLowerCase()}`);
}

export function tokenVariable(category: string, name: string): string {
  return `--${kebab(category)}-${kebab(name)}`;
}

export function applyTokens(root: HTMLElement = document.documentElement): void {
  for (const [category, values] of Object.entries(tokens)) {
    for (const [name, value] of Object.entries(values)) {
      root.style.setProperty(tokenVariable(category, name), String(value));
    }
  }
}
