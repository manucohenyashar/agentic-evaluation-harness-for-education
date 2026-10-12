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
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from .errors import AuthoringCancelled
from .types import AuthoringCancel, AuthoringObserver, AuthoringProgress

#: The temporary suffix an in-flight artifact write carries, in the output directory itself
#: (the same volume, so the rename into place is atomic).
_PART_SUFFIX = ".part"


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
    (`FR-AUTHOR-30`)."""

    output.mkdir(parents=True, exist_ok=True)
    temporaries: list[tuple[Path, Path]] = []
    try:
        for path, text in pairs:
            temporary = path.with_name(path.name + _PART_SUFFIX)
            temporary.write_text(text, encoding="utf-8")
            temporaries.append((temporary, path))
        for temporary, path in temporaries:
            os.replace(temporary, path)
        for prior in priors:
            prior.unlink()
    except BaseException:
        for temporary, _path in temporaries:
            temporary.unlink(missing_ok=True)
        raise


def _cancelled() -> AuthoringCancelled:
    return AuthoringCancelled(
        "the authoring run was cancelled at a step boundary (FR-AUTHOR-30): the artifacts "
        "on disk are exactly the last completed step left them — a draft that existed "
        "before the run stands untouched (CT-AUTHOR-24).")
