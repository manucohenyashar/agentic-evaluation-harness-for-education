---
name: plan-to-issues
description: Turn a detailed design and its test plan into dependency-linked GitHub issues, created in topological order so "Depends on" links point at real issue numbers. The only thing in this harness that creates issues.
disable-model-invocation: true
---

Convert $ARGUMENTS (a path to a folder containing the design documents and test plan, or
paths to the documents themselves) into GitHub issues that `scripts/ready-issues.sh`,
`/fix-issue`, and `/write-tests` can pick up.

**This skill is the only thing in the harness that creates issues, and it is a
transcription step, not a planning step.** The detailed design decided the modules and
requirements; the test plan decided the test cases and sized the test stories. Your job is
to carry those decisions into GitHub without losing the IDs, not to redo them. Re-deriving
the breakdown here is the failure mode that made the previous version of this harness
produce two incompatible backlogs from the same design.

Read `references/issue-templates.md` before creating anything — it defines the exact body
format every issue must have.

## 1. Read the documents

Read every document in the folder, recursing into subfolders. Expect two:

- **`detailed-design.md`** — modules (`M-*`), functional and non-functional requirements
  (`FR-*`, `NFR-*`), interfaces, data structures, and the module dependency graph
- **`test-plan.md`** — the risk register, test cases (`TC-*`), and §8.2's test-story table,
  which already lists the stories, what they cover, their dependencies, and whether each is
  written ahead of implementation

If the test plan is missing, stop and say so rather than proceeding. A story track without
a test track produces a backlog that ships untested code, and inventing the test cases here
would put them in the one place that has no traceability check over it. The fix is one
command: `/create-test-plan <design-path>`.

## 2. Extract the two tracks together

**Code stories** come from the design's functional requirements, grouped so that one story
is one reviewable PR. Use the module boundaries and the requirement grouping the design
already established; a module with eight requirements is usually three or four stories, not
one and not eight.

**Test stories** come from the test plan's §8.2 table directly. It already has the title,
the `TC-*` IDs covered, the dependency, and the ahead-of-implementation flag. Transcribe
it; do not re-partition it.

For every story capture:

- Title — short, imperative
- **Goal** — one clear sentence, the acceptance criterion a reviewer checks the PR against
- **Traces to** — the `FR-*` / `NFR-*` / `TC-*` IDs it covers. This is what keeps the RTM
  alive past the GitHub boundary; an issue with no `Traces to:` line is untraceable work.
- Acceptance criteria, technical notes, and evaluation strategy per the templates
- Dependencies, by story title for now — they don't have issue numbers yet
- `type:story` or `type:test`

Extract both tracks in one pass so cross-track dependencies are captured together. **Every
`type:story` must have at least one `type:test` covering its requirements** — the test
plan's RTM guarantees this at the `TC-*` level, so verify it survived into the story
grouping rather than re-deriving it.

## 3. Order them

Topologically sort so every dependency comes before what depends on it. Code stories order
by the design's module dependency graph; test stories order by their stated dependency, and
the ones written ahead of implementation have none and can go first.

If you find a cycle, stop and report it. Don't create issues for a graph that can't
resolve.

## 4. Create issues in that order

Make sure the labels exist (idempotent, safe to re-run):

```bash
gh label create "type:story" --color 1D76DB --force
gh label create "type:test" --color 5319E7 --force
gh label create "status:in-progress" --color FBCA04 --force
gh label create "status:in-review" --color 0E8A16 --force
gh label create "status:needs-attention" --color B60205 --force
```

Then, for each story in sorted order:

- Resolve its dependencies' titles to the real issue numbers you created earlier in this
  same loop — dependencies always come first, so the numbers exist.
- Run `gh issue create` with `--title`, `--label`, and `--body` built from the matching
  template in `references/issue-templates.md`.
- The dependency line is literally `Depends on: #12, #34`. Omit it entirely when there are
  none. Never `Depends on: none` and never a story title: `ready-issues.sh` parses
  `#`-numbers and reports anything else as malformed.
- Keep a running map of story title to issue number.

## 5. Verify the transcription

Before reporting, confirm nothing was lost between the documents and GitHub:

```bash
./scripts/trace-issues.sh <docs-path>
```

It reports requirements and test cases that reached no issue, and issues whose `Traces to:`
IDs don't exist in the documents. Fix what it finds — usually a missing `Traces to:` line
or a requirement that quietly got dropped during grouping — and re-run until clean.

## 6. Report

Print every created issue with its number, type, `Traces to:` IDs, and dependency links, so
the graph can be sanity-checked before any agent picks anything up. Then say what to run
next:

- **CI:** nothing — `dispatch-ready-work.yml` picks up ready issues on the next event.
- **Local:** `/goal every open type:story and type:test issue is closed or needs-attention;
  stop after 40 turns`, then `/work-backlog`.
