"""`python -m harness.corpora.build` — emit `fixtures/`, or check that it is still what the
generator emits.

    python -m harness.corpora.build              # write fixtures/ from the generators
    python -m harness.corpora.build --check      # regenerate into a temp dir and diff

`--check` is what `tests/regression/test_corpora_are_reproducible.py` runs, and it is the
mechanism behind §8.1's word *reproducible*: a corpus edited by hand, a generator edited
without rebuilding, or a checkout that mangled line endings all fail it, and each failure
names the files that differ.

Everything is written with explicit `\\n` line endings and UTF-8. `.gitattributes` pins
`fixtures/**` to LF for the same reason: content addressing is over bytes, so a CRLF checkout
would give the same corpus different hashes on Windows and Linux and quietly break every
manifest in the tree.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from harness.corpora import adv_inj, adv_pdf, graphic, hand, reference_package, stats, synth
from harness.corpora.baselines import (
    BASELINES,
    WORK_ID_INPUTS,
    work_id_reference_tuples,
)
from harness.corpora.manifest import (
    CORPUS_ROOT,
    Manifest,
    ManifestEntry,
    as_document,
    entries_from,
    fixture_set_id,
    set_content_hash,
    write_manifest,
)

CORPUS_VERSION = "1"


def _json_bytes(payload: object) -> bytes:
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
    return (text + "\n").encode("utf-8")


def _build_submission_corpus(root: Path, corpus: str, seed: int, generator: str,
                             description: str,
                             submissions: tuple[synth.SyntheticSubmission, ...]) -> None:
    members = [
        (
            s.submission_id,
            f"submissions/{s.submission_id}.md",
            as_document(s.as_document()),
            {
                "student_ref": s.student_ref,
                "consent_class": "synthetic",
                # Declared honestly rather than left absent. `FR-CONFORM-03` requires the
                # conformance set to carry *real* scanned handwriting; these are generated
                # Markdown and say so. Stamping `scanned_handwriting` here would make
                # `CT-CONFORM-02`'s composition assertion pass against a clean-typed-text
                # corpus — the exact measurement §6.11.18 says that clause exists to prevent.
                # See `harness.corpora.hand` for where the real-medium tier is declared.
                "media_kind": hand.SYNTHETIC_MEDIA_KIND,
                "pages": len(s.pages),
                # The known reference labels FR-CONFORM-01 requires of the frozen set. Carried
                # by every submission corpus, because an agreement figure computed against a
                # corpus with no reference labels is a figure against nothing.
                "reference_bands": dict(s.bands),
                "reference_points": s.reference_points,
            },
        )
        for s in submissions
    ]
    entries = entries_from(root, members)
    write_manifest(
        root,
        Manifest(
            corpus=corpus,
            version=CORPUS_VERSION,
            seed=seed,
            generator=generator,
            description=description,
            entries=entries,
            extra={
                "package_id": reference_package.PACKAGE_ID,
                "package_version": reference_package.PACKAGE_VERSION,
                "consent_class": "synthetic",
                "max_points": reference_package.MAX_POINTS,
            },
        ),
    )


def _build_graphic(root: Path) -> None:
    members = [
        (
            page.page_id,
            f"pages/{page.page_id}.md",
            as_document(
                f"# {page.page_id}\n\n"
                f"element_kind: {page.element_kind}\n"
                f"question_id: {page.question_id}\n"
                f"consent_class: synthetic\n\n"
                f"{page.page_source}"
            ),
            {
                "element_kind": page.element_kind,
                "question_id": page.question_id,
                # The same two declarations every other committed corpus carries. F-GRAPHIC is
                # the corpus most likely to be mislabelled a real medium later — it stands in for
                # page *images* — and review found it sitting outside both sweeps, so neither the
                # consent check nor the media check would have noticed.
                "consent_class": "synthetic",
                "media_kind": hand.SYNTHETIC_MEDIA_KIND,
                "required_fields": list(page.required_fields),
                **page.extra,
            },
        )
        for page in graphic.PAGES
    ]
    entries = entries_from(root, members)
    write_manifest(
        root,
        Manifest(
            corpus="F-GRAPHIC",
            version=CORPUS_VERSION,
            seed=None,
            generator="harness.corpora.graphic",
            description=(
                "One page per FR-INGEST-10 element kind, plus the page whose correct "
                "description is easily confusable with a verdict (FR-INGEST-11)."
            ),
            entries=entries,
            extra={
                "consent_class": "synthetic",
                "element_kinds": list(graphic.ELEMENT_KINDS),
                "evaluative_terms": list(graphic.EVALUATIVE_TERMS),
            },
        ),
    )


def _build_adv_inj(root: Path) -> None:
    """`F-ADV-INJ` — both halves of every twin pair, in pair order.

    The pairing is carried in the manifest by `twin_id` on **both** members, so a reader of one
    entry can find the other without reconstructing the naming convention. `payload_line` is what
    lets `TC-CONFORM-09` reconstruct the benign document from the injected one and assert the two
    really are identical but for the payload.
    """
    members = []
    for member in adv_inj.submissions():
        extra: dict[str, object] = {
            "student_ref": member.student_ref,
            "consent_class": "synthetic",
            "media_kind": hand.SYNTHETIC_MEDIA_KIND,
            "pair_id": member.pair_id,
            "variant": member.variant,
            "twin_id": member.twin_id,
            # `null` for the benign half rather than absent, so a case can select on the key
            # without a membership test — and so a benign member that acquired a payload would
            # show up as a changed value rather than as a new key nobody was reading.
            "injection_kind": member.injection_kind,
            "pages": len(member.pages),
            "reference_bands": dict(member.bands),
            "reference_points": member.reference_points,
        }
        if member.payload is not None:
            extra["payload_line"] = member.payload_line
            extra["payload_lines"] = list(member.payload.lines)
            extra["payload_intent"] = member.payload.intent
            if member.payload.forged_quote is not None:
                extra["forged_quote"] = member.payload.forged_quote
        members.append(
            (
                member.submission_id,
                f"submissions/{member.submission_id}.md",
                as_document(member.as_document()),
                extra,
            )
        )

    entries = entries_from(root, members)
    write_manifest(
        root,
        Manifest(
            corpus="F-ADV-INJ",
            version=CORPUS_VERSION,
            seed=adv_inj.INJ_SEED,
            generator="harness.corpora.adv_inj:twin_pairs",
            description=(
                "Injection twin pairs (§4.4, FR-CONFORM-09). Each pair is one submission "
                "carrying an injection payload and one benign twin identical in content but "
                "for the payload; both halves carry the same reference bands, so a band "
                "difference downstream is attributable to the payload and to nothing else."
            ),
            entries=entries,
            extra={
                "package_id": reference_package.PACKAGE_ID,
                "package_version": reference_package.PACKAGE_VERSION,
                "consent_class": "synthetic",
                "pairs": len(adv_inj.twin_pairs()),
                "payload_kinds": list(adv_inj.PAYLOAD_KINDS),
                "pairs_per_kind": adv_inj.PAIRS_PER_KIND,
            },
        ),
    )


def _build_adv_pdf(root: Path) -> None:
    """`F-ADV-PDF` — the manifest only. §4.7: *generated, not committed as binaries*.

    The digests are computed by generating each construct here and discarding the bytes, which is
    what keeps `--check` able to catch a generator edited without a rebuild while leaving fourteen
    scanner-tripping files out of the repository. `materialize_adv_pdfs` writes the real files
    into a temp directory when a case needs them, verifying each against the digest below.
    """
    root.mkdir(parents=True, exist_ok=True)
    rows = adv_pdf.manifest_entries()
    # Hashed the same way every other corpus is, although this manifest is assembled by hand:
    # `NFR-CONFORM-01`'s content addressing is about the set, and a corpus exempt from it because
    # its bytes are not committed would be the one corpus nobody could cite.
    digest = set_content_hash(
        tuple(
            ManifestEntry(id=row["id"], path=row["path"], content_hash=row["content_hash"])
            for row in rows
        )
    )
    (root / "manifest.json").write_bytes(
        _json_bytes(
            {
                "corpus": "F-ADV-PDF",
                "version": CORPUS_VERSION,
                "seed": None,
                "generator": "harness.corpora.adv_pdf:build_construct",
                "set_content_hash": digest,
                "fixture_set_id": fixture_set_id("F-ADV-PDF", CORPUS_VERSION, digest),
                "description": (
                    "One PDF per malicious or malformed construct §4.4 names. Every one must "
                    "quarantine at V0 and reach no model call (FR-CONFORM-09, FR-INGEST-33/34, "
                    "NFR-INGEST-08, R74)."
                ),
                # The header field that says why there are no files next to this manifest.
                "committed_bytes": False,
                "committed_bytes_reason": (
                    "Test plan §4.7: F-ADV-PDF is generated, not committed as binaries. The "
                    "digests below are what make it reproducible from committed scripts (§4.8); "
                    "tests.support.corpora.materialize_adv_pdfs() writes the files on demand."
                ),
                "consent_class": "synthetic",
                "expected_outcome": adv_pdf.EXPECTED_OUTCOME,
                "quarantine_gate": adv_pdf.QUARANTINE_GATE,
                "expected_model_calls": adv_pdf.EXPECTED_MODEL_CALLS,
                "constructs_in_section_4_4_order": list(adv_pdf.SECTION_4_4_CONSTRUCTS),
                "submissions": rows,
            }
        )
    )


def _build_hand(root: Path) -> None:
    """`F-HAND` — a declaration, and no student work. See `harness.corpora.hand`."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "registry.json").write_bytes(_json_bytes(hand.registry()))


