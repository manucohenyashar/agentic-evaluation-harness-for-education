"""The canonical byte encoding of a request, and `request_key`, its SHA-256 hash."""

from __future__ import annotations

import dataclasses
import hashlib
from decimal import Decimal
from typing import Any

from aeh.conf import ModelRef

from .records import PromptPayload, SamplingParams


# --- the canonical request encoding -------------------------------------------------------------
#
# `FR-PROV-13`/`CT-PROV-05` (dispatch the payload byte-identically) and `FR-PROV-10` (key the
# fixture on a hash of the fully-assembled request) are the same problem seen from two sides,
# so they share one encoding. Both are served by *framing*: every component goes into the
# stream as an 8-byte big-endian length followed by its bytes.
#
# Framing rather than a separator join, and that is the whole point of this block. A join over
# `(name, value)` pairs is not injective when a value may contain the separator — and payload
# values are submission prose, which legitimately contains newlines, tabs and every byte a
# separator could be. `ModelRef` closed the same hole on #4 by refusing control characters;
# that fix is unavailable here. Without framing, a single field reading
# `"...\x1fsubmission\x1f..."` can produce the key of a *different* two-field payload — a
# stale fixture silently answering a changed prompt, which is verbatim the RISK-37 failure
# `TC-PROV-14` exists to prevent, arriving through the encoding rather than through the hash.

#: Bumping this invalidates every stored key, which is exactly what an encoding change should
#: do: a fixture recorded under a different scheme misses loudly instead of answering.
KEY_SCHEME = b"aeh.prov/request-key/1"


_FRAME_WIDTH = 8


_TAG_NONE = b"\x00"


_TAG_BOOL = b"\x01"


_TAG_INT = b"\x02"


_TAG_FLOAT = b"\x03"


_TAG_STR = b"\x04"


_TAG_DECIMAL = b"\x05"


_TAG_SEQ = b"\x06"


#: Named explicitly rather than read from `dataclasses.fields(ModelRef)`: `M-CONF` owns that
#: type, and a field added there must be a deliberate decision here — silently rekeying every
#: recording in the repository is not something `M-CONF` should be able to do by accident.
_MODEL_REF_FIELDS = ("role", "provider", "build_id", "quantization")


def _frame(chunk: bytes) -> bytes:
    """`chunk`, length-prefixed, so a concatenation of frames decodes unambiguously."""
    return len(chunk).to_bytes(_FRAME_WIDTH, "big") + chunk


def _emit_framed(emit: Any, chunk: bytes) -> None:
    """`_frame`, without the concatenation. Two emits, byte-identical to one framed chunk.

    `emit` is `hashlib`'s `update` or a `bytearray`'s `extend`. Split in two because
    `_frame(value)` allocates a second copy of every field value, and field values are the
    invariant prefix `NFR-PROV-02` forbids copying per call.
    """
    emit(len(chunk).to_bytes(_FRAME_WIDTH, "big"))
    emit(chunk)


def _emit_payload(emit: Any, prompt: PromptPayload) -> None:
    """The payload's canonical encoding, emitted in the caller's field order.

    **The only place a `PromptPayload` is encoded.** `payload_bytes` and `request_key` both go
    through here, so the wire body and the fixture key can never disagree about what the
    payload was — which is what would otherwise let a change to one silently fail to move the
    other once #21 derives its request body from `payload_bytes`.

    A value that is not encodable as UTF-8 (a lone surrogate) raises `UnicodeEncodeError`,
    which is a `ValueError` — the same class `PromptPayload.__post_init__` raises for every
    other malformed payload, and not part of the `ProviderError` taxonomy, because a payload
    that cannot be encoded is a caller defect rather than a provider failure.
    """
    for name, value in prompt.fields:
        _emit_framed(emit, name.encode("utf-8"))
        _emit_framed(emit, value.encode("utf-8"))


def _encode_scalar(value: Any) -> bytes:
    """One `ModelRef` or `SamplingParams` value, type-tagged and framed.

    The tag is what keeps `0`, `0.0`, `"0"` and `Decimal("0")` four distinct requests. Floats
    go in as `float.hex`, which is exact and canonical — `str(0.1)` is neither across
    platforms, and a key that drifts by platform is a fixture set that misses on CI only.
    """
    if value is None:
        return _TAG_NONE + _frame(b"")
    if isinstance(value, bool):  # before int: bool is a subclass of it
        return _TAG_BOOL + _frame(b"1" if value else b"0")
    if isinstance(value, int):
        return _TAG_INT + _frame(str(value).encode("utf-8"))
    if isinstance(value, float):
        return _TAG_FLOAT + _frame(float.hex(value).encode("ascii"))
    if isinstance(value, str):
        return _TAG_STR + _frame(value.encode("utf-8"))
    if isinstance(value, Decimal):
        return _TAG_DECIMAL + _frame(str(value).encode("ascii"))
    if isinstance(value, (tuple, list)):
        body = b"".join(_encode_scalar(item) for item in value)
        return _TAG_SEQ + _frame(len(value).to_bytes(_FRAME_WIDTH, "big") + body)
    raise ValueError(
        f"cannot encode {type(value).__name__} into a request key. Every part of the "
        f"assembled request must have a canonical encoding (FR-PROV-10); add a tag above "
        f"rather than letting an unencodable value fall through to a shared key."
    )


def payload_bytes(prompt: PromptPayload) -> bytes:
    """The caller's assembled payload, serialized without adding, reordering or normalizing.

    The single point at which a `PromptPayload` becomes bytes, so `CT-PROV-05`'s byte-level
    differential has one thing to compare against. Field order is the caller's, names and
    values are verbatim, and nothing is inserted between them but the frame lengths.

    `complete()` does **not** call this — the fixture path needs only the key, and hashing
    streams (see `request_key`). It exists for the live implementations of #21, which derive
    their wire body from it, and for the differential itself. Both go through `_emit_payload`,
    so this function and the key can never encode the same payload differently.
    """
    buffer = bytearray()
    _emit_payload(buffer.extend, prompt)
    return bytes(buffer)


def request_key(
    prompt: PromptPayload, model_ref: ModelRef, params: SamplingParams
) -> str:
    """`sha256` over the fully-assembled request: payload, model ref and sampling params.

    Everything that would change what a backend returns is in here, which is what makes
    `TC-PROV-14` pass for the right reason: a punctuation byte, a whitespace change, a case
    change, a different build and a different temperature each move the key, because each is
    part of the request rather than of a normalized view of it.

    Streamed into the hasher rather than assembled into a buffer, and framed without
    concatenation (`_emit_framed`), so the only copy of a field value made per call is the one
    `str.encode` must make for `hashlib`. `NFR-PROV-02` forbids a per-call copy of the
    invariant prefix — the prefix is a shared string the caller owns, and hashing it in place
    means an observed `cache_hit_rate` reflects the caller's prompt ordering rather than this
    module's allocation behaviour (`CT-PROV-12`).

    The element counts go in ahead of the elements. Framing alone decodes unambiguously
    *within* a section; the counts are what keep a payload field named `"model_ref"` from
    being read as the start of the next section.
    """
    digest = hashlib.sha256()
    digest.update(_frame(KEY_SCHEME))

    digest.update(_frame(b"payload"))
    digest.update(len(prompt.fields).to_bytes(_FRAME_WIDTH, "big"))
    _emit_payload(digest.update, prompt)

    digest.update(_frame(b"model_ref"))
    for name in _MODEL_REF_FIELDS:
        digest.update(_frame(name.encode("utf-8")))
        digest.update(_encode_scalar(getattr(model_ref, name)))

    digest.update(_frame(b"params"))
    param_fields = dataclasses.fields(params)
    digest.update(len(param_fields).to_bytes(_FRAME_WIDTH, "big"))
    for field in param_fields:
        digest.update(_frame(field.name.encode("utf-8")))
        digest.update(_encode_scalar(getattr(params, field.name)))

    return "sha256:" + digest.hexdigest()
