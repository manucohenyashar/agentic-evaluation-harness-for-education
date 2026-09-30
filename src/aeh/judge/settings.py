"""The prompt version and the environment knobs that tune judging."""

from __future__ import annotations


# --- vocabulary ----------------------------------------------------------------------------------

#: The version the prompt template renders under (`§3.10 Configuration`; the extract
#: module's `EXTRACTION_PROMPT_TEMPLATE_VERSION` precedent). The run's
#: `prompt_template_v` is the CALLER's declared value of this version and is already an
#: input to `work_id` (`FR-ORCH-01`), so a template change invalidates dependent work
#: through the id — this constant is what the render is actually built from, and the
#: fixture contract keys on it (a fixture recorded against an old render misses rather
#: than mis-replays). Changing the render changes this string, in the same change.
JUDGE_PROMPT_TEMPLATE_V = "judge-prompt/2"


#: The strike budget's env knob (`FR-JUDGE-10`): production default three, adjustable
#: per environment without a code change — the third seam. Read at call time, like
#: every knob here.
MAX_ATTEMPTS_ENV = "HARNESS_JUDGE_MAX_ATTEMPTS"


#: The sampling temperature's knob (§3.10 Configuration: `JUDGE_TEMPERATURE`,
#: Assumption 0). Judgment is a temperature-zero task; the knob exists so an
#: environment can move it without a code change — and because the fixture key is the
#: render plus the parameters, a moved knob moves the key (a recorded fixture misses
#: rather than mis-replays). Read at call time. NOT a determinism guarantee
#: (CT-JUDGE-15's wording).
TEMPERATURE_ENV = "HARNESS_JUDGE_TEMPERATURE"


JUDGE_TEMPERATURE = 0.0


#: The output cap's knob (§3.10 Configuration: `JUDGE_MAX_OUTPUT_TOKENS`, Assumption
#: 400). SHIPPED DEFAULT: unset — no explicit cap is sent, and the backend's own
#: default governs. Disclosed reason: the provider fixture key is the fully-assembled
#: request (CT-PROV-05), so an always-on cap would move every recorded key away from
#: the render the tests record; the knob carries the design's assumed value where an
#: environment wants it. Set to a positive integer to cap; there is no unset-and-zero
#: conflation (a zero override refuses, the `_env_int` posture).
MAX_OUTPUT_TOKENS_ENV = "HARNESS_JUDGE_MAX_OUTPUT_TOKENS"


#: The exemplar-order salt's knob (`FR-JUDGE-08`): the permutation of a criterion's
#: exemplars is keyed on (question, criterion) plus this salt, so the order is fixed
#: within a batch and differs across batches while staying reproducible for fixture
#: recording. Read at call time.
EXEMPLAR_SEED_ENV = "HARNESS_JUDGE_EXEMPLAR_SEED"


_EXEMPLAR_SEED_DEFAULT = JUDGE_PROMPT_TEMPLATE_V


#: The assessment re-request's budget knob (`FR-JUDGE-10`: "rejected and re-requested
#: once, then accepted with an integrity flag"). Production default ONE — the design's
#: word — adjustable per environment without a code change, read at call time like every
#: knob here. The re-request is NOT a replay: a re-issued identical payload would
#: re-sample a verdict, which `FR-PROV-06` forbids on any path that got a parseable
#: reply — so the re-request goes out with an AMENDED prompt (`_amended_payload`: the
#: assessment ground-rules correction inserted before the final submission field), a
#: different fully-assembled request and therefore a different fixture key (`CT-PROV-05`)
#: and a different call in the `FR-PROV-06` sense. A prose-only reply that recurs after
#: the amendment budget is spent is an ordinary strike toward the main budget
#: (`MAX_ATTEMPTS_ENV`), whose exhaustion quarantines the unit (`NFR-JUDGE-05`) — never
#: a fallback band.
ASSESSMENT_RETRIES_ENV = "HARNESS_JUDGE_ASSESSMENT_RETRIES"


ASSESSMENT_RETRIES_DEFAULT = 1


#: The integrity flag's name (`FR-JUDGE-10`'s "accepted with an integrity flag"): set on
#: a `ScoringResult.integrity_flags` exactly when the accepted verdict's dispatch used at
#: least one assessment amendment re-request. Stage-level observability next to the
#: outcome (`CT-INGEST-08`'s per-gate shape), so a downstream consumer can see — without
#: re-reading the prompt log — that this verdict's assessment was re-requested before it
#: was accepted.
ASSESSMENT_AMENDED = "assessment_amended"