def _build_stats(root: Path) -> None:
    members = [
        (str(case["case_id"]), f"cases/{case['case_id']}.json", _json_bytes(case), None)
        for case in stats.CASES
    ]
    entries = entries_from(root, members)
    write_manifest(
        root,
        Manifest(
            corpus="F-STATS",
            version=CORPUS_VERSION,
            seed=None,
            generator="harness.corpora.stats",
            description=(
                "Label sets whose kappa, QWK, ordinal alpha, entropy and interior rate were "
                "worked out by hand, including every degenerate case NFR-STATS-01 names."
            ),
            entries=entries,
            extra={"note": "Undefined figures are null with a stated reason, never 0 (CT-STATS-03)."},
        ),
    )


def _build_baselines(root: Path) -> None:
    registry = {
        "source": "docs/design/test-plan.md §6.9",
        "policy": (
            "Snapshot testing degrades into 'regenerate until green' unless the reviewer and "
            "the grounds are named. No golden file in this registry may be regenerated without "
            "the named reviewer and one of the stated grounds."
        ),
        "work_id_inputs": list(WORK_ID_INPUTS),
        "baselines": [b.as_json() for b in BASELINES],
    }
    (root / "registry.json").parent.mkdir(parents=True, exist_ok=True)
    (root / "registry.json").write_bytes(_json_bytes(registry))

    # The `TC-REG-06` baseline population. The `work_id` values are null until `M-ORCH` exists
    # — see `harness.corpora.baselines` for why a guessed digest would be worse than none.
    work_id_dir = root / "TC-REG-06"
    work_id_dir.mkdir(parents=True, exist_ok=True)
    (work_id_dir / "work-id-reference.inputs.json").write_bytes(
        _json_bytes(
            {
                "requirement": "FR-ORCH-01",
                "inputs_in_requirement_order": list(WORK_ID_INPUTS),
                "note": (
                    "Ten tuples: a base, and one variant per input differing in exactly that "
                    "one field. FR-ORCH-01 promises each variant is a different unit."
                ),
                "tuples": work_id_reference_tuples(),
            }
        )
    )


def _build_package(root: Path) -> None:
    (root / "reference-package.json").parent.mkdir(parents=True, exist_ok=True)
    (root / "reference-package.json").write_bytes(_json_bytes(reference_package.as_json()))


_README = """\
# fixtures/ — generated. Do not edit by hand.

Every file in this tree is emitted by `python -m harness.corpora.build`, and
`python -m harness.corpora.build --check` fails if any of them differs from what the
generators produce. That check runs as a test
(`tests/regression/test_corpora_are_reproducible.py`), so a hand edit here fails the suite
rather than surviving as an artifact nobody can account for — test-plan §8.1: the corpora are
*"generated from committed scripts so they are reproducible rather than archaeological"*.

To change a corpus, change its generator under `harness/corpora/` and rebuild.

| Path | What it is |
|---|---|
| `package/` | The 5-question, 15-criterion reference package every corpus is written against (§4.4) |
| `F-SYNTH/` | 350 generated submissions with known reference bands |
| `F-FROZEN/` | The held-out conformance set, 36 submissions spanning the score range (`FR-CONFORM-01`) |
| `F-DEV/` | The 8 submissions development iterates against, disjoint from `F-FROZEN` (`TC-CONFORM-10`) |
| `F-GRAPHIC/` | One page per `FR-INGEST-10` element kind, plus the confusable-with-a-verdict page |
| `F-STATS/` | Label sets whose statistics were worked out by hand (`NFR-STATS-01`) |
| `F-ADV-INJ/` | Injection twin pairs: each payload paired with a benign twin (`FR-CONFORM-09`) |
| `F-ADV-PDF/` | **Manifest only.** One entry per malicious/malformed construct, with the digest of the bytes the generator emits |
| `F-HAND/` | **Declaration only.** The consented real-handwriting corpus is never committed (§4.4 Tier C) |
| `baselines/` | The §6.9 golden-baseline registry: which artifact, whose signature, on what grounds |

`F-ADV-PDF/` holds no `.pdf` files, deliberately: §4.7 says the corpus is *"generated, not
committed as binaries"*. `tests.support.corpora.materialize_adv_pdfs()` writes them into a
temp directory on demand and verifies each against the digest in the manifest.

`F-HAND/` holds no student work and never will. §4.4's PII rules make it the only corpus
containing real work and forbid committing it; `registry.json` is the committed declaration of
what it must contain and where a machine that has it keeps the corpus.

`baselines/` holds no golden files yet. A baseline is the output of a producer and no producer
exists; see `tests/support/baselines.py` for why committing one early would be worse than
committing none.

`.gitattributes` pins this tree to LF. Every manifest declares a `sha256` over member bytes,
so a CRLF checkout would change every hash in it.
"""


