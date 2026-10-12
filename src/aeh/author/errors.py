"""The error M-AUTHOR raises on inputs no reasoning can recover (FR-AUTHOR-13)."""

from __future__ import annotations


class AuthoringInputError(RuntimeError):
    """A teacher document cannot be read, or yields no text at all while transcription is off.

    Raised **before any model call and without writing any artifact** — fail fast on inputs
    no reasoning can recover, naming the failing document (and, for a text-less page, the
    page number). Once at least one document has yielded text, this error never fires again:
    every downstream failure becomes an unresolved item and a placeholder (`CT-AUTHOR-10`),
    because a partial draft the teacher can complete is worth more than no draft at all.

    Not a `ProviderError` and not a `ConfigurationError`: it is an *input* failure. A profile
    that names no judge model is a different failure — `ConfigurationError` from `M-CONF`
    (`panel_for_profile`, FR-CONF-33), which likewise precedes any call.
    """


class OverwriteRefusedError(RuntimeError):
    """The output directory already holds a draft and report for the same package id, and the
    caller has not confirmed the overwrite (FR-AUTHOR-22, the library mirror of the CLI's
    `--force`: `draft(..., force=True)`).

    Raised before anything is written — the refusal names what would be replaced and that
    recorded review answers may carry over (FR-AUTHOR-23: the carry-over itself reads the
    prior report and re-applies matching answers provisionally at draft time, through
    `carryover.apply_carry_over`). Nothing is written without confirmation: a
    half-reviewed draft holds the teacher's work.
    """