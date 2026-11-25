"""TC-JUDGE-51 (#907), the manifest arm: the judge recordings were re-keyed honestly.

Traces: FR-JUDGE-42, CT-JUDGE-31; RSV-19. Source: `docs/design/statistical_validity_test_plan.md`
§3.1, story T10. The re-key is #863 (PR #918), so this case is not written ahead.

S1 moved the judge prompt from judge-prompt/3 to /4: `cited_spans` is now declared as
`{start, end, text}`. That changes every judge request, so every judge recording's key moved too.
The recordings were re-keyed, not re-captured. The old declaration in each stored request was
replaced and the key recomputed, and the reply was left as it was. The sha256 manifest of the
replies is committed at `tests/regression/baselines/judge_prompt_4_rekey.json`.

For every `F-*` recording of a judge-prompt request:

- every `cited_spans` item in the reply carries `text`;
- the reply bodies equal the bodies from before the re-key, byte for byte. This is a multiset
  over the manifest's `reply_sha256_before` (duplicates included), compared per corpus;
- no reply exists without a captured request. The stored request rebuilds into a
  `PromptPayload`, `ModelRef` and `SamplingParams` whose `request_key` equals the stored key and
  the file name. A reply whose request was edited, or written by hand under an invented key,
  fails here.

**The universe.** The census looks at every `fixtures/F-*` file, not only the manifest's five
directories. A judge-prompt recording that sits in a directory the manifest does not list is a
recording the re-key never accounted for, and it fails the census. "Judge-prompt" means the
request carries the judge directive's fields. F-AUTHOR also has `role = "judge"` recordings, but
those are authoring calls (`instruction`, `prompt_template_version`, `documents`), and they are
named as such below.

The property arm, over the F-DEV replay, is
`tests/integration/judge/test_tc_judge_51_stored_spans_verify.py`.

Isolation: rung 0. Files on disk, `request_key`, no store, no provider.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from aeh.conf import ModelRef
from aeh.prov import request_key
from aeh.prov.records import PromptPayload, SamplingParams

pytestmark = pytest.mark.contract

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "fixtures"
MANIFEST = REPO / "tests" / "regression" / "baselines" / "judge_prompt_4_rekey.json"

#: The judge request's fields, in the order the prompt assembles them (judge-prompt/4).
JUDGE_FIELDS = ("directive", "criterion", "bands", "question", "exemplars", "evidence_rules",
                "submission")
#: The field names of F-AUTHOR's authoring calls, which also run under `role = "judge"`.
AUTHORING_FIELDS = ("instruction", "prompt_template_version", "documents")
#: 26 + 30 + 30 + 24 + 192, the manifest's own count (#863's commit message: "The 302 judge
#: recordings are re-keyed").
JUDGE_RECORDINGS = 302


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _completion_recordings() -> list[tuple[Path, dict]]:
    """Every `aeh.prov/fixture/1` recording under `fixtures/F-*`, with its parsed document."""
    out = []
    for path in sorted(FIXTURES.glob("F-*/**/*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(document, dict) and document.get("schema") == "aeh.prov/fixture/1":
            out.append((path, document))
    return out


def _field_names(document: dict) -> tuple[str, ...]:
    return tuple(name for name, _ in document["request"]["fields"])


def _judge_recordings() -> dict[str, list[tuple[Path, dict]]]:
    """Judge-prompt recordings, grouped by their directory relative to the repo."""
    grouped: dict[str, list[tuple[Path, dict]]] = {}
    for path, document in _completion_recordings():
        if _field_names(document) == JUDGE_FIELDS:
            grouped.setdefault(path.parent.relative_to(REPO).as_posix(), []).append(
                (path, document))
    return grouped


def _rebuilt_key(request: dict) -> str:
    """`request_key` over the stored request, rebuilt into the provider's own types."""
    params = dict(request["params"])
    params["stop"] = tuple(params["stop"])
    return request_key(PromptPayload(fields=tuple((n, v) for n, v in request["fields"])),
                       ModelRef(**request["model_ref"]), SamplingParams(**params))


