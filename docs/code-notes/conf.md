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

## Details moved out of the code

These notes were the longer parts of docstrings in `aeh.conf`. Each section is named after the file and the function or class it describes.

### frozen.py: _typeerror_on_mutation

`FR-CONF-02` and `CT-CONF-04` both name `TypeError` specifically, and a plain
`@dataclass(frozen=True)` raises `dataclasses.FrozenInstanceError` — which subclasses
`AttributeError`, not `TypeError`. A `pytest.raises(TypeError)` written from the requirement
would fail against a correct implementation.

`__replace__` is closed too, which shuts `copy.replace` (Python 3.13+): a copy carrying a
different `backend_profile` or `panel` is precisely the rebinding `CT-CONF-04` forbids and
RISK-22 describes.

`dataclasses.replace` does **not** route through `__replace__` — verified on CPython 3.14,
where it calls `obj.__class__(**changes)` directly — so this decorator cannot see it. It is
narrowed from the other end instead: `RunConfig.__post_init__` enforces `CT-CONF-02`,
`CT-CONF-03` and `CT-CONF-07` on the *type*, so a replace that rebinds the backend, the
hardware profile, either cost field, or the panel raises. Direct construction of a legal
literal keeps working, which design §3.1's Compatibility note requires in as many words:
*"Consumers test against a literal `RunConfig` value rather than a double — the type is
frozen and cheap to construct."*

Precisely what stays open, so nobody reads more into this than it does:

- a *self-consistent* rebuild (`replace(cfg, backend_profile=…, hardware_profile=None,
  panel=<hosted builds>, cost_ceiling=…, cost_currency=…, panel_build_ref=…)`), which is
  indistinguishable from constructing the literal directly and so cannot be closed without
  forbidding both;
- `replace(cfg, concurrency_ceiling=999)`, because the ceiling a config was resolved under
  depends on the hardware table used at resolution time, which the value does not carry;
- pickle's `__setstate__` and a hand-edited `run` row.

All three belong to `TC-CONF-C14`'s back-door sweep — see `docs/code-notes/conf.md`'s note on
which issue owns that clause.

The decorator is applied *after* `@dataclass(frozen=True)`, which is required: assigning
`__setattr__` inside the class body makes the dataclass decorator itself raise. The
generated `__init__` writes through `object.__setattr__`, so construction is unaffected.

### model_ref.py: ModelRef

