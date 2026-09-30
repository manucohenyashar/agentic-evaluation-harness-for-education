"""Loading the version-pinned fixture set, verifying each fixture's bytes against its digest."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from harness.corpora import adv_pdf
from harness.corpora.manifest import CORPUS_ROOT, ManifestEntry, read_manifest, set_content_hash

from .constants import CORPUS_NAME, FIXTURE_ROOT_ENV
from .errors import ConformanceError, StaleFixtureError
from .bands import _shift_bands_one_step, _SUBSTITUTION_CRITERION
from .reports import DistributionReport


@dataclasses.dataclass(frozen=True)
class FixtureSubmission:
    """One fixture, with everything about it declared rather than guessed.

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
        """A copy of the fixture with a different reference score. Changing any declared value must
        change the set's hash (NFR-CONFORM-01), and this is how that is tested."""
        return dataclasses.replace(self, reference_score=score)

    def declared_digest(self) -> str:
        """The digest of everything this fixture declares: its contribution to the set's hash.

        Over the **declared** fields rather than the source bytes: the set's identity is what a
        result cites, and a reference score corrected in the manifest must move it even though
        no byte on disk changed. The source digest rides inside the payload, so a re-anchored
        fixture moves the set hash too.
        """
        payload = json.dumps(dataclasses.asdict(self), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclasses.dataclass(frozen=True)
class FixtureSet:
    """A loaded fixture set: a version, an order, and a hash over both.

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
        """Replace one submission by name. A replacement with a different id is refused, because it
        would silently change what the set is identified by."""
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
        """The set's declared score distribution per criterion, as if one backend had run it.

        This is `TC-REG-05`'s surface: the frozen corpus re-run and its per-criterion band
        shares recomputed, so a *shift* on an unchanged package can be detected as build
        substitution (`FR-CONFORM-08`) rather than absorbed as a new baseline. `backend` names
        the (single) backend the distribution stands for — the frozen set carries the declared
        references, and the recorded transport replays them; `simulate_build_change` applies the
        substitution shift (one criterion, one step up its declared scale) so the detection path
        has a shift to catch.
        """
        distribution: dict[str, dict[str, float]] = {}
        unshifted: dict[str, dict[str, float]] = {}
        carrying: dict[str, int] = {}
        declared_bands = self.reference_bands or {}
        for submission in self.submissions:
            bands = dict(declared_bands.get(submission.submission_id, {}))
            if not bands:
                continue
            if simulate_build_change:
                plain = dict(declared_bands.get(submission.submission_id, {}))
                for criterion, band in plain.items():
                    counts = unshifted.setdefault(criterion, {})
                    counts[band] = counts.get(band, 0.0) + 1.0
                bands = _shift_bands_one_step(bands)
            for criterion, band in bands.items():
                counts = distribution.setdefault(criterion, {})
                counts[band] = counts.get(band, 0.0) + 1.0
                carrying[criterion] = carrying.get(criterion, 0) + 1
        shares = {
            criterion: {band: n / carrying[criterion] for band, n in counts.items()}
            for criterion, counts in distribution.items()
        }
        if simulate_build_change:
            plain_shares = {
                criterion: {band: n / carrying[criterion] for band, n in counts.items()}
                for criterion, counts in unshifted.items()
            }
            if shares == plain_shares:
                raise ConformanceError(
                    "the simulated build shift moved nothing: every fixture's "
                    f"{_SUBSTITUTION_CRITERION!r} band already sat at the top of its declared "
                    "scale, so the rerun equals the baseline and would measure a substitution "
                    "that was not applied (FR-CONFORM-08's detection needs a shift that exists)"
                )
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
    """The manifest version a pin label names; `v1` and `1` are the same set.

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
    """A fixture's source bytes, checked against the digest it records.

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
    """Load the fixture set for a pinned version (FR-CONFORM-01, NFR-CONFORM-01).

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
    """Load a source corpus (such as `F-FROZEN`) as a fixture set, with its declared bands.

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
