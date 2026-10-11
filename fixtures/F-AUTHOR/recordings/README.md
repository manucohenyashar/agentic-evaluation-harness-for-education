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
