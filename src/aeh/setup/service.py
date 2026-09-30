"""`SetupService`: runs the setup steps for one package version and publishes it."""

from __future__ import annotations

from typing import Any, NoReturn

from aeh.pkg import PackageCatalog, PackageVersionId
from aeh.prov import InferenceProvider, ModelRef, SamplingParams

from .settings import LOGGER
from .errors import SetupOrderError
from .records import InventoryProposal
from .inventory import InventoryStepMixin, _proposal_from_row
from .readback import ReadbackStepMixin
from .keys_and_policy import KeysAndPolicyMixin
from .decomposability import DecomposabilityMixin
from .dependencies import DependencyStepMixin
from .progress import ProgressMixin


def setup_service_for_store(
    store: Any, package_id: str, *, provider: Any = None, model_ref: Any = None,
    cohort_id: str | None = None,
) -> "SetupService":
    """A `SetupService` over a real store's package (the console's setup door, #398).

    The rubric read-back reads stored documents through `M-INGEST`, so when a `cohort_id`
    and a model are given an `Ingestor` over that cohort is bound. It only reads documents:
    no page is rasterized or sanitized here, so those seams stay unbound. Without them, the
    confirm and answer-key steps still work, since they call no model."""
    from aeh.ingest import Ingestor
    from aeh.prov import SamplingParams

    catalog = PackageCatalog(store.package(package_id), package_id=package_id)
    ingestor = None
    if cohort_id and provider is not None and model_ref is not None:
        ingestor = Ingestor(store.cohort(cohort_id), store.blobs(), provider, model_ref,
                            SamplingParams(temperature=0.0), None, sanitizer=None)
    return SetupService(catalog, ingestor, provider, model_ref)


