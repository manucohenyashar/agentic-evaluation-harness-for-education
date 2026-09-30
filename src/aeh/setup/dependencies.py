"""Proposing likely dependencies between criteria; only the teacher's approval writes an edge."""

from __future__ import annotations

import json
from typing import Mapping, Sequence

from aeh.pkg import PackageVersionId
from aeh.prov import PromptPayload

from .settings import _configured_proposal_attempts, LOGGER, SETUP_DEPENDENCIES_TEMPLATE_V
from .errors import _ReplyError, SetupError, SetupOrderError
from .records import DependencyProposal
from .prompts import _DEPENDENCIES_INSTRUCTION
from .decomposability import _json_object


def _parse_dependencies_reply(
    text: str, known_ids: frozenset[str] | set[str],
) -> tuple[tuple[str, str, str], ...]:
    """Parse the dependency proposal reply into `(criterion_id, depends_on, reason)` triples,
    raising `_ReplyError` for anything invalid, so the attempt loop asks again. An edge naming a
    criterion the version does not have, or linking a criterion to itself, is invalid: the write
    would refuse it, so the proposal does too."""
    parsed = _json_object(text)
    items = parsed.get("dependencies")
    if items is None:
        items = parsed.get("proposals")
    if not isinstance(items, list):
        raise _ReplyError(
            "the reply's JSON does not carry a 'dependencies' list."
        )
    triples: list[tuple[str, str, str]] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise _ReplyError(f"dependency #{index} is not an object.")
        criterion_id = raw.get("criterion_id")
        depends_on = raw.get("depends_on")
        if not isinstance(criterion_id, str) or not criterion_id.strip():
            raise _ReplyError(f"dependency #{index}: criterion_id must be a string.")
        if not isinstance(depends_on, str) or not depends_on.strip():
            raise _ReplyError(
                f"dependency #{index} ({criterion_id!r}): depends_on must be a string."
            )
        if criterion_id == depends_on:
            raise _ReplyError(
                f"dependency #{index}: {criterion_id!r} cannot depend on itself — a "
                "self-edge is the cycle the write path refuses."
            )
        for end in (criterion_id, depends_on):
            if end not in known_ids:
                raise _ReplyError(
                    f"dependency #{index}: criterion {end!r} is not in this version's "
                    "criteria — a proposal attaches to criteria that exist."
                )
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise _ReplyError(
                f"dependency {criterion_id!r} -> {depends_on!r}: reason must state, "
                "in words, what the grading presupposes — a dependency without its "
                "why cannot be rendered as plain language (FR-SETUP-10)."
            )
        triples.append((criterion_id, depends_on, reason.strip()))
    return tuple(triples)


