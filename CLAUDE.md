# Project conventions

Architecture, rationale, and setup: **README.md**. This file is only the always-loaded
subset — the rules that must hold even when no skill is running, since that's where they'd
otherwise be missed.

## Pipeline ownership

`detailed-design.md` → `test-plan.md` → GitHub issues → PRs. One owner per artifact; don't
produce another stage's:

| Artifact | Owner |
|---|---|
| `FR-*` / `NFR-*` IDs, `docs/design/detailed-design.md` | `/detailed-design-generator` |
| `TC-*` IDs, risk register, test-story sizing, `docs/design/test-plan.md` | `/create-test-plan` |
| GitHub issues | `/plan-to-issues` — nothing else runs `gh issue create` |
| Implementation code | `/fix-issue` |
| Test code | `/write-tests` |

Asked for a later artifact without the earlier one? Run the earlier skill rather than
improvising the output — each is one command, and hand-made versions don't carry the IDs
the next stage reads.

## Test authorship

Test cases live in `test-plan.md` and are implemented by `/write-tests`. **`/fix-issue`
does not write them** — two suites for one requirement is the result.

Exception: a defect fix with no existing `TC-*` coverage. Write the regression test inline,
confirm it fails against the unfixed code, and add the case to `test-plan.md` in the same
PR. A test in the repo but not in the plan makes the plan lie about coverage.

## Issues

- `type:story` → `/fix-issue`; `type:test` → `/write-tests`. `status:*` labels are the claim
  mechanism and are set by `/work-backlog` as it picks up and releases each issue — set them
  by hand only when you're working an issue outside that skill.
- Dependencies are one literal line: `Depends on: #12, #34` — that exact wording,
  `#`-prefixed **numbers**. Omit the line when there are none; never `Depends on: none` or a
  story title. `scripts/ready-issues.sh` parses it.
- Every issue carries a **`Goal:`** line (one checkable sentence) and a **`Traces to:`** line
  naming its `FR-*`/`TC-*` IDs. Implementation skills plan against the Goal and the
  `reviewer` subagent checks diffs against it; `Traces to:` is what keeps traceability alive
  past the GitHub boundary. Full body format:
  `.claude/skills/plan-to-issues/references/issue-templates.md`.

## Working rules

- Beyond a one-line fix, work in plan mode first: read the code, then write a plan before
  editing.
- Never declare work done because it looks right. Run `TEST_CMD` and show the output. If you
  can't find the right command, ask rather than guess.
- Before opening a PR, use the `reviewer` subagent against the issue's Goal and acceptance
  criteria. Fix correctness findings; treat style nitpicks as optional.
- For a genuinely hard call — an ambiguous design decision, a bug that's resisted two fix
  attempts, or right before declaring a big task complete — consult the advisor
  (`/advisor opus`).

## Environment

- `TEST_CMD` in `.claude/settings.json` is **empty**, which disables the Stop-hook
  verification gate. Set it once this project has a real suite.
- Stage 3 onward needs git and a GitHub remote (PRs, `git diff`, working-tree checks). If
  `git rev-parse` fails here, stop and say so rather than working around it.
- **All work runs locally.** GitHub hosts the repo and the issue graph; it does not run
  agents. The workflows under `.github/workflows/` are `.disabled` deliberately — don't
  re-enable them or add new ones without being asked. `/work-backlog` is the dispatcher.

## Code conventions

<!-- Add this repo's actual code conventions here: style, branch naming, PR expectations,
     anything Claude can't infer from reading the code. -->