def test_tc_judge_51_every_judge_recording_is_in_the_rekey_manifest():
    """The census: every judge-prompt recording is in a corpus the manifest accounts for, it
    declares the judge-prompt/4 shape, and the total is the manifest's 302."""
    manifest = _manifest()
    grouped = _judge_recordings()
    assert set(grouped) == set(manifest["recordings"]), (
        f"judge-prompt recordings outside the re-key manifest: "
        f"{sorted(set(grouped) - set(manifest['recordings']))}; manifest corpora with none: "
        f"{sorted(set(manifest['recordings']) - set(grouped))}")
    assert sum(len(v) for v in grouped.values()) == JUDGE_RECORDINGS
    for corpus, recordings in grouped.items():
        assert len(recordings) == manifest["recordings"][corpus]["recordings_rekeyed"], corpus
        for path, document in recordings:
            directive = dict(document["request"]["fields"])["directive"]
            assert manifest["new_shape"] in directive, f"{path.name}: not judge-prompt/4"
            assert manifest["old_shape"] not in directive, f"{path.name}: still judge-prompt/3"
            assert document["request"]["model_ref"]["role"] == "judge", path.name

    # Everything else with `role = "judge"` is an F-AUTHOR authoring call, not a judge prompt.
    others = {(path.parent.relative_to(REPO).parts[1], _field_names(document)[:3])
              for path, document in _completion_recordings()
              if document["request"]["model_ref"]["role"] == "judge"
              and _field_names(document) != JUDGE_FIELDS}
    assert others == {("F-AUTHOR", AUTHORING_FIELDS)}, others


def test_tc_judge_51_every_cited_span_in_a_judge_reply_carries_text():
    """FR-JUDGE-42: each reply's `cited_spans` items carry `text` (a non-empty quote)."""
    checked = 0
    for corpus, recordings in _judge_recordings().items():
        for path, document in recordings:
            reply = json.loads(document["completion"]["text"])
            spans = reply["cited_spans"]
            assert isinstance(spans, list), (corpus, path.name, reply)
            for span in spans:
                assert isinstance(span.get("text"), str) and span["text"], (
                    f"{corpus}/{path.name}: a cited span without its quote: {span}")
                checked += 1
    assert checked >= JUDGE_RECORDINGS, f"only {checked} cited spans checked"


def test_tc_judge_51_reply_bodies_are_byte_identical_to_before_the_rekey():
    """Per corpus, the sha256 multiset of the reply bodies equals the manifest's BEFORE list. A
    reply that was edited, added or dropped since judge-prompt/3 changes the multiset."""
    manifest = _manifest()["recordings"]
    for corpus, recordings in _judge_recordings().items():
        now = Counter(hashlib.sha256(document["completion"]["text"].encode("utf-8")).hexdigest()
                      for _, document in recordings)
        before = Counter(manifest[corpus]["reply_sha256_before"])
        assert now == before, (
            f"{corpus}: reply bodies moved since the re-key; now-only {now - before}, "
            f"before-only {before - now}")


def test_tc_judge_51_no_reply_exists_without_its_captured_request():
    """Every judge reply's stored request rebuilds to its own key, which is also its file name,
    and the key is one the manifest maps an old judge-prompt/3 key onto."""
    manifest = _manifest()["recordings"]
    for corpus, recordings in _judge_recordings().items():
        mapped = set(manifest[corpus]["keys"].values())
        for path, document in recordings:
            key = _rebuilt_key(document["request"])
            assert key == document["key"], (
                f"{corpus}/{path.name}: stored key {document['key']} is not the request's "
                f"{key}: a reply with no matching captured request")
            assert path.name == key.replace(":", "-") + ".json", path.name
            assert key in mapped, f"{corpus}/{path.name}: a key the re-key map never produced"
        assert len(mapped) == len(recordings), corpus
