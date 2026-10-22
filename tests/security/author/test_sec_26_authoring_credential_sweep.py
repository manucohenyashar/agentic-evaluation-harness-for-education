"""`SEC-26` — the credential canary sweep over every output channel of the full fixture
corpus (`NFR-AUTHOR-04`, `CT-AUTHOR-16`, cross-cutting; TS-168, issue #701).

Test plan §5.5, written from design delta §3.1 (Security) and its Technical notes:

> the OpenRouter key lives in `.env-dev` and reaches the provider only through the
> environment (`OPENROUTER_API_KEY`) — it is never hard-coded in this suite or any file,
> never reproduced in an assertion or a failure message, and the sweep asserts its *absence*
> from every output channel. The canary is a distinct sentinel value seeded by the test,
> not the real key.

| Channel | What the sweep asserts |
|---|---|
| request payloads | the canary is absent from every assembled request the module hands `M-PROV`, and the teacher document text reaches the model ONLY there (the designed egress, `FR-AUTHOR-03`) |
| reply payloads | the canary is absent from every recorded completion the provider hands back |
| log lines | the canary is absent from every record the run emits at ANY level, including `DEBUG` (`FR-AUTHOR-19`) |
| artifacts | the canary is absent from every byte the run writes (the draft, the report, and anything else) |
| AI-call journal | the canary, the real key and the credential shapes are absent from every journal line the run writes, and so are TC-PROV-67's needles: `Authorization`, `Bearer`, `HTTP-Referer` and any base64 run over 200 characters (TC-PROV-67's FR-PROV-46/CT-PROV-31 sweep joins this one, console clarity test plan §4.4; issue #820). A `JsonlCallJournal` is installed for each fixture's draft, outside the artifact folder, and each fixture must journal at least one line per provider request |
| exception messages | the canary is absent from anything `draft()` raises — exercised non-vacuously by the `CT-AUTHOR-09` fail-fast arm this file drives itself (an unreadable document path, refused before any step runs) alongside the thirteen recorded runs |
| egress | the socket guard records zero outbound attempts across all thirteen runs — `SEC-26` doubles as the no-other-egress assertion |

**The two halves, and why both.** As `test_no_credentials_leak.py` records for `TC-CONF-11`,
a scan seeded only through the environment proves the module never *reaches for* a
credential, while a canary placed where the module's outputs could carry it proves nothing
*passes one through*. Authoring's credential path is the environment's (`OPENROUTER_API_KEY`
is the provider's, never the module's), so the sweep runs both halves: the canary is written
into the environment for the run, and the *real* key's value — read out of the environment
before the canary replaces it, and never printed, logged, or echoed by this file — is
asserted absent from every channel alongside it. If the environment carries no key, that
half skips; the canary half never does.

**Non-vacuousness is asserted, not assumed.** A sweep that captures nothing proves nothing:
each fixture's run must have assembled at least one provider request (the payload channel
existed — a request is assembled and handed to `M-PROV` whether the recording answers it or
not), the sweep as a whole must have captured log records and driven all thirteen fixtures,
and it must have captured at least one provider REPLY (the reply-payload channel existed —
if no recording ever answered a request, the reply-channel assertions would pass vacuously
while the sweep looked green, so a floor is asserted across the sweep). The per-fixture
artifact channel is scanned for whatever the run wrote — the report is written "even when
every reasoning step failed, provided at least one document's text was extracted"
(`FR-AUTHOR-12`), so a fixture whose transcription recording is absent may legitimately
write nothing, and the sweep scans what is there rather than pinning a file count that
belongs to `TC-AUTHOR-17`. The exception channel has its own non-vacuousness guard: the
fail-fast arm asserts its input actually raised, because with the thirteen valid fixtures
the recorded tier's `draft()` is designed never to raise (`CT-AUTHOR-10`) and the channel
would otherwise never be exercised.

**The document-text egress half is the parametrized companion test below.** For every
fixture document with a text layer, the whole extracted document text is asserted absent
from the authoring log lines, the artifacts and the exception messages — wholesale document
text never leaves through anything but `M-PROV` (`NFR-AUTHOR-04`) — and a probe phrase from
it is asserted PRESENT in the assembled requests, because a document whose text never
reached the model would make the absence assertions pass for the wrong reason. `AF-10` is
the scan fixture: its pages have no text layer (`TC-AUTHOR-02`), so its case asserts exactly
that and skips rather than pretending an empty extraction sweeps anything; and any document
whose extraction comes back effectively empty (a textless page inside a mixed fixture,
should the corpus ever carry one) skips that document's probes by the same guard rather
than sweeping whitespace.

**Written ahead of the implementation it sweeps — and landed.** #690 shipped the module,
the reasoning steps, the validation gate and #686's captured recordings, so every body's
`require()`/`require_path()` guards resolve and the `writtenahead` marker came off (the
#701 registry entry dropped, the sweep kept). The guards stay: the sweep needs the whole
draft workflow and the recordings behind it, and a missing limb must name itself.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import urllib.parse

import pytest

from aeh.prov import JsonlCallJournal, journal_installed, journal_root
from tests.support.author_vocabulary import (
    AUTHOR_MODULE,
    CORPUS_ISSUE,
    CountingProvider,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
)
from tests.support.impl import require, require_path

pytestmark = [pytest.mark.integration]

#: The corpus the sweep covers, in id order (the §5.5 precondition: "all 13 fixtures").
EXPECTED_AF_IDS = [f"AF-{i:02d}" for i in range(1, 14)]

#: The canary: a distinct sentinel value seeded by the test, never the real key. It is
#: shaped like a real OpenRouter key (`sk-` prefix) so a redaction pass keyed on the real
#: key's shape cannot tell them apart.
CANARY = "sk-or-canary-sec26-sweep-0000000000000000"

#: The credential *shapes* the sweep scans artifacts and exception messages for (the
#: `test_no_credentials_leak.py` pattern half). Deliberately NOT that file's opaque-hex and
#: generic-assignment patterns: the provider's own DEBUG lines carry request keys — sha256
#: hex — and the draft's TOML spells `key = "..."`, so those two would false-positive on
#: honest channels. What remains is exactly the shape a credential takes when it leaks.
CREDENTIAL_PATTERNS = {
    "openrouter / openai key": re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    "bearer token": re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
}


def _canary_forms() -> dict[str, str]:
    """The canary in the three forms `TC-CONF-11` step 2 names — raw, base64 and
    URL-encoded: a filter matching the raw string misses the base64 of the same string
    entirely."""
    return {
        "raw": CANARY,
        "base64": base64.b64encode(CANARY.encode()).decode(),
        "url-encoded": urllib.parse.quote(CANARY, safe=""),
    }


class SweepProvider(CountingProvider):
    """The `CountingProvider` plus the reply half of the payload channel.

    The plan's sweep covers "provider payload" — the request the module assembles AND the
    completion the provider hands back. `CountingProvider` keeps the requests; this adds
    the reply texts, so a credential that arrived inside a recording's completion text is
    swept too.
    """

    def __init__(self, inner):  # noqa: ANN001 — the vocabulary's wrapper sets the shape
        super().__init__(inner)
        self.replies: list[str] = []

    def complete(self, prompt, model_ref, params):  # noqa: ANN001
        completion = super().complete(prompt, model_ref, params)
        self.replies.append(str(getattr(completion, "text", "")))
        return completion


def _guards():
    """The written-ahead guards, each naming the issue that lands its limb (#635's rule).

    The module and its §3.1 names are #690's. The sweep additionally needs nothing from
    #693's gate — it sweeps the workflow's outputs, whatever the validator decided. The
    corpus directories, the recordings tree and the coverage manifest are #686's (the
    manifest is what the registry probe for this file holds on: the sweep stays a
    *credential* sweep even against an empty recordings tree — every miss still assembles a
    request — but the fixture corpus this sweep is written to cover is the recorded one).
    """
    author = require(AUTHOR_MODULE, issue="#690")
    require(
        AUTHOR_MODULE,
        "AuthoringService",
        "DraftResult",
        "AuthoringSettings",
        "AuthoringInputError",
        issue="#690",
    )
    for af_id in EXPECTED_AF_IDS:
        require_path(af(af_id), f"the {af_id} authored fixture", issue=CORPUS_ISSUE)
    require_path(RECORDINGS, "the authoring recordings tree", issue=CORPUS_ISSUE)
    require_path(
        RECORDINGS / "coverage.json",
        "the authoring recordings coverage manifest",
        issue=CORPUS_ISSUE,
    )
    return author


def _records_text(records) -> str:
    """Every log record rendered: the message AND the record's own extra fields (`FR-19`'s
    leak would ride `extra=` as happily as the message)."""
    return "\n".join(
        f"{record.name}|{record.getMessage()}|{record.__dict__!r}" for record in records
    )


def _files_text(out_dir) -> str:
    """Everything the run wrote: file names (a credential can leak into one) and bytes."""
    parts: list[str] = []
    for path in sorted(out_dir.rglob("*")):
        parts.append(path.name)
        if path.is_file():
            parts.append(path.read_bytes().decode("utf-8", errors="replace"))
    return "\n".join(parts)


#: TC-PROV-67's journal needles (FR-PROV-46, CT-PROV-31), over and above the credential
#: shapes: no HTTP header name and no binary payload is journaled.
JOURNAL_NEEDLES = {
    "Authorization header": re.compile(r"Authorization"),
    "Bearer scheme": re.compile(r"Bearer"),
    "HTTP-Referer header": re.compile(r"HTTP-Referer"),
    "base64 run over 200 characters": re.compile(r"[A-Za-z0-9+/]{201,}={0,2}"),
}


def _journal_text(data_dir) -> tuple[str, int]:
    """The AI-call journal channel: every journal file's text, and how many lines it holds."""
    root = journal_root(data_dir)
    texts = [path.read_bytes().decode("utf-8", errors="replace")
             for path in sorted(root.rglob("*")) if path.is_file()]
    return "\n".join(texts), sum(len(text.splitlines()) for text in texts)


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _redact(text: str, *secrets: str) -> str:
    """Every credential-shaped value out of a string that may be embedded in an assertion
    message: this file's rule (and the issue's) is that a credential is never reproduced in
    a failure message — and a failure message about a credential leak is exactly where one
    would otherwise land."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def _payload_text(provider: SweepProvider) -> str:
    """The payload channel, whole: every assembled request and every reply.

    Disclosed reconcile (the landing): the request renders its field values RAW — the
    `repr()`-of-the-call form escaped every newline of the quoted document text as a
    literal backslash-n, so no probe-phrase window drawn from the squeezed document text
    (the `TC-AUTHOR-C16` selection rule below: "a phrase repr cannot mangle") could ever
    match a payload that carried the text, and the egress half failed on documents the
    module had in fact sent. Field values raw render the channel the sweep sweeps; the
    model ref and params keep their `repr` (no document text rides there), and the reply
    half stays raw as it already was.
    """
    return (
        "\n".join(
            " | ".join([f"{name}: {value}" for name, value in prompt.fields]
                       + [repr(model_ref), repr(params)])
            for prompt, model_ref, params in provider.calls)
        + "\n"
        + "\n".join(provider.replies)
    )


# --- SEC-26: the canary sweep over every channel of all thirteen fixtures ---------------------


def test_sec_26_the_seeded_canary_reaches_no_channel_of_any_of_the_thirteen_fixtures(
    tmp_path, caplog, network_guard, monkeypatch, make_fixture_provider
):
    """With the canary in the environment (and the real key's value, if one is set, read
    out first), a full recorded draft round trip of all 13 fixtures leaves the credential in
    no request payload, no reply, no log line, no artifact and no exception message — and
    the socket guard records zero outbound attempts (`NFR-AUTHOR-04`, `CT-AUTHOR-16`)."""
    author = _guards()
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    # The real key, read out before the canary replaces it, and never printed: the sweep
    # asserts its *absence* (the issue's technical note), reporting only WHICH channel
    # leaked, if any.
    real_key = os.environ.get("OPENROUTER_API_KEY")
    monkeypatch.setenv("OPENROUTER_API_KEY", CANARY)
    caplog.set_level(logging.DEBUG)

    leaked: list[str] = []
    runs = 0
    records_seen = 0
    providers: list[SweepProvider] = []
    for af_id in EXPECTED_AF_IDS:
        provider = SweepProvider(make_fixture_provider(recordings))
        providers.append(provider)
        caplog.clear()
        exc_text = ""
        journal_dir = tmp_path / "journal" / af_id
        try:
            with journal_installed(JsonlCallJournal(journal_dir)):
                make_service(author, chain_from_config(), provider).draft(
                    documents=sorted(af(af_id).glob("*.pdf")), output_dir=tmp_path / af_id
                )
        except Exception as exc:  # noqa: BLE001 — the sweep owns every failure text
            exc_text = f"{type(exc).__name__}: {exc}"
        runs += 1
        journal_text, journal_lines = _journal_text(journal_dir)
        records_seen += len(caplog.records)

        channels = {
            "request payloads": _payload_text(provider),
            "log lines": _records_text(caplog.records),
            "artifacts": _files_text(tmp_path / af_id),
            "exception messages": exc_text,
            "AI-call journal": journal_text,
        }

        for form, needle in _canary_forms().items():
            for channel, text in channels.items():
                if needle in text:
                    leaked.append(f"{af_id}: {form} canary in {channel}")
        if real_key:
            for channel, text in channels.items():
                if real_key in text:
                    leaked.append(f"{af_id}: the real environment key in {channel}")
        for shape, pattern in CREDENTIAL_PATTERNS.items():
            for channel in ("artifacts", "exception messages", "AI-call journal"):
                if pattern.search(channels[channel]):
                    leaked.append(f"{af_id}: {shape} shape in {channel}")
        for needle, pattern in JOURNAL_NEEDLES.items():
            if pattern.search(journal_text):
                leaked.append(f"{af_id}: {needle} in AI-call journal")

        # Non-vacuousness: the payload channel existed for this fixture — a request was
        # assembled and handed to M-PROV whether its recording answered it or not — or the
        # sweep asserted nothing. Any exception text quoted here is redacted first: a
        # failure ABOUT a leak is the one place a credential would otherwise be reproduced.
        assert provider.calls, (
            f"SEC-26 swept {af_id} without a single provider request — the payload "
            f"channel never existed, so the sweep proved nothing for this fixture"
            + (f" (the run raised: {_redact(exc_text, CANARY, real_key or '')!r})"
               if exc_text else "")
        )
        # The journal channel, non-vacuously: one line per attempt, so at least one per request.
        assert journal_lines >= len(provider.calls), (
            f"SEC-26 swept {af_id}'s AI-call journal with {journal_lines} line(s) for "
            f"{len(provider.calls)} provider request(s): the journal was not written for every "
            f"call, so its absence assertions proved nothing")

    # The exception-message channel, non-vacuously: the thirteen valid fixtures are
    # designed never to raise on the recorded tier (`CT-AUTHOR-10`), so the sweep drives
    # the fail-fast arm itself (`CT-AUTHOR-09`): a document path that does not exist is
    # refused before any step runs, and the sweep sweeps that refusal text like any other
    # channel. The arm asserts its input actually raised — otherwise the channel was never
    # exercised and its absence assertions proved nothing.
    fail_fast = tmp_path / "no-such-document.pdf"
    ff_exc = ""
    try:
        make_service(author, chain_from_config(), SweepProvider(
            make_fixture_provider(recordings))).draft(
            documents=[fail_fast], output_dir=tmp_path / "fail-fast")
    except Exception as exc:  # noqa: BLE001 — the sweep owns every failure text
        ff_exc = f"{type(exc).__name__}: {exc}"
    assert ff_exc, (
        "the fail-fast input did not raise — the exception-message channel was never "
        "exercised, so this sweep's exception-channel absence assertions proved nothing"
    )
    for form, needle in _canary_forms().items():
        if needle in ff_exc:
            leaked.append(f"fail-fast arm: {form} canary in exception messages")
    if real_key and real_key in ff_exc:
        leaked.append("fail-fast arm: the real environment key in exception messages")
    for shape, pattern in CREDENTIAL_PATTERNS.items():
        if pattern.search(ff_exc):
            leaked.append(f"fail-fast arm: {shape} shape in exception messages")

    assert records_seen > 0, (
        "the sweep captured no log record at all — the log channel never existed, so the "
        "log-line assertions proved nothing"
    )
    assert any(len(provider.replies) for provider in providers), (
        "the sweep captured no provider reply at all — the reply-payload channel never "
        "existed (no recording answered any request), so the reply-channel absence "
        "assertions proved nothing"
    )
    assert not leaked, (
        "SEC-26: a credential reached an output channel:\n  "
        + "\n  ".join(_redact(line, CANARY, real_key or "") for line in leaked)
    )
    network_guard.assert_no_network()


# --- SEC-26's egress half: teacher text leaves only through the payloads ----------------------


def _extracted_documents(af_id: str) -> list[tuple[str, str]]:
    """`(document name, extracted text)` for the fixture's PDFs, read with the same library
    the module uses (`FR-AUTHOR-02`'s `pypdf`) — the text whose only exit is a step request
    through `M-PROV` (`FR-AUTHOR-03`)."""
    from pypdf import PdfReader

    return [
        (path.name, " ".join(" ".join((page.extract_text() or "").split())
                             for page in PdfReader(str(path)).pages))
        for path in sorted(af(af_id).glob("*.pdf"))
    ]


@pytest.mark.parametrize("af_id", EXPECTED_AF_IDS)
def test_sec_26_teacher_document_text_leaves_only_through_provider_payloads(
    af_id, tmp_path, caplog, network_guard, make_fixture_provider
):
    """Per fixture: the whole extracted document text is absent from the authoring log
    lines, the artifacts and any exception message — wholesale document text never leaves
    through anything but `M-PROV` (`NFR-AUTHOR-04`) — while a probe phrase from it IS inside
    the assembled requests, because a document whose text never reached the model would make
    every absence assertion here pass for the wrong reason (`FR-AUTHOR-03`'s designed
    egress)."""
    author = _guards()
    caplog.set_level(logging.DEBUG)

    documents = _extracted_documents(af_id)
    assert documents, f"{af_id} carries no PDF document at all"
    if af_id == "AF-10":
        # The scan fixture: no text layer by design (`TC-AUTHOR-02`), so there is no
        # wholesale text to sweep — assert exactly that rather than sweep nothing.
        textless = [name for name, text in documents if len(_squeeze(text)) < 200]
        assert len(textless) == len(documents), (
            f"AF-10 was specified as the no-text-layer fixture, but "
            f"{sorted(name for name, _ in documents if name not in textless)} carry a text "
            f"layer — the corpus changed under this case"
        )
        pytest.skip("AF-10 has no text layer by design; its egress is the transcription payload")

    provider = SweepProvider(make_fixture_provider(RECORDINGS))
    exc_text = ""
    try:
        make_service(author, chain_from_config(), provider).draft(
            documents=sorted(af(af_id).glob("*.pdf")), output_dir=tmp_path / "out"
        )
    except Exception as exc:  # noqa: BLE001 — the sweep owns every failure text
        exc_text = f"{type(exc).__name__}: {exc}"

    payloads = _squeeze(_payload_text(provider))
    artifacts = _squeeze(_files_text(tmp_path / "out"))
    author_records_sq = _squeeze(
        _records_text([r for r in caplog.records if r.name == AUTHOR_MODULE])
    )
    exc_sq = _squeeze(exc_text)

    for name, text in documents:
        squeezed = _squeeze(text)
        if len(squeezed) < 200:
            # An effectively textless document (a scan page, should the corpus carry one
            # inside a mixed fixture): there is no wholesale text to sweep — the
            # transcription payload is its designed egress, disclosed in the docstring.
            continue
        # A probe phrase that repr() cannot mangle: no quote, no backslash in the window
        # (the `TC-AUTHOR-C16` selection rule).
        phrase = next(
            squeezed[i:i + 40] for i in range(0, len(squeezed) - 40, 25)
            if not (set(squeezed[i:i + 40]) & {'"', "'", "\\"})
        )
        assert phrase in payloads, (
            f"{af_id}/{name}: the document text never reached the model through M-PROV — "
            f"the designed egress did not happen, so this sweep's absence assertions "
            f"would be vacuous"
        )
        assert squeezed not in author_records_sq, (
            f"{af_id}/{name}: wholesale document text in an authoring log line"
        )
        assert squeezed not in artifacts, (
            f"{af_id}/{name}: wholesale document text in an artifact"
        )
        assert squeezed not in exc_sq, (
            f"{af_id}/{name}: wholesale document text in an exception message"
        )

    network_guard.assert_no_network()