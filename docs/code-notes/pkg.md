# `aeh.pkg`: design notes

These notes were the docstring of `src/aeh/pkg.py` before it was split into the `aeh/pkg/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

`M-PKG` — Assessment Package Catalog (design §3.4).

Owns Tier P: package identity and version lineage, the §6.2 schema lock, criteria and
bands, the dependency graph, exemplars, the grade policy, and validation records. This
file landed **#26** — version lineage and published-version immutability
(`FR-PKG-01`, `-02`, `-04`, `NFR-PKG-01`); #27-#31 have since added the schema lock's
enumerable list, bands and the dependency graph, validation records, the grade policy,
boundaries, answer keys and elicitation history, and single-file export/import with the
provenance gate (`FR-PKG-10..13`).

It owns **no student text**: Tier P never contains student work (design §3.3's tier
table), and nothing here reads or writes any other tier.

Immutability is enforced twice (`NFR-PKG-01`: "a database constraint or a data-layer
guard"):

1. **Data-layer guard** — every mutating `PackageCatalog` method calls `_refuse_mutation`,
   which raises `PublishedVersionImmutableError` before a statement is attempted.
2. **Database triggers** — migration `pkg_version_lineage` installs `BEFORE UPDATE`
   triggers on `package_version` and every table referencing it, so a write that routes
   around the catalog (a raw handle, another process) fails at the database. The trigger
   is the backstop that makes "no caller, including `M-CALIB`, can route around it" a
   property of the *data*, not of who remembers to call the guard.

## Details moved out of the code

These notes were the longer parts of docstrings in `aeh.pkg`. Each section is named after the file and the function or class it describes.

### validation.py: record_validation_baseline

`M-STATS`'s ``promote`` is the intended caller, and the split of work between the two
modules is the point of this function's shape. `M-STATS` counts — it knows how many of
the administration's judged labels landed in each band, by NAME, because that is what a
label carries. It does not know what those names are worth: the ordinal scale lives in
Tier P's ``band`` table, which is this module's schema (`CT-PKG-12`). So the caller sends
the distribution and this side maps it, which is also why the write carries `M-PKG`'s
frames the way `record_promotion` does (`CT-STATS-15`'s indirection).

**The scale is the declared ordinal, and that is load-bearing.** `should_escalate`
computes ``z = (ordinal - expected_mean) / expected_sd`` where ``ordinal`` is the score's
DECLARED band ordinal (`agg._band_by_ordinal`). A baseline computed on any other scale —
the band's name read as a number, or `aeh.stats._band_ordinals`' inferred rank — would be
a z-score between two different spaces, wrong by a constant for every package and
silently so. Bands are 0-based (`store.py`'s ``CHECK (ordinal >= 0)``).

Refuses rather than guesses, in three cases, each returning ``False`` with nothing
written:

* The version is not in this data directory's packages.
* A band NAME in the histogram is not one the criterion declares. A mean over a scale the
  package does not declare is a fabricated figure, and a partial mean over "the ones I
  recognised" is worse — it would silently drop a band and shift the baseline.
* The version is published — with #525's one sanctioned exception. `FR-PKG-04` makes a
  published version's rows immutable and the triggers enforce it; since decision (a) of
  2026-10-07, a baseline APPEND is the one write those triggers admit on a published version
  (a new row, or a row whose three figure columns are still NULL — evidence ABOUT the
  version, added after publication, never altering a recorded figure). A rewrite of
  recorded figures, and every agreement or verdict write, still refuse. Refused is
  `BASELINE_PUBLISHED` on the returned record, not a raise: a promote of an administration
  against a published package is a normal thing to do, and it must not fail because one
  optional record could not be filed.

Returns a `BaselineWrite` — the status AND the reason — so the caller reports what
happened rather than assuming it worked. Every refusal above is an ordinary event on
the production path, so a caller that cannot name the reason cannot tell a promote
that stored a baseline from one that quietly did not.

### validation_reads.py: ValidationReadsMixin.baseline_for

Shaped for `aeh.agg.should_escalate`'s ``baseline=`` argument — the keys are ``mean``
and ``std``, the names it reads — so the figure this module stores reaches the rule
that needs it without a caller in between reshaping (and possibly rescaling) it.

**The signature mirrors `validation_for` deliberately**, down to the argument order
and the `scoring_model` default, because it reads the SAME row under the same
six-part key (`FR-PKG-08`). Naming the key is the caller's job here exactly as it is
there: defaults on `backend_profile` and `panel_build_ref` would let a caller who
names neither read back a `NoValidationData` for a baseline that IS stored, and
`record_validation_baseline` writes both (they are the two parts `M-STATS` carries).
`criterion_id` is required rather than optional — see the statement's own note.

`NoValidationData` is returned for BOTH "no row" and "a row with no baseline", and
the second case is the one that matters: a `validation_record` written by
``store_validation`` carries agreement and n but no baseline until an administration
is promoted, and its three NULL columns are not a distribution. Returning the same
sentinel `validation_for` returns keeps absence one type on this surface rather than
two, and it is what makes the distributional-anomaly rule skip (`FR-AGG-08`) instead
of dividing by a zero that was never measured.

Named `baseline_for` rather than `validation_baseline` so the surface keeps
`CT-PKG-07`'s prohibition legible: every public name carrying "validation" on this
class is the keyed record read or its write, and nothing else.
