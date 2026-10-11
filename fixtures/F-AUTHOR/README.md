# fixtures/F-AUTHOR -- the authoring fixture corpus (TC-AUTHOR-28)

Thirteen teacher test descriptions, `AF-01`..`AF-13`, one directory each: the documents a
teacher would hand a colleague, plus an `expected.toml` stating the **outcome class** the
tests assert -- which items resolve, which placeholder, whether the build publishes or is
refused. The matrix is design delta §5.1; the double-honesty rule (test-plan §4.2) lives in
`recordings/`.

**Generated, not edited by hand.** Regenerate with:

    python fixtures/F-AUTHOR/build_authoring_fixtures.py

The generator is committed in this directory (the `build_sample_materials.py` pattern:
committed generator, committed outputs, stdlib only) and is byte-for-byte reproducible: a
changed PDF in a review means a changed script. The rendering itself is
`harness.corpora.pdf_writer.typed_document` (typed pages) and
`harness.corpora.scan.render_hand_page` (AF-10's scan) -- nothing here reimplements it.

This corpus is deliberately exempt from `python -m harness.corpora.build --check`
(`_IN_TREE_GENERATED_TREES` in `harness/corpora/build.py`): that check regenerates the
corpora its own module emits, and this corpus's generator lives here, not there. The pin is
TC-AUTHOR-28's census instead, which re-runs this script and diffs the bytes.

## expected.toml schema

| key | meaning |
|---|---|
| `af` | the fixture id, `AF-01`..`AF-13` |
| `description` | what the fixture exercises (§5.1's wording) |
| `documents` | the PDF filenames in this directory, in hand-in order |
| `outcome` | `resolved` (fully drafted), `partial` (named placeholders), `unresolved` (not converging after all attempts) |
| `placeholders` | the placeholder fields the outcome class expects (empty when `resolved`) |
| `build` | `publishes` (once any placeholders are filled at review) or `refused` (FR-PKG-28's gate) |
| `retry_of` | AF-13 only: the fixture this re-drafts |
| `carry_over` | AF-13 only: the carry-over outcome class |
| `notes` | one line for a human |

The recorded tier replays exact content through `RecordedFixtureProvider`; the live tier
(`@live`, real OpenRouter) asserts these outcome classes -- **never exact wording**: two runs
of a real model agree on structure, not prose (CT-AUTHOR-17's non-promise).
