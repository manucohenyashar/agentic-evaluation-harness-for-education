"""`TC-AUTHOR-43` — the draft save's atomic rename waits out a concurrent reader
(#797's finding 3, the Windows sharing violation).

`commit_artifacts` writes `*.part` temporaries and `os.replace`s each into place. On
Windows that rename fails with a sharing violation (Win32 error 5 or 32) whenever any
reader holds the target open — a second console session reading the draft, or the SPA's
own reads racing a save — and the console answered the action 500. POSIX replaces over an
open reader freely, so only Windows ever saw it.

The fix is a bounded retry-with-backoff around the rename, with both constants env-gated
(seam 3): `HARNESS_AUTHOR_COMMIT_RETRIES` (retries after the first try; 0 is a legal
"never retry") and `HARNESS_AUTHOR_COMMIT_BACKOFF_MS` (the pause between tries). A
concurrent reader now delays the save by at most retries × backoff instead of failing it;
a rename that is not a sharing violation, or one that outlasts the budget, still fails
loudly with its original error, and the temporaries still clean up.

Arms:

1. **The fake reader releases** (any platform): a rename that raises the sharing
   violation twice and then succeeds is retried and lands — red before the fix, which
   raised on the first violation.
2. **The budget is bounded**: a rename that never succeeds fails with its own error after
   exactly 1 + retries attempts, and the `.part` temporaries are gone.
3. **A non-sharing error is never retried**: a plain OSError (winerror absent) fails on
   the first attempt.
4. **The knobs refuse a malformed value, naming the knob** (CT-AUTHOR-14's rule).
5. **A real concurrent reader** (Windows only, skipped elsewhere): the genuine sharing
   violation — a file handle open on the target — is waited out; the reader closing
   mid-retry lets the save land.

Rung 1: `commit_artifacts` touches nothing but the output directory, so the suite needs
no store and no corpus.
"""

from __future__ import annotations

import os
import threading

import pytest

from aeh.author.progress import (
    BACKOFF_MS_ENV,
    RETRIES_ENV,
    commit_artifacts,
)
from aeh.conf import ConfigurationError

#: The Win32 codes a sharing violation answers with: ERROR_SHARING_VIOLATION (32) and
#: ERROR_ACCESS_DENIED (5 — the code MoveFileEx answers when the target lacks the delete
#: access an open reader withholds). Verified against the real thing on Windows: a plain
#: `open()` handle on the target makes `os.replace` raise `PermissionError` winerror 5.
SHARING_WINERRORS = (32, 5)


def sharing_violation() -> OSError:
    """The sharing violation, as an exception object the predicate reads the same way on
    every platform: the Win32 code rides `winerror`, which only Windows sets natively."""
    error = OSError(
        "the process cannot access the file because it is being used by another process")
    error.errno = 13
    error.winerror = 5
    assert error.winerror in SHARING_WINERRORS
    return error


def test_commit_artifacts_retries_a_sharing_violation_until_the_reader_releases(
        tmp_path, monkeypatch):
    """Arm 1 — a rename that fails twice with the sharing violation and then succeeds is
    retried and lands; the artifact is written and no `.part` survives."""
    monkeypatch.setenv(RETRIES_ENV, "5")
    monkeypatch.setenv(BACKOFF_MS_ENV, "0")
    real_replace = os.replace
    attempts: list[BaseException | None] = []

    def flaky_replace(src, dst):
        if len(attempts) < 2:
            error = sharing_violation()
            attempts.append(error)
            raise error
        attempts.append(None)
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    target = tmp_path / "pkg-abc.package.draft.toml"

    commit_artifacts(tmp_path, [(target, "the draft text")])

    assert len(attempts) == 3, f"the rename was attempted {len(attempts)} time(s)"
    assert target.read_text(encoding="utf-8") == "the draft text"
    assert not list(tmp_path.glob("*.part")), "a .part temporary survived the commit"


