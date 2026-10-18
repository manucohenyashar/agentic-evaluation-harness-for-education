"""The CS-AUTHOR clause suite's assumed surface of `aeh.author` (M-AUTHOR, #689) — one place.

Design §3.1 (the package-authoring delta, `docs/design/package_authoring_design_delta.md`) pins
the Python names in its Interfaces and Data-structures blocks — `AuthoringService`,
`validate_draft`, `DraftResult`, `ReviewResult`, `ReviewAnswer`, `DraftIssue`, `StepOutcome`,
`ItemStatus`, `AuthoringSettings` — so the TS-165 clause suite resolves THOSE, and this file
holds them once so the registry conjunction cannot name a symbol the tests stopped using (the
`TS26_EXTRACT_SYMBOLS` precedent). What the design does *not* pin, the suite must still agree
on, and the names below are the disclosed assumptions — each carries its status, and if the
implementing stories (#686 corpus, #690-#698 service, #695 CLI) ship a name differently, the
rename is one line here and nowhere else.

| Name in this file | Assumed thing | Status |
|---|---|---|
| `AUTHOR_MODULE` | `aeh.author` | **design-named** (§3.1 module inventory) |
| `AUTHOR_SURFACE` | the nine §3.1-declared names | **design-named** — the conjunction the rung-1 registry entry is BUILT from |
| `chain_from_config()` | the corpus is recorded against the dev-ci profile's reasoning chain | **assumed, corpus coupling** — `fixtures/F-AUTHOR/recordings/` is keyed on the assembled request, which includes the model build id, so the rung-1 tests must inject the same chain the corpus was captured with. The only chain a repo file names is `docs/live-tests/config/live-test.dev-ci.toml`'s (`[[panel]]` then `[[escalation_judge]]`, FR-AUTHOR-04's order), so this helper reads it and every rung-1 file injects what it returns. If #686 records through a different chain, the fix is here |
| `ABSENT_HEAD_BUILD` | a pinned build id recorded nowhere | **invented here** — CT-AUTHOR-06's fallback-order case needs a chain head whose every call misses the recordings. `RecordedFixtureProvider` raises `FixtureMissingError` (a `ProviderError`) for it, which is exactly FR-AUTHOR-05a's fallback trigger, so the fallback path needs no live flake and no extra corpus recording |
| `FORCE_KWARG` | `draft(..., force=True)` | **invented here** — FR-AUTHOR-22 pins the CLI's `--force` but not the library form CT-AUTHOR-18's rung-1 carry-over case needs; the keyword mirror of the flag is the smallest bet . Disclosed limitation: the design delta pins `draft(self, documents, output_dir)` — no third parameter — so the mechanism itself is #697's (overwrite confirmation, TS-163); if #697 ships it as a settings field, a confirm callback or CLI-only confirmation, the rename here cannot fix the call and the case re-keys per the `#698` registry entry's disclosure |
| `RETRY_ISSUE` | the retry/recreate/overwrite/carry-over story is #697 | **design-named** — TS-163’s implementing story (`docs/design/package_authoring_test_plan.md` §8); the TC-AUTHOR-25/26/27 files’ require gates and registry entry name it |
| `PLACEHOLDER_FIELDS_AS_ITEM_IDS` | a placeholder's review item id is the sentinel's `<field>` | **assumed** — the report names item ids (CT-AUTHOR-05) and `ReviewAnswer(item_id=...)` must use them; the sentinel's field name is the one id the draft itself states. The scripted-review cases derive answers from this |
| `REVIEW_ISSUE` | the review walk's blocking story is #696 | **design-named** — TS-162's implementing story (`docs/design/package_authoring_test_plan.md` §8); the TC-AUTHOR-23/24 files' require gates and registry entry name it |
| `FINGERPRINT_RE` | a content fingerprint renders as a hex run of 12–64 chars | **assumed** — FR-AUTHOR-12/CT-AUTHOR-19 pin that the report's Items section carries "the content fingerprint it was given against", "the hash over the item's id and underlying content", but not its rendering; if #696 renders it base64 or prefixed/truncated, the regex here and the TC-AUTHOR-23 oracle are the one-line change |
| `AF01_VARIANT_RECORDINGS` | `fixtures/F-AUTHOR/recordings-af01-variant/` | **path guessed here** — TC-AUTHOR-29's second recorded set for AF-01; the design fixes neither the name nor the layout, so the path is declared once and #686 reconciles it here if it lands elsewhere |
| `AF13_PAIR` | the carry-over pair is (AF-01 documents, AF-13 documents) | **design-named** (§5.1: "AF-01's test with one question reworded") — same package id, so the re-draft sees the prior report |
| `AuthoringSettings()` | a zero-argument constructor | **assumed** — §3.1 declares the parameter but no fields; the knobs are env-read per invocation |
| `FALLBACK_ISSUE` | TC-AUTHOR-04..08's blocking story is #691 | **design-named** — TS-156's implementing story (test plan §8); the fallback/repair file's require gates and registry entry name it |
| `ABSENT_SECOND_BUILD` | a SECOND pinned build id recorded nowhere | **invented here** — TC-AUTHOR-06's order oracle needs two absent heads so `failures[0]` and `failures[1]` are each pinned by cross-run equality against that head's solo run (the CS-C06 technique); see `ABSENT_HEAD_BUILD` |
| `GarbageProvider` / `ScriptedProvider` | provider doubles for the unparseable and validator-failing repair triggers | **invented here** — FR-AUTHOR-05b needs no recording: a fixed unparseable reply, and a parseable-proposal-then-invalid-proposal script, exhaust the budget deterministically |
| `repair_pairs()` | a repair attempt is the same prompt PLUS the rejection reason | **assumed, two encodings** — the design pins the shape ("the same prompt plus the validator's rejection reason"), not its representation; a repair implemented by REWRITING the prompt reconciles this one helper (the #635 rule) |

Nothing here imports `aeh.author`; resolution happens inside the test bodies via
`tests.support.impl.require`, so a missing module is a stated failure, not a collection error.
`aeh.conf` and `aeh.prov` are shipped and are imported freely.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from aeh.conf import ModelRef
from aeh.prov import Capabilities, Completion, CostEstimate, RetentionReport

AUTHOR_ISSUE = "#689"
CORPUS_ISSUE = "#686"
CLI_ISSUE = "#695"
#: TS-162's implementing story — the review walk and the ready gate (test plan §8).
REVIEW_ISSUE = "#696"
CHAIN_ISSUE = "#687"

AUTHOR_MODULE = "aeh.author"

#: The §3.1-declared surface, in the order the Interfaces block states it. `ItemStatus` is the
#: clause suite's one type alias (CT-AUTHOR-03 asserts its members); `StepId` is *not* here —
#: no clause asserts its members by name.
AUTHOR_SURFACE = (
    "AuthoringService",
    "validate_draft",
    "DraftResult",
    "ReviewResult",
    "ReviewAnswer",
    "DraftIssue",
    "StepOutcome",
    "ItemStatus",
    "AuthoringSettings",
)

#: The `symbols` conjunction for the rung-1 registry entry — built here so the registry cannot
#: drift from the tests (the `TS26_EXTRACT_SYMBOLS` construction).
AUTHOR_SURFACE_CONJUNCTION = ",".join(f"{AUTHOR_MODULE}:{name}" for name in AUTHOR_SURFACE)

#: The one item id the sentinel itself states (see module docstring).
PLACEHOLDER_FIELDS_AS_ITEM_IDS = True

#: The library form of the CLI's `--force` (see module docstring).
FORCE_KWARG = "force"
#: TS-163’s implementing story — retry, recreate, overwrite protection, carry-over
#: (test plan §8); the TC-AUTHOR-25/26/27 files’ require gates and registry entry name it.
RETRY_ISSUE = "#697"
#: The build-gate sentinel refusal (TS-160) — landed; the journeys name it because the
#: refusal is what journey (b) and the pre-review build of journey (c) walk into.
PKG_GATE_ISSUE = "#688"

# --- the fixture corpus ----------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHOR_CORPUS = REPO_ROOT / "fixtures" / "F-AUTHOR"
#: The authoring recordings — one tree, the same single-tree shape the other `F-*` corpora use
#: (design §5.2), pointed at with `HARNESS_FIXTURE_DIR` for the CLI and passed as `fixture_dir=`
#: for the injected rung-1 provider.
RECORDINGS = AUTHOR_CORPUS / "recordings"
#: TC-AUTHOR-29's second recorded set for AF-01 (see module docstring).
AF01_VARIANT_RECORDINGS = AUTHOR_CORPUS / "recordings-af01-variant"
#: The dev-ci configuration the corpus was RECORDED through — a frozen, test-owned copy of the
#: live-test file with the recorded transcriber and judge builds. Not the live file itself:
#: `aea6eeb` re-pinned that to another model, and since the recordings are keyed on the build
#: id, reading the live file made every recorded authoring case miss (the old ~35-red baseline).
DEV_CI_CONFIG = REPO_ROOT / "tests" / "support" / "author-corpus.dev-ci.toml"
#: The live-test file itself, for the cases that are about IT (its models, its comments).
LIVE_DEV_CI_CONFIG = REPO_ROOT / "docs" / "live-tests" / "config" / "live-test.dev-ci.toml"


def af(af_id: str) -> Path:
    """One authored-fixture directory: `fixtures/F-AUTHOR/<af-id>/` with its PDFs and `expected.toml`."""
    return AUTHOR_CORPUS / af_id


#: The carry-over pair: AF-13 is AF-01's test with one question reworded and the rubric memo
#: edited (design §5.1), so before = AF-01's documents and after = AF-13's.
AF13_PAIR = ("AF-01", "AF-13")


# --- the chain the recordings are keyed against ----------------------------------------------

#: A pinned build id the corpus records nothing for — every call for it raises
#: `FixtureMissingError`, which is the provider-error trigger of FR-AUTHOR-05a. Date-pinned so
#: `ModelRef` accepts it as a resolved build; a floating tag would be refused.
ABSENT_HEAD_BUILD = "openrouter/devci-authoring-absent-head@0001-01-01"


def _ref(section: dict[str, Any]) -> ModelRef:
    return ModelRef(
        role=section["role"],
        provider=section["provider"],
        build_id=section["build_id"],
        quantization=section.get("quantization"),
    )


def chain_from_config(config: Path = DEV_CI_CONFIG, profile: str = "dev-ci") -> list[ModelRef]:
    """The profile's reasoning chain in FR-AUTHOR-04's order: `[[panel]]` refs in declared
    order, then `[[escalation_judge]]` refs, de-duplicated by build identity.

    This is the chain the rung-1 cases inject — the corpus's recordings are keyed on the
    assembled request, build id included, so the injected chain must be the one #686 recorded
    through (see module docstring). De-duplication keeps a config that names the same build in
    both sections honest; the module's own chain construction is FR-AUTHOR-04's and is the
    config-resolution story's (#687), not this helper's.
    """
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    section = data["profiles"][profile]
    refs = [*(section.get("panel") or []), *(section.get("escalation_judge") or [])]
    chain: list[ModelRef] = []
    seen: set[str] = set()
    for ref in refs:
        model = _ref(ref)
        if model.build_id not in seen:
            seen.add(model.build_id)
            chain.append(model)
    return chain


def transcriber_from_config(config: Path = DEV_CI_CONFIG, profile: str = "dev-ci") -> ModelRef:
    """The profile's transcriber build (FR-AUTHOR-02) — the `transcriber=` argument."""
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    return _ref(data["profiles"][profile]["transcriber"])


