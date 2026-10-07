"""The errors M-JUDGE raises."""

from __future__ import annotations

from aeh.prov import MalformedResponseError


class IsolationViolation(Exception):
    """A request contains something outside the whitelist (design §3.10, §7.2 Rule 1). Raised by
    `assert_isolated`; building a request refuses earlier where it can."""


class JudgmentError(Exception):
    """No legal verdict could be produced: the attempts ran out, the reply was malformed, or the
    band is not a declared one. There is no fallback band and no default verdict anywhere
    (NFR-JUDGE-05): a broken judge must fail visibly, never grade confidently."""


class CompositeUnitError(JudgmentError):
    """A work unit names a composite (`evidence_sum`) criterion (FR-JUDGE-38, ADR-39). A composite
    has no band set to judge — its points are its aspects' sum — so enumeration never creates
    such a unit; one found in the ledger (a hand-corrupted store) is refused before any
    transport call, and its failures quarantine it like a malformed unit's."""


class ProseAssessmentError(MalformedResponseError):
    """The reply's `evidence_assessment` is free evaluative prose: it uses the configured magnitude
    phrases and refers to no span and no band condition (FR-JUDGE-10, R42).

    It subclasses `aeh.prov.MalformedResponseError`, because the reply breaks the response
    contract. The dispatch loop treats it as the one refusal that earns a single re-request with an
    amended prompt, never a verbatim replay (FR-PROV-06)."""
