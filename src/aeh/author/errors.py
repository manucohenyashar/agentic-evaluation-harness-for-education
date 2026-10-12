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


class DocumentRefusedError(AuthoringInputError):
    """A teacher document the intake tier refuses outright (FR-AUTHOR-28).

    Raised by `intake.normalize_document` / `intake.check_document` — and by the intake
    step inside `draft()` — **before any model call and without writing any artifact**
    (`CT-AUTHOR-23`): every row of the refusal matrix is decided by magic bytes and cheap
    local checks, so no reasoning can recover the file and no provider is ever involved.

    `sentence` is the teacher-facing refusal, verbatim from FR-AUTHOR-28's matrix (the
    console renders it as-is); `next_step`, when the sentence does not already carry one,
    says what to do instead; `detail` is the operator-facing reason (which check fired and
    why) — never shown in a toast, always in the report and the log. The error's text is
    the sentence plus the file's name, so a multi-document refusal says which file it was.
    """

    def __init__(self, sentence: str, name: str, *, detail: str = "",
                 next_step: str = "") -> None:
        self.sentence = sentence
        self.name = name
        self.detail = detail
        self.next_step = next_step
        tail = f" {next_step}" if next_step else ""
        super().__init__(f"{sentence}{tail} ({name})")


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