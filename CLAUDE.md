# Project conventions

Architecture, rationale, and setup: **README.md**. This file is only the always-loaded
subset — the rules that must hold even when no skill is running, since that's where they'd
otherwise be missed.

## Pipeline ownership

`detailed-design.md` → `test-plan.md` → GitHub issues → PRs. One owner per artifact; don't
produce another stage's:

| Artifact | Owner |
|---|---|
| `FR-*` / `NFR-*` / `CT-*` IDs, `docs/design/detailed-design.md` | `/detailed-design-generator` |
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

- `TEST_CMD` is `./scripts/test.sh` — the fast tier, and the Stop-hook verification gate. It
  needs the dev environment: `python -m venv .venv` then
  `.venv/Scripts/python -m pip install -r requirements-dev.txt` (`.venv/bin/python` on
  POSIX). `.venv/` is gitignored, so a fresh clone must do this once.
- **`writtenahead` is load-bearing.** Test plan §8.2 has every test story land **red**,
  written ahead of its implementation — and the Stop hook blocks the turn whenever `TEST_CMD`
  fails. So `scripts/test.sh` adds `and not writtenahead` to test-plan §4.7's marker string,
  and red-by-design tests carry `@pytest.mark.writtenahead`. When an implementing issue
  closes, **remove the marker, never the test**, and drop its entry from
  `WRITTEN_AHEAD_BLOCKERS` in `tests/support/impl.py` — a gate test fails until you do, which
  is what stops a P0 case sitting outside the gate forever. `pytest -q` with no marker filter
  is the honest full picture and is what a PR reports.
- Stage 3 onward needs git and a GitHub remote (PRs, `git diff`, working-tree checks). If
  `git rev-parse` fails here, stop and say so rather than working around it.
- **All work runs locally.** GitHub hosts the repo and the issue graph; it does not run
  agents. The workflows under `.github/workflows/` are `.disabled` deliberately — don't
  re-enable them or add new ones without being asked. `/work-backlog` is the dispatcher.

## Code conventions

### The four seams — build them in, don't retrofit them

From `/harness-bootstrap` ; rationale in
`docs/harness-adoption.md`). These are cheap now and expensive later, so every module carries
them from its first commit:

1. **A headless driver.** The system runs end-to-end from code, returning a structured result
   plus a per-stage trace. Nothing may require the console to run — `CT-CONSOLE-01`.
2. **A deterministic transport for every external dependency.** Added the same moment the
   dependency is. The system must run with no network and no real upstream: that is
   `RecordedFixtureProvider` (`CT-PROV-10`), and it stays the only egress point
   (`CT-PROV-15`).
3. **Env-gated knobs for every environment-sensitive constant** — timeout, page size,
   concurrency, retry count. Production value is the default; the knob exists so a slower test
   box can adjust without a code change. A constant calibrated for prod that is hard-coded
   becomes a phantom bug in every other environment.
4. **Stage-level observability in the result.** Surface what each stage did, next to the
   status. A bare `status=success` sitting on top of an empty result is the top silent-failure
   trap — `IngestReport.gates` is deliberately per-gate rather than one boolean (`CT-INGEST-08`).

### Co-evolution: the pair ships together, not the same commit

The harness rule is "every new capability ships with its case." Here that means the
`type:story` and its `type:test` issue are **scheduled and merged as a pair** — it does *not*
mean `/fix-issue` writes tests. Test authorship stays separate on purpose: the agent that wrote
the code is the wrong one to judge whether its tests would catch its own bugs. Keep both rules;
they are compatible as long as "same change" is read as "same pair", not "same author".

Every environment-sensitive constant discovered mid-implementation becomes a knob in that same
pass, and every bug found later becomes a permanent case.
