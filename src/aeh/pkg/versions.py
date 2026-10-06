"""Minting a version, publishing it, and finding a package's versions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .vocabulary import (
    DEFAULT_SCORE_METHOD, default_evaluation_mode, LOGGER, PackageVersionId)
from .records import PackageDraft, _REVISION_COPY_KEYS
from .statements import PKG_STATEMENTS


class VersionsMixin:
    """Mints, publishes and finds the package's versions."""

    # -- the lineage surface -----------------------------------------------------------------

    def create_version(
        self, parent: PackageVersionId | None, draft: PackageDraft | None = None
    ) -> PackageVersionId:
        """Create a version: a new package's first version (`parent=None`) or a revision of an
        existing one (FR-PKG-02).

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
                       evaluation_mode=default_evaluation_mode("open"),
                       score_method=DEFAULT_SCORE_METHOD, component_of=None)
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
        """Publish a version by setting `locked = 1`, the only update a version row allows. From
        then on it cannot change (FR-PKG-01).

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
        # FR-PKG-24/26, CT-PKG-21: the method vocabulary, the composite shape and the
        # `general` derivation gate — also before the lock flips.
        self._validate_score_methods(v)
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
        """Create the package row if it does not exist. `create_version` will not create one, so
        M-SETUP's `ensure_version` calls this first (FR-SETUP-16)."""
        if not self._handle.query(PKG_STATEMENTS["count_package"],
                                  p=self._package_id)[0]["n"]:
            with self._handle.transaction() as tx:
                tx.execute(PKG_STATEMENTS["insert_package"], p=self._package_id)
            LOGGER.info("created package %s (M-SETUP's initial version)", self._package_id)

    def draft_version(self) -> PackageVersionId | None:
        """The package's latest unpublished version, or None: the version setup works on. It is
        read from the file each time, so setup can resume in a new process (CT-SETUP-03). A
        published version is never the draft."""
        rows = self._handle.query(PKG_STATEMENTS["select_latest_draft_version"],
                                  p=self._package_id)
        return rows[0]["package_version_id"] if rows else None

    def has_version(self) -> bool:
        """Whether the package has any version at all. This tells "setup not started" (no version)
        apart from "setup finished" (a published version and no draft)."""
        return bool(self._handle.query(PKG_STATEMENTS["select_has_version"],
                                       p=self._package_id))

    def latest_version(self) -> PackageVersionId | None:
        """The package's newest version, published or not. After setup finishes there is no draft,
        but the published version's step records still say what was taken, and the console reads
        them through this."""
        rows = self._handle.query(PKG_STATEMENTS["select_latest_package_version"],
                                  p=self._package_id)
        return rows[0]["package_version_id"] if rows else None