`build_id` takes one of two forms, and `is_resolved()` judges it by form alone — there is no
backend argument on this type, so the per-backend rule ("weights path for `edge-local`,
pinned slug otherwise") lives in `resolve_run_config`.

| `build_id` | `quantization` | form | resolved |
|---|---|---|---|
| `/models/llama-3.3-70b.gguf@sha256:aaaa` | `"q4"` | edge-weights | yes |
| `/models/llama-3.3-70b.gguf@sha256:aaaa` | `None` | — | no — `FR-CONF-03` wants path **plus quantization plus** hash |
| `/models/llama-3.3-70b.gguf` | `"q4"` | — | no — no weights hash |
| `/models/llama:latest.gguf@sha256:aaaa` | `"q4"` | — | no — floating tag, on either form |
| `openrouter/llama-3.3-70b-instruct@2024-12-06` | any | provider-pinned | yes |
| `openrouter/llama-3.3-70b-instruct` | any | — | no — a bare slug is not pinned |
| `llama3.3:latest@2024-12-06` | any | — | no — floating tag |
| `Llama 3.3 70B` | any | — | no — a friendly name (`FR-CONF-03`, verbatim) |

The two forms are told apart by `WEIGHTS_SUFFIXES`, not by the presence of `@sha256:`
alone: a hosted build pinned by content digest (`openrouter/x@sha256:abcd`) is
provider-pinned, not a weights path.

The digest is required to be hex and non-empty, but **not** 64 characters: the repository
already commits `sha256:aaaa` as a legal judge build
(`tests/unit/prov/test_recorded_fixture_provider.py`). Verifying that a digest matches the
bytes on disk belongs to `M-STORE`, not here — this module never opens a file.

### rehydrate.py: rehydrate_run_config

`FR-CONF-04`: *"a run resumed after interruption resolves to the `backend_profile` and
`provider_config` persisted on its `run` row, and a mismatch against current configuration
raises `BackendMismatchError` rather than proceeding."* RISK-22 is a resumed run silently
changing the grader — half a cohort scored by one panel, half by another, and nothing in the
record saying so.

**`cfg` is optional, and that is deliberate.** `TC-CONF-16`'s round-trip property calls this
with the row alone, so a one-argument call must reconstruct; `TC-CONF-04` steps 2 and 3 call
it *"with current configuration set to `cloud-hosted`"* and require `BackendMismatchError`.
Both hold only if current configuration is an optional second argument — additive to §3.1's
`rehydrate_run_config(run_row)`.

The comparison is against `cfg` **directly**, never against `resolve_run_config(cfg, cohort)`:
resolving would run the consent gate and could raise `ConsentGateError` where `TC-CONF-04`
expects a mismatch, and it would demand a `cohort` a resume check has no reason to hold.

Reconstruction is from the **row**, never from current configuration — that is the whole
point. Current configuration is only ever consulted to *refuse*.

**`cohort` re-runs the consent gate on resume, and is optional for the same reason.**
`FR-CONF-08` says "refuse to produce a `RunConfig` binding a remote provider" for
non-consented work, and this function produces exactly that. The row can only exist if
`resolve_run_config` already passed the gate — but consent can be *withdrawn* between a run
starting at 9pm and resuming at 3am, and a hand-edited row is a back door this module
already documents. Pass the cohort and the gate runs again; omit it and it does not, which
is the caller asserting the run is unattended machinery replaying its own row.

### resolution.py: resolve_run_config

Pure (`NFR-CONF-01`, `CT-CONF-05`): reads no `os.environ`, opens no file, makes no network
call and no database read. The environment reaches it only through the snapshot the caller
merged into `cfg` — see `environment_snapshot`. Same inputs, same result, including
`panel_build_ref`.

Writes nothing (`CT-CONF-09`). Every failure is raised **before** a `RunConfig` exists, so a
failed resolution leaves no partial value to clean up (`CT-CONF-08`), and every failure is
one of the four declared types — `TC-CONF-15`'s invariant is that no other exception escapes.

`cohort` is read by the consent gate (`FR-CONF-08`), which runs last — see `_check_consent`.
When that gate passes **because of an override**, `M-ORCH` must also call
`consent_override_for(cfg, cohort)` and persist the record it returns: this module writes
nothing (`CT-CONF-09`), so resolution alone leaves no audit trail of who authorised the
remote dispatch of real student work.

Config keys, all read from `cfg`:

| key | required | meaning |
|---|---|---|
| `HARNESS_PROFILE` | always | `edge-local` \| `cloud-hosted` \| `dev-ci`. No default |
| `HARNESS_HARDWARE_PROFILE` | iff `edge-local` | key into `HARDWARE_PROFILES` |
| `HARNESS_COST_CEILING` / `_CURRENCY` | iff hosted | zero accepted, negative refused |
| `HARNESS_CONCURRENCY` | no | clamps the derived ceiling **down**; never raises it |
| `HARNESS_ALLOW_REMOTE_REAL_WORK` | no | defaults `False`; overrides the consent gate, and **requires** `allow_remote_real_work_supplied_by` |
| `panel` | always | 1, 3 or 5 `ModelRef`s, each `role="judge"` |
| `transcriber` | always | `ModelRef`, `role="transcriber"` |
| `off_panel_checker` | no | `ModelRef`, `role="off_panel"` |
| `prompt_template_v` | always | non-empty string |
| `retention_setting` | **iff `cloud-hosted`** | one of `RETENTION_SETTINGS`; unset or unrecognized is refused (`FR-CONF-12`) |
| `allow_remote_real_work_supplied_by` | iff the override is used | who authorised sending real work remotely; the override is refused without it |
| `hardware_profiles` | no | overrides `HARDWARE_PROFILES` for this call |

### run_config.py: ProfileSummary

The design names this type twice and never specifies it, so the field set is chosen here.
Two consumers constrain it and both are worth naming, because a later editor will otherwise
read the shape as arbitrary:

* `CT-CONSOLE-10` puts it on **every** grade view — "a grade is never displayed without its
  provenance" — which is why `quantization` is never blank (see `PROVIDER_MANAGED`).
* `TC-CONF-17` is a **differential**: the stored summary must be byte-identical to the one
  logged at run start. That is what `to_canonical_json` is for, and why both paths must call
  it rather than each formatting the record their own way.

`panel_build_ref` is carried although `FR-CONF-09` does not list it — additive per §3.1's
Compatibility note, and an audit record holding a run's grader identity without the key that
identity is filed under would be a strange thing to have stored.

Credential-free with respect to everything this module reads (`CT-CONF-10`): every field is
a build identity, a profile name or a retention setting, and none is read from the
environment. That is not the same as credential-free against *caller* data — a key embedded
in a `build_id` would land here and in the log record. The four-surface sentinel scan that
settles it is `TC-CONF-11`, on issue #8.

Note for `TC-CONF-C14`'s reflection sweep (issue #9): this **constructor** takes
`backend_profile`, `panel` and `retention_setting`, as `RunConfig`'s already does. The sweep
is over operations that rebind *an object that already exists*, so it must exempt
constructors — otherwise every frozen value object in the module fails it.
