"""Minting a version, publishing it, and finding a package's versions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .vocabulary import default_evaluation_mode, LOGGER, PackageVersionId
from .records import PackageDraft, _REVISION_COPY_KEYS
from .statements import PKG_STATEMENTS


class VersionsMixin:
    """Mints, publishes and finds the package's versions."""

    # -- the lineage surface -----------------------------------------------------------------

    def create_version(
        self, parent: PackageVersionId | None, draft: PackageDraft | None = None
    ) -> PackageVersionId:
        """Mint a version: a brand-new package's first version (`parent=None`) or a
        revision of an existing one (`FR-PKG-02`).

        A revision **copies** the parent's content rows into the new version — the copy is
        how a §6.2 clarification edit happens (`FR-PKG-04`): the edit lands in the new,
        unlocked version, and the parent is untouched. The new version is born unlocked."""
        version_id = f"{self._package_id}@{uuid.uuid4().hex[:12]}"
        with self._handle.transaction() as tx:
            if parent is None:
                self._refuse_no_such_package(tx)
                tx.execute(PKG_STATEMENTS["insert_first_version"],
                           v=version_id, p=self._package_id)
            else:
                # NOTE: the parent may be published — a revision of a published version
                # is exactly FR-PKG-02's flow. create_version only READS the parent
                # (the copy) and INSERTs new rows, so no guard fires here; the triggers
                # backstop the parent's rows against UPDATE, not the lineage copy.
                revision = self._next_revision(tx, parent)
                parent_row = tx.execute(PKG_STATEMENTS["select_version"], v=parent)[0]
                tx.execute(PKG_STATEMENTS["insert_revision"],
                           v=version_id, p=self._package_id, rev=revision,
                           parent=parent)
                for key in _REVISION_COPY_KEYS:
                    tx.execute(PKG_STATEMENTS[key], new=version_id, old=parent)
                # The copy's completeness gate (#230): a criterion that fails the copy —
                # a declared band_count the copied bands do not satisfy (FR-PKG-06's
                # even-band bar) — refuses the revision HERE, inside the transaction,
                # rather than shipping a half-copied child (CT-PKG-02). The refusal is
                # a no-op on disk: the child row and every copy roll back together.
                self._validate_band_sets(
                    lambda name: tx.execute(PKG_STATEMENTS[name], v=version_id),
                    boundary="shipped as a revision",
                )
        for criterion_id in (draft.criteria if draft is not None else ()):
            tx.execute(PKG_STATEMENTS["insert_criterion"], v=version_id,
                       criterion_id=criterion_id, question_id=criterion_id,
                       kind="open", max_points=0.0, scoring_model="atomic",
                       construct_tag="", band_count=None, evidence_type=None,
                       # A draft placeholder is `kind="open"`, so: judged.
                       evaluation_mode=default_evaluation_mode("open"))
        if parent is not None:
            copied = ", ".join(
                f"{row['surface']}={row['n']}" for row in self._handle.query(
                    PKG_STATEMENTS["pkg_revision_copied_counts"], v=version_id))
            LOGGER.info(
                "created package version %s (package %s, parent %s): revision %d -> "
                "%d, copied verbatim %s — the copy changed no field; explicit edits "
                "land on the unlocked child through the guarded write surface",
                version_id, self._package_id, parent, parent_row["revision"],
                revision, copied)
        else:
            LOGGER.info("created package version %s (package %s, parent %s)",
                        version_id, self._package_id, parent)
        return version_id

    def publish(self, v: PackageVersionId, approved_by: str) -> None:
        """Set `locked = 1` — the one permitted update to a version row, and the moment
        its immutability begins (`FR-PKG-01`).

        `FR-PKG-06`'s count half runs at the publish boundary — every declared
        band_count fully populated and even/2..6 — and BEFORE the lock flips, so a
        refused publish is a no-op: a version locked with an incomplete band set would
        be an immutable invalid instrument, which is worse than an unpublished one."""
        self._refuse_mutation(v)
        # The validation counts THIS VERSION's rows from the database — not the
        # per-run cache (which holds whatever version was read last), and not a
        # criterion-id lookup (which would count every revision's copied bands of the
        # same criterion id; the parent's rows are not this version's).
        self._validate_band_sets(
            lambda name: self._handle.query(PKG_STATEMENTS[name], v=v),
            boundary="publishable",
        )
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS["publish"], by=approved_by, v=v)
            LOGGER.info("published package version %s by %s at %s",
                        v, approved_by, datetime.now(timezone.utc).isoformat())
        self._invalidate()

    # -- the question inventory and setup proposal (#50) --------------------------------------
    #
    # The Tier P storage M-SETUP's Stage A reaches: the package row its first version
    # needs, the proposal record, and the confirmed question inventory. M-PKG validates
    # every structural constraint on the way in (CT-PKG-12) — whatever M-SETUP checked,
    # the data layer checks again — and the confirmation lock lives with the data
    # (FR-SETUP-02): `update_question_field` is the surface that proves it.

    def ensure_package(self) -> None:
        """Create the package row if absent. `create_version` refuses to mint one —
        its refusal names M-SETUP's initial version as the writer (`FR-SETUP-16`'s
        first move is exactly this) — so setup's `ensure_version` calls here first."""
        if not self._handle.query(PKG_STATEMENTS["count_package"],
                                  p=self._package_id)[0]["n"]:
            with self._handle.transaction() as tx:
                tx.execute(PKG_STATEMENTS["insert_package"], p=self._package_id)
            LOGGER.info("created package %s (M-SETUP's initial version)", self._package_id)

    def draft_version(self) -> PackageVersionId | None:
        """The package's latest UNPUBLISHED version, or None — the version setup works
        on, across processes (nothing is held in memory: resume is a fresh catalog
        reading the same Tier P file, CT-SETUP-03). A published version is never the
        draft: setup has already finished for it."""
        rows = self._handle.query(PKG_STATEMENTS["select_latest_draft_version"],
                                  p=self._package_id)
        return rows[0]["package_version_id"] if rows else None

    def has_version(self) -> bool:
        """Whether the package holds ANY version — the read that distinguishes
        `setup has not started` (no version at all) from `setup has finished` (a
        published version, no draft) in the console's step report."""
        return bool(self._handle.query(PKG_STATEMENTS["select_has_version"],
                                       p=self._package_id))

    def latest_version(self) -> PackageVersionId | None:
        """The package's most recent version, published or not (`#53`): the read
        the FINISHED step report needs — once setup finishes the draft is gone,
        but the step records the published version carries are still the truth
        about what was taken, and the console reads them through this."""
        rows = self._handle.query(PKG_STATEMENTS["select_latest_package_version"],
                                  p=self._package_id)
        return rows[0]["package_version_id"] if rows else None
