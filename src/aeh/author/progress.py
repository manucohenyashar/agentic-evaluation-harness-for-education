"""The console-drivable run's step boundaries (FR-AUTHOR-30): the observer/cancel rhythm
`service.draft`, `service.draft_from_scratch` and `review.run_review` share.

The rule the design pins (`FR-AUTHOR-30`, `CT-AUTHOR-24/25`): the observer is called
**between steps, never mid-step**, and the cancel is checked at exactly the same
boundaries — so a run's progress story and its stopping points are the same events. A
boundary reports the step that just completed and then honors a cancel; a cancel that
became true only during the run's final step has no next step to stop, so the run
completes and its result is returned rather than discarded after the work was done.

The artifacts commit atomically (`commit_artifacts`): both files are written to `*.part`
temporaries first, then the temporaries are renamed into place, and only then are the
replaced-by-a-different-spelling priors removed — so a cancel at any boundary the service
checks leaves the output directory byte-for-byte as the last completed step left it
(which, for every boundary before the write step, is the state before the run started:
`CT-AUTHOR-24`, RS-12). A failure inside the commit removes the temporaries it wrote; a
`*.part` file is never a draft artifact. A hard failure *between* the two renames (or
between a rename and its prior's unlink) can leave a mixed old/new pair on disk — the
commit is atomic per artifact, not across the pair — and a cooperative cancel can never
land there: `commit_artifacts` checks no cancel.

On Windows the rename into place fails with a sharing violation (Win32 error 5 or 32)
whenever any reader holds the target open — a second console session reading the draft,
or the SPA's own reads racing a save — where POSIX replaces over an open reader freely.
The rename therefore waits a bounded budget out (`RETRIES` tries after the first, each
`BACKOFF_MS` apart, both env-gated: `HARNESS_AUTHOR_COMMIT_RETRIES` /
`HARNESS_AUTHOR_COMMIT_BACKOFF_MS`), so a concurrent reader delays the save instead of
failing it; a rename that is not a sharing violation, or one that outlasts the budget,
still fails with its own error.
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from pathlib import Path

from aeh.conf import ConfigurationError

from .errors import AuthoringCancelled
from .types import AuthoringCancel, AuthoringObserver, AuthoringProgress

#: The temporary suffix an in-flight artifact write carries, in the output directory itself
#: (the same volume, so the rename into place is atomic).
_PART_SUFFIX = ".part"

#: The rename's retry budget (seam 3): retries after the first try when the rename fails
#: with a Windows sharing violation. 0 is a legal "never retry". The production default
#: covers a reader that releases within a couple of seconds; the knobs exist so a slower
#: environment can widen the budget without a code change.
RETRIES_ENV = "HARNESS_AUTHOR_COMMIT_RETRIES"
DEFAULT_RETRIES = 20

#: The pause between rename tries, in milliseconds — the same seam, the same default
#: discipline: the production value ships as the default, the environment overrides it.
BACKOFF_MS_ENV = "HARNESS_AUTHOR_COMMIT_BACKOFF_MS"
DEFAULT_BACKOFF_MS = 100

#: The Win32 codes a sharing violation answers with: ERROR_SHARING_VIOLATION (32) and
#: ERROR_ACCESS_DENIED (5 — what MoveFileEx answers when the target's open reader
#: withholds the delete access the replace needs).
_SHARING_WINERRORS = frozenset({32, 5})


def check_cancel(cancel: AuthoringCancel | None) -> None:
    """The run-start boundary: a cancel already true stops the run before its first step,
    with nothing read and nothing written."""

    if cancel is not None and cancel():
        raise _cancelled()


def emit(observer: AuthoringObserver | None, cancel: AuthoringCancel | None,
         progress: AuthoringProgress) -> None:
    """One step boundary: report the completed step to the observer (the console's only
    progress source — the service logs no progress lines for it to scrape, `FR-AUTHOR-30`),
    then honor a cancel at the same boundary (`CT-AUTHOR-24`)."""

    if observer is not None:
        observer(progress)
    if cancel is not None and cancel():
        raise _cancelled()


def emit_completion(observer: AuthoringObserver | None,
                    progress: AuthoringProgress) -> None:
    """The run's final boundary: the observer hears the last completed step, and no cancel
    check runs — there is no next step left to stop, and raising after the artifacts were
    committed would report a cancellation whose work was in fact done."""

    if observer is not None:
        observer(progress)


def _is_sharing_violation(error: BaseException) -> bool:
    """Whether the rename failed because a reader holds the target open: the Win32
    sharing-violation codes on `winerror`, which only Windows sets (POSIX, immune,
    carries only the errno)."""
    return getattr(error, "winerror", None) in _SHARING_WINERRORS


def _replace_retries() -> int:
    """The rename's retry budget, read at call time so a changed environment applies to
    the next commit without a restart; a malformed or negative value refuses naming the
    knob, before the first rename is attempted (CT-AUTHOR-14's rule). Any `.part`
    temporaries a refusing commit had already written are removed by the commit's own
    cleanup."""
    raw = os.environ.get(RETRIES_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_RETRIES
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigurationError(
            f"{RETRIES_ENV}={raw!r} is not an integer. The knob bounds how long the draft "
            "save waits for a concurrent reader to release the draft file before the "
            "rename gives up; it is read at call time, so a malformed value never "
            "half-drives a save."
        ) from None
    if value < 0:
        raise ConfigurationError(
            f"{RETRIES_ENV}={value} is outside its legal range: the budget is a count of "
            f"retries after the first try, 0 meaning never retry ({RETRIES_ENV})."
        )
    return value


def _replace_backoff_ms() -> int:
    """The pause between rename tries, in milliseconds, under the same discipline as the
    retry budget: read at call time, refuse malformed values naming the knob."""
    raw = os.environ.get(BACKOFF_MS_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_BACKOFF_MS
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigurationError(
            f"{BACKOFF_MS_ENV}={raw!r} is not an integer. The knob is the pause between "
            "the draft save's rename tries while a concurrent reader holds the draft "
            "file; it is read at call time, so a malformed value never half-drives a "
            "save."
        ) from None
    if value < 0:
        raise ConfigurationError(
            f"{BACKOFF_MS_ENV}={value} is outside its legal range: the backoff is a "
            f"non-negative number of milliseconds ({BACKOFF_MS_ENV})."
        )
    return value


def _replace_with_retry(temporary: Path, path: Path) -> None:
    """Rename the temporary into place, waiting out a Windows sharing violation: the
    rename is retried up to the budgeted count with the budgeted pause between tries,
    so a concurrent reader delays the save instead of failing it. Any other error — and
    a sharing violation that outlasts the budget — propagates as itself."""
    retries = _replace_retries()
    backoff_s = _replace_backoff_ms() / 1000.0
    attempt = 0
    while True:
        try:
            os.replace(temporary, path)
            return
        except OSError as error:
            if attempt >= retries or not _is_sharing_violation(error):
                raise
            attempt += 1
            if backoff_s > 0:
                time.sleep(backoff_s)


def commit_artifacts(output: Path, pairs: Sequence[tuple[Path, str]],
                     priors: Sequence[Path] = ()) -> None:
    """Write every `(path, text)` artifact atomically into `output`: temporaries first,
    then each temporary is renamed into place, then the priors that would survive under a
    different spelling of the same case-insensitive package id
    (`carryover.prior_artifacts`'s rule) are removed. The unlink runs *after* the renames
    on purpose: the names differ, so the ordering is free, and a rename that failed after
    an earlier unlink would have destroyed the prior draft for nothing. A failure in the
    write or rename phase removes the temporaries; a failure after the first rename can
    leave a mixed old/new pair (atomic per artifact, not across the pair) — the window a
    cooperative cancel can never reach, since this helper checks no cancel
    (`FR-AUTHOR-30`). The rename waits a bounded Windows sharing violation out (a
    concurrent reader holding the draft open), under the
    `HARNESS_AUTHOR_COMMIT_RETRIES` / `HARNESS_AUTHOR_COMMIT_BACKOFF_MS` knobs."""

    output.mkdir(parents=True, exist_ok=True)
    temporaries: list[tuple[Path, Path]] = []
    try:
        for path, text in pairs:
            temporary = path.with_name(path.name + _PART_SUFFIX)
            temporary.write_text(text, encoding="utf-8")
            temporaries.append((temporary, path))
        for temporary, path in temporaries:
            _replace_with_retry(temporary, path)
        written = [path for _temporary, path in temporaries]
        for prior in priors:
            # On a case-insensitive file system (Windows, macOS by default) a prior spelled
            # `HIST7-ROME-01.…` and the new `hist7-rome-01.…` are ONE file: the rename above
            # already replaced it, and unlinking the "prior" would delete the draft just
            # written.
            if any(_same_file(prior, path) for path in written):
                continue
            prior.unlink()
    except BaseException:
        for temporary, _path in temporaries:
            temporary.unlink(missing_ok=True)
        raise


def _same_file(one: Path, other: Path) -> bool:
    """Whether two paths name the same file on disk (False when either is missing)."""
    try:
        return os.path.samefile(one, other)
    except OSError:
        return False


def _cancelled() -> AuthoringCancelled:
    return AuthoringCancelled(
        "the authoring run was cancelled at a step boundary (FR-AUTHOR-30): the artifacts "
        "on disk are exactly the last completed step left them — a draft that existed "
        "before the run stands untouched (CT-AUTHOR-24).")
