# Issue Templates

The exact body format for every issue `/plan-to-issues` creates. These are the contract
between the planning documents and the implementation skills: `/fix-issue` and
`/write-tests` plan against these fields, and the `reviewer` subagent checks diffs against
the Goal and acceptance criteria. An issue missing them produces an agent run that has to
guess, and guessing is where scope drift starts.

Two templates — story and test — plus the sizing check that applies to both.

---

## `type:story` — implementation work

```markdown
**Goal:** <one sentence, checkable. The single thing a reviewer verifies the PR against.>

**Traces to:** FR-AUTH-01, NFR-AUTH-02
**Module:** M-AUTH
**Written from:** docs/design/detailed-design.md §3.2

As a caller of the Auth Service, I want a signed JWT issued on valid credentials, so that
downstream services can verify identity without re-checking passwords.

*(For internal work with no user-facing angle, state it directly instead of forcing the
"as a…" form: "The Auth Service shall issue a signed JWT on valid credentials.")*

**Acceptance criteria**
- [ ] Given valid credentials, when `POST /auth/login` is called, then a JWT is returned with a 15-minute expiry
- [ ] Given invalid credentials, when `POST /auth/login` is called, then HTTP 401 is returned with no token
- [ ] Given 6 attempts from one IP inside a minute, when the 6th arrives, then HTTP 429 is returned

At least one criterion must be a failure or edge path. A story whose criteria are all happy
paths will be implemented as a happy path.

**Technical notes**
- Endpoint: `POST /auth/login` — request `{email, password}`, response `{token, expires_at}`
- Sign with RS256; private key from the secrets manager, never from config
- Rate limit 5 attempts/min/IP (NFR-AUTH-02)
- Entities touched: `Session`, `Credential` (detailed-design §3.2 data model)

Restate the specifics here rather than writing "see detailed design §3.2". This section is
what saves an implementer — human or agent — a trip back to the design doc, and an agent
that has to go find the design doc will read more of it than it needs and drift.

**Evaluation strategy**
How a reviewer or the `reviewer` subagent confirms this is actually done: which tests are
expected to cover it (`TC-AUTH-01`, `TC-AUTH-02`), what to run, what to inspect manually if
anything.

**Definition of done**
- [ ] Acceptance criteria pass
- [ ] `TEST_CMD` passes
- [ ] `reviewer` subagent findings on correctness addressed
- [ ] Observability from the design implemented (login attempts and failures logged)

**Depends on:** #12, #34
```

Omit the `Depends on:` line entirely when there are no dependencies. Never write
`Depends on: none` or a story title — `scripts/ready-issues.sh` parses `#`-numbers, and a
line it can't parse is a line that reports the issue as malformed rather than ready.

---

## `type:test` — test implementation work

```markdown
**Goal:** <one sentence: what this test suite proves.>

**Traces to:** TC-AUTH-01, TC-AUTH-02, TC-AUTH-03 (covering FR-AUTH-01, FR-AUTH-02)
**Module:** M-AUTH
**Written from:** docs/design/test-plan.md §5.1
**Test level:** Unit
**Isolation:** Rung 0 — clock stubbed, no I/O
**Written ahead of implementation:** no

**Test cases to implement**

| TC ID | Behavior | Technique | Oracle | Priority |
|---|---|---|---|---|
| TC-AUTH-01 | Issues a JWT with 15-minute expiry on valid credentials | Happy path | Exact expected claims | P0 |
| TC-AUTH-02 | Rejects an expired token with 401 | Boundary (1s past expiry) | Exact status + error type | P0 |
| TC-AUTH-03 | Rejects a token signed with the wrong key | Negative | Exact error type | P0 |

Copy the specifics from the test plan — preconditions, concrete input values, the oracle,
and the expected result — rather than paraphrasing them. A test issue that says "test the
auth module" gets a test suite that executes the auth module and asserts very little.

**Evaluation strategy**
The suite must fail if the behavior under test is wrong, not merely run. Where the test
plan named an oracle other than an exact expected value (property, metamorphic,
statistical), state it here so the implementer doesn't silently downgrade it to
`assertNotNull`.

**Definition of done**
- [ ] Every listed TC ID has a corresponding test
- [ ] Tests follow the repo's existing framework and naming
- [ ] Suite state matches the "written ahead of implementation" flag (see below)
- [ ] `reviewer` subagent confirms the tests exercise the requirements, not just execute

**Depends on:** #12
```

### The `Written ahead of implementation` field

This is the field that tells `/write-tests` which of its two modes it is in, and it must be
stated rather than inferred:

- **`no`** — the implementation exists or is being built under the issue named in
  `Depends on:`. The tests are expected to pass. A failure is a bug in the test or a real
  bug worth reporting, never a reason to weaken an assertion.
- **`yes`** — tests are written against the design's interface before the code exists. They
  are expected to fail, and the PR references the issue without closing it. Such an issue
  has **no** `Depends on:` line; that is what makes it schedulable immediately and is the
  whole reason the code and test tracks can run in parallel.

Source this from the test plan's §8.2 story table, which already carries the column.

---

## Sizing check — apply to both types

Before creating an issue, confirm it is **INVEST**-shaped:

- **I**ndependent — as much as its dependency list allows
- **N**egotiable — describes what, not a rigid how
- **V**aluable — someone can say why it matters
- **E**stimable — enough detail to size
- **S**mall — one focused implementation session, one reviewable PR
- **T**estable — acceptance criteria are checkable, not vibes

The practical test for **Small**: could one agent run complete this without mid-story
clarification, and would the resulting diff be reviewable in one sitting? A story spanning
six modules fails both.

**Sizing is inherited, not re-decided.** The test plan sized the test stories (§8.2) and the
design's module graph ordered the code stories. If a story genuinely fails the sizing check,
split it and record the split in both resulting issues — but treat that as a finding worth
reporting back, because it means the planning documents under-decomposed and the next run
will make the same mistake.

---

## Gherkin, briefly

**Given** sets up state, **When** is the single action under test, **Then** is the
observable, checkable outcome. One action per scenario — a criterion with two `When`s is two
criteria. Write at least one failure-path scenario per issue; happy-path-only acceptance
criteria are how a story passes review while the feature is broken in the branch nobody
wrote a criterion for.
