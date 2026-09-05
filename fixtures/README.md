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