def build(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_bytes(_README.encode("utf-8"))
    _build_package(root / "package")
    _build_submission_corpus(
        root / "F-SYNTH",
        "F-SYNTH",
        synth.SYNTH_SEED,
        "harness.corpora.synth:synth_cohort",
        "350 generated submissions against the 5-question, 15-criterion reference package.",
        synth.synth_cohort(),
    )
    _build_submission_corpus(
        root / "F-FROZEN",
        "F-FROZEN",
        synth.FROZEN_SEED,
        "harness.corpora.synth:frozen_set",
        (
            "The held-out conformance set: 36 submissions spanning the score range including "
            "mid-range partial credit (FR-CONFORM-01). Never used during development."
        ),
        synth.frozen_set(),
    )
    _build_submission_corpus(
        root / "F-DEV",
        "F-DEV",
        synth.DEV_SEED,
        "harness.corpora.synth:dev_set",
        "The 8 submissions development iterates against, disjoint from F-FROZEN (§4.4).",
        synth.dev_set(),
    )
    _build_graphic(root / "F-GRAPHIC")
    _build_stats(root / "F-STATS")
    _build_adv_inj(root / "F-ADV-INJ")
    _build_adv_pdf(root / "F-ADV-PDF")
    _build_hand(root / "F-HAND")
    _build_baselines(root / "baselines")


# The two files under `baselines/` that this module *does* emit. Everything else there is a
# recorded golden artifact.
_GENERATED_UNDER_BASELINES = frozenset(
    {"baselines/registry.json", "baselines/TC-REG-06/work-id-reference.inputs.json"}
)


def _is_recorded_baseline(path: str) -> bool:
    """Is this a §6.9 golden that a producer recorded, rather than generated corpus data?

    `--check` asks "is `fixtures/` still what the generators emit". Golden baselines are not
    emitted by anything here — they are the *output of a producer*, captured deliberately by
    the story that builds it, and every `TC-REG-*` docstring instructs exactly that. Without
    this exemption the first recorded baseline would turn
    `test_the_committed_corpora_are_exactly_what_the_generators_emit` red, and the fix a reader
    would reach for is deleting the golden.

    Only the *unexpected file* direction is exempted. A golden that differs from a generated
    file of the same name would still be reported, and the two files this module does write
    under `baselines/` are checked like everything else. Nothing checks that a golden is
    *registered* here — `tests/support/baselines.py` does, by refusing to compare against a
    path the registry does not list.
    """
    return path.startswith("baselines/") and path not in _GENERATED_UNDER_BASELINES


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)).replace("\\", "/"): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def check(committed_root: Path) -> list[str]:
    """Regenerate into a scratch directory and return the differing paths."""
    with tempfile.TemporaryDirectory() as tmp:
        fresh_root = Path(tmp) / "fixtures"
        build(fresh_root)
        fresh, committed = _tree(fresh_root), _tree(committed_root)

    problems: list[str] = []
    for path in sorted(set(fresh) - set(committed)):
        problems.append(f"missing from the repo: {path}")
    for path in sorted(set(committed) - set(fresh)):
        if _is_recorded_baseline(path):
            continue
        problems.append(f"in the repo but not emitted by the generator: {path}")
    for path in sorted(set(fresh) & set(committed)):
        if fresh[path] != committed[path]:
            problems.append(f"differs from what the generator emits: {path}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; report any file that differs from what the generator emits",
    )
    parser.add_argument("--root", type=Path, default=CORPUS_ROOT)
    args = parser.parse_args(argv)

    if args.check:
        problems = check(args.root)
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            print(
                f"\n{len(problems)} difference(s). The corpora are generated from committed "
                f"scripts (test-plan §8.1): rebuild with `python -m harness.corpora.build` "
                f"rather than editing fixtures/ by hand.",
                file=sys.stderr,
            )
            return 1
        print("fixtures/ matches the generators")
        return 0

    build(args.root)
    manifest_count = len(list(args.root.rglob("manifest.json")))
    print(f"wrote {len(_tree(args.root))} files under {args.root} ({manifest_count} manifests)")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