def test_commit_artifacts_gives_up_after_the_budgeted_retries_and_cleans_up(
        tmp_path, monkeypatch):
    """Arm 2 — a rename that never succeeds fails with its own error after exactly
    1 + retries attempts, and the temporaries it wrote are removed."""
    monkeypatch.setenv(RETRIES_ENV, "2")
    monkeypatch.setenv(BACKOFF_MS_ENV, "0")
    attempts: list[int] = []

    def always_violating(src, dst):
        attempts.append(1)
        raise sharing_violation()

    monkeypatch.setattr(os, "replace", always_violating)
    target = tmp_path / "pkg-abc.package.draft.toml"
    other = tmp_path / "pkg-abc.report.md"

    with pytest.raises(OSError, match="used by another process"):
        commit_artifacts(tmp_path, [(target, "one"), (other, "two")])

    assert len(attempts) == 1 + 2, f"the rename was attempted {len(attempts)} time(s)"
    assert not target.exists() and not other.exists()
    assert not list(tmp_path.glob("*.part")), "a .part temporary survived the failure"


def test_commit_artifacts_never_retries_a_non_sharing_error(tmp_path, monkeypatch):
    """Arm 3 — an OSError that carries no Win32 code (a POSIX errno, a full disk) is not
    a sharing violation: it fails on the first attempt, with the retry budget untouched."""
    monkeypatch.setenv(RETRIES_ENV, "9")
    monkeypatch.setenv(BACKOFF_MS_ENV, "0")
    attempts: list[int] = []

    def disk_full(src, dst):
        attempts.append(1)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", disk_full)

    with pytest.raises(OSError, match="No space left"):
        commit_artifacts(tmp_path, [(tmp_path / "pkg-abc.package.draft.toml", "text")])

    assert len(attempts) == 1, f"a non-sharing error was retried {len(attempts)} time(s)"


def test_commit_artifacts_refuses_a_malformed_knob_naming_it(tmp_path, monkeypatch):
    """Arm 4 — the knobs are read at call time and validated there, so a malformed value
    refuses before anything is written, naming the knob (CT-AUTHOR-14's rule)."""
    monkeypatch.setenv(RETRIES_ENV, "many")
    target = tmp_path / "pkg-abc.package.draft.toml"

    with pytest.raises(ConfigurationError, match=RETRIES_ENV):
        commit_artifacts(tmp_path, [(target, "text")])

    monkeypatch.setenv(RETRIES_ENV, "1")
    monkeypatch.setenv(BACKOFF_MS_ENV, "soon")
    with pytest.raises(ConfigurationError, match=BACKOFF_MS_ENV):
        commit_artifacts(tmp_path, [(target, "text")])

    monkeypatch.setenv(RETRIES_ENV, "-1")
    monkeypatch.setenv(BACKOFF_MS_ENV, "0")
    with pytest.raises(ConfigurationError, match=RETRIES_ENV):
        commit_artifacts(tmp_path, [(target, "text")])


@pytest.mark.skipif(os.name != "nt",
                    reason="the sharing violation is Windows behaviour; POSIX replaces "
                           "over an open reader freely, so the real-reader arm has "
                           "nothing to reproduce there")
def test_commit_artifacts_waits_out_a_real_concurrent_reader(tmp_path, monkeypatch):
    """Arm 5 — the genuine defect, reproduced with a real handle: a reader holding the
    draft open makes the rename fail with WinError 5, and the save lands once the reader
    closes mid-retry. The red-before-fix form is the same call without the closer — it
    fails with the sharing violation (the first arm's fake pins the mechanism everywhere;
    this one pins the real error code)."""
    monkeypatch.setenv(RETRIES_ENV, "50")
    monkeypatch.setenv(BACKOFF_MS_ENV, "20")
    target = tmp_path / "pkg-abc.package.draft.toml"
    target.write_text("before", encoding="utf-8")

    # The raw defect first, with a real handle on the target: the rename fails with the
    # sharing violation itself — the error the console answered the action 500 with.
    temporary = target.with_name(target.name + ".part")
    temporary.write_text("after", encoding="utf-8")
    reader = open(target, "r", encoding="utf-8")
    try:
        with pytest.raises(OSError) as raised:
            os.replace(temporary, target)
        assert getattr(raised.value, "winerror", None) in SHARING_WINERRORS, (
            f"the probe did not reproduce the sharing violation: {raised.value!r}")
        temporary.unlink()

        # The same conditions, reader still open: the save now waits out the reader —
        # the timer closes it mid-retry — instead of failing the save.
        closer = threading.Timer(0.3, reader.close)
        closer.start()
        commit_artifacts(tmp_path, [(target, "after")])
    finally:
        reader.close()

    assert target.read_text(encoding="utf-8") == "after"