class DependencyStepMixin:
    """Proposes criterion dependencies and writes the edges the teacher approves."""

    def propose_dependencies(self) -> tuple[DependencyProposal, ...]:
        """Propose the dependencies between criteria that the subject makes likely, and write
        nothing: every criterion starts with no dependencies, and a proposal is only a suggestion
        for the teacher (FR-SETUP-10, CT-SETUP-08).

        One version-pinned model call proposes the edges; each comes back rendered in
        plain language naming both criteria and the reason — the sentence
        `FR-SETUP-10` gives the standard for. A version with no criteria proposes
        nothing (there is nothing to attach to). The proposals are recorded on the
        step's provenance row — the record `confirm_dependencies` approves against
        (`CT-SETUP-03`: state is the database) — and the step's base case, nothing
        likely, is recorded too rather than left indistinguishable from a skip."""
        v = self._require_draft_version()
        rows = self._catalog.criteria(v)
        known = frozenset(row["criterion_id"] for row in rows)
        if not known:
            LOGGER.info("version %s carries no criteria — no dependency proposal", v)
            return ()
        listing = [
            {"criterion_id": row["criterion_id"], "question_id": row["question_id"],
             "kind": row["kind"], "construct": row.get("construct_tag", "")}
            for row in rows
        ]
        payload = PromptPayload(fields=(
            ("instruction", _DEPENDENCIES_INSTRUCTION),
            ("criteria", json.dumps(listing, sort_keys=True)),
        ))
        budget = _configured_proposal_attempts()
        last_error = ""
        for attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(payload, self._model_ref,
                                                     self._params)
                triples = _parse_dependencies_reply(completion.text, known)
            except _ReplyError as error:
                last_error = f"attempt {attempt}: {error}"
                LOGGER.warning(
                    "dependency-proposal reply failed to parse (%d/%d): %s",
                    attempt, budget, error)
                continue
            except Exception as error:  # contained: the transport's failure is a
                # failed attempt (CT-SETUP-12's pattern).
                last_error = f"attempt {attempt}: {type(error).__name__}: {error}"
                LOGGER.warning("dependency-proposal attempt %d/%d failed: %s",
                               attempt, budget, error)
                continue
            proposals = tuple(
                DependencyProposal(criterion_id=criterion_id, depends_on=depends_on,
                                   reason=reason)
                for criterion_id, depends_on, reason in triples
            )
            self._record_dependency_proposals(v, proposals)
            LOGGER.info(
                "proposed %d dependency edge(s) for version %s in %d attempt(s), "
                "prompt %s — nothing written; approval is the teacher's act "
                "(FR-SETUP-10)", len(proposals), v, attempt,
                SETUP_DEPENDENCIES_TEMPLATE_V,
            )
            return proposals

        # The budget is spent: degraded but complete (`CT-SETUP-12`) — the default
        # (zero dependencies) stands, and the failure is on the step's record.
        self._record_dependency_proposals(v, (), status="dependencies_needs_review",
                                          reason=last_error)
        LOGGER.warning(
            "dependency proposals for version %s degraded to the zero-dependency "
            "default after %d attempt(s): %s", v, budget, last_error,
        )
        return ()

    def _record_dependency_proposals(
        self, v: PackageVersionId, proposals: Sequence[DependencyProposal],
        *, status: str | None = None, reason: str = "",
    ) -> None:
        """Save the dependency proposals in the step's provenance row, where `confirm_dependencies`
        checks approvals against them (CT-SETUP-03). The row is merged, not replaced (see
        `_record_decomposability_step`). Skipped when the catalog cannot record it."""
        if status is None:
            status = ("dependencies_proposed" if proposals
                      else "dependencies_none_proposed")
        self._record_decomposability_step(v, status=status, update={
            "proposals": [
                {"criterion_id": item.criterion_id,
                 "depends_on": item.depends_on,
                 "reason": item.reason,
                 "rendered": str(item)}
                for item in proposals
            ],
            "template_version": SETUP_DEPENDENCIES_TEMPLATE_V,
            **({"reason": reason} if reason else {}),
        })

    def confirm_dependencies(
        self,
        approved: Sequence[DependencyProposal | tuple[str, str] | Mapping],
    ) -> None:
        """Record the teacher's approval of proposed dependencies. This is the only way a
        dependency edge gets written (FR-SETUP-10, CT-SETUP-08).

        Each approval names a criterion pair; every pair must be among the proposals
        recorded on the step's row (approval confirms a proposal, not an idea), and
        the whole approved set is written in ONE `M-PKG` call — transactional, and
        cycle-refusing inside that transaction (a `PackageError` propagates
        unchanged, `CT-SETUP-12`). A dependency the teacher declines is simply absent:
        declining needs no call, and the empty graph it leaves is the design's base
        case."""
        v = self._require_draft_version()
        reader = getattr(self._catalog, "step_record", None)
        recorded = reader(v, "decomposability") if reader is not None else None
        proposed: set[tuple[str, str]] = set()
        payload: dict = {}
        if recorded is not None:
            try:
                loaded = json.loads(recorded["payload"])
            except (ValueError, TypeError):
                loaded = None
            if isinstance(loaded, dict):
                payload = loaded
            for item in payload.get("proposals", []):
                if isinstance(item, dict) and "criterion_id" in item \
                        and "depends_on" in item:
                    proposed.add((str(item["criterion_id"]),
                                  str(item["depends_on"])))
        if not proposed:
            raise SetupOrderError(
                f"no dependency proposal is recorded for version {v!r} — call "
                "propose_dependencies first; approval confirms a proposal, not an "
                "idea (FR-SETUP-10)."
            )
        pairs: list[tuple[str, str]] = []
        for item in approved:
            if isinstance(item, DependencyProposal):
                pairs.append((item.criterion_id, item.depends_on))
            elif isinstance(item, Mapping):
                pairs.append((str(item["criterion_id"]), str(item["depends_on"])))
            else:
                criterion_id, depends_on = item
                pairs.append((str(criterion_id), str(depends_on)))
        unproposed = sorted(set(pairs) - proposed)
        if unproposed:
            raise SetupError(
                f"approval names pair(s) {unproposed} that were never proposed for "
                f"version {v!r} — a dependency edge is written on the teacher's "
                "approval OF a proposal (FR-SETUP-10); hand-authored edges are "
                "M-PKG's own path."
            )
        # The edge is (before, after): `after` depends on `before` — the proposal's
        # `depends_on` is the earlier criterion whose credited work the later one
        # would see. Approving in batches ACCUMULATES: the graph write is a replace
        # (M-PKG's set_dependencies), so each approval writes the union of every
        # approval so far — read off this row's own recorded approvals, the
        # state-is-the-database rule — never just this batch, which would silently
        # un-approve an earlier one.
        merged: dict[tuple[str, str], dict] = {}
        for item in payload.get("approved", []):
            if isinstance(item, dict) and "criterion_id" in item \
                    and "depends_on" in item:
                merged[(str(item["criterion_id"]),
                        str(item["depends_on"]))] = item
        for criterion_id, depends_on in pairs:
            merged.setdefault((criterion_id, depends_on), {
                "criterion_id": criterion_id, "depends_on": depends_on})
        approved_pairs = list(merged.values())
        edges = [(item["depends_on"], item["criterion_id"])
                 for item in approved_pairs]
        self._catalog.set_dependencies(v, edges)
        self._record_decomposability_step(
            v, status="dependencies_approved",
            update={"approved": approved_pairs, "edge_count": len(edges)})
        LOGGER.info(
            "teacher approved %d dependency edge(s) for version %s — written in one "
            "M-PKG call (FR-SETUP-10)", len(edges), v,
        )
