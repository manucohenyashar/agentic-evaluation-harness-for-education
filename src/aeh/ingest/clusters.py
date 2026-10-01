"""Cohort-wide unresolved tokens, and applying an operator's resolution to every occurrence."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Any, Sequence

from .settings import LOGGER
from .errors import IngestError
from .schema import INGEST_STATEMENTS
from .records import ClusterResolution, TokenCluster


class TokenClustersMixin:
    """Lists the cohort's unresolved tokens and applies a resolution to all of them."""

    # -- cohort-wide token clustering (FR-INGEST-20) --------------------------------------

    def clusters(self, cohort_id: str) -> tuple[TokenCluster, ...]:
        """The cohort's unresolved-token clusters (FR-INGEST-20): each distinct token the
        transcription marked `<unresolved>`, grouped once across all regions, so the operator
        resolves it once rather than once per occurrence. The cluster id comes from the token, so
        the same token always maps to the same cluster."""
        rows = self._handle.query(INGEST_STATEMENTS["select_all_regions"])
        grouped: dict[str, TokenCluster] = {}
        for row in rows:
            for token in re.findall(r"<unresolved>(.*?)</unresolved>",
                                    row["content"] or ""):
                normalized = token.strip().lower()
                if not normalized:
                    continue
                if normalized not in grouped:
                    grouped[normalized] = TokenCluster(
                        cluster_id=f"clu-{hashlib.sha256(normalized.encode()).hexdigest()[:12]}",
                        cohort_id=cohort_id,
                        token=normalized,
                        document_ids=[])
                if row["document_id"] not in grouped[normalized].document_ids:
                    grouped[normalized].document_ids.append(row["document_id"])
        return tuple(grouped.values())

    def resolve_cluster(
        self, cluster_id: str, resolution: str,
        *, package_catalog: Any | None = None, package_version: str | None = None,
    ) -> "ClusterResolution":
        """Apply one operator resolution to every occurrence of the cluster's token, handled per
        region kind (FR-INGEST-20, FR-INGEST-36): each region carrying it is updated, the
        resolution is recorded once in `token_cluster`, and the ids of the documents that changed
        are returned.

        More detail: `docs/code-notes/ingest.md`, section `clusters.py: TokenClustersMixin.resolve_cluster`.
        """
        matches = [cluster for cluster in self.clusters(self._cohort_id)
                   if cluster.cluster_id == cluster_id]
        if not matches:
            raise IngestError(f"cluster {cluster_id!r} does not exist.")
        token = matches[0].token
        # The affected documents are captured BEFORE the update — the resolution
        # replaces the token, so a read-after-write would find nothing.
        affected = tuple(row["document_id"] for row in self._handle.query(
            INGEST_STATEMENTS["select_unresolved_documents"], token=token))
        region_ids = [row["region_id"] for row in self._handle.query(
            INGEST_STATEMENTS["select_region_ids_for_token"], token=token)]
        catalog = package_catalog if package_catalog is not None else self._package_catalog
        version = package_version if package_version is not None else self._package_version
        try:
            # ONE transaction for the whole resolution: the region writes, the token's
            # retirement and the cluster record. A resolution that is half-applied — content
            # rewritten while the token still reads unresolved — is the state no operator can
            # act on, and the earlier two-transaction shape could produce it.
            with self._handle.transaction() as tx:
                unresolved = self._write_region_resolutions(
                    tx, region_ids, token, resolution, catalog, version
                )
                tx.execute(INGEST_STATEMENTS["delete_unresolved_token"], token=token)
                tx.execute(INGEST_STATEMENTS["insert_cluster"],
                           cluster_id=cluster_id, cohort_id=matches[0].cohort_id,
                           token=token, resolution=resolution, resolved_at=self._now())
        except sqlite3.IntegrityError as error:
            # FR-INGEST-37's trigger, at the module boundary (`CT-INGEST-21`). The message
            # names the biconditional only when the database's own text does; any other
            # integrity failure is reported as itself rather than given a cause nobody checked.
            detail = (
                "A resolved selection mark carries a selection (CT-INGEST-05). "
                if "selection" in str(error).lower() else ""
            )
            raise IngestError(
                f"the resolution of cluster {cluster_id!r} was refused by the database: "
                f"{error}. {detail}Nothing was written."
            ) from error
        LOGGER.info(
            "resolved cluster %s token=%r across %d document(s); %d selection mark(s) "
            "left ambiguous", cluster_id, token, len(affected), len(unresolved))
        return ClusterResolution(affected, selection_unresolved=tuple(unresolved))

    def _write_region_resolutions(
        self, tx: Any, region_ids: Sequence[str], token: str, resolution: str,
        package_catalog: Any | None, package_version: str | None,
    ) -> list[str]:
        """Write one cluster resolution's changes per region kind, and return the ids of regions
        left ambiguous. Writes in the caller's transaction, so the whole resolution commits or
        aborts together."""
        unresolved: list[str] = []
        for region_id in region_ids:
            rows = self._handle.query(
                INGEST_STATEMENTS["select_regions_by_id"], region_id=region_id)
            region = rows[0] if rows else None
            kind = str(region["region_kind"]) if region is not None else ""
            if kind != "selection_mark":
                # Text and graphic regions: content only (FR-INGEST-36).
                tx.execute(INGEST_STATEMENTS["update_region_text"],
                           region_id=region_id, resolution=resolution, token=token)
                continue
            # `#373`: the stored owner, falling back to `element_kind` for rows written
            # before the column existed (the migration backfills nothing, by design). A
            # mark that declared its own question reads the same either way; one that did
            # NOT — the transcript tagged the question on the text above and the mark
            # below it carries the generic kind — used to resolve against an option set
            # read for the literal question `"text"`, i.e. against nothing, and the
            # operator's correct answer was listed `selection_unresolved` (RISK-50, from
            # the other side).
            question = ""
            if region is not None:
                question = str(region["question_id"] or region["element_kind"] or "")
            options = self._declared_options(
                package_catalog, package_version, question,
            )
            if resolution in options:
                tx.execute(INGEST_STATEMENTS["resolve_selection_region"],
                           region_id=region_id, resolution=resolution,
                           token=token, selection=resolution)
            else:
                # Stays ambiguous, content replaced, and the operator is told.
                tx.execute(INGEST_STATEMENTS["update_region_text"],
                           region_id=region_id, resolution=resolution, token=token)
                unresolved.append(region_id)
        return unresolved