class SetupService(InventoryStepMixin, ReadbackStepMixin, KeysAndPolicyMixin, DecomposabilityMixin, DependencyStepMixin, ProgressMixin):
    """M-SETUP's Stage A, end to end, from code (`CT-SETUP-11`'s headless driver).

    `SetupService(catalog, ingestor, provider, model_ref)` — the Tier P catalog the
    package lives in, the `M-INGEST` gateway the assessment is read through, and the
    `M-PROV` seam the proposal call goes through. `params` defaults to
    `SamplingParams(temperature=0.0)`: a proposal is a reading task, not a sampling
    one.

    Design §3.6's protocol, and what this story stages:

    ============================  =============================================
    operation                     status
    ============================  =============================================
    `propose_inventory`           here — one proposal per version (`CT-SETUP-16`)
    `confirm_inventory`           here — BLOCKING gate 1; locks the rows
    `read_back_rubric`            here — #51: criteria and even band sets, magnitude
                                  descriptors rejected and re-requested; one read
                                  back per version (`CT-SETUP-16`)
    `set_answer_keys`             here — BLOCKING gate 2; the full FR-SETUP-03
                                  semantics since #53 (the confirmed inventory's
                                  deterministic criteria are staged, every key is
                                  validated against its question's options)
    `classify_decomposability`    here — #52: the §5.3 ANSWERS from the model, the
                                  decision table from the module; confirmations
                                  capped at `SETUP_MAX_CONFIRMATIONS` headlessly
    `confirm_classifications`     here — #52: the teacher's confirmation recorded
                                  apart from the module's default (`R62`)
    `propose_dependencies`        here — #52: plain-language proposals, nothing
                                  written; `confirm_dependencies` writes only on
                                  explicit approval
    `publish`                     here — refused until both gates hold; records
                                  each skipped step's default (FR-SETUP-14)
    `ensure_version`, `steps`,    here — the resume and console surfaces
    `current_proposal`
    `set_grade_policy`            here — #53: the declared policy, or the default
                                  taken explicitly and recorded (FR-SETUP-12)
    `check_prefix_budget`         here — #53: per-(question, criterion) counts,
                                  lowest-value exemplar drops behind a calibration
                                  floor (FR-SETUP-11)
    `store_calibration_papers`    here — #53: stored-not-used intake; ambiguity
                                  discovery waits for M-CALIB (FR-SETUP-15)
    ============================  =============================================
    """

    def __init__(
        self, catalog: PackageCatalog, ingestor: Any, provider: InferenceProvider,
        model_ref: ModelRef, *, params: SamplingParams | None = None,
        run_config: Any = None,
    ) -> None:
        self._catalog = catalog
        self._ingestor = ingestor
        self._provider = provider
        self._model_ref = model_ref
        self._params = params if params is not None else SamplingParams(temperature=0.0)
        # The resolved run config (`FR-SETUP-11`, #53): the prefix-budget check
        # compares against ITS per-profile `prefix_token_ceiling` (FR-CONF-06/-10;
        # aeh.conf's RunConfig is the intended shape, consumed duck-typed so the
        # import graph stays the store boundary — CT-SETUP-16). Optional so a
        # harness that stages setup before a run config is resolved still
        # constructs; the fallback is documented at
        # `SETUP_PREFIX_TOKEN_CEILING_DEFAULT`.
        self._run_config = run_config
        # The confirmation cap's counter (`FR-SETUP-07`, `CT-SETUP-13`): confirmations
        # REQUESTED per draft version, this service's accounting of what the teacher
        # has been asked so far. Keyed by version so one service carrying several
        # drafts never lets one package's spend buy another's confirmations.
        self._confirmations_requested: dict[str | None, int] = {}

    @property
    def package_id(self) -> str:
        """The package this service stages, as the catalog knows it."""
        return self._catalog.package_id

    # -- the version and the resume surface -------------------------------------------------

    def ensure_version(self) -> PackageVersionId:
        """The draft version setup works on, minted on first call: the package row and
        its initial version are exactly what `create_version` refuses to mint itself
        (`FR-SETUP-16`'s first move). Resumption calls this and gets the SAME draft —
        the latest unpublished version — because state is the database (`CT-SETUP-03`).

        On a package whose setup has FINISHED this is the mint route's refusal
        (`CT-SETUP-16`'s no-route half, #229): no draft exists and every version is
        published, so minting would open a second Stage A — a fresh root version — on
        the same package. The refusal names the published version that blocked it;
        a new instrument is a new package or a revision (`FR-PKG-02`), never a
        setup operation."""
        draft = self._catalog.draft_version()
        if draft is not None:
            return draft
        if self._catalog.has_version():
            self._refuse_finished_package()
        self._catalog.ensure_package()
        version = self._catalog.create_version(None)
        LOGGER.info("minted initial package version %s for setup", version)
        return version

    def current_proposal(self) -> InventoryProposal | None:
        """The draft version's stored proposal, or None — what a resuming console
        re-renders without calling the model again."""
        v = self._catalog.draft_version()
        if v is None:
            return None
        stored = self._catalog.proposal(v)
        return _proposal_from_row(v, stored) if stored else None

    def publish(self, approved_by: str) -> PackageVersionId:
        """Publish the version — the point the §6.2 lock takes effect (`FR-SETUP-02`).

        Both blocking gates are checked HERE and refused with the gate named: the
        confirmed inventory (gate 1) and every deterministic criterion keyed (gate 2).
        Beside them, the `FR-SETUP-09` structural check refuses a draft whose judged
        criteria do not each carry an `evidence_type` (#232, `TC-SETUP-12`).
        The publication itself is `M-PKG`'s one-transaction lock flip (`FR-PKG-01`) —
        setup assembles and gates; the Tier P writer writes (`CT-PKG-12`)."""
        v = self._require_draft_version()
        self._refuse_unmet_gates(v)
        self._record_uncompleted_step_default(v)
        self._catalog.publish(v, approved_by)
        LOGGER.info(
            "published package version %s by %r — both blocking gates satisfied; the "
            "§6.2 schema lock now holds (FR-SETUP-02)", v, approved_by,
        )
        return v

    def _refuse_finished_package(self) -> NoReturn:
        """The post-publish refusal every mutating entry point shares (`CT-SETUP-16`'s
        no-route half, #229): the package's versions are all published, so setup has
        nothing left to offer — the error names the published version that blocked it
        (`RISK-06`'s setup end), never a bare "finished" flag a caller could reason
        around."""
        latest_reader = getattr(self._catalog, "latest_version", None)
        latest = latest_reader() if latest_reader is not None else None
        blocked = (
            f"version {latest!r} is published and locked (FR-SETUP-02)"
            if latest is not None else "its version is published"
        )
        raise SetupOrderError(
            f"no unpublished version exists for package {self.package_id!r} — "
            f"setup has finished: {blocked}; a new instrument is a new package or "
            "a revision (FR-PKG-02), not a setup operation (CT-SETUP-16)."
        )

    def _require_draft_version(self) -> PackageVersionId:
        """The draft the operation works on, or the honest refusal: a package whose
        setup has finished has a published version and no draft, and operating on a
        published version is not setup's business — that refusal names the published
        version that blocked it (#229's observability half). The other no-draft state
        is a package that never started, and keeps the mint hint."""
        v = self._catalog.draft_version()
        if v is None:
            if self._catalog.has_version():
                self._refuse_finished_package()
            raise SetupOrderError(
                f"no unpublished version exists for package {self.package_id!r} — "
                "the initial version was never minted: call ensure_version() first."
            )
        return v

    def _refuse_unmet_gates(self, v: PackageVersionId) -> None:
        """The two blocking gates, each refused with its number and its unblocking
        step — the console renders the refusal verbatim (`FR-CONSOLE-06`: exactly two
        screens block) — and beside them the structural check `FR-SETUP-09` owes
        publication: no judged criterion without its `evidence_type` locks (#232)."""
        stored = self._catalog.proposal(v)
        if stored is None or stored["confirmed_at"] is None:
            raise SetupOrderError(
                "publish refused: the question inventory is not confirmed — blocking "
                "gate 1 of 2 (§4.2.1). The teacher's confirmation is the assertion "
                "the §6.2 lock records (FR-SETUP-02): confirm_inventory first."
            )
        unkeyed = [
            row["criterion_id"] for row in self._catalog.criteria(v)
            if row.get("scoring_model") == "atomic" and not row.get("answer_key")
        ]
        if unkeyed:
            raise SetupOrderError(
                "publish refused: answer keys missing for the deterministic criteria "
                f"{', '.join(unkeyed)} — blocking gate 2 of 2 (§4.2.1): "
                "set_answer_keys first."
            )
        # The structural check beside the two blocking gates (`FR-SETUP-09`, #232): a
        # JUDGED criterion — kind `open`, the kind the judged set is (`aeh.pkg`,
        # `PackageDraft`: "criteria names the judged criteria as bare ids (kind
        # `open`...)") — must carry its `evidence_type`, the declaration M-INTEG routes
        # on (`FR-INTEG-03`). The read back attaches the default when the model
        # proposes none, so a judged criterion without one entered the package outside
        # the read back (the degraded path's hand-entry, `needs_manual_entry`) — and a
        # package cannot lock with an undeclared criterion in it. A criterion that is
        # NOT judged (kind `mcq`, #53's staged deterministic criteria) is keyed, not
        # judged, and does not require one: the gate reads judged-ness, not the whole
        # criterion set (`TC-SETUP-12`). Every offender is named, not just the first.
        untyped = [
            row["criterion_id"] for row in self._catalog.criteria(v)
            if row["kind"] == "open"
            and not str(row.get("evidence_type") or "").strip()
        ]
        if untyped:
            raise SetupOrderError(
                "publish refused: evidence_type missing for the judged criteria "
                f"{', '.join(untyped)} (FR-SETUP-09). A judged criterion must declare "
                "what kind of textual evidence satisfies it — M-INTEG routes on the "
                "declaration (FR-INTEG-03), and the read back attaches the default "
                "when the model proposes none, so a judged criterion without one "
                "entered the package outside the read back. Deterministic (mcq) "
                "criteria are keyed, not judged, and do not require one."
            )
