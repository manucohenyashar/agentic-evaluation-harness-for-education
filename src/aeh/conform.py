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
from pathlib import Path
from typing import Any, Mapping, Sequence

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
    """
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
    fixtures = FixtureSet(version=manifest["version"], submissions=submissions)
    # The verification IS the load: an entry whose source bytes moved is a refusal here, not a
    # surprise in the middle of a measured run.
    for submission in submissions:
        _materialize_bytes(submission)
    return fixtures


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
    ) -> Any:
        """Run the identical fixture set through the full pipeline on every backend.

        The consent gate is the surface and it is live: every backend config is checked against
        the cohort through `M-CONF` before anything else happens, and a cohort not so flagged is
        refused before a single fixture is read — sending unconsented work anywhere is the
        failure the gate exists to make impossible.

        The divergence measurement itself is #134's (design §3.18's run/compare pair against
        `DivergenceReport`, with the build-substitution detection the clause pairs with it).
        Until that story lands the run stops here, loudly, rather than returning a report that
        measured nothing.
        """
        configs = list(backend_configs)
        if not configs:
            raise ConformanceError(
                "a conformance run needs at least one backend config; nothing was given"
            )
        for backend_config in configs:
            self._enforce_consent(backend_config, cohort)
        raise NotImplementedError(
            "ConformanceSuite.run measures backend divergence over the fixture set; that "
            "machinery (per-backend pipeline, build-substitution detection, the five "
            "divergence dimensions) is #134's. #133 delivers the fixture set, the consent "
            "boundary above, and ingest_one."
        )

    def compare(self, a: Any, b: Any) -> Any:
        """The divergence comparison — declared by design §3.18's Protocol, built by #134."""
        raise NotImplementedError(
            "ConformanceSuite.compare reports per-dimension divergence between two backends' "
            "results; the divergence machinery is #134's."
        )

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

        # The ten-module migration chain (CLAUDE.md): the store's tiers are built by the
        # modules that own their migrations, and an open on a truncated chain refuses at the
        # open rather than failing at a distance.
        import aeh.agg  # noqa: F401
        import aeh.det  # noqa: F401
        import aeh.extract  # noqa: F401
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
