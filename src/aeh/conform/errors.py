"""The errors the conformance suite raises."""

from __future__ import annotations


class ConformanceError(Exception):
    """The conformance suite was misused, for example with no provider or an unknown fixture id."""


class ConsentRefused(Exception):
    """The suite refused to run on a cohort that is not flagged as consented for it (FR-CONFORM-02,
    R31).

    The decision is not made here: the raise happens when the `M-CONF` consent gate
    (`aeh.conf.consent_override_for`) refuses a backend configuration for the cohort. This
    module wraps the refusal so a consumer can catch the conformance suite's own type without
    importing the gate's — the boundary the clause draws is about the *decision*, not the
    exception name.
    """


class StaleFixtureError(ConformanceError):
    """A fixture's source bytes no longer match the digest the manifest records.

    A conformance result measured against a corpus that changed between runs is not a result
    (`NFR-CONFORM-01`). Staleness is a refusal, never a warning.
    """


class MergeRefused(ConformanceError):
    """A write that would merge two backends' validation records into one was refused.

    `CT-CONFORM-06`'s decisive negative: a record spanning two backends answers for no
    population — there is no backend it describes, and `CT-STATS-04` forbids the same shape
    for the same reason. The merged write is exactly what a consumer reaches for because it is
    the one that answers "how did we do", which is why the surface must refuse it rather than
    merely decline to offer it.
    """
