# fixtures/F-AUTHOR -- the authoring fixture corpus (TC-AUTHOR-28)

Twenty-three teacher test descriptions, `AF-01`..`AF-23`, one directory each: the documents a
teacher would hand a colleague, plus an `expected.toml` stating the **outcome class** the
tests assert -- which items resolve, which placeholder, whether the build publishes or is
refused. AF-01..AF-13 are the package-authoring delta's §5.1 matrix; AF-14..AF-21 are the
console-redesign delta's §5.1 intake matrix (built by #753 ahead of the intake tier, #754);
AF-22/AF-23 are the console-clarity variants of the ENG7 sample test (#812): its four PDFs,
rendered by `docs/live-tests/sample-materials/build_sample_materials.py`, with the rubric's
grade table left out (AF-22) or naming *pass* with no boundary (AF-23). Alongside the numbered fixtures sit the adversarial intake set (`adversarial/`) and the
roster CSVs (`rosters/`). The double-honesty rule (test-plan §4.2) lives in `recordings/`.

**Generated, not edited by hand.** Regenerate with:

    python fixtures/F-AUTHOR/build_authoring_fixtures.py

The generator is committed in this directory (the `build_sample_materials.py` pattern:
committed generator, committed outputs, stdlib only) and is byte-for-byte reproducible: a
changed PDF in a review means a changed script. The rendering itself is
`harness.corpora.pdf_writer.typed_document` (typed pages) and
`harness.corpora.scan.render_hand_page` (AF-10's scan); the intake fixtures' .docx packages,
OLE containers, and PNG part are built here with stdlib `zipfile`/`struct`/`zlib` over
deterministic content models -- nothing here reimplements the repo's readers.

This corpus is deliberately exempt from `python -m harness.corpora.build --check`
(`_IN_TREE_GENERATED_TREES` in `harness/corpora/build.py`): that check regenerates the
corpora its own module emits, and this corpus's generator lives here, not there. The pin is
TC-AUTHOR-28's census instead, which re-runs this script and diffs the bytes.

## expected.toml schema

| key | meaning |
|---|---|
| `af` | the fixture id, `AF-01`..`AF-23` |
| `description` | what the fixture exercises (§5.1's wording) |
| `documents` | the document filenames in this directory, in hand-in order |
| `outcome` | `resolved` (fully drafted), `partial` (named placeholders), `unresolved` (not converging after all attempts), `refused` (the intake refuses the hand-in, FR-AUTHOR-28) |
| `placeholders` | the placeholder fields the outcome class expects (empty when `resolved`) |
| `build` | `publishes` (once any placeholders are filled at review) or `refused` (FR-PKG-28's gate, or an intake refusal) |
| `refusal` | AF-18..AF-20 only: FR-AUTHOR-28's exact teacher sentence the intake refuses with (test plan §4.3: exact-match, so copy drift fails). Present iff `outcome = "refused"` |
| `warnings` | the `IntakeWarning` codes the outcome class requires to be present (§3.1.1's vocabulary: `image_not_carried`, `equation_not_carried`, `structure_guessed`, `formatting_dropped`, `encoding_fallback`). Presence, not exhaustiveness |
| `format` | one source format per document, aligned with `documents` (`docx` \| `txt` \| `pdf`, `NormalizedDocument.source_format`'s domain) |
| `table_rows` | AF-14 only: the rubric table's rows, carried verbatim for TC-AUTHOR-33's cell match |
| `retry_of` | AF-13 only: the fixture this re-drafts |
| `carry_over` | AF-13 only: the carry-over outcome class |
| `notes` | one line for a human |
| `[review.answers]` | the scripted review answers the publishing fixtures' drafts complete with (TC-REQ-136); item id = value, a list answers a repeated id one value per occurrence in document order. Refused fixtures (AF-09, AF-11, AF-18..AF-20) carry none |

## adversarial/ -- the refusal arms with no fixture directory

Three files whose shape belongs to no numbered fixture, each refused before any content is
read (test plan §3.1, TC-AUTHOR-37's matrix): a password-protected `.docx` (a Compound File
Binary container holding an `EncryptedPackage` stream -- what an encrypted docx actually
is), a `.rtf` (outside the three formats), and real PDF bytes under a `.docx` name. Their
`adversarial/expected.toml` is a different, smaller schema: one `[[file]]` table per entry
naming `name`, `looks_like`, and the exact `refusal` sentence.

## rosters/ -- class lists (TC-CONSOLE-65's inputs)

`console-world-3-students.csv` carries the `console_world` seed cohort's three students
(`c-ts48`, refs `ref-sub-c-ts48-01`..`03`), so a case written against it needs no rewrite
when the console tests land. `console-world-malformed.csv` carries the shapes that make a
roster file suspect: a duplicated name (legal to the reader -- deciding that two refs are
one student is the cohort layer's call), a row with a ref but no name (refused, naming
the line), a fully blank row (skipped), and one valid row. The names are synthetic
(`tests/support/roster.py`'s stem style) -- the corpus never carries a real name.

## What the intake fixtures do NOT carry

No recordings exist for AF-14..AF-21: the intake tier's prompts do not exist until #754
lands, and a recording captured before its prompt is a key no request will ever ask for.
The implementing stories capture them, once, from a live run (see `recordings/README.md`).
AF-22 and AF-23 carry none either: their drafting replies are captured from the live ENG7
walk (console-clarity TC-E2E-14, `record=True`), never fabricated, so the recorded
build-gate walk (TC-REQ-136) skips them until that capture lands.
The oversize refusal arm (FR-AUTHOR-28's 10 MB sentence) has no committed fixture either:
its tests generate the oversize file through the `HARNESS_AUTHOR_DOC_MAX_BYTES` knob.

The recorded tier replays exact content through `RecordedFixtureProvider`; the live tier
(`@live`, real OpenRouter) asserts these outcome classes -- **never exact wording**: two runs
of a real model agree on structure, not prose (CT-AUTHOR-17's non-promise). The one exact
wording the corpus does pin is the refusal table: FR-AUTHOR-28's sentences are the
teacher-facing copy the design table states verbatim, so a test asserts them exactly.