# --- shared test doubles and parsers ----------------------------------------------------------


def make_service(module: Any, chain: list[ModelRef], provider: Any, settings: Any = None) -> Any:
    """Construct the §3.1 `AuthoringService` with its declared keyword names.

    `transcriber` is the profile's transcriber build (FR-AUTHOR-02); `settings` defaults to a
    zero-argument `AuthoringSettings()` (see module docstring).
    """
    return module.AuthoringService(
        chain=chain,
        provider=provider,
        transcriber=transcriber_from_config(),
        settings=settings if settings is not None else module.AuthoringSettings(),
    )


def scripted_answers(module: Any, draft_text: str, values: dict[str, str]) -> list[Any]:
    """One `ReviewAnswer` per placeholder in the draft, with the value the test names.

    The item ids are the sentinel fields (`PLACEHOLDER_FIELDS_AS_ITEM_IDS`); every placeholder
    a test reviews must get a value here — a placeholder left without one stays in
    `ReviewResult.remaining`, which is exactly what the cases that expect `ready` must not do.
    """
    fields = placeholder_fields(draft_text)
    missing = [field for field in fields if field not in values]
    if missing:
        raise AssertionError(f"scripted review has no answer for {missing}")
    return [module.ReviewAnswer(item_id=f, value=values[f]) for f in fields]


class CountingProvider:
    """Wraps a real `InferenceProvider`, counting `complete()` calls and keeping the requests.

    The C13 ceiling (steps × items × ATTEMPTS × |chain|), C06's model attribution and C16's
    payload sweep all read one of these. Delegates every interface method, so the wrapped
    provider stays the only egress point (`CT-PROV-15`).
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[tuple[Any, Any, Any]] = []

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        self.calls.append((prompt, model_ref, params))
        return self.inner.complete(prompt, model_ref, params)

    def capabilities(self, model_ref: Any) -> Any:
        return self.inner.capabilities(model_ref)

    def estimate_cost(self, plan: Any) -> Any:
        return self.inner.estimate_cost(plan)

    def verify_retention(self, model_refs: Any) -> Any:
        return self.inner.verify_retention(model_refs)

    @property
    def models_called(self) -> list[str]:
        return [model_ref.build_id for _prompt, model_ref, _params in self.calls]


#: The sentinel value, verbatim (FR-AUTHOR-11). The draft text must contain it exactly this
#: often: once per placeholder item, each with its reason comment on the line above.
SENTINEL_RE = re.compile(r"<<PLACEHOLDER: ([^<>\n]+?)>>")
#: The reason group is nested-paren-tolerant (greedy up to the last `):`): a reason may
#: itself carry a parenthesised citation — the grades gap's `... never invented
#: (FR-AUTHOR-08)` was the first to prove it. Disclosed reconcile (the landing).
PLACEHOLDER_COMMENT_RE = re.compile(r"#\s*PLACEHOLDER\((.+)\):\s*(.+?)\s*$")
#: A content fingerprint as the report renders it — a hex run of 12–64 characters (see the
FINGERPRINT_RE = re.compile(r"\b[0-9a-f]{12,64}\b", re.IGNORECASE)

def unresolved_fields(report_text: str) -> list[str]:
    """The `<field>` of every sentinel the report's Unresolved section names, in review order.

    The report's section set is pinned (`CT-AUTHOR-05`: Documents→Steps→Items→Unresolved→Next
    command) and the Unresolved list is the review walk's order (`FR-AUTHOR-16`), so it is the
    one section a teacher — or a walkthrough that must not read the draft — may take its
    remaining items from. The disclosed assumption (see the module docstring's table): each
    entry carries the sentinel it must fill, the same `<<PLACEHOLDER: <field>>>` the draft
    carries, since the report is the draft's state description. If the report names items a
    different way, the reconciliation is this one helper. The section cut treats a `#`-led
    line as the next heading only when it is not a placeholder comment
    (`PLACEHOLDER_COMMENT_RE`), so a draft excerpt quoted inside the list — comment lines
    included — cannot truncate the section.
    """
    match = re.search(r"^#+\s*Unresolved\b[^\n]*\n", report_text, re.M)
    if match is None:
        return []
    rest = report_text[match.end():]
    section_end = None
    for heading in re.finditer(r"^#+\s\S[^\n]*", rest, re.M):
        line = rest[heading.start():heading.end()]
        if PLACEHOLDER_COMMENT_RE.match(line) is None:
            section_end = heading.start()
            break
    section = rest[:section_end] if section_end is not None else rest
    return SENTINEL_RE.findall(section)



def placeholder_fields(draft_text: str) -> list[str]:
    """The `<field>` of every sentinel in a draft, in document order — the item ids the
    scripted review answers (`PLACEHOLDER_FIELDS_AS_ITEM_IDS`).
    """
    return SENTINEL_RE.findall(draft_text)


def sha256_of(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- TS-156 (#708), TC-AUTHOR-04..08: the fallback, repair and payload doubles ---------------

#: The fixed unparseable reply — deliberately not JSON, not TOML, and not a sentinel: no
#: parser the module plausibly runs accepts it, and no placeholder scan mistakes it.
GARBAGE_REPLY = ": : not-a-proposal"

#: TC-AUTHOR-04..08's blocking story — chain resolution, fallback and the repair budget
#: (test plan §8, TS-156). The fallback/repair file's require gates and registry entry name it.
FALLBACK_ISSUE = "#691"

#: A SECOND pinned build id recorded nowhere, for TC-AUTHOR-06's order oracle: with two absent
#: heads, the fallback run's `failures[0]` and `failures[1]` are each pinned by cross-run
#: equality against that head's own solo run (the CS-C06 technique). Date-pinned so `ModelRef`
#: accepts it as a resolved build; recorded nowhere, like `ABSENT_HEAD_BUILD`.
ABSENT_SECOND_BUILD = "openrouter/devci-authoring-absent-head-2@0001-01-02"


def absent_ref(build_id: str = ABSENT_HEAD_BUILD) -> ModelRef:
    """The judge `ModelRef` for a never-recorded build id — FR-AUTHOR-05a's trigger.

    `RecordedFixtureProvider` raises `FixtureMissingError` (a `ProviderError`) for it, so the
    provider-error fallback path needs no live flake and no extra recording.
    """
    return ModelRef(role="judge", provider="openrouter", build_id=build_id, quantization=None)


class _StaticDouble:
    """The `InferenceProvider` protocol methods that answer statically, shared by the two
    TS-156 doubles below. `complete()` is each double's own; every other method has an
    honest static answer, so the run's capability, cost and retention paths never see an
    `AttributeError` masquerading as a finding. The double IS the egress point and delegates
    to nothing — the socket guard proves nothing dials out around it (`CT-PROV-15`).
    """

    def capabilities(self, model_ref: Any) -> Any:
        return Capabilities(
            supports_seed=False,
            supports_prefix_cache=False,
            max_concurrency=1,
            deterministic_at_temperature_zero=False,
            cost_per_token=None,
        )

    def estimate_cost(self, plan: Any) -> Any:
        return CostEstimate(calls=0, tokens_in=0, tokens_out=0, cost=None)

    def verify_retention(self, model_refs: Any) -> Any:
        return RetentionReport(confirmed=tuple(model_refs), unconfirmed=())

    @property
    def models_called(self) -> list[str]:
        return [model_ref.build_id for _prompt, model_ref, _params in self.calls]

    def _completion(self, reply: str, model_ref: Any) -> Any:
        return Completion(
            text=reply,
            tokens_in=1,
            tokens_out=1,
            latency_ms=1,
            resolved_build=model_ref.build_id,
            cached_prefix_tokens=0,
            cost=None,
        )


class GarbageProvider(_StaticDouble):
    """A provider double whose every reply is unparseable (TC-AUTHOR-04, TC-AUTHOR-07a).

    FR-AUTHOR-05b's trigger with no recording at all: the reply is a fixed non-JSON,
    non-TOML, non-sentinel string, so the parser's complaint path fires on every call and
    the repair budget is spent to exhaustion against a single model — which is what makes
    the repair payload inspectable without any captured recording. Records every
    `(prompt, model_ref, params)`; the payload inspection and `repair_pairs` read `calls`.
    """

    def __init__(self, reply: str = GARBAGE_REPLY) -> None:
        self.reply = reply
        self.calls: list[tuple[Any, Any, Any]] = []

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        self.calls.append((prompt, model_ref, params))
        return self._completion(self.reply, model_ref)


class ScriptedProvider(_StaticDouble):
    """A provider double replaying replies in order, repeating the last once exhausted
    (TC-AUTHOR-07b).

    The script serves a PARSEABLE proposal first and a parseable-but-INVALID one second —
    the validator-failing half of FR-AUTHOR-05 needs a reply the parser accepts and the
    deterministic rules reject, which no recorded fixture provides (the corpus records
    converging runs). Replies go to calls for `build_id` only; every other call (the
    transcriber's, if transcription rides the provider) gets `other_reply`, so the script
    cannot be desynced by a pre-step the design may or may not route through the provider.
    Repeating the last reply once exhausted is what spends the budget: every repair attempt
    re-proposes the same failing shape.
    """

    def __init__(self, replies: list[str], build_id: str,
                 other_reply: str = GARBAGE_REPLY) -> None:
        self.replies = list(replies)
        self.build_id = build_id
        self.other_reply = other_reply
        self.calls: list[tuple[Any, Any, Any]] = []
        self._served = 0

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        self.calls.append((prompt, model_ref, params))
        if model_ref.build_id == self.build_id:
            reply = self.replies[min(self._served, len(self.replies) - 1)]
            self._served += 1
        else:
            reply = self.other_reply
        return self._completion(reply, model_ref)


def repair_pairs(calls: list, build_id: str | None = None) -> list:
    """The consecutive same-model call pairs where the second prompt EXTENDS the first —
    the "same prompt plus the rejection reason" shape of FR-AUTHOR-05's repair attempts.

    The design pins the shape but not its representation, so two encodings are unioned:

    1. **superset** — the later payload's `(name, value)` pairs are a strict superset of the
       earlier's (the reason arrives as new fields);
    2. **append** — the same field names in order, and exactly one value is a strict
       extension of the earlier one (the reason is appended to the prompt).

    A repair is same-model by definition, so only consecutive calls for one build id pair
    up; `build_id` narrows further (to the reasoning chain's head, away from any
    transcription calls that may share the provider). Deliberately NOT detected: a repair
    that REWRITES the prompt rather than extending it — if #691 ships that shape, the
    reconciliation is this one helper and the assertions that use it (the `#635` rule), not
    a loosening of the oracle. The command-probe entry for this file runs the same two
    encodings, so the gate and the tests resolve together.
    """
    pairs: list = []
    for index in range(len(calls) - 1):
        p1, r1, _params = calls[index]
        p2, r2, _params2 = calls[index + 1]
        if r1.build_id != r2.build_id:
            continue
        if build_id is not None and r1.build_id != build_id:
            continue
        fields1, fields2 = list(p1.fields), list(p2.fields)
        set1 = set(fields1)
        if set1 <= set(fields2) and fields1 != fields2:
            added = [pair[1] for pair in fields2 if pair not in set1]
            if any(str(value).strip() for value in added):
                pairs.append((p1, p2))
                continue
        if [name for name, _value in fields1] == [name for name, _value in fields2]:
            extensions = [
                (v1, v2)
                for (_n1, v1), (_n2, v2) in zip(fields1, fields2)
                if v2 != v1 and v2.startswith(v1)
            ]
            unchanged = all(
                v1 == v2
                for (_n1, v1), (_n2, v2) in zip(fields1, fields2)
                if not (v2 != v1 and v2.startswith(v1))
            )
            if len(extensions) == 1 and unchanged and str(extensions[0][1]).strip():
                pairs.append((p1, p2))
    return pairs
