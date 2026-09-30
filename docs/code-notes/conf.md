# `aeh.conf`: design notes

These notes were the docstring of `src/aeh/conf.py` before it was split into the `aeh/conf/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

`M-CONF` — Deployment Profile & Run Configuration (design §3.1).

Resolves the deployment profile into one immutable `RunConfig` before a run begins, so every
consumer reads one frozen answer to "which grader is this run" and none can change it. The module
is a **leaf**: it has no downstream dependency, writes nothing, and its resolution is a pure
function of `(cfg, cohort)`.

Scope of this file today
------------------------
`M-CONF` shipped across three stories, all landed: **#4** (`FR-CONF-01`, `-02`, `-03`, `-06`,
`-07`, `NFR-CONF-01`, `NFR-CONF-03`), **#5** (`FR-CONF-05`, `-09`, `-10`) and **#6**
(`FR-CONF-04`, `-08`, `-11`, `-12`, `NFR-CONF-02`, `NFR-CONF-04`).

`M-CONF` is complete: nothing the design's Interfaces block names is absent.

Decisions this file fixes, that the design underdetermines
----------------------------------------------------------
Recorded here rather than in a commit message because `TS-03` (#7) and `TS-58` (#9) are written
**against whatever this module ships**, and a signature they have to guess is a suite that asserts
the wrong thing.

| Decision | Choice | Forced by |
|---|---|---|
| Exception taxonomy | Four **siblings** under `RunConfigError`; all four declared, two raised here | `TC-CONF-15` names four; siblings keep every "exact exception type" oracle discriminating |
| `is_resolved()` | Judges `build_id` by **form** only — no backend argument exists on `ModelRef` | `TC-CONF-03`: "`is_resolved()` agrees with the outcome in every case" |
| Backend cross-check | Lives in `resolve_run_config`, not in `is_resolved()` | `CT-CONF-C03`: "assert per backend what resolution *means*" |
| Mutation raises | `TypeError`, via `_typeerror_on_mutation` | `FR-CONF-02` says `TypeError`; `dataclasses.FrozenInstanceError` is an `AttributeError` |
| Residency + quantization | Public **data** in `HARDWARE_PROFILES`, not fields and not code paths | `CT-CONF-C02` pins `RunConfig` to 12 fields; `TC-CONF-14` forbids platform branches |
| `HARNESS_*` namespace | Stays at **exactly six** keys; structural inputs use plain keys | `TC-CONF-C11` sweeps "each of the six `HARNESS_*` keys" |
| `HARNESS_CONCURRENCY` | **Clamps down, never up**: `min(key, hardware ceiling)`; alone on a hosted backend | Precedence is unstated; a ceiling a variable can raise is not a ceiling |
| Inapplicable `HARNESS_*` keys | Ignored, not refused | `CT-CONF-02`'s iff constrains `RunConfig` fields; refusing would make `environment_snapshot` unusable |
| Where the iffs live | `RunConfig.__post_init__`, not only the resolver | An invariant enforced only by the function that builds the value is forgeable through `dataclasses.replace` |
| `edge-weights` vs `provider-pinned` | Told apart by `WEIGHTS_SUFFIXES`, not by `@sha256:` alone | Otherwise a digest-pinned hosted build reads as a weights path |
| `ModelRef` / `HardwarePolicy` validate on construction | Shape only, raising `ConfigurationError` | Both are caller-supplied and reach a primary key (`panel_build_ref`) or an arithmetic clamp; a bad one must not surface as a bare `TypeError` (`TC-CONF-15`) |
| A `RunConfig` literal must be **legal** | `__post_init__` refuses one violating `CT-CONF-02`/`-03`/`-07` | §3.1 says the type is "cheap to construct"; it does not say a value carrying none of its guarantees is a `RunConfig` |
| `ProfileSummary`'s field set | Chosen here; the design names the type twice and never specifies it | `FR-CONF-09` lists the *contents*, not the shape |
| `quantization` on a hosted backend | The `PROVIDER_MANAGED` sentinel, never blank | `CT-CONSOLE-10` renders this under every grade; empty reads as "unknown", not "not applicable" |
| One serializer, `to_canonical_json()` | Both the log line and `M-ORCH`'s audit record call it | `TC-CONF-17` is a **differential** against "the one logged at run start" |
| The run-start log line | `log_run_start()`, separate from resolution | `CT-CONF-12` lets `M-CONSOLE` resolve on the request path, so logging inside resolution would emit two lines for one run |
| The prefix ceiling's knob | `cfg["hardware_profiles"]` on `edge-local`, `cfg["hosted_prefix_token_ceiling"]` otherwise — no seventh `HARNESS_*` key | `FR-CONF-06`/`-10` derive the ceiling *from* the profile; a separate env key would permit `unified-large` with a ceiling of 500 |
| Control characters refused in `provider`, `build_id`, `quantization` | `ModelRef.__post_init__` | Two of them are `compute_panel_build_ref`'s separators, so one inside a field makes the encoding ambiguous and the key non-unique (`CT-CONF-07`) |

The second of those changes an input class `TS-03` will meet: an empty or whitespace `build_id`,
or a `role` outside the four, now raises from the **constructor** rather than surfacing as an
unresolved ref out of `resolve_run_config`. `TC-CONF-03`'s listed inputs (a friendly name, a
GGUF path with no hash, a bare slug) are all still constructible and still refused by the
resolver, which is where that case looks.

`CT-CONF-14` is a P0 safety property (design §4.7) and is owned: its case `TC-CONF-C14` is on
issue #9's `Traces to`, and the implementation obligation reaches #6 through `FR-CONF-04`.
Clauses are tracked through their `TC-*-C*` cases rather than by `CT-*` ID — no issue's
`Traces to` names a `CT-*` ID, for any of the design's 330 clauses. What #9 needs from here is
the list of back doors this module leaves open, which `_typeerror_on_mutation` records
explicitly so that sweep starts from a written list rather than a search.

Credentials (`NFR-CONF-02`) never appear in an exception raised here: a message names the
offending **key**, and echoes a **value** only for the four non-credential `HARNESS_*` keys.
