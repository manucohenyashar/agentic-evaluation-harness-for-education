---
name: fix-issue
description: Turn a type:story GitHub issue into a reviewed, tested pull request using plan mode, a verification loop, and an adversarial review subagent.
disable-model-invocation: true
---

Implement GitHub issue: $ARGUMENTS. Follow every phase in order — don't skip verification
or review even if the change looks obviously correct.

This skill owns **implementation code**. It does not own test code: the test cases for the
requirements you're implementing live in `docs/design/test-plan.md` and are implemented by
`/write-tests` under their own `type:test` issue. See "The test boundary" below before
writing a test file — it is the rule most easily broken in good faith, and breaking it
produces two test suites for one requirement.

## 1. Understand (plan mode)

- Run `gh issue view $ARGUMENTS --comments` for the full issue including comments.
- Read the issue's **Goal** line first. That single sentence is what the PR is judged
  against, by a human reviewer and by the `reviewer` subagent. If the Goal is missing or
  vague, stop and say so rather than inferring one — an issue without a checkable goal
  produces a PR nobody can review, and the fix belongs upstream in `/plan-to-issues`.
- Note the **Traces to** IDs. Open `docs/design/detailed-design.md` at those `FR-*`/`NFR-*`
  sections for the interface and data-structure specifics, and `docs/design/test-plan.md`
  at the matching `TC-*` cases so you know what will be asserted about your code.
- If the issue body has a `Depends on: #N` line, confirm each referenced issue is closed
  (`gh issue view <n> --json state`). This shouldn't normally trigger — whatever dispatched
  you should only hand you unblocked work — but if a dependency is still open, stop and
  report it rather than building on an interface that might still change.
- Enter plan mode if you aren't already in it. Read the relevant code paths. Do not edit
  anything yet.
- Write a short plan: which files change, what the change is, what could break, and how
  you'll verify it — which existing tests cover it, or (per the boundary below) which
  regression test you'll add.
- If the issue is ambiguous, or the change touches more than a couple of files, consult the
  advisor before committing to the plan (`/advisor opus` if one isn't already configured).

## 2. Implement

Exit plan mode and make the change. Implement to the design's stated interface — the exact
signatures, field names, status codes, and error types in `detailed-design.md` — because
the tests written from the test plan assert against that interface, not against whatever
you find natural. A story that works but renames a field breaks a test suite that was
correct.

### The test boundary

- **The `TC-*` cases for this requirement are `/write-tests`' work, not yours.** Don't
  write them "while you're in there." Two suites for one requirement, in two styles,
  asserting slightly different things, is the outcome — and the second one to arrive
  usually gets deleted along with a case the first one missed.
- **Exception: a defect fix with no existing `TC-*` coverage.** Then write the regression
  test inline — that is what a regression test *is*, and deferring it to another issue
  means shipping a fix nothing pins. Two obligations come with it: the test must fail
  against the unfixed code (verify that, don't assume it), and you add the new case to
  `docs/design/test-plan.md` in the same PR. A test in the repo but not in the plan is how
  the plan starts lying about what's covered.
- **If a test that should exist doesn't**, and this isn't a defect fix, say so in the PR
  body and check whether the paired `type:test` issue is still open. Don't fill the gap
  silently — a missing test issue is a planning bug worth surfacing.

## 3. Verify (loop until it's actually green)

- Run the project's test command (`TEST_CMD` in `.claude/settings.json`). If `TEST_CMD` is
  empty, the project has no suite yet — say so explicitly in the PR rather than implying
  the change was verified.
- If it fails, fix the root cause — not the symptom — and run it again. Repeat until it
  passes. Show the passing output as evidence; don't just assert success.
- **If the paired `type:test` issue hasn't landed yet**, the suite won't cover your change.
  Verify against the issue's acceptance criteria directly and say in the PR that automated
  coverage is pending on that issue, naming it. Don't let "the suite is green" stand in for
  "this works" when the suite doesn't test it.
- `.claude/hooks/verify.sh` also enforces this as a Stop hook if you try to end the turn
  with uncommitted changes and a failing test command — but verify explicitly yourself
  rather than relying on it to catch you.

## 4. Adversarial review

- Use the `reviewer` subagent to review your diff against the issue's **Goal and acceptance
  criteria** and the plan from step 1. Give it the issue and the plan, not your reasoning
  about the implementation.
- Fix anything it flags that affects correctness or a stated requirement. Treat style
  nitpicks as optional.

## 5. Ship

- Commit with a descriptive message referencing the issue (e.g. "Fixes #123").
- Push a branch and open a PR with `gh pr create`, summarizing the change, how it was
  verified, the `FR-*` IDs it implements, and any coverage still pending on a test issue.
