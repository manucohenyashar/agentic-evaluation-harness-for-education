# fixtures/F-AUTHOR/recordings -- captured, not generated

The model replies a complete authoring run asks for, in the single-tree shape the other
recording corpora use (`F-DEV-PIPE/recordings/`): one JSON document per `request_key`, named
`sha256-<hex>.json`, schema `aeh.prov/fixture/1`, written by `RecordedFixtureProvider`'s
`record()` half during a real run with `HARNESS_FIXTURE_DIR` pointing at this directory.
Coverage.json indexes the same keys in the `sha256:...` form; the files are written with a
dash (`sha256-<hex>.json`) because a colon is not legal in a filename on Windows.

The keys are sha256 over the assembled request, **including the prompt templates -- so they
do not exist until M-AUTHOR's prompts exist**. A recording captured before its prompt is a
key that no request will ever ask for. They are captured by the implementing stories
(#690 onward), once, from a live run.

Alongside the recordings sits `coverage.json`, written by the same capture pass:

    {"fallback_exercises": ["sha256:...", ...], "placeholder_exercises": ["sha256:...", ...]}

It names the recordings that exercise the two paths the double-honesty rule (test-plan §4.2)
demands: a **failing head-of-chain reply** (the fallback path must not need a live flake to
be exercised) and the **placeholder path** (an unresolved item). TC-AUTHOR-28's honesty
census refuses a corpus whose recordings replay successes only.

## The console-redesign capture pass (AF-14, AF-17, AF-21; issue #773)

The intake fixtures' recordings were captured on 2026-10-14 by the committed script
`scripts/capture_authoring_recordings.py`, one invocation per fixture, from a live
`dev-ci` run (the key comes from the operator's `Code/.env-dev`; no `HARNESS_FIXTURE_DIR`
is set — the boundary records every reply the live backend answers and nulls its cost,
CT-PROV-03). The commands, from the repository root:

    python scripts/capture_authoring_recordings.py         --docs fixtures/F-AUTHOR/AF-14/hist7-rome-01-test-and-grading.docx         --out %TEMP%f14-capture      # TC-E2E-08's journey: 6 recording(s)
    python scripts/capture_authoring_recordings.py         --docs fixtures/F-AUTHOR/AF-17/hist6-great-fire-01-prose-test.txt         --out %TEMP%f17-capture      # TC-E2E-09's journey: 5 recording(s)
    python scripts/capture_authoring_recordings.py         --docs fixtures/F-AUTHOR/AF-21/mus8-instruments-01-test.docx                fixtures/F-AUTHOR/AF-21/mus8-instruments-01-marking-memo.txt                fixtures/F-AUTHOR/AF-21/hist7-rome-01-test-and-grading.txt         --out %TEMP%f21-capture      # TC-E2E-11's journey: 9 recording(s)

**The build pin is not the older qwen pin.** These recordings key on
`openai/gpt-6-luna@2026-06-01` (`tests.support.console_journeys.JOURNEY_AUTHORING_BUILD`),
the vendor-qualified build the live-test configuration moved to, minus the `openrouter/`
transport prefix the dev-ci chain carries inside its build ids. This account's guardrails
remove every Qwen endpoint at the zero-retention routing ("Model bloc", verified by
dispatch on 2026-10-14); the AF-01..13 recordings keep their qwen keys and the tests that
replay them keep the old constants — the two pins coexist, each key hashing the build it
was captured under. The journeys render the identical string through the shared module, so
a replay asks for exactly the keys captured here. A future canonical re-capture (keying on
dev-ci's full build id) would let these recordings also serve replays that ride the dev-ci
chain itself — TC-AUTHOR-38's capture guard (`tests/support/impl.py`'s
`_INTAKE_CAPTURE_PROBE`) is the check that fires when that lands.

**A disclosed capture divergence (finding, not a fix).** The captured chains for AF-17 and
AF-21 leave grade-boundary placeholders their `expected.toml` contracts do not declare
(`placeholders = []`): the capture model read AF-17's "a D is less" and AF-21's merged
grade tables as boundaries not numerically stated, and the extraction never invents one
(FR-AUTHOR-08). AF-14's capture satisfies its contract exactly. The journeys fill those
boundaries at the review walk — the teacher action that walk exists for — and disclose the
divergence in their docstrings; the corpus's generated `expected.toml` was left untouched
for the corpus owner to decide on.
