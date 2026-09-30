"""The errors M-JUDGE raises."""

from __future__ import annotations

from aeh.prov import MalformedResponseError


class IsolationViolation(Exception):
    """A request violated the whitelist (`§3.10`: the machine-checkable form of §7.2
    Rule 1). Raised by `assert_isolated`; construction refuses earlier where it can."""


class JudgmentError(Exception):
    """The boundary could not produce a legal verdict — budget exhausted, a malformed
    reply, a band outside the declared set. There is NO fallback band and NO default
    verdict on any path (`NFR-JUDGE-05`): a broken judge must fail visibly, never
    grade confidently."""


class ProseAssessmentError(MalformedResponseError):
    """The reply's `evidence_assessment` is free evaluative prose: it matches the
    configured magnitude-phrase vocabulary and references no span and no band condition
    (`FR-JUDGE-10`'s rejection, `R42`). A subclass of `aeh.prov`'s
    `MalformedResponseError` — the reply IS malformed under the response contract, so
    the `FUZZ-04` oracle's named exception is what surfaces — and the dispatch loop
    treats the name as the re-request trigger: this one refusal earns an AMENDED prompt
    (never a verbatim replay, `FR-PROV-06`), once per dispatch."""
