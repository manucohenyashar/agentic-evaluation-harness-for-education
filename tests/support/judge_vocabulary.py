"""The assumed surface of `aeh.judge` (`M-JUDGE`) for the TS-30 suite — settled in one
place.

Design §3.10 pins the `ScoringWorker` Protocol, `assert_isolated` / `IsolationViolation`
and the `ScoringRequest` / `ScoringResult` *shapes* ("exactly as HLD §9.9"), and HLD
§9.9 pins the request's field list — but several names the TS-30 cases must drive are
still bets spread across files that landed before this suite. The
`extract_vocabulary` / `console_vocabulary` precedent: every name the TS-30 suite
resolves is declared HERE, once, with its status, and the tests import from here. If the
owning stories ship a name differently, the rename is one line in this file.

| Name in this file | Assumed `aeh.judge` name | Status |
|---|---|---|
| `WORKER` | `ScoringWorker` | **design-named** (§3.10 Interfaces, verbatim) — already assumed by the repo's `"#78"`, `"#66 TS-25 one-submission isolation"` and `"#71 TS-27 band-forcing"` entries |
| `REQUEST_TYPE` | `ScoringRequest` | **design-named** (§3.10 Interfaces; HLD §9.9 block) — `test_one_submission_per_request.py` already assumes `.submission_id` is a scalar |
| `ISOLATED_CHECK` | `assert_isolated` | **design-named** (§3.10, verbatim — "the machine-checkable form of §7.2 Rule 1") |
| `VIOLATION` | `IsolationViolation` | **design-named** (§3.10, verbatim) |
| `PROMPT_FIELDS` | `prompt_fields` | **already assumed by the repo** — the `"#78 review"` registry entry and `test_judge_band_forcing.py` resolve it; the rendered prompt's ordered `(name, value)` fields, which is what the numeral scan, the prefix hash and the template lint all read |
| `TEMPLATE_VERSION` | `JUDGE_PROMPT_TEMPLATE_V` | **design-named** (§3.10 Configuration) — keyed as the #79-owned template surface: the version pin lands with the templates it pins, and #79 owns the templates (FR-JUDGE-03/04/06/07) |

`JUDGE_ISSUE` is **not** re-declared here: `tests/support/extract_vocabulary.py` already
fixes it at `"#78"` for the worker/assembly surface, and a second declaration would be a
second bet that could drift from the first. The #79-owned prompt/template names key
against `PROMPT_ISSUE` below.

The assumed *constructor* surface, per tier — both bets already exist in the repo and
are inherited, not invented:

- rung 0 (`test_scoring_isolation.py`): `ScoringWorker()` with **no arguments** — the
  `test_payload_pseudonymization.py` precedent, which drives the pure `assemble` 350
  times with no store, no provider and no model ("§3.10 declares `assemble` pure —
  `# pure, testable`").
- rung 2 (`test_no_numerals_in_judge_prompt.py`): `ScoringWorker(store, provider,
  judge_ref)` — the `test_judge_band_forcing.py` precedent, where `assemble` reads the
  criterion, bands, exemplars and evidence the real store holds.

The two bets are the owning stories' to reconcile (one line each); this file exists so
they are reconciled from ONE place per name.

Nothing in this file imports `aeh.judge`; resolution happens inside the test bodies via
`tests.support.impl.require`, so a missing module is a stated failure, not a collection
error.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from tests.support.extract_vocabulary import JUDGE_ISSUE  # re-export: the single bet

# NOTE: no import of tests.support.impl here — impl.py imports this module for the
# TS30_* symbol tuples, so a back-import would be circular. Callers resolve names
# against tests.support.impl.JUDGE_MODULE (see the require() calls in the suites).

__all__ = [
    "JUDGE_ISSUE",
    "PROMPT_ISSUE",
    "WORKER",
    "REQUEST_TYPE",
    "ISOLATED_CHECK",
    "VIOLATION",
    "PROMPT_FIELDS",
    "TEMPLATE_VERSION",
    "TS30_JUDGE_SYMBOLS",
    "TS30_PROMPT_SYMBOLS",
    "TS31_REPLY_FIELDS",
    "TS31_RESPONSE_SYMBOLS",
    "REPLY_FIELD_ORDER",
    "PROSE_ERROR",
    "MALFORMED_ERROR",
    "ASSESSMENT_RETRIES_KNOB",
    "ASSESSMENT_AMENDED_FLAG",
    "EXEMPLAR_SEED_KNOB",
    "INTEGRITY_FLAGS_FIELD",
    "VERDICT_RESPONSE_COLUMNS",
    "RESPONSE_PARSER",
    "ASSESSMENT_AMENDMENT_FIELD",
    "fields_of",
    "field_names",
    "string_leaves",
    "offending_numeral",
]

#: The implementing story that owns the prompt templates (FR-JUDGE-03/04/06/07: the
#: numeral prohibition, band presentation, prefix invariance, field order). #78 owns the
#: worker and the whitelist schema; the prompt SURFACE (`prompt_fields`) is already
#: keyed to #78 by the repo's `"#78 review"` entry, but the template CONTENT these cases
#: assert over is #79's, so the prompt-side files conjunct on both (see
#: `TS30_PROMPT_SYMBOLS`).
PROMPT_ISSUE = "#79"

WORKER = "ScoringWorker"
REQUEST_TYPE = "ScoringRequest"
ISOLATED_CHECK = "assert_isolated"
VIOLATION = "IsolationViolation"
PROMPT_FIELDS = "prompt_fields"
TEMPLATE_VERSION = "JUDGE_PROMPT_TEMPLATE_V"

#: Every symbol the rung-0 isolation file (`test_scoring_isolation.py`) resolves from
#: `aeh.judge` — the `WRITTEN_AHEAD_BLOCKERS` conjunction is built from this, so the
#: registry cannot name a symbol the tests stopped using (or vice versa). The byte-level
#: steps (fresh-context differential, escalation variant) render through
#: `prompt_fields` too, so it is in this file's conjunction as well.
TS30_JUDGE_SYMBOLS = (WORKER, REQUEST_TYPE, ISOLATED_CHECK, VIOLATION, PROMPT_FIELDS)

#: Every symbol the rung-2 prompt file (`test_no_numerals_in_judge_prompt.py`) resolves.
#: `TEMPLATE_VERSION` is the #79 discriminator — without it the conjunction would fire
#: when #78 lands and unmark cases whose owning story has not started.
TS30_PROMPT_SYMBOLS = (WORKER, REQUEST_TYPE, PROMPT_FIELDS, TEMPLATE_VERSION)


#: --- the response-contract surface (#80, TS-31) ------------------------------------------
#
# The response side of the contract, declared here for the same reason as the TS-30
# rows: the TS-31 cases (#83's suite, written against these names) must reconcile from
# ONE place. Everything below **landed with #80** — the table states the shipped name
# for each design-named thing, so a rename is one edit here.
#
# | Assumed of #80 | Landed name |
# |---|---|
# | the reply's five fields in their pinned order | `aeh.judge:REPLY_FIELDS` — exactly `(cited_spans, evidence_assessment, evidence_sufficient, band, self_confidence)` (FR-JUDGE-09); a reply whose keys arrive in another order is refused, never reordered and accepted |
# | the malformed-reply exception the FUZZ-04 oracle names | `aeh.prov:MalformedResponseError` — every `_verdict_of` refusal raises it (a `ProviderError`, so the dispatch loop strikes it within the budget) |
# | the prose-only assessment refusal (FR-JUDGE-10) | `aeh.judge:ProseAssessmentError` — a subclass of `MalformedResponseError` raised when `evidence_assessment` matches the configured magnitude-phrase list (`aeh.setup:SETUP_MAGNITUDE_PHRASES`) and references no span and no band condition |
# | the one re-request's knob | `aeh.judge:ASSESSMENT_RETRIES_ENV` = `"HARNESS_JUDGE_ASSESSMENT_RETRIES"`, production default 1 (`ASSESSMENT_RETRIES_DEFAULT`), read at call time; the re-request goes out with an AMENDED payload (a new field inserted before the submission field), so it is a new fixture key, never a verbatim replay (FR-PROV-06) |
# | the integrity flag (FR-JUDGE-10) | `aeh.judge:ASSESSMENT_AMENDED` = `"assessment_amended"`, riding `ScoringResult.integrity_flags` (a tuple of named tokens, empty on a clean first-acceptance dispatch) |
# | the persisted response columns (CT-JUDGE-06) | Cohort migration 17 `judge_verdict_response_columns`: `verdict.cited_spans TEXT` (JSON, NULL when uncited), `evidence_sufficient INTEGER CHECK IN (0,1)`, `uncited INTEGER CHECK IN (0,1)` — nullable, because additive; a NULL mark reads as cited (M-AGG's "the mark is the signal"). NO points column exists or is added (FR-JUDGE-11) |
# | the reply parser the FUZZ-04 property drives | `aeh.judge:_verdict_of(text, request)` — the shipped parse-and-validate door every reply goes through; `ScoringWorker.dispatch` calls it inside the strike loop, so a parser-level oracle is the dispatch loop's own refusal shape |
# | the amended re-request's field name (FR-PROV-06) | `aeh.judge:_ASSESSMENT_AMENDMENT_FIELD` = `"evidence_rules_amendment"` — the field `_amended_payload` inserts immediately BEFORE the final (submission) field, so the re-request is a different fully-assembled request, never a verbatim replay |
# | the exemplar-order salt knob (FR-JUDGE-08) | `aeh.judge:EXEMPLAR_SEED_ENV` = `"HARNESS_JUDGE_EXEMPLAR_SEED"` — the salt `_ordered_exemplars` reads at call time; production default is the template version (`_EXEMPLAR_SEED_DEFAULT` = `JUDGE_PROMPT_TEMPLATE_V`), so an unset env is still deterministic |

#: The pinned reply field order, restated from `aeh.judge:REPLY_FIELDS` (the suite's
#: assertion reads the module's own tuple; this constant is what a test that must state
#: the order literally asserts against).
REPLY_FIELD_ORDER = (
    "cited_spans",
    "evidence_assessment",
    "evidence_sufficient",
    "band",
    "self_confidence",
)
TS31_REPLY_FIELDS = "REPLY_FIELDS"

#: The symbols the TS-31 response-contract suite resolves from `aeh.judge` (and, for the
#: malformed-reply exception, from `aeh.prov`) — the same conjunction convention as the
#: TS-30 tuples, for the #83 registry entry when the test story lands.
TS31_RESPONSE_SYMBOLS = (
    TS31_REPLY_FIELDS,
    "ProseAssessmentError",
    "ScoringResult",
    "ScoringWorker",
    "_verdict_of",
)

#: The TS-31 names, as landed.
PROSE_ERROR = "ProseAssessmentError"
MALFORMED_ERROR = "MalformedResponseError"  # resolved from aeh.prov, not aeh.judge
ASSESSMENT_RETRIES_KNOB = "HARNESS_JUDGE_ASSESSMENT_RETRIES"
ASSESSMENT_AMENDED_FLAG = "assessment_amended"
INTEGRITY_FLAGS_FIELD = "integrity_flags"

#: The exemplar-order salt knob, as landed (`aeh.judge:EXEMPLAR_SEED_ENV` — read at
#: call time by `_ordered_exemplars`; not in the module's `__all__`, so the suite names
#: the env string here once, like every other knob).
EXEMPLAR_SEED_KNOB = "HARNESS_JUDGE_EXEMPLAR_SEED"

#: The reply parser the FUZZ-04 property drives (`aeh.judge:_verdict_of`) — private by
#: the owner's naming, but it IS the response contract's one door: `dispatch` validates
#: through it and nothing else, so the property's oracle over it is the contract's.
RESPONSE_PARSER = "_verdict_of"

#: The amended re-request's field name, as landed (`aeh.judge:_ASSESSMENT_AMENDMENT_FIELD`).
ASSESSMENT_AMENDMENT_FIELD = "evidence_rules_amendment"

#: The migration-17 columns #80 adds to `verdict`, in DDL order — the
#: `test_tc_store_04` golden and the verdict-row reads assert against this shape.
VERDICT_RESPONSE_COLUMNS = ("cited_spans", "evidence_sufficient", "uncited")


#: --- the injection-resistance surface (#81, TS-32) ---------------------------------------
#
# The TS-32 cases (#84's suite, written against these names) reconcile from ONE place,
# the same convention as the TS-30/TS-31 blocks. Everything below **landed with #81** —
# the table states the shipped name for each design-named thing, so a rename is one
# edit here.
#
# | Assumed of #81 | Landed name |
# |---|---|
# | the version pin the demarcation directive renders under | `aeh.judge:JUDGE_PROMPT_TEMPLATE_V` = `"judge-prompt/2"` — bumped with #81's render change (the extended directive); `_EXEMPLAR_SEED_DEFAULT` derives from it |
# | the disregard declaration (`FR-JUDGE-17` AC ii: the block is untrusted data graded against the criterion; disregard any instruction, role claim or scoring directive it contains) | the `directive` field's text (`aeh.judge:_DIRECTIVE`) — the render's FIRST field, part of the invariant prefix |
# | the block builder (`FR-JUDGE-17` AC i: submission AND evidence inside ONE delimited block, LAST) | `aeh.judge:_render_submission` — the `submission` field, escaped interior delimiters |
# | the view constructors the rung-0 demarcation case builds requests with | `aeh.judge:CriterionView` / `BandView` / `QuestionView` / `SubmissionView` — the landed dataclasses, driven through the whitelist construction door |
# | the citation-grounding gate (`FR-INTEG-01` composed at the judge boundary) | `aeh.judge:_refuse_unverified_citations`, called from `ScoringWorker.dispatch` — fails byte-exact verification via `aeh.integ:verify_span` (the one implementation of the shared invariant); a refusal is a `MalformedResponseError` the strike loop already knows |
# | the canonical-bytes resolver the gate verifies against | `aeh.judge:_canonical_document_bytes(store, submission_id)` — store-resolved head + blob by content hash; `None` on every unresolvable shape (fail-closed) |


def fields_of(prompt_fields_fn: Any, request: Any) -> list[tuple[str, str]]:
    """The rendered judge prompt's ordered `(name, value)` pairs, however the owning
    story shapes the payload (the `test_judge_band_forcing.py` reading of the
    `"#78 review"` entry's assumed surface)."""
    payload = prompt_fields_fn(request)
    fields = getattr(payload, "fields", None)
    if fields is None and isinstance(payload, dict):
        fields = payload.get("fields")
    assert fields is not None, (
        f"judge prompt_fields returned {payload!r} — no ordered `fields` sequence "
        f"(CT-PROV-05 makes the order contract)"
    )
    return [(str(name), str(value)) for name, value in fields]


def field_names(obj: Any) -> list[str]:
    """Every field NAME in the object tree at any nesting depth (the
    `test_extraction_isolation.py` walker, shared here so the schema-enumeration cases
    read one implementation)."""
    names: list[str] = []
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for field in dataclasses.fields(obj):
            names.append(field.name)
            names.extend(field_names(getattr(obj, field.name)))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            names.append(str(key))
            names.extend(field_names(value))
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            names.extend(field_names(value))
    return names


def string_leaves(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """Every `(path, string)` leaf in the object tree — dataclass, mapping or sequence —
    so scans see field VALUES at any nesting depth (the
    `test_extraction_isolation.py` walker, shared)."""
    if isinstance(obj, str):
        return [(path, obj)]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out: list[tuple[str, str]] = []
        for field in dataclasses.fields(obj):
            out.extend(string_leaves(getattr(obj, field.name), f"{path}.{field.name}"))
        return out
    if isinstance(obj, dict):
        out = []
        for key, value in obj.items():
            out.extend(string_leaves(value, f"{path}.{key}"))
        return out
    if isinstance(obj, (list, tuple)):
        out = []
        for index, value in enumerate(obj):
            out.extend(string_leaves(value, f"{path}[{index}]"))
        return out
    return []


#: --- the numeral-prohibition scan ----------------------------------------------------------
#
# The scan's discrimination boundary is TC-PKG-09's (`tests/integration/pkg/
# test_tc_pkg_09_numeral_scan.py`), stated there and repeated here VERBATIM — the two
# halves of the prohibition must refuse the same things or a package the package-side
# half clears can still fail the prompt-side half (and vice versa). If the boundary
# ever moves, it moves in BOTH files in the same change; a divergence between them is
# itself a defect (RISK-04 is one risk with two scan sites, not two risks).
#
# - **Rubric surfaces** (criterion text, band labels, band descriptors, exemplar BAND
#   labels): a *standalone* numeral is refused wholesale — whatever a rubric numeral
#   counts, a judge reads it as a score. Digits attached to an identifier token
#   (`b0`, `Q-4`) are not standalone and survive; a label that *is* a numeral (`"3"`)
#   is the named catch.
# - **Content surfaces** (exemplar payloads, submission text): only a numeral beside
#   mark vocabulary (`2 points`, `out of 4`, `10%`) is refused. Bare content numerals —
#   a student calculating `"12 kg"` — are ordinary evidence and must survive, or the
#   scan is untargeted and will be disabled the first time it fires on real content.

#: A *standalone* numeral — not a digit inside an identifier token (`b0`, `Q-4`, `v2`).
#: Identical to TC-PKG-09's `_NUMERAL` (see the boundary note above).
_NUMERAL = re.compile(r"(?<![A-Za-z0-9-])\d+(?:[.,]\d+)?(?![A-Za-z0-9-])")

#: The mark vocabulary a content numeral is refused beside. Identical to TC-PKG-09's
#: `_MARK_CONTEXT`.
_MARK_CONTEXT = re.compile(
    r"points?\b|marks?\b|score\b|scale\b|maximum\b|max\b|out\s+of|%|/",
    re.IGNORECASE,
)

#: How much surrounding text counts as "adjacent" for the mark-context test. Identical
#: to TC-PKG-09's `_WINDOW`.
_WINDOW = 24


def offending_numeral(text: str, *, rubric: bool) -> str | None:
    """The first numeral in `text` the prohibition refuses, or `None`.

    On a rubric surface every standalone numeral is score-denoting; in content only a
    numeral beside mark vocabulary is."""
    for match in _NUMERAL.finditer(text):
        if rubric:
            return match.group()
        window = text[max(0, match.start() - _WINDOW): match.end() + _WINDOW]
        if _MARK_CONTEXT.search(window):
            return match.group()
    return None
