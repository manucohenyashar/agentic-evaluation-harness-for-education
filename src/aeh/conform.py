"""`M-CONFORM`'s fixture surface (#133): the pinned fixture set, the consent boundary, and the
ingest seam the adversarial tier drives.

`FR-CONFORM-01` requires 30-50 submissions spanning the score range; `-02/03/09` require consent
declarations, the real medium, and the adversarial tier; `NFR-CONFORM-01` requires the set to be
content-addressed and version-pinned. This module is what a conformance run **loads** those
fixtures through, and the two operations the clause suite drives on them:

* `load_fixture_set(pin)` — the fixture set as data: known reference scores, media and legibility
  classes, twin pairing, PDF threat kinds, and the content hash a result cites. Every file-backed
  entry is verified against its source bytes at load, because a conformance result measured
  against a corpus that changed between runs is not a result.
* `build_conformance_suite(provider=...)` — the suite surface design §3.18 declares: `run` (whose
  consent gate is live in this story; the divergence machinery is #134's) and `ingest_one`
  (the real ingest pipeline over one fixture, including the V0 quarantine the malicious PDFs
  must reach no model call past).

The consent boundary is **delegated, not re-implemented** (`CT-CONFORM-10`): `run` asks
`aeh.conf.consent_override_for` — the same function `M-ORCH` resolves runs through — and turns a
`ConsentGateError` into this module's `ConsentRefused`. This module reads `consent_class` to
carry it and decides nothing with it; `test_tc_conform_c10_the_suite_does_not_reimplement_the_
consent_check` asserts that structurally.

First cross-package import, stated rather than smuggled
-------------------------------------------------------
`aeh` is the system; `harness` is its test harness. No `aeh.*` module imports `harness` today
and no `harness.*` module imports `aeh`, and this module ends that symmetry on purpose: the
fixture set's identity is the corpora build's artifact (`F-CONFORM`'s manifest), so reading it
means reading `harness.corpora.manifest`, and the malicious-PDF fixtures' bytes come from
`harness.corpora.adv_pdf`'s generator. The walker is unaffected (nothing imports back), and the
dependency is one-way: `harness` never imports `aeh`.

Why `ingest_one` holds the declared refusal world
-------------------------------------------------
`FR-INGEST-33`'s strip knob has two declared worlds (SEC-05's fork): at its default the
sanitizer *strips* active constructs and the pipeline processes the stripped copy; with
`HARNESS_INGEST_STRIP_ACTIVE_CONTENT=false` the same construct **quarantines** and reaches no
model call. The adversarial tier is the second world — the F-ADV-PDF manifest's
`expected_outcome: quarantine` is written for it — so `ingest_one` sets the knob for the ingest
it performs and restores the caller's value afterwards. The knob stays where M-INGEST put it
(read from the environment at call time, so a run can retune without a code change); the suite
choosing the refusal world for the corpus it measures is the declared reading, not a bypass.

The strip knob alone is not that whole world. The decompression bomb (`ADV-PDF-09`) carries no
active content — its declared outcome (`reference_score_basis: "quarantine_at_v0"`) is written
for a world whose decompressed-bytes **ceiling** sits below its declared 64 MiB expansion.
M-INGEST's production default (512 MiB) accepts it at V0, and the construct is then rasterized
and transcribed: three model calls, quarantine at V1 — exactly the failure a review of this
module's first pass caught, because `_markdown_pages`' sibling wrapper pinned only the strip
knob. So the ingest seam holds **both** knobs at the declared refusal world and restores them
afterwards: quarantine-at-V0-with-no-model-call is what every F-ADV-PDF row declares, and that
outcome only holds in a world whose ceilings refuse it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

# The fixture set's identity is the corpora build's artifact, so this module reads it from the
# generators rather than copying the constants: `CORPUS_NAME` and `VERSION_LABEL` are one fact in
# `conform_set`, and the manifest the build writes is the thing this module loads. See the
# module docstring — this is the first `aeh` -> `harness` import, deliberate and one-way.
from harness.corpora import adv_pdf, conform_set, reference_package
from harness.corpora.manifest import CORPUS_ROOT, ManifestEntry, read_manifest, set_content_hash
from harness.corpora.pdf_writer import typed_document

CORPUS_NAME = conform_set.CORPUS_NAME

#: The pin label the callers use (`load_fixture_set("v1")`). Normalized by stripping a leading
#: `v` before comparing to the manifest's version, so `load_fixture_set("v1")` and a future
#: `load_fixture_set("1")` name the same set rather than two.
DEFAULT_PIN_LABEL = conform_set.VERSION_LABEL

#: Env knob (seam 3): where the corpora live. Production value is the committed `fixtures/`
#: directory; the knob exists for a run that keeps them elsewhere.
FIXTURE_ROOT_ENV = "HARNESS_FIXTURE_ROOT"

#: The cohort the ingest surface writes into — an ephemeral store's whole population, so the
#: name is a label rather than a scope to be careful about.
INGEST_COHORT = "c-conform-fixtures"

#: The declared refusal world's decompressed-bytes ceiling, derived from the corpora's own
#: declaration: one sixty-fourth of the bomb's expansion (`BOMB_DECOMPRESSED_BYTES`, 64 MiB) —
#: 1 MiB today. Below it ADV-PDF-09 crosses the ceiling at V0 and quarantines having reached no
#: model call; above it sit every legitimate fixture with orders of magnitude to spare (the
#: largest figure measured through the sanitizer's own accounting among the committed PDFs is
#: SC-04's 1,338 bytes). M-INGEST's production default (512 MiB) *accepts* the bomb — that
#: default is the production posture; this is the stricter world the F-ADV-PDF rows' declared
#: outcomes (`quarantine_at_v0`) are written against. Deriving from the declaration keeps the
#: wrapper below the bomb if the declaration is ever retuned, and the regression case
#: (`test_regression_..._decompression_bomb_...`) fails if either side drifts.
_DECLARED_REFUSAL_MAX_DECOMPRESSED_BYTES = adv_pdf.BOMB_DECOMPRESSED_BYTES // 64

#: The gate order `IngestReport.gates` is read in when naming the first gate that failed. V3's
#: failing values are its own (the identity gate reports `unmatched`/`ambiguous`, not `fail`),
#: which is why the refusal values come from M-INGEST's table rather than a literal here.
_GATE_ORDER: tuple[str, ...] = ("v0", "v1", "v2", "v3", "v4")

# --- the comparison vocabulary (design §3.18, adopted as declared) -------------------------------
#
# These names are the conformance comparison's declared surface — the same words
# `tests/support/conform_vocabulary.py` declares for the suite that drives them. They are
# re-declared here rather than imported from the tests because a production module does not
# import its tests; the vocabulary file carries the adoption note, and a rename is one edit in
# each place.

#: The five divergence dimensions §7.4 declares, as the report keys them.
SCORE_DISTRIBUTION_DIMENSION = "per_criterion_score_distribution"
AGREEMENT_DIMENSION = "chance_corrected_agreement"
CONFIDENCE_DIMENSION = "confidence_and_escalation_rate"
EVIDENCE_INTEGRITY_DIMENSION = "evidence_integrity_failure_rate"
SELF_AGREEMENT_DIMENSION = "self_agreement_over_repeated_runs"
DIVERGENCE_DIMENSIONS = (
    SCORE_DISTRIBUTION_DIMENSION,
    AGREEMENT_DIMENSION,
    CONFIDENCE_DIMENSION,
    EVIDENCE_INTEGRITY_DIMENSION,
    SELF_AGREEMENT_DIMENSION,
)

#: The three divergence classifications (§7.4). `blocking` gates the release; `informational`
#: is a finding recorded beside the decision; `unavailable` means no gate may fire for the
#: dimension at all — CT-CONFORM-14 declines to declare a statistic for the score-distribution
#: comparison, so its gate *cannot* fire rather than firing loosely.
CLASSIFICATION_BLOCKING = "blocking"
CLASSIFICATION_INFORMATIONAL = "informational"
CLASSIFICATION_UNAVAILABLE = "unavailable"

#: The static classification per dimension (§7.4's table): the integrity gate blocks, the
#: score distribution is not computable as a gate (CT-CONFORM-14), and the rest are findings.
EXPECTED_CLASSIFICATION: Mapping[str, str] = {
    SCORE_DISTRIBUTION_DIMENSION: CLASSIFICATION_UNAVAILABLE,
    AGREEMENT_DIMENSION: CLASSIFICATION_INFORMATIONAL,
    CONFIDENCE_DIMENSION: CLASSIFICATION_INFORMATIONAL,
    EVIDENCE_INTEGRITY_DIMENSION: CLASSIFICATION_BLOCKING,
    SELF_AGREEMENT_DIMENSION: CLASSIFICATION_INFORMATIONAL,
}

#: The two gated dimensions, as the clause suite names them.
UNAVAILABLE_GATE_DIMENSION = SCORE_DISTRIBUTION_DIMENSION
LIVE_GATE_DIMENSION = EVIDENCE_INTEGRITY_DIMENSION

#: The gates and the findings, partitioned once: every dimension is exactly one of the two.
GATE_DIMENSIONS = (UNAVAILABLE_GATE_DIMENSION, LIVE_GATE_DIMENSION)
INFORMATIONAL_DIMENSIONS = tuple(
    dimension for dimension in DIVERGENCE_DIMENSIONS if dimension not in GATE_DIMENSIONS
)

#: The dispatch value a recorded-transport run reports for its transcription stage, and the
#: result field it is reported under (`TC-CONFORM-04`'s dispatch assertion reads the field).
TRANSCRIPTION_DISPATCH_FIELD = "transcription_dispatch"
RECORDED_FIXTURE_DISPATCH = "recorded_fixture"

#: The self-agreement figure (`TC-CONFORM-12`): reported per backend, keyed under the
#: dimension name in each backend's `figures`, carrying its stated `n`.
SELF_AGREEMENT_FIELD = "self_agreement"
SELF_AGREEMENT_REPEATS_FIELD = "n"
MIN_SELF_AGREEMENT_REPEATS = 2

#: The per-backend figures mapping's field name (`TC-CONFORM-12`'s `figures.get(...)`).
PER_BACKEND_FIGURES_FIELD = "figures"

#: The alert surface (`TC-CONFORM-13`), named after the two shipped alert readers
#: (`aeh.orch:evaluate_alerts`, `aeh.grade:evaluate_grade_alerts`), and the two alert kinds.
CONFORMANCE_ALERT_SURFACE = "evaluate_conformance_alerts"
ALERT_DIVERGENCE_GATE_CROSSED = "divergence_gate_crossed"
ALERT_BUILD_SUBSTITUTION_DETECTED = "build_substitution_detected"

#: Design §3.18's observability line: the three fields a divergence needs to be attributable.
OBSERVABILITY_FIELDS = frozenset({
    "per_dimension_divergence",
    "fixture_set_version",
    "resolved_builds",
})
RESOLVED_BUILDS_FIELD = "resolved_builds"
REQUESTED_BUILDS_FIELD = "requested_builds"

#: The stages a conformance run executes (`TC-CONFORM-03`'s sweep), the stage no recorded
#: transport may stand in for (`CT-CONFORM-03`), the VLM path the real-medium clause names,
#: and the shortcut stage that must appear for none of it.
PIPELINE_STAGES = ("ingest", "transcribe", "extract", "judge", "integrity", "aggregate", "grade")
UNSTUBBABLE_STAGE = "ingest"
VLM_STAGE = "transcribe"
TEXT_SHORTCUT_STAGE = "text_passthrough"

#: §4.7's per-backend conformance budget (the live-tier threshold `TC-CONFORM-11` prices).
CONFORMANCE_BUDGET_SECONDS = 3600

#: The env knob (seam 3) that says this box declares the live backends a live conformance
#: run dispatches through. It chooses the transport (`live_conformance_backends`'s docstring):
#: a profile it names is dispatched through the shipped live providers; every other run uses
#: the recorded derivation.
LIVE_BACKENDS_ENV = "HARNESS_CONFORM_LIVE_BACKENDS"


class ConformanceError(Exception):
    """A misuse of the conformance surface (a missing provider, an unknown fixture id)."""


class ConsentRefused(Exception):
    """The suite refused to run against a cohort not so flagged (`FR-CONFORM-02`, R31).

    The decision is not made here: the raise happens when the `M-CONF` consent gate
    (`aeh.conf.consent_override_for`) refuses a backend configuration for the cohort. This
    module wraps the refusal so a consumer can catch the conformance suite's own type without
    importing the gate's — the boundary the clause draws is about the *decision*, not the
    exception name.
    """


class StaleFixtureError(ConformanceError):
    """A fixture's cited source bytes no longer hash to the digest the manifest cites.

    A conformance result measured against a corpus that changed between runs is not a result
    (`NFR-CONFORM-01`). Staleness is a refusal, never a warning.
    """


@dataclasses.dataclass(frozen=True)
class FixtureSubmission:
    """One fixture, with everything known about it declared rather than guessed.

    Field-for-field the manifest entry's surface: the known reference score on its scale, the
    media and legibility class, the injection pairing and PDF threat, the consent declaration,
    and the provenance (which source corpus, which member, and that member's content hash). A
    field that is not applicable is `None` rather than missing, so a caller can select on any
    of them without `.get()` guesses.
    """

    submission_id: str
    consent_class: str
    reference_score: float
    max_score: float
    media_kind: str | None
    legibility: str | None
    injection_kind: str | None
    twin_id: str | None
    pdf_threat_kind: str | None
    source_corpus: str
    source_path: str
    content_hash: str
    reference_score_basis: str | None = None

    def with_reference_score(self, score: float) -> "FixtureSubmission":
        """The same fixture with a different reference score — the differential behind
        `NFR-CONFORM-01`'s identity assertion: changing one declared value must change the
        set's hash."""
        return dataclasses.replace(self, reference_score=score)

    def declared_digest(self) -> str:
        """The digest of everything this fixture declares — the identity one fixture contributes
        to the set's hash.

        Over the **declared** fields rather than the source bytes: the set's identity is what a
        result cites, and a reference score corrected in the manifest must move it even though
        no byte on disk changed. The source digest rides inside the payload, so a re-anchored
        fixture moves the set hash too.
        """
        payload = json.dumps(dataclasses.asdict(self), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclasses.dataclass(frozen=True)
class FixtureSet:
    """The loaded fixture set: a version, an order, and a hash over both.

    The submissions carry the manifest's order, and the hash is computed over the ordered
    `(id, declared_digest)` pairs with the same function the corpora manifests use — a set
    digest that ignores order would let two runs measure different orderings under one
    identity, and run order is exactly what self-agreement (one of the five divergence
    dimensions) measures.
    """

    version: str
    submissions: tuple[FixtureSubmission, ...]
    #: Per-fixture declared reference bands (`submission_id -> criterion -> band`), carried by
    #: the corpora that declare them (`F-FROZEN`, `F-SCAN`, `F-ADV-INJ` rows) and joined onto
    #: `F-CONFORM` selections from the source corpus each member cites. `None` for a set built
    #: from a corpus that declares none. Carried on the set rather than re-read at run time so
    #: `run` is a pure function of what the loader verified — and so the content hash stays a
    #: hash of the *submissions*, which this field does not enter.
    reference_bands: Mapping[str, Mapping[str, str]] | None = None
    #: The package version the set measures (`F-FROZEN`'s manifest declares it); `None` for a
    #: set that declares none. A result citing a package version must cite what the set names.
    package_version: str | None = None
    #: The manifest's fixture-set identity (`F-ADV-INJ@1+sha256:...`), when the corpus declares
    #: one — what an adversarial-tier report cites to name the fixtures that produced it.
    fixture_set_id: str | None = None

    @property
    def content_hash(self) -> str:
        return set_content_hash(
            ManifestEntry(id=s.submission_id, path=s.source_path, content_hash=s.declared_digest())
            for s in self.submissions
        )

    @property
    def fixture_ids(self) -> tuple[str, ...]:
        return tuple(s.submission_id for s in self.submissions)

    def replace_submission(
        self, submission_id: str, replacement: FixtureSubmission
    ) -> "FixtureSet":
        """One submission replaced by name. Refuses a rename: the call names which fixture it is
        replacing, and a replacement carrying a different id would silently change what the set
        is addressed by."""
        if not any(s.submission_id == submission_id for s in self.submissions):
            raise ConformanceError(
                f"no fixture {submission_id!r} in the set; the set holds "
                f"{len(self.submissions)} submissions"
            )
        if replacement.submission_id != submission_id:
            raise ConformanceError(
                f"replace_submission({submission_id!r}, ...) was handed a submission whose id is "
                f"{replacement.submission_id!r}; a rename changes what the set is addressed by "
                f"and is not what this call is for"
            )
        return FixtureSet(
            version=self.version,
            submissions=tuple(
                replacement if s.submission_id == submission_id else s for s in self.submissions
            ),
            reference_bands=self.reference_bands,
        )

    def run(
        self, backend: str = "recorded-fixture", *, simulate_build_change: bool = False
    ) -> "DistributionReport":
        """The set's declared per-criterion score distribution, as a run of one backend.

        This is `TC-REG-05`'s surface: the frozen corpus re-run and its per-criterion band
        shares recomputed, so a *shift* on an unchanged package can be detected as build
        substitution (`FR-CONFORM-08`) rather than absorbed as a new baseline. `backend` names
        the (single) backend the distribution stands for — the frozen set carries the declared
        references, and the recorded transport replays them; `simulate_build_change` applies the
        substitution shift (one criterion, one step up its declared scale) so the detection path
        has a shift to catch.
        """
        distribution: dict[str, dict[str, float]] = {}
        carrying: dict[str, int] = {}
        declared_bands = self.reference_bands or {}
        for submission in self.submissions:
            bands = dict(declared_bands.get(submission.submission_id, {}))
            if not bands:
                continue
            if simulate_build_change:
                bands = _shift_bands_one_step(bands)
            for criterion, band in bands.items():
                counts = distribution.setdefault(criterion, {})
                counts[band] = counts.get(band, 0.0) + 1.0
                carrying[criterion] = carrying.get(criterion, 0) + 1
        shares = {
            criterion: {band: n / carrying[criterion] for band, n in counts.items()}
            for criterion, counts in distribution.items()
        }
        return DistributionReport(
            per_criterion_distribution=shares,
            package_version=self.package_version,
            backend=backend,
        )


def _fixture_root() -> Path:
    raw = os.environ.get(FIXTURE_ROOT_ENV)
    if not raw:
        return CORPUS_ROOT
    return Path(raw)


def _version_for_pin(pin: str) -> str:
    """The manifest version a pin label names: `v1` and `1` are the same set.

    The corpora manifests version with the bare string (`version: "1"`); the suite's callers
    pass the label (`run("v1", ...)`). Normalizing here, once, keeps the two spellings from
    becoming two facts.
    """
    label = pin.strip()
    if label[:1] in {"v", "V"}:
        label = label[1:]
    if not label:
        raise ConformanceError(f"pin {pin!r} names no version")
    return label


def _submission_from_row(row: Mapping[str, Any]) -> FixtureSubmission:
    return FixtureSubmission(
        submission_id=row["submission_id"],
        consent_class=row["consent_class"],
        reference_score=row["reference_score"],
        max_score=row["max_score"],
        media_kind=row.get("media_kind"),
        legibility=row.get("legibility"),
        injection_kind=row.get("injection_kind"),
        twin_id=row.get("twin_id"),
        pdf_threat_kind=row.get("pdf_threat_kind"),
        source_corpus=row["source_corpus"],
        source_path=row["source_path"],
        content_hash=row["content_hash"],
        reference_score_basis=row.get("reference_score_basis"),
    )


def _materialize_bytes(submission: FixtureSubmission) -> bytes:
    """The source bytes a fixture cites, verified against the digest it cites them with.

    `F-CONFORM` is a selection, not a source: the bytes live in the corpus each entry cites,
    so the manifest is only as good as its citations. This is the one place they are checked,
    and both load and ingest go through it — an entry whose source moved on is a refusal at the
    point of use, not a silent measurement against something else.
    """
    if submission.source_corpus == "F-ADV-PDF":
        # Manifest-only corpus: the bytes are the committed generator's, verified against the
        # manifest's digest of them (the same contract `materialize_adv_pdfs` gives the
        # security suite).
        data = adv_pdf.build_construct(submission.submission_id)
    else:
        path = _fixture_root() / submission.source_corpus / submission.source_path
        data = path.read_bytes()
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    if digest != submission.content_hash:
        raise StaleFixtureError(
            f"{submission.source_corpus}/{submission.source_path} hashes to {digest}, but the "
            f"fixture set cites {submission.content_hash}. The corpus moved under the pinned "
            f"set; rebuild the corpora (`python -m harness.corpora.build`) rather than loading "
            f"a set nobody generated."
        )
    return data


def load_fixture_set(pin: str) -> FixtureSet:
    """The version-pinned fixture set (`FR-CONFORM-01`, `NFR-CONFORM-01`).

    Reads `F-CONFORM`'s manifest from the corpora root (`HARNESS_FIXTURE_ROOT` overrides it),
    refuses a pin that does not name the manifest's version, and verifies every entry against
    the source bytes it cites before the set is handed out. The returned set is addressed by
    `content_hash` — the digest a conformance result cites — and `fixture_ids` is exactly the
    ids in it, so a result naming the set names what produced it.

    A pin that names a source corpus instead (`F-FROZEN`, `F-SCAN`, `F-ADV-INJ`) loads that
    corpus itself — the regression surface (`TC-REG-05`) re-runs a frozen source corpus and its
    declared reference bands, so the set is loadable by the same name its manifest declares.
    The same verification applies: every cited source digest is checked at load.
    """
    corpus_root = _fixture_root() / pin
    if pin != CORPUS_NAME and (corpus_root / "manifest.json").exists():
        return _load_corpus_fixture_set(pin, corpus_root)
    version = _version_for_pin(pin)
    manifest = read_manifest(_fixture_root() / CORPUS_NAME / "manifest.json")
    if manifest["corpus"] != CORPUS_NAME or manifest["version"] != version:
        raise ConformanceError(
            f"the fixture set is pinned as {CORPUS_NAME}@{version}, but the manifest at "
            f"{_fixture_root() / CORPUS_NAME} is {manifest['corpus']}@{manifest['version']}"
        )
    submissions = tuple(_submission_from_row(row) for row in manifest["submissions"])
    if len({s.submission_id for s in submissions}) != len(submissions):
        raise ConformanceError("the manifest carries duplicate submission ids")
    fixtures = FixtureSet(
        version=manifest["version"],
        submissions=submissions,
        fixture_set_id=manifest.get("fixture_set_id"),
    )
    # The verification IS the load: an entry whose source bytes moved is a refusal here, not a
    # surprise in the middle of a measured run.
    for submission in submissions:
        _materialize_bytes(submission)
    return fixtures


def _load_corpus_fixture_set(corpus: str, corpus_root: Path) -> FixtureSet:
    """Load a source corpus (`F-FROZEN`, ...) as a fixture set, with its declared bands.

    The regression surface re-runs a frozen corpus whose rows carry their per-criterion
    reference bands directly; those bands ride on the set (`reference_bands`) so `run` is a
    pure function of the loaded set. The verification is the same one `load_fixture_set`
    applies: a row whose source bytes moved refuses here.
    """
    manifest = read_manifest(corpus_root / "manifest.json")
    max_score = manifest.get("max_points")
    # The consent class is read, never decided: a row's declared value, falling back to the
    # corpus's manifest-level declaration. No consent-class literal is invented here — the
    # corpus declares what it is (`FR-CONFORM-02`), and the M-CONF gate is what enforces it.
    manifest_consent = manifest.get("consent_class")
    submissions: list[FixtureSubmission] = []
    bands: dict[str, dict[str, str]] = {}
    for row in manifest["submissions"]:
        submission = FixtureSubmission(
            submission_id=row["id"],
            consent_class=row.get("consent_class") or manifest_consent,
            reference_score=float(row.get("reference_points") or 0.0),
            max_score=float(row.get("max_score") or max_score or 0.0),
            media_kind=row.get("media_kind"),
            legibility=row.get("legibility"),
            injection_kind=row.get("injection_kind"),
            twin_id=row.get("twin_id"),
            pdf_threat_kind=None,
            source_corpus=corpus,
            source_path=row["path"],
            content_hash=row["content_hash"],
        )
        if row.get("reference_bands"):
            bands[submission.submission_id] = dict(row["reference_bands"])
        _materialize_bytes(submission)
        submissions.append(submission)
    ordered = tuple(submissions)
    if len({s.submission_id for s in ordered}) != len(ordered):
        raise ConformanceError(f"corpus {corpus} carries duplicate submission ids")
    return FixtureSet(
        version=manifest["version"],
        submissions=ordered,
        reference_bands=bands,
        package_version=manifest.get("package_version"),
        fixture_set_id=manifest.get("fixture_set_id"),
    )


@dataclasses.dataclass(frozen=True)
class IngestOutcome:
    """What ingesting one fixture did — the per-gate trace next to the status (seam 4).

    `quarantined_at` names the FIRST gate that failed, in the ladder's order, as the gate's
    report key upper-cased (`V0`): the malicious-PDF clause (`FR-CONFORM-09`) is about the first
    gate, and a submission that failed V0 and was never scored is a different fact from one that
    failed V3. `None` means no gate failed.
    """

    submission_id: str
    ingest_status: str
    gates: Mapping[str, str]
    quarantined_at: str | None
    detail: Mapping[str, Any]


class ConformanceSuite:
    """The suite surface design §3.18 declares: a run, a comparison, and the fixture seam.

    Built by `build_conformance_suite(provider=...)`. `provider` is the deterministic transport
    the transcription stage dispatches through (`CT-PROV-10`): the suite never opens a socket
    itself, and the fast tier passes a recorded or counting provider. `ingest_one` runs the real
    ingest pipeline over one fixture — the surface the malicious-PDF clause drives — and needs
    a provider for the same reason the pipeline does.
    """

    def __init__(self, provider: Any | None = None) -> None:
        self._provider = provider

    # -- CT-CONFORM-10: the consent boundary ------------------------------------------------------

    def _enforce_consent(self, backend_config: Mapping[str, Any], cohort: Any) -> None:
        """The consent decision, delegated whole to `M-CONF` (`CT-CONFORM-10`).

        `aeh.conf.consent_override_for` is the one implementation of the rule — this module
        calls it and reports the refusal under its own exception name. A second copy of the
        check here would drift from the first, and the one that drifts open is the one nobody
        is watching (RISK-10); the structural scan over this module asserts none of this file
        decides on a consent class.
        """
        from aeh.conf import ConsentGateError, consent_override_for

        try:
            consent_override_for(backend_config, cohort)
        except ConsentGateError as error:
            raise ConsentRefused(str(error)) from error

    def run(
        self,
        version: str,
        backend_configs: Sequence[Mapping[str, Any]],
        *,
        cohort: Any,
        tier: str | None = None,
    ) -> Any:
        """Run the identical fixture set through the full pipeline on every backend.

        The consent gate is the surface and it is live: every backend config is checked against
        the cohort through `M-CONF` before anything else happens, and a cohort not so flagged is
        refused before a single fixture is read — sending unconsented work anywhere is the
        failure the gate exists to make impossible.

        What the run does, in the order the clauses ask for it (`CT-CONFORM-03`..`-07`,
        `-10`..`-14`): the identical set (`CT-CONFORM-01`'s one input hash) passes through the
        seven pipeline stages per backend with no ingestion stub on the unstubable stage; the
        five §7.4 dimensions are measured per backend and compared — per dimension, never a
        headline (`CT-CONFORM-04`); the two named gates partition the dimensions — the live
        evidence-integrity gate blocks on crossing (`FR-CONFORM-07`), the score-distribution
        gate is always `unavailable` because no statistic is declared for it (`CT-CONFORM-14`),
        and the three informational dimensions are findings; every backend's figure set is
        recorded backend-scoped through `M-PKG` and promoted — never merged (`CT-CONFORM-06`);
        the report carries resolved next to requested builds and the per-dimension divergence
        (`CT-CONFORM-13`), and the run's own report artifact is the only write of its kind.
        """
        configs = list(backend_configs)
        if not configs:
            raise ConformanceError(
                "a conformance run needs at least one backend config; nothing was given"
            )
        for backend_config in configs:
            self._enforce_consent(backend_config, cohort)

        fixture_set = _load_set_memo(version)
        bands_by_id = _source_bands()
        results: dict[str, BackendResult] = {}
        for backend_config in configs:
            profile = str(backend_config["HARNESS_PROFILE"])
            if profile in results:
                raise ConformanceError(
                    f"two backend configs declare the profile {profile!r}; a run compares "
                    "distinct backends, and a second config under the same profile would "
                    "overwrite the first's measurement"
                )
            results[profile] = _run_backend(self, fixture_set, backend_config, bands_by_id)

        divergence = _dimension_divergence(
            list(results.values()), frozenset(_ACTIVE_INDUCED_DIMENSIONS)
        )

        # The partition (`CT-CONFORM-05`/`-14`): exhaustive by construction, and the
        # score-distribution gate never passes — no statistic is declared for it, so no run may
        # report it green.
        tolerance = _divergence_tolerance()
        unavailable = (UNAVAILABLE_GATE_DIMENSION,)
        blocking = tuple(
            dimension
            for dimension in GATE_DIMENSIONS
            if dimension not in unavailable and divergence.dimensions[dimension] > tolerance
        )
        findings = {
            dimension: divergence.dimensions[dimension]
            for dimension in INFORMATIONAL_DIMENSIONS
            if divergence.dimensions[dimension] > tolerance
        }
        passing = tuple(
            dimension
            for dimension in DIVERGENCE_DIMENSIONS
            if dimension not in unavailable
            and dimension not in blocking
            and dimension not in findings
        )

        # Backend-scoped records (`CT-CONFORM-06`): one per backend, keyed on the catalog's
        # seven fields with the administration naming the backend profile the figures speak
        # for. The write goes into the package validation registry (`FR-CONFORM-05` — the
        # figures land where `aeh.pkg.validation_for` reads them back, not only on the report
        # object), and the durable half is the promotion through `M-PKG` (`CT-CONFORM-12`).
        from aeh import pkg as pkg_module

        records: list[ValidationRecord] = []
        for backend_config in configs:
            profile = str(backend_config["HARNESS_PROFILE"])
            result = results[profile]
            record = ValidationRecord(
                package_version=fixture_set.package_version or version,
                criterion="package",
                population_scope=getattr(cohort, "cohort_id", ""),
                backend_profile=profile,
                panel_build_ref=_panel_build_ref(backend_config),
                scoring_model=str(backend_config.get("prompt_template_v") or ""),
                administration=(
                    f"{getattr(cohort, 'cohort_id', '')}@{profile}:{fixture_set.version}"
                ),
                figure=dict(result.figures),
            )
            records.append(record)
            pkg_module.record_validation(
                package_version=record.package_version,
                population_scope=record.population_scope,
                criterion=record.criterion,
                backend_profile=record.backend_profile,
                panel_build_ref=record.panel_build_ref,
                scoring_model=record.scoring_model,
                administration=record.administration,
                figure=dict(record.figure),
            )
            _promote_validation(record)

        observability = {
            "per_dimension_divergence": dict(divergence.dimensions),
            "fixture_set_version": fixture_set.version,
            RESOLVED_BUILDS_FIELD: {
                str(config["HARNESS_PROFILE"]): _resolved_builds(config) for config in configs
            },
            REQUESTED_BUILDS_FIELD: {
                str(config["HARNESS_PROFILE"]): _requested_builds(config) for config in configs
            },
            "fixture_set_id": fixture_set.fixture_set_id,
        }

        first = next(iter(results.values()))
        report = ConformanceReport(
            per_backend=results,
            divergence=divergence,
            observability=observability,
            validation_records=tuple(records),
            input_set_hash=fixture_set.content_hash,
            package_version=fixture_set.package_version or version,
            build_changed_error_raised=False,
            blocked=bool(blocking),
            blocking_dimensions=blocking,
            findings=findings,
            unavailable_dimensions=unavailable,
            passing_dimensions=passing,
            completed=True,
            fixtures_scored=len(first.outcomes),
            tier=tier,
            consent_class=str(getattr(cohort, "consent_class", "") or ""),
        )
        # The run's own observability write — the one M-CONFORM-attributed write kind
        # `CT-CONFORM-12` permits (`_is_own_report_artifact` names the target shape).
        _write_report_artifact(report, fixture_set)
        return report

    def compare(self, a: Any, b: Any) -> Any:
        """The divergence comparison — design §3.18's Protocol, as `CT-CONFORM-04` reads it.

        Takes two backends' results and returns the per-dimension divergence — five named
        dimensions, no headline. Induced dimensions active at the call drive their values, so
        the gate's blocking behaviour is drivable on the recorded transport (`CT-CONFORM-05`).
        """
        return _dimension_divergence([a, b], frozenset(_ACTIVE_INDUCED_DIMENSIONS))

    # -- the ingest seam ---------------------------------------------------------------------------

    def ingest_one(self, submission: FixtureSubmission) -> IngestOutcome:
        """Ingest one fixture through the real pipeline on an ephemeral store.

        The fixture's bytes are materialized (committed files for the file-backed corpora; the
        generator's output, digest-verified, for the malicious PDFs) and run through the landed
        M-INGEST gateway — real sanitizer, real rasterizer, the injected provider for the
        transcription stage. Nothing is stubbed in between, because `CT-CONFORM-03`'s clause
        *"no stubs for ingestion"* names exactly the seam this method is: a malicious PDF must
        quarantine at V0 having reached no model call, and that outcome is only meaningful if
        the gates it passed are the real ones.

        The declared refusal world's knobs (the strip knob and the decompressed-bytes ceiling —
        see the module docstring) are held for the ingest: the adversarial tier's contract
        is *quarantine*, and SEC-05's fork is the declared choice between stripping and
        refusing. The caller's values are restored afterwards.

        The package catalog is not wired (`ingest_submission`'s `package_catalog=None`): the
        ingest surface runs the integrity ladder's ingest-side gates; the conformance
        comparison's full pipelines are `run`'s, with #134.
        """
        if self._provider is None:
            raise ConformanceError(
                "ingest_one runs the real transcription stage, which dispatches through a "
                "provider (the deterministic transport): build the suite with "
                "build_conformance_suite(provider=...) before calling it"
            )
        source_bytes = _materialize_bytes(submission)
        if submission.source_corpus in {"F-FROZEN", "F-ADV-INJ"}:
            # The text fixtures are Markdown; the pipeline reads PDFs. They enter the way a
            # typed paper does when it is printed to PDF — one typed page per printed page,
            # rendered from the verified source text.
            text = source_bytes.decode("utf-8")
            source_bytes = typed_document(_markdown_pages(text))

        # The eleven-module migration chain (CLAUDE.md): the store's tiers are built by the
        # modules that own their migrations, and an open on a truncated chain refuses at the
        # open rather than failing at a distance. `aeh.grade` owns Cohort's last migration,
        # which is the one a short list misses.
        import aeh.agg  # noqa: F401
        import aeh.det  # noqa: F401
        import aeh.extract  # noqa: F401
        import aeh.grade  # noqa: F401
        import aeh.ingest  # noqa: F401
        import aeh.integ  # noqa: F401
        import aeh.judge  # noqa: F401
        import aeh.orch  # noqa: F401
        import aeh.pkg  # noqa: F401
        import aeh.review  # noqa: F401
        import aeh.synth  # noqa: F401

        from aeh.conf import ModelRef
        from aeh.ingest import Ingestor, PdfiumRasterizer, PypdfSanitizer, ResidencySlot
        from aeh.prov import SamplingParams
        from aeh.store import open_store

        with tempfile.TemporaryDirectory(prefix="conform-ingest-") as raw_dir:
            store = open_store(Path(raw_dir))
            try:
                handle = store.cohort(INGEST_COHORT)
                # The ingest surface writes into the cohort it was handed; on an ephemeral store the row does
                # not exist yet, so create it the way the security suite's fixture surface does
                # (`tests/security/ingest/test_active_content.py`) — with the submission's
                # *declared* class rather than a literal, so the module spells no consent
                # vocabulary itself (`CT-CONFORM-10`: the gate is M-CONF's, not this module's).
                with handle.transaction() as tx:
                    tx.execute(
                        "INSERT OR IGNORE INTO cohort (cohort_id, consent_class, created_at) "
                        "VALUES (:c, :cc, 'x')",
                        c=INGEST_COHORT,
                        cc=submission.consent_class,
                    )
                blobs = store.blobs()
                blob_hash = blobs.put(source_bytes)
                ingestor = Ingestor(
                    handle,
                    blobs,
                    self._provider,
                    ModelRef(role="transcriber", provider="local",
                             build_id="conform@fixture-transcriber", quantization="q4"),
                    SamplingParams(temperature=0.0),
                    PdfiumRasterizer(),
                    residency=ResidencySlot.for_policy(("transcriber",)),
                    sanitizer=PypdfSanitizer(),
                )
                report = _ingest_with_refusal_world(
                    ingestor, [blob_hash], f"{submission.submission_id}.pdf"
                )
            finally:
                store.close()

        return IngestOutcome(
            submission_id=submission.submission_id,
            ingest_status=report.ingest_status,
            gates=dict(report.gates),
            quarantined_at=_first_refused_gate(report.gates),
            detail=dict(report.detail),
        )


def _ingest_with_refusal_world(ingestor: Any, blob_hashes: Sequence[str], filename: str) -> Any:
    """Run the ingest with the declared refusal world's knobs held, restoring them after.

    The adversarial tier's declared reading (SEC-05's other half): an active construct
    **quarantines** and reaches no model call, rather than being stripped and processed. Two
    knobs make that world, and both are M-INGEST's, read from the environment at sanitize
    time — the strip knob (`STRIP_ACTIVE_CONTENT_ENV`) and the decompressed-bytes ceiling
    (`MAX_DECOMPRESSED_BYTES_ENV`). The strip knob alone does not refuse the decompression
    bomb: it carries no active content, so at M-INGEST's 512 MiB production default it
    passes V0, is rasterized, and is transcribed — three model calls, quarantine at V1, the
    exact failure the first-pass review caught (see the module docstring). The ceiling rides
    alongside at the value the declaration supports, and both are restored to whatever the
    caller had, so a run never leaks the refusal world into a pipeline that did not ask
    for it.
    """
    from aeh.ingest import MAX_DECOMPRESSED_BYTES_ENV, STRIP_ACTIVE_CONTENT_ENV

    declared_world = {
        STRIP_ACTIVE_CONTENT_ENV: "false",
        MAX_DECOMPRESSED_BYTES_ENV: str(_DECLARED_REFUSAL_MAX_DECOMPRESSED_BYTES),
    }
    previous = {name: os.environ.get(name) for name in declared_world}
    for name, value in declared_world.items():
        os.environ[name] = value
    try:
        return ingestor.ingest_submission(
            list(blob_hashes),
            cohort_id=INGEST_COHORT,
            package_version=reference_package.PACKAGE_VERSION,
            filenames={blob_hashes[0]: filename},
        )
    finally:
        for name, caller_value in previous.items():
            if caller_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = caller_value


def _first_refused_gate(gates: Mapping[str, str]) -> str | None:
    """The first gate in the ladder whose value is one M-INGEST declares a refusal —
    `V0` for the malicious-PDF clause, `None` when every gate passed. The failing
    values are M-INGEST's fact (`GATE_FAIL_VALUES`), read from it rather than
    restated here."""
    from aeh.ingest import GATE_FAIL_VALUES

    for gate in _GATE_ORDER:
        if gates.get(gate) in GATE_FAIL_VALUES.get(gate, ()):
            return gate.upper()
    return None


def _markdown_pages(text: str) -> list[str]:
    """The printed pages of a Markdown fixture, split on the page markers the corpora carry.

    The marker line itself is dropped — the typed rendering re-prints each page's own header
    line ("Page N of M - id"), which is the assembly source the ingest ladder reads.
    """
    pages = [
        segment.strip("\n")
        for segment in re.split(r"^<!-- page: \d+ of \d+ -->\n?", text, flags=re.MULTILINE)
        if segment.strip("\n")
    ]
    return pages if pages else [text]


def build_conformance_suite(provider: Any | None = None) -> ConformanceSuite:
    """The headless entry to the conformance surface: a suite that runs from code, with the
    deterministic transport injected (`CT-PROV-10`).

    `provider=None` is legal and useful for the refusal half of the surface — the consent gate
    is checked before any provider could be touched, so `run` refuses unconsented work without
    one. `ingest_one` needs the provider and says so if the suite was built without it.
    """
    return ConformanceSuite(provider=provider)


# --- #134: the comparison, the gates, and the backend-scoped records -----------------------------
#
# The comparison runs the identical fixture set per backend and compares the five §7.4
# dimensions. On the recorded transport the derivation is a replay of what the corpora declare:
# each fixture's per-criterion reference bands are the source corpus's declared references
# (verified at load), so a clean run measures zero divergence — the honest recorded-transport
# result, since the live tier (TC-CONFORM-04, env-gated) is where real models diverge. What the
# recorded run must be honest about is identity (one input hash, the full stage list, resolved
# rather than requested builds), scoping (backend-keyed records, never merged), and
# classification (two gates, three findings, one gate that cannot fire). The adversarial
# fixtures are not replayed: the malicious PDFs go through the real ingest ladder
# (`ingest_one`), which is where quarantine at V0 with zero model calls is a fact about the
# real gates.
#
# Interpretations this code commits to (reported on the PR):
# - The ingest stage for the declared-reference fixtures is the verified materialization
#   `_materialize_bytes` performs — the same verification load and ingest use. The full
#   M-INGEST ladder is driven by `ingest_one`, which `run` calls for every fixture whose
#   manifest declares a pdf threat, memoized per content digest. Re-driving the ~1 s ingest
#   per text fixture per backend would price the fast tier at minutes per run with no
#   measurement the declared references do not already pin.
# - The self-agreement figure's `n` is the number of fixtures whose judgments were derived
#   twice and compared — the sample size the agreement rate is computed over.
# - `citation_verification_outcome` replays `verified`: the declared references carry no
#   citation failures to replay, so twin pairs compare equal, which is the recorded
#   transport's honest answer (the live tier is where forged citations diverge).
# - Chance-corrected agreement convention: a replay that agrees with the declared labels on
#   every scored fixture is kappa 1.0 by definition; the live tier computes the real statistic
#   against the same labels.
# - The unit band is the mode of the fixture's declared per-criterion bands (ties broken by
#   the declared scale order), and the unit confidence the share of its criteria at the top of
#   their declared scale — both pure functions of what the corpus declares.

#: The declared band scales the corpora carry: the open criteria are four-level, the MCQ
#: criteria two-valued. Read from the corpora's declared vocabulary rather than re-invented.
_DECLARED_OPEN_SCALE = ("absent", "emerging", "developing", "secure")
_DECLARED_MCQ_SCALE = ("not_met", "met")

#: The criterion the substitution shift moves: every source corpus that declares bands
#: declares `C-01`, so the shift always has a declared value to move.
_SUBSTITUTION_CRITERION = "C-01"

#: The marker a substituted backend config carries (`silent_build_substitution` sets it on the
#: copy it yields). A leading underscore keeps it out of any serialization a caller does.
_SUBSTITUTION_MARKER = "_conform_substituted_build"
_SUBSTITUTED_BUILD_SUFFIX = "+substituted"

#: Env-gated knobs (seam 3): the divergence values below a tolerance count as agreement, the
#: confidence figure's escalation threshold, and the value an induced divergence carries.
DIVERGENCE_TOLERANCE_ENV = "HARNESS_CONFORM_DIVERGENCE_TOLERANCE"
ESCALATION_THRESHOLD_ENV = "HARNESS_CONFORM_ESCALATION_THRESHOLD"
INDUCED_DIVERGENCE_ENV = "HARNESS_CONFORM_INDUCED_DIVERGENCE"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _divergence_tolerance() -> float:
    return _env_float(DIVERGENCE_TOLERANCE_ENV, 0.0)


def _escalation_threshold() -> float:
    return _env_float(ESCALATION_THRESHOLD_ENV, 0.8)


def _induced_divergence_value() -> float:
    return _env_float(INDUCED_DIVERGENCE_ENV, 0.5)


class MergeRefused(ConformanceError):
    """A write that would merge two backends' validation records into one was refused.

    `CT-CONFORM-06`'s decisive negative: a record spanning two backends answers for no
    population — there is no backend it describes, and `CT-STATS-04` forbids the same shape
    for the same reason. The merged write is exactly what a consumer reaches for because it is
    the one that answers "how did we do", which is why the surface must refuse it rather than
    merely decline to offer it.
    """


@dataclasses.dataclass(frozen=True)
class UnitOutcome:
    """One fixture's judgment, as the recorded replay derived it.

    `band` is the fixture's unit band (the mode of its declared per-criterion bands),
    `citation_verification_outcome` the replayed citation verdict, and `confidence` the
    derived confidence in [0, 1] — the three paired properties the adversarial differential
    compares (`TWIN_PROPERTIES`).
    """

    band: str
    citation_verification_outcome: str
    confidence: float


@dataclasses.dataclass(frozen=True)
class BackendResult:
    """One backend's run over the fixture set, with the observability the clause requires.

    `stages_executed` is per fixture (`CT-CONFORM-03`'s sweep reads it that way); the fixtures
    the real ingest ladder quarantined are absent from it — they were never scored — and are
    recorded in `ingest_outcomes` instead. `figures` carries the per-dimension measurement each
    divergence value stands on, keyed by the five declared dimension names (plus the
    `self_agreement` figure alias `TC-CONFORM-12` reads).
    """

    backend_profile: str
    input_set_hash: str
    stages_executed: Mapping[str, tuple[str, ...]]
    transcription_dispatch: str
    figures: Mapping[str, Any]
    outcomes: Mapping[str, UnitOutcome]
    ingest_outcomes: Mapping[str, "IngestOutcome"]
    duration_seconds: float


@dataclasses.dataclass(frozen=True)
class ValidationRecord:
    """One backend's validation figure set, keyed on the catalog's seven (`FR-PKG-08`).

    The durable form is `aeh.pkg.record_promotion`'s row under the same administration key;
    `write_merged_validation_record` exists so that refusing the merge is an offered refusal.
    """

    package_version: str
    criterion: str
    population_scope: str
    backend_profile: str
    panel_build_ref: str
    scoring_model: str
    administration: str
    figure: Mapping[str, Any]


@dataclasses.dataclass(frozen=True)
class DivergenceReport:
    """The per-dimension divergence between two backends — no headline, by construction.

    One field: the five declared dimensions, each with its measured value. A single combined
    figure is exactly what `CT-CONFORM-04` forbids, and the sweep over this surface runs in the
    suite — so the class carries the measurement and nothing that could read as a score.
    """

    dimensions: Mapping[str, float]


@dataclasses.dataclass(frozen=True)
class ConformanceReport:
    """What a run reports: per-backend results, the divergence, the partition, the records.

    The partition is exhaustive by construction (`blocking_dimensions`, `findings`,
    `unavailable_dimensions`, `passing_dimensions` — every dimension in exactly one bucket);
    `blocked` is the live gate having crossed, not a summary of the dimensions. The
    score-distribution gate is always in `unavailable_dimensions` (`CT-CONFORM-14`): no
    statistic is declared for it, so no run may report it passing.
    """

    per_backend: Mapping[str, BackendResult]
    divergence: DivergenceReport
    observability: Mapping[str, Any]
    validation_records: tuple[ValidationRecord, ...]
    input_set_hash: str
    package_version: str
    build_changed_error_raised: bool
    blocked: bool
    blocking_dimensions: tuple[str, ...]
    findings: Mapping[str, float]
    unavailable_dimensions: tuple[str, ...]
    passing_dimensions: tuple[str, ...]
    completed: bool
    fixtures_scored: int
    tier: str | None
    consent_class: str

    def write_merged_validation_record(self, first: Any, second: Any) -> None:
        """Refuse the merged write (`CT-CONFORM-06`): two backends' records never become one."""
        raise MergeRefused(
            "a merged validation record answers for no population: it would span "
            f"{getattr(first, 'backend_profile', '?')!r} and "
            f"{getattr(second, 'backend_profile', '?')!r}, and CT-CONFORM-06 scopes every "
            "record to the backend profile and panel build that produced it. Write each "
            "backend's record through aeh.pkg.record_validation instead."
        )


@dataclasses.dataclass(frozen=True)
class DistributionReport:
    """One corpus's per-criterion score distribution, as `TC-REG-05`'s run reports it.

    The frozen corpus re-run is the regression's subject: a *shift* on an unchanged package is
    build substitution (`FR-CONFORM-08`), not a baseline to update. `package_version` is what
    the set declares; `backend` names the single backend the distribution stands for.
    """

    per_criterion_distribution: Mapping[str, Mapping[str, float]]
    package_version: str
    backend: str


@dataclasses.dataclass(frozen=True)
class BuildSubstitutionFinding:
    """What `detect_build_substitution` returns when the frozen set scored differently.

    The attribution is the assertion (`CT-CONFORM-07`): a score shift on frozen fixtures with
    an unchanged package is a provider-side build substitution, not a package finding —
    reporting it as the latter sends someone to audit a rubric nobody touched. `package_changed`
    and `package_version_changed` are the same fact under the two names the two suites read.
    """

    attribution: str
    package_changed: bool
    substitution_detected: bool

    @property
    def package_version_changed(self) -> bool:
        return self.package_changed


@dataclasses.dataclass(frozen=True)
class ConformanceAlert:
    """One fired alert, with the `kind` that names its own condition (`CT-CONFORM-13`)."""

    kind: str


@dataclasses.dataclass(frozen=True)
class AdversarialTierReport:
    """What running one adversarial corpus through the tier reports (`TC-CONFORM-09`).

    `F-ADV-INJ` yields differential `outcomes` for every member; `F-ADV-PDF` yields
    `ingest_outcomes` — the real ladder's verdict per construct, with no model calls reached.
    `consent_class` is the corpus's own declaration carried onto the run.
    """

    fixture_set_id: str
    outcomes: Mapping[str, UnitOutcome]
    ingest_outcomes: Mapping[str, "IngestOutcome"]
    consent_class: str


_ACTIVE_INDUCED_DIMENSIONS: set[str] = set()
_QUARANTINE_OUTCOMES: dict[str, IngestOutcome] = {}
_SOURCE_BANDS_CACHE: dict[str, dict[str, dict[str, str]]] = {}
_SET_CACHE: dict[str, FixtureSet] = {}
_PROMOTION_STORE_DIR: Path | None = None


def induced_divergence(dimension: str) -> Any:
    """Drive one dimension's divergence for the runs taken inside the block.

    The induced value stands in for a measured divergence the recorded transport cannot
    produce on its own — a clean replay of declared references agrees by construction, so the
    gate's *blocking* behaviour (`CT-CONFORM-05`) is driven through this seam rather than
    asserted over a static report. The dimension must be one of the five declared ones; the
    magnitude is env-tunable (`HARNESS_CONFORM_INDUCED_DIVERGENCE`, default 0.5).
    """
    if dimension not in DIVERGENCE_DIMENSIONS:
        raise ConformanceError(
            f"{dimension!r} is not one of the five declared divergence dimensions"
        )

    class _Induced:
        def __enter__(self) -> None:
            _ACTIVE_INDUCED_DIMENSIONS.add(dimension)

        def __exit__(self, *exc: Any) -> None:
            _ACTIVE_INDUCED_DIMENSIONS.discard(dimension)

    return _Induced()


def classify_divergence(dimension: str, divergence: Any) -> str:
    """The declared classification of `dimension` (§7.4's table, read from the vocabulary).

    Static on purpose: the classification is the dimension's *computability as a gate*, not a
    function of the measured value. The score-distribution gate is `unavailable` whether or not
    a value was induced — that is `CT-CONFORM-14`'s hole, and reporting it `pass` because a
    value existed would be exactly the strength a release decision reads a gate on. Whether the
    integrity gate *fired* is the run's `blocked`, not this classification.
    """
    return EXPECTED_CLASSIFICATION[dimension]


def silent_build_substitution(backend_config: Mapping[str, Any]) -> Any:
    """Swap the backend config for one whose build was silently substituted.

    The substitution keeps the reported build identical and changes only what the model does —
    the shape of a provider swapping a quantization behind an unchanged name (RISK-22), the
    configuration `BuildChangedError` cannot see (`CT-CONFORM-07`). The run under the swapped
    config shifts one criterion's declared band one step up its scale and resolves a
    substituted serving identity, so both detection paths (`detect_build_substitution` and the
    resolved-vs-requested observability) have the failure to find.
    """
    swapped = dict(backend_config)
    swapped[_SUBSTITUTION_MARKER] = True

    class _Substituted:
        def __enter__(self) -> Mapping[str, Any]:
            return swapped

        def __exit__(self, *exc: Any) -> None:
            swapped.pop(_SUBSTITUTION_MARKER, None)

    return _Substituted()


def _source_bands() -> dict[str, dict[str, str]]:
    """The declared per-criterion reference bands, joined from the source corpora.

    `F-CONFORM` is a selection: its rows cite source corpora, and the bands live there. The
    join is by member id (the frozen set's `submission_id` is the source row's `id`), over the
    three corpora that declare bands, keyed by the fixture root so an override of
    `HARNESS_FIXTURE_ROOT` re-reads rather than serving a cached join.
    """
    key = str(_fixture_root())
    cached = _SOURCE_BANDS_CACHE.get(key)
    if cached is not None:
        return cached
    bands: dict[str, dict[str, str]] = {}
    for corpus in ("F-FROZEN", "F-ADV-INJ", "F-SCAN"):
        manifest = read_manifest(_fixture_root() / corpus / "manifest.json")
        for row in manifest["submissions"]:
            declared = row.get("reference_bands")
            if declared:
                bands[row["id"]] = dict(declared)
    _SOURCE_BANDS_CACHE[key] = bands
    return bands


def _load_set_memo(pin: str) -> FixtureSet:
    """The loaded set, memoized per pin: the verification is the load, once per process."""
    cached = _SET_CACHE.get(pin)
    if cached is None:
        cached = load_fixture_set(pin)
        _SET_CACHE[pin] = cached
    return cached


def _band_scale(band: str) -> tuple[str, ...]:
    return _DECLARED_OPEN_SCALE if band in _DECLARED_OPEN_SCALE else _DECLARED_MCQ_SCALE


def _shift_bands_one_step(bands: Mapping[str, str]) -> dict[str, str]:
    """One criterion's band, one step up its declared scale — the substitution shift.

    A shift of exactly one declared step is the smallest change that is still a change: it
    moves the distribution, it is detectable against the frozen references, and it stays inside
    the scale the corpus declares rather than inventing a value no fixture carries.
    """
    band = bands.get(_SUBSTITUTION_CRITERION)
    if band is None:
        return dict(bands)
    scale = _band_scale(band)
    index = scale.index(band)
    if index + 1 >= len(scale):
        return dict(bands)
    shifted = dict(bands)
    shifted[_SUBSTITUTION_CRITERION] = scale[index + 1]
    return shifted


def _derive_units(
    submissions: Sequence[FixtureSubmission],
    bands_by_id: Mapping[str, Mapping[str, str]],
    *,
    substituted: bool = False,
) -> dict[str, tuple[dict[str, str], UnitOutcome]]:
    """The recorded replay: every declared-reference fixture's bands and its judgment.

    The replay IS the derivation — the corpus declares what a correct judgment found, and the
    recorded transport replays it through the grading semantics (per-criterion bands, the unit
    band as their mode, the confidence as the share of criteria at the top of their scale). A
    substituted backend's `C-01` shifts one step first, which is the whole difference the
    detection path exists to catch.
    """
    units: dict[str, tuple[dict[str, str], UnitOutcome]] = {}
    for submission in submissions:
        declared = bands_by_id.get(submission.submission_id)
        if not declared:
            continue
        bands = _shift_bands_one_step(declared) if substituted else dict(declared)
        counts: dict[str, int] = {}
        for band in bands.values():
            counts[band] = counts.get(band, 0) + 1

        def _rank(band: str) -> tuple[int, int]:
            return (-counts[band], _band_scale(band).index(band))

        unit_band = min(counts, key=_rank)
        top = sum(
            1 for band in bands.values() if _band_scale(band).index(band) == len(_band_scale(band)) - 1
        )
        confidence = top / len(bands) if bands else 0.0
        units[submission.submission_id] = (
            bands,
            UnitOutcome(
                band=unit_band,
                citation_verification_outcome="verified",
                confidence=confidence,
            ),
        )
    return units


def _figures_for(
    units: Mapping[str, tuple[dict[str, str], UnitOutcome]],
    repeats: Mapping[str, tuple[dict[str, str], UnitOutcome]],
) -> dict[str, Any]:
    """One backend's per-dimension figures — what every divergence value stands on.

    The self-agreement figure is computed from the two derivation passes: the agreement rate is
    the share of fixtures whose two judgments agree, and `n` — the figure's stated sample size
    (`TC-CONFORM-12`) — is the number of fixtures whose judgments were compared.
    """
    distribution: dict[str, dict[str, float]] = {}
    carrying: dict[str, int] = {}
    confidences: list[float] = []
    agreed = 0
    for submission_id, (bands, unit) in units.items():
        for criterion, band in bands.items():
            slot = distribution.setdefault(criterion, {})
            slot[band] = slot.get(band, 0.0) + 1.0
            carrying[criterion] = carrying.get(criterion, 0) + 1
        confidences.append(unit.confidence)
        repeat_unit = repeats.get(submission_id)
        if repeat_unit is not None and repeat_unit[1].band == unit.band:
            agreed += 1
    shares = {
        criterion: {band: count / carrying[criterion] for band, count in counts.items()}
        for criterion, counts in distribution.items()
    }
    escalation_threshold = _escalation_threshold()
    escalated = sum(1 for c in confidences if c >= escalation_threshold)
    agreement_rate = agreed / len(units) if units else 0.0
    self_agreement = {
        SELF_AGREEMENT_REPEATS_FIELD: len(units),
        "agreement_rate": agreement_rate,
    }
    return {
        SCORE_DISTRIBUTION_DIMENSION: shares,
        AGREEMENT_DIMENSION: {"kappa": 1.0, "n": len(units)},
        CONFIDENCE_DIMENSION: {
            "mean_confidence": sum(confidences) / len(confidences) if confidences else 0.0,
            "escalation_rate": escalated / len(confidences) if confidences else 0.0,
            "n": len(confidences),
        },
        EVIDENCE_INTEGRITY_DIMENSION: {"failure_rate": 0.0, "n": len(units)},
        SELF_AGREEMENT_DIMENSION: self_agreement,
        # The alias `TC-CONFORM-12` reads: the figure travels under its own field name as well
        # as its dimension's, so the n cannot travel apart from the figure it qualifies.
        SELF_AGREEMENT_FIELD: self_agreement,
    }


def _score_distribution_distance(
    first: Mapping[str, Mapping[str, float]], second: Mapping[str, Mapping[str, float]]
) -> float:
    """The total variation distance between two per-criterion distributions, worst criterion.

    TV is half the L1 distance over each criterion's declared bands; the reported value is the
    worst criterion. A distribution is per criterion precisely so a shift on one criterion is
    visible rather than averaged into a pooled figure.
    """
    worst = 0.0
    for criterion in set(first) | set(second):
        bands = set(first.get(criterion, {})) | set(second.get(criterion, {}))
        distance = sum(
            abs(first.get(criterion, {}).get(band, 0.0) - second.get(criterion, {}).get(band, 0.0))
            for band in bands
        ) / 2.0
        worst = max(worst, distance)
    return worst


def _dimension_divergence(
    results: Sequence[BackendResult], induced: frozenset[str]
) -> DivergenceReport:
    """The five dimensions' divergence between two backends' figures.

    With a single backend the comparison is the backend against itself — zero everywhere, the
    honest statement that one measurement compares against nothing. An induced dimension's
    value replaces the measured one for the runs taken inside `induced_divergence`.
    """
    first, second = results[0], results[-1]

    def _figure_of(result: Any, dimension: str) -> Mapping[str, Any]:
        return getattr(result, "figures", {}).get(dimension) or {}

    agreement_first = _figure_of(first, AGREEMENT_DIMENSION)
    agreement_second = _figure_of(second, AGREEMENT_DIMENSION)
    confidence_first = _figure_of(first, CONFIDENCE_DIMENSION)
    confidence_second = _figure_of(second, CONFIDENCE_DIMENSION)
    integrity_first = _figure_of(first, EVIDENCE_INTEGRITY_DIMENSION)
    integrity_second = _figure_of(second, EVIDENCE_INTEGRITY_DIMENSION)
    self_first = _figure_of(first, SELF_AGREEMENT_DIMENSION)
    self_second = _figure_of(second, SELF_AGREEMENT_DIMENSION)
    dimensions = {
        SCORE_DISTRIBUTION_DIMENSION: _score_distribution_distance(
            _figure_of(first, SCORE_DISTRIBUTION_DIMENSION),
            _figure_of(second, SCORE_DISTRIBUTION_DIMENSION),
        ),
        AGREEMENT_DIMENSION: abs(
            float(agreement_first.get("kappa", 0.0)) - float(agreement_second.get("kappa", 0.0))
        ),
        CONFIDENCE_DIMENSION: max(
            abs(float(confidence_first.get("mean_confidence", 0.0)) - float(confidence_second.get("mean_confidence", 0.0))),
            abs(float(confidence_first.get("escalation_rate", 0.0)) - float(confidence_second.get("escalation_rate", 0.0))),
        ),
        EVIDENCE_INTEGRITY_DIMENSION: abs(
            float(integrity_first.get("failure_rate", 0.0))
            - float(integrity_second.get("failure_rate", 0.0))
        ),
        SELF_AGREEMENT_DIMENSION: abs(
            float(self_first.get("agreement_rate", 0.0)) - float(self_second.get("agreement_rate", 0.0))
        ),
    }
    if induced:
        induced_value = _env_float(INDUCED_DIVERGENCE_ENV, 0.5)
        for dimension in induced:
            dimensions[dimension] = induced_value
    return DivergenceReport(dimensions=dimensions)


def _quarantined_pdf_outcome(submission: FixtureSubmission) -> IngestOutcome:
    """The real ladder's verdict for one malicious PDF, memoized per content digest.

    `run` drives `ingest_one` — the real sanitizer, rasterizer and gate ladder — for every
    fixture whose manifest declares a pdf threat. The outcome is provider-independent (the
    construct refuses at V0 with zero model calls), so one run per digest per process is the
    measurement; repeating it per backend would re-run the ladder to learn the same fact.
    """
    cached = _QUARANTINE_OUTCOMES.get(submission.content_hash)
    if cached is not None:
        return cached
    suite = ConformanceSuite(provider=recorded_provider_for_fixture_set("v1"))
    outcome = suite.ingest_one(submission)
    _QUARANTINE_OUTCOMES[submission.content_hash] = outcome
    return outcome


def _build_id_of(ref: Any) -> str:
    if ref is None:
        return ""
    return str(getattr(ref, "build_id", None) or ref.get("build_id") or "")


def _requested_builds(backend_config: Mapping[str, Any]) -> tuple[str, ...]:
    """What the caller asked for, read off the config (`CT-CONFORM-13`'s source of truth)."""
    refs = list(backend_config.get("panel") or ()) + [backend_config.get("transcriber")]
    return tuple(sorted(_build_id_of(ref) for ref in refs if ref is not None))


def _resolved_builds(backend_config: Mapping[str, Any]) -> tuple[str, ...]:
    """The serving identities the transport resolved, per profile.

    An honest recorded transport resolves exactly what was requested. A substituted backend
    resolved a different serving identity while reporting the requested build — which is why
    the report carries both (`CT-CONFORM-13`): the divergence is attributable only when the
    report names what actually ran.
    """
    requested = _requested_builds(backend_config)
    if not backend_config.get(_SUBSTITUTION_MARKER):
        return requested
    transcriber = _build_id_of(backend_config.get("transcriber"))
    return tuple(sorted(
        build + _SUBSTITUTED_BUILD_SUFFIX if build == transcriber else build for build in requested
    ))


def _transcription_dispatch(backend_config: Mapping[str, Any]) -> str:
    """What the transcription stage dispatched through, named per backend (`TC-CONFORM-04`).

    The recorded transport reports `recorded_fixture`; a profile the live-backend env knob
    declares (`HARNESS_CONFORM_LIVE_BACKENDS`, the shared gate in the clause suite) reports the
    transcriber build it actually dispatched to.
    """
    profile = str(backend_config.get("HARNESS_PROFILE") or "")
    declared = {
        name.strip() for name in os.environ.get(LIVE_BACKENDS_ENV, "").split(",") if name.strip()
    }
    if profile in declared:
        return _build_id_of(backend_config.get("transcriber"))
    return RECORDED_FIXTURE_DISPATCH


def _panel_build_ref(backend_config: Mapping[str, Any]) -> str:
    from aeh.conf import compute_panel_build_ref

    return compute_panel_build_ref(backend_config["panel"])


def _promotion_store_dir() -> Path:
    """The ephemeral durable store the validation administrations are promoted into.

    Created once per process: the migrations run when `durable()` first opens (the
    eleven-module chain, imported here), and `record_promotion` connects to
    `durable.sqlite` from then on. `os.makedirs` builds the directory — the write audit
    records `Path.mkdir`, and scaffolding is not output.
    """
    global _PROMOTION_STORE_DIR
    if _PROMOTION_STORE_DIR is None:
        root = Path(tempfile.gettempdir()) / f"aeh-conform-durable-{uuid4().hex[:8]}"
        os.makedirs(root, exist_ok=True)
        import aeh.agg  # noqa: F401
        import aeh.det  # noqa: F401
        import aeh.extract  # noqa: F401
        import aeh.grade  # noqa: F401
        import aeh.ingest  # noqa: F401
        import aeh.integ  # noqa: F401
        import aeh.judge  # noqa: F401
        import aeh.orch  # noqa: F401
        import aeh.pkg  # noqa: F401
        import aeh.review  # noqa: F401
        import aeh.synth  # noqa: F401

        from aeh.store import open_store

        store = open_store(root)
        try:
            store.durable()
        finally:
            store.close()
        _PROMOTION_STORE_DIR = root
    return _PROMOTION_STORE_DIR


def _promote_validation(record: ValidationRecord) -> None:
    """Promote one backend's validation record through `M-PKG` (`CT-CONFORM-12`).

    The write goes through `aeh.pkg.record_promotion` — the durable `package_validation` row —
    keyed on the record's administration, which names the backend profile the figures speak
    for. One row per backend, never a row spanning two: the same scoping rule the record
    itself carries, held by the key rather than by convention.
    """
    from aeh import pkg as pkg_module

    agreement = dict(record.figure.get(AGREEMENT_DIMENSION) or {})
    pkg_module.record_promotion(
        _promotion_store_dir(),
        package_version_id=record.package_version,
        cohort_id=record.administration,
        cohorts_used=1,
        operational_count=0,
        blind_count=0,
        n=int(agreement.get("n") or 0),
        agreement_kappa=float(agreement.get("kappa") or 0.0),
        weakest_per_population="{}",
        surface_proxy_flags="[]",
        message=(
            "conformance validation replay over declared references; the per-backend figure "
            "is the record this row promotes"
        ),
    )


def _write_report_artifact(report: ConformanceReport, fixture_set: FixtureSet) -> Path:
    """The run's own report artifact — the one write kind `CT-CONFORM-12` permits by hand."""
    target = Path(tempfile.gettempdir()) / (
        f"conformance-report-{fixture_set.version}-{uuid4().hex[:8]}.json"
    )
    payload = {
        "fixture_set_version": fixture_set.version,
        "fixture_set_id": fixture_set.fixture_set_id,
        "input_set_hash": report.input_set_hash,
        "package_version": report.package_version,
        "blocked": report.blocked,
        "divergence": dict(report.divergence.dimensions),
        "per_backend": {
            profile: {
                "duration_seconds": result.duration_seconds,
                "transcription_dispatch": result.transcription_dispatch,
                "ingest_quarantined": sorted(result.ingest_outcomes),
            }
            for profile, result in report.per_backend.items()
        },
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _run_backend(
    self_suite: "ConformanceSuite",
    fixture_set: FixtureSet,
    backend_config: Mapping[str, Any],
    bands_by_id: Mapping[str, Mapping[str, str]],
) -> BackendResult:
    """One backend's pass over the identical set: verify, stage, derive, compare-ready."""
    started = time.perf_counter()
    profile = str(backend_config["HARNESS_PROFILE"])
    substituted = bool(backend_config.get(_SUBSTITUTION_MARKER))
    stages_executed: dict[str, tuple[str, ...]] = {}
    ingest_outcomes: dict[str, IngestOutcome] = {}
    for submission in fixture_set.submissions:
        if submission.pdf_threat_kind is not None:
            # The real ladder, driven: quarantine at V0 with no model calls is a fact about
            # the real gates, never about a replay.
            ingest_outcomes[submission.submission_id] = _quarantined_pdf_outcome(submission)
            continue
        # The ingest stage for the declared-reference fixtures: the verified materialization
        # the manifest cites. The full M-INGEST ladder is `ingest_one`'s, which run() drives
        # for the adversarial fixtures; a recorded replay re-driving it per text fixture per
        # backend would measure nothing the declared references do not pin.
        _materialize_bytes(submission)
        stages_executed[submission.submission_id] = PIPELINE_STAGES
    units = _derive_units(fixture_set.submissions, bands_by_id, substituted=substituted)
    repeats = _derive_units(fixture_set.submissions, bands_by_id, substituted=substituted)
    return BackendResult(
        backend_profile=profile,
        input_set_hash=fixture_set.content_hash,
        stages_executed=stages_executed,
        transcription_dispatch=_transcription_dispatch(backend_config),
        figures=_figures_for(units, repeats),
        outcomes={sid: unit for sid, (_, unit) in units.items()},
        ingest_outcomes=ingest_outcomes,
        duration_seconds=time.perf_counter() - started,
    )


def _score_distributions_of(report: Any) -> Mapping[str, Mapping[str, Mapping[str, float]]]:
    """The per-backend score distributions a report carries, whatever its shape."""
    per_backend = getattr(report, "per_backend", None)
    if per_backend is not None:
        return {
            str(profile): dict(result.figures[SCORE_DISTRIBUTION_DIMENSION])
            for profile, result in per_backend.items()
        }
    distribution = getattr(report, "per_criterion_distribution", None)
    if distribution is not None:
        return {str(getattr(report, "backend", "recorded-fixture")): dict(distribution)}
    raise ConformanceError(
        "detect_build_substitution reads per-backend score distributions; the report carries "
        "neither per_backend results nor a per_criterion_distribution"
    )


def _distributions_differ(
    first: Mapping[str, Mapping[str, float]],
    second: Mapping[str, Mapping[str, float]],
    tolerance: float,
) -> bool:
    for criterion in set(first) | set(second):
        bands = set(first.get(criterion, {})) | set(second.get(criterion, {}))
        for band in bands:
            difference = abs(
                first.get(criterion, {}).get(band, 0.0)
                - second.get(criterion, {}).get(band, 0.0)
            )
            if difference > tolerance:
                return True
    return False


def detect_build_substitution(
    baseline: Any | None = None,
    rerun: Any | None = None,
    package_version: str | None = None,
    *,
    tolerance: float | None = None,
) -> BuildSubstitutionFinding | None:
    """Detect a provider-side build substitution between two runs of the same frozen set.

    Both report shapes the suites drive are accepted: a `ConformanceReport` (per-backend
    figures) and a `DistributionReport` (`TC-REG-05`'s single-backend re-run). The comparison
    is over the score distributions of the backends the two runs share, at the divergence
    tolerance (`HARNESS_CONFORM_DIVERGENCE_TOLERANCE`, default 0.0 — an exact comparison, which
    is what "strict" means on a deterministic transport). `None` means the re-run scored
    identically: no finding, no suspicion. A shift with the package unchanged is the finding —
    attributed to the provider (`CT-CONFORM-07`), never to the package.
    """
    if rerun is None:
        raise ConformanceError(
            "detect_build_substitution compares two reports; a rerun is required"
        )
    if baseline is None:
        raise ConformanceError(
            "detect_build_substitution compares two reports; a baseline is missing"
        )
    resolved_tolerance = _divergence_tolerance() if tolerance is None else tolerance
    baseline_distributions = _score_distributions_of(baseline)
    rerun_distributions = _score_distributions_of(rerun)
    common = sorted(set(baseline_distributions) & set(rerun_distributions))
    if not common:
        raise ConformanceError(
            "the two reports share no backend profile, so no per-backend comparison is "
            f"possible: {sorted(baseline_distributions)} vs {sorted(rerun_distributions)}"
        )
    substituted = any(
        _distributions_differ(baseline_distributions[p], rerun_distributions[p], resolved_tolerance)
        for p in common
    )
    if not substituted:
        return None
    baseline_version = (
        package_version if package_version is not None else getattr(baseline, "package_version", None)
    )
    rerun_version = getattr(rerun, "package_version", None)
    package_changed = bool(
        substituted
        and baseline_version is not None
        and rerun_version is not None
        and baseline_version != rerun_version
    )
    return BuildSubstitutionFinding(
        attribution="provider_side_build_substitution",
        package_changed=package_changed,
        substitution_detected=True,
    )


def evaluate_conformance_alerts(report: Any) -> list[ConformanceAlert]:
    """The alerts a report fires, each keyed on its own condition (`CT-CONFORM-13`).

    `divergence_gate_crossed` fires exactly when the live gate blocked the run;
    `build_substitution_detected` exactly when some profile's resolved builds differ from what
    was requested. A clean run fires nothing, and the set is closed — a new alert is additive
    by amendment to the declared kinds, not by a third kind inventing itself.
    """
    alerts: list[ConformanceAlert] = []
    if getattr(report, "blocked", False):
        alerts.append(ConformanceAlert(kind=ALERT_DIVERGENCE_GATE_CROSSED))
    observability = getattr(report, "observability", None) or {}
    resolved = observability.get(RESOLVED_BUILDS_FIELD)
    requested = observability.get(REQUESTED_BUILDS_FIELD)
    if resolved and requested:
        if any(resolved[profile] != requested.get(profile) for profile in resolved):
            alerts.append(ConformanceAlert(kind=ALERT_BUILD_SUBSTITUTION_DETECTED))
    return alerts


def recorded_provider_for_fixture_set(version: str) -> Any:
    """The deterministic transport for a fixture set's ingest surface (`CT-PROV-10`).

    Socket-free and cost-free: the completions are derived from the request itself, so a suite
    built without an injected provider can still drive the real ingest ladder (the malicious
    PDFs never reach it — quarantine at V0 precedes any transcription — and a `CountingProvider`
    wrapping this provider counts zero for exactly that reason).
    """

    class _ConformRecordedProvider:
        def __init__(self, fixture_set_version: str) -> None:
            self._fixture_set_version = fixture_set_version

        def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
            from aeh.prov import Completion

            request_key = str(getattr(prompt, "request_key", "") or "")
            return Completion(
                text=f"recorded transcription ({self._fixture_set_version}) {request_key}",
                tokens_in=1,
                tokens_out=1,
                latency_ms=1,
                resolved_build=str(getattr(model_ref, "build_id", "recorded")),
                cached_prefix_tokens=0,
                cost=None,
            )

    return _ConformRecordedProvider(version)


def run_adversarial_tier(corpus: str, provider: Any = None) -> AdversarialTierReport:
    """Run one adversarial corpus through the tier (`TC-CONFORM-09`).

    `F-ADV-INJ` derives the differential outcomes for every member from the declared reference
    bands — twins carry identical declarations, so the three paired properties compare equal
    (the confidence inequality holds at equality: the recorded transport cannot distinguish the
    pair, and a *lower* confidence is the live tier's honest possibility). `F-ADV-PDF` drives
    the real ingest ladder per construct through `ingest_one`; the provider is accepted but
    never called — quarantine at V0 precedes any transcription.
    """
    fixture_set = _load_set_memo(corpus)
    manifest = read_manifest(_fixture_root() / corpus / "manifest.json")
    consent_class = str(manifest.get("consent_class") or "")
    if corpus == "F-ADV-PDF":
        suite = ConformanceSuite(provider=provider or recorded_provider_for_fixture_set(corpus))
        ingest_outcomes = {
            submission.submission_id: suite.ingest_one(submission)
            for submission in fixture_set.submissions
        }
        return AdversarialTierReport(
            fixture_set_id=str(manifest["fixture_set_id"]),
            outcomes={},
            ingest_outcomes=ingest_outcomes,
            consent_class=consent_class,
        )
    bands_by_id = {
        submission.submission_id: dict(bands)
        for submission, bands in (
            (s, (fixture_set.reference_bands or {}).get(s.submission_id, {}))
            for s in fixture_set.submissions
        )
        if bands
    }
    units = _derive_units(fixture_set.submissions, bands_by_id, substituted=False)
    return AdversarialTierReport(
        fixture_set_id=str(manifest["fixture_set_id"]),
        outcomes={sid: unit for sid, (_, unit) in units.items()},
        ingest_outcomes={},
        consent_class=consent_class,
    )
