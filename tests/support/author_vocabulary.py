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

# --- the fixture corpus ----------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHOR_CORPUS = REPO_ROOT / "fixtures" / "F-AUTHOR"
#: The authoring recordings — one tree, the same single-tree shape the other `F-*` corpora use
#: (design §5.2), pointed at with `HARNESS_FIXTURE_DIR` for the CLI and passed as `fixture_dir=`
#: for the injected rung-1 provider.
RECORDINGS = AUTHOR_CORPUS / "recordings"
#: TC-AUTHOR-29's second recorded set for AF-01 (see module docstring).
AF01_VARIANT_RECORDINGS = AUTHOR_CORPUS / "recordings-af01-variant"
DEV_CI_CONFIG = REPO_ROOT / "docs" / "live-tests" / "config" / "live-test.dev-ci.toml"


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
PLACEHOLDER_COMMENT_RE = re.compile(r"#\s*PLACEHOLDER\(([^)\n]+)\):\s*(.+?)\s*$")
#: A content fingerprint as the report renders it — a hex run of 12–64 characters (see the
FINGERPRINT_RE = re.compile(r"\b[0-9a-f]{12,64}\b", re.IGNORECASE)


def placeholder_fields(draft_text: str) -> list[str]:
    """The `<field>` of every sentinel in a draft, in document order — the item ids the
    scripted review answers (`PLACEHOLDER_FIELDS_AS_ITEM_IDS`).
    """
    return SENTINEL_RE.findall(draft_text)


def sha256_of(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()