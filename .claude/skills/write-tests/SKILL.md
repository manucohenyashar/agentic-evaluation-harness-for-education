---
name: write-tests
description: Implement the test cases described in a type:test issue, following the same plan, implement, verify, review, ship loop as fix-issue.
disable-model-invocation: true
---

Implement the test cases described in issue: $ARGUMENTS. This mirrors `/fix-issue`, but the
deliverable is test code written from the test plan, not a feature.

This skill owns **test code**. `/fix-issue` implements the production code and does not
write these tests — so if a case in this issue looks like it's already covered by a test
someone added alongside the implementation, that's a duplication worth reporting rather
than quietly working around.

## 1. Understand (plan mode)

- Run `gh issue view $ARGUMENTS --comments`.
- Read the issue's **Goal**, **Traces to** (`TC-*` IDs), **Test level**, **Isolation**, and
  the **test cases table**. Then open `docs/design/test-plan.md` at those TC IDs and read
  the full specifications — preconditions, concrete input values, the oracle, and the
  expected result. The issue carries the summary; the plan carries the detail, and the
  detail is what makes the difference between a test that asserts something and a test that
  merely runs.
- **Check `Written ahead of implementation:`** in the issue body. This decides what a
  failing test means, and it is stated rather than inferred:
  - **`no`** — the code exists (or lands under the issue named in `Depends on:`). Your
    tests are expected to pass. Treat a failure as a bug in your test, or a real bug worth
    flagging — never weaken an assertion to make it green.
  - **`yes`** — you're writing tests against the design's interface before the code exists.
    It's expected that they fail, or don't compile against a not-yet-written interface.
    Write them against the interface in `docs/design/detailed-design.md` and say so
    explicitly in the PR.
  - If the field is missing, fall back to the dependency line — a `Depends on:` pointing at
    an implementation story means `no` — and note in the PR that the issue was missing the
    field, so `/plan-to-issues` gets fixed.
- If there's a `Depends on: #N` line, check whether that issue is closed
  (`gh issue view <n> --json state`) — it tells you whether the code you're testing exists
  yet.
- Enter plan mode. Read the repo's existing test conventions: framework, fixtures, naming,
  directory layout. Write a short plan covering which TC IDs you'll implement, what
  fixtures or test doubles you need, and which of the two cases above applies.

## 2. Implement

- Exit plan mode and write the tests.
- **One test per TC ID**, named so a failure report identifies the case without opening the
  file. Reference the TC ID in the test name or a comment so the RTM stays navigable from
  the code.
- **Honor the isolation rung the plan specifies.** A case specified at rung 2 (real
  containerized dependency) is not satisfied by a mocked version — the mock is what that
  case exists to check *past*. If the rung isn't achievable in this repo yet, say so in the
  PR rather than silently substituting a weaker one.
- **Honor the oracle.** Where the plan names a property, metamorphic relation, or
  statistical threshold, implement that — don't downgrade it to an assertion that the call
  returned non-null. A test whose oracle is weaker than specified passes in cases the plan
  intended it to fail.
- Follow the repo's existing test structure and naming. Don't introduce a second test
  framework or a different pattern than what's already there.

## 3. Verify

- Run the test command (`TEST_CMD` in `.claude/settings.json`).
- **If the implementation exists**, the new tests must pass — loop until they do.
- **If it doesn't exist yet**, confirm the tests at least run and fail for the *right*
  reason: a clear assertion failure or "not implemented" error, not a crash on a syntax
  error or a missing import. A test that fails because it doesn't compile proves nothing
  and will be "fixed" later by someone who doesn't know what it was meant to assert.
- Check the suite is order-independent if the framework makes that easy to check. Tests
  that pass in order and fail when shuffled are hiding shared state.

## 4. Adversarial review

Use the `reviewer` subagent to check that the tests actually exercise the requirements in
the issue and the plan, not merely that they execute. Give it the issue and the TC
specifications. The specific question worth asking it: *would each of these tests fail if
the behavior it names were wrong?*

## 5. Ship

- Commit and open a PR referencing the issue, e.g. "Adds tests for #123", listing the TC
  IDs implemented.
- Only use a closing keyword ("Fixes #123") if the tests pass. If they're intentionally red
  pending implementation, reference the issue **without** closing it and explain why in the
  PR body — this also keeps anything that depends on this test issue correctly blocked
  until it's genuinely done.
- If you found a TC case you couldn't implement as specified (unavailable isolation rung,
  missing fixture data, an oracle the repo can't express yet), say so in the PR and name
  the TC ID. An unimplementable test case is a finding about the plan, and swallowing it
  makes the RTM claim coverage that doesn't exist.
