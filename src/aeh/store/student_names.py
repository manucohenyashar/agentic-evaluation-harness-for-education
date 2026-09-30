"""Keeping student names out of the durable tier: the name-column test and the guards."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from .errors import StudentNameInTierDError
from .interfaces import Statement


# --- the FR-STORE-12 name vocabulary -----------------------------------------------------------
#
# `FR-STORE-12` says Tier D "shall reject any insert containing a column mapped as a
# student-name field", and design §3.3 puts the identity mapping in Tier C alone. The
# requirement names the *concept*, not the spellings, so the guard needs a mapping — and a
# mapping is only as good as its worst omission, since a name-bearing column that no pattern
# matches is precisely the leak `CT-STORE-09` promises callers cannot happen.
#
# **Not a `*_name` rule.** The obvious version — flag any column whose name contains `name` —
# was measured against this module and flagged `criterion_name`, `stat_name`, `scope_name`,
# `run_name`, `metric_name`, `display_name` and nine more. Tier D holds `criterion_stats`,
# `mcq_item_stats` and `run_metrics` (design §3.3), so those are not hypothetical columns: that
# rule reds the build against a *correct* store, and a rule that does that is one the first
# `M-STORE` commit switches off. A switched-off rule catches nothing at all, which is strictly
# worse than the leak it was guarding.
#
# So the rule is **person + name**, not name alone: a column is a student-name column when it
# names a *person* and names their *name*. Two token sets, and the intersection is the finding.
#
# This rule is runtime behaviour as of #13 — the write guard executes it on every Tier D
# insert — so it lives here, and `tests/support/store_vocabulary.py` re-exports it rather than
# carrying a second copy that could drift from the one the store actually enforces.

#: Who the column is about. Absent these, `*_name` is a criterion, a run or a metric.
PERSON_TOKENS: frozenset[str] = frozenset({"student", "pupil", "learner", "candidate", "child"})


#: What about them, in two strengths — and the split is the whole rule.
#:
#: **Strong** tokens mean a name wherever they appear next to a person token. **Weak** ones do
#: not: `first`, `last`, `family`, `display` and the rest are ordinary English that Tier D has
#: every reason to use. Measured against a rule that treated them as strong,
#: `student_first_seen`, `student_last_seen_at`, `student_family_income`,
#: `student_display_order`, `learner_given_consent`, `student_preferred_language` and
#: `pupil_last_updated` were all flagged — longitudinal per-student columns, which is precisely
#: what a permanent pseudonymous tier is *for*. Redding the build against those is the same
#: failure the `*_name` rule had, wearing different clothes.
#:
#: So a weak token counts only when it is **terminal** (`student_first` is as identifying as
#: `student_first_name`) or **immediately followed by a strong token** (`student_first_name`,
#: `student_display_name`).
STRONG_NAME_TOKENS: frozenset[str] = frozenset(
    {
        "name", "names", "fullname", "firstname", "lastname", "surname", "forename",
        "givenname", "familyname", "initials",
    }
)


WEAK_NAME_TOKENS: frozenset[str] = frozenset(
    {"first", "last", "given", "family", "middle", "preferred", "display"}
)


#: Kept as the union for readers and for callers that want the whole vocabulary.
NAME_TOKENS: frozenset[str] = STRONG_NAME_TOKENS | WEAK_NAME_TOKENS


#: The pseudonymous shape `FR-STORE-12` *requires*. A person token with one of these is the
#: sanctioned Tier D column, not a violation — `student_ref` is the whole point of the clause,
#: and a rule that flagged it would flag the correct implementation.
PSEUDONYM_TOKENS: frozenset[str] = frozenset(
    {"ref", "id", "key", "uuid", "hash", "token", "code", "pseudonym", "anon"}
)


#: Spellings that identify a person with no person token attached, so the person+name rule
#: cannot see them. A bare `name` column in a Tier D table is a finding on its own.
BARE_NAME_COLUMNS: frozenset[str] = frozenset(
    {
        "name", "names", "full_name", "fullname", "first_name", "firstname", "last_name",
        "lastname", "surname", "forename", "given_name", "givenname", "family_name",
        "familyname", "middle_name", "preferred_name", "legal_name", "maiden_name",
    }
)


#: The pseudonymous key Tier D is allowed to carry instead (`FR-STORE-12`).
TIER_D_IDENTITY_COLUMN = "student_ref"


def is_student_name_column(column: str) -> bool:
    """Does this column name a student's name?

    `person token AND name token`, with a pseudonym token vetoing the match. See the block
    comment above for why this is not a `*_name` rule.

    Known limit, stated rather than hidden: an unsegmented abbreviation like `sname` or `fname`
    matches nothing here. Catching those needs guessing at abbreviations, and every guess is a
    false positive against some legitimate column. `TC-STORE-12`'s third limb is a sweep over a
    real schema, so the residual risk is a column somebody deliberately obfuscated — which is a
    different threat from the one `FR-STORE-12` describes.
    """
    lowered = column.lower().strip()
    words = re.split(r"[_\s-]+", lowered)
    unique = set(words)

    if lowered in BARE_NAME_COLUMNS:
        return True

    if unique & PERSON_TOKENS:
        # Scan order is the rule: a **strong name token outranks the pseudonym veto**
        # (`student_name_hash` is a dictionary attack away from the name on the small
        # populations Tier D serves), and so does a **weak name token that a pseudonym
        # token follows** (`student_given_hash`, `student_first_hash` — a hash of a
        # partial name is the same attack with a smaller dictionary). The veto then
        # protects what remains: `student_ref`, `pupil_id`, `learner_uuid` — the shape the
        # clause requires — and the longitudinal columns (`student_first_seen`,
        # `student_family_income`) that a permanent pseudonymous tier exists for.
        for position, word in enumerate(words):
            if word in STRONG_NAME_TOKENS:
                return True
            if word in WEAK_NAME_TOKENS:
                next_word = words[position + 1] if position + 1 < len(words) else None
                terminal = next_word is None
                if terminal or next_word in STRONG_NAME_TOKENS or next_word in PSEUDONYM_TOKENS:
                    return True
        if unique & PSEUDONYM_TOKENS:
            return False

    # `studentname`, `pupilForename` — a person and a name glued into one token.
    return bool(
        re.search(r"(student|pupil|learner|candidate|child)\w*(name|forename|surname)", lowered)
    )


# --- the Tier D student-name guard (FR-STORE-12, CT-STORE-09) ----------------------------------


#: The header of an INSERT that names columns: `INSERT [OR …] INTO <tbl> (cols)` and
#: `REPLACE INTO <tbl> (cols)`, where `<tbl>` may be schema-qualified (`main.label`) and the
#: whole header may sit behind a CTE (`WITH x AS (...) INSERT INTO ...`) or comments.
#: Written as one literal, in the declared-statement pattern: the *text* contains SQL
#: keywords, but it is a regular expression, nothing is assembled, and the scanner that
#: flags assembled SQL reads it as one constant — the same discipline every statement in
#: this module follows.
#:
#: Two mechanical properties the guard depends on, both paid for here:
#:
#: **Every comment matcher is atomic.** A naive `/\*.*?\*/` inside a `*`-quantified
#: alternation backtracks exponentially when the header fails to match — a 200-byte
#: statement of the string-literal shape the unanchored search admits can freeze the
#: caller's thread for tens of seconds at a door that runs inline (`Tx.execute`,
#: `enqueue_write`). `/\*(?:[^*]|\*(?!/))*\*/` matches the same comments in linear time.
#:
#: **The column list is not `[^)]*`.** That form stops at the first `)`, so a comment or
#: quoted identifier containing one (`(band /* until (v2) */, student_name)`) truncates the
#: parse and silently hides every column after it — a false negative in exactly the control
#: that must not have one. The list body therefore consumes comments, `--` lines, quoted
#: and bracketed identifiers as units, and treats everything else as ordinary characters
#: except the closing paren.
#:
#: **Unanchored, deliberately.** Anchoring on `INSERT` made `WITH x AS (...) INSERT INTO t
#: (student_name) ...` invisible to the guard — a name lands in the permanent tier with no
#: error, which is the failure a security control may not have. Searching for the header
#: instead buys the CTE case at a stated cost: a statement whose *string literal* quotes
#: insert-shaped text can be refused when it would have run. That trade is chosen on purpose
#: — a false positive fails loud (a write the caller can see and rephrase), a false negative
#: is silent contamination of the one tier nothing can purge — and every caller here is
#: in-process trusted code whose statements are declared literals reviewed in PRs.
_INSERT_COLUMN_LIST = re.compile(
    r"\b(?:INSERT(?:\s|--[^\n]*|/\*(?:[^*]|\*(?!/))*\*/)*(?:OR(?:\s|--[^\n]*"
    r"|/\*(?:[^*]|\*(?!/))*\*/)*\w+(?:\s|--[^\n]*|/\*(?:[^*]|\*(?!/))*\*/)*)?INTO"
    r"|REPLACE(?:\s|--[^\n]*|/\*(?:[^*]|\*(?!/))*\*/)*INTO)"
    r"(?:\s|--[^\n]*|/\*(?:[^*]|\*(?!/))*\*/)*"
    r"((?:\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*)"
    r"(?:(?:\s|--[^\n]*|/\*(?:[^*]|\*(?!/))*\*/)*\."
    r"(?:\s|--[^\n]*|/\*(?:[^*]|\*(?!/))*\*/)*"
    r"(?:\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*))*)"
    r"(?:\s|--[^\n]*|/\*(?:[^*]|\*(?!/))*\*/)*"
    r"\(((?:/\*(?:[^*]|\*(?!/))*\*/|--[^\n]*|\[[^\]]*\]|\"[^\"]*\"|`[^`]*`|[^)])*)\)",
    re.IGNORECASE | re.DOTALL,
)


def _reject_tier_d_student_name_insert(declared: Statement) -> None:
    """Raise `StudentNameInTierDError` if `declared` inserts a student-name column into Tier D.

    Runs on the durable tier's two write doors (`enqueue_write` before queueing,
    `Tx.execute` before executing) and nowhere else: the requirement is about *inserts* into
    *Tier D*, and a guard on the other tiers or on reads would be a rule without a threat
    behind it. Parses the column list out of the statement's INSERT header — `INSERT [OR …]
    INTO tbl (cols)`, `REPLACE INTO tbl (cols)` — and applies `is_student_name_column` to
    each named column.

    What the parse tolerates, because each was a silent bypass in an earlier draft: CTE
    prefixes (`WITH x AS (...) INSERT INTO ...` — hence the unanchored search, with its
    string-literal trade recorded above), comments between the header's tokens and inside
    the column list, and schema-qualified tables (`main.label` — the last identifier is the
    table). What it deliberately does not: a statement with **no column list** (`INSERT
    INTO t DEFAULT VALUES`, `INSERT INTO t SELECT ...`, or a bare `VALUES (...)`) names no
    column and passes the header parse — the rest of that defense is structural, not
    textual: the schema authorizer (`_refuse_tier_d_schema`) refuses to let a name-bearing
    column be *created* through a Tier D write connection, so the tables a no-column-list
    insert can reach are exactly those the migrations shipped, which the sweep
    (`TC-STORE-12`'s third limb) holds clean at test time. Nor does the mapping see
    unsegmented abbreviations (`sname`) — `is_student_name_column`'s own stated limit.

    Exactness is the control that makes this a guard rather than a wrapper: only a
    name-mapped column raises. Every other failure — a typo'd column, a CHECK violation, a
    locked database — passes through exactly as SQLite raised it, so a caller can trust
    `StudentNameInTierDError` to mean the one thing it names.
    """
    matched = _INSERT_COLUMN_LIST.search(declared.sql)
    if matched is None:
        return
    # Schema-qualified: `main"."label`, `main.label`, `"main".label` — the table is the last
    # identifier. Split on the dots after unquoting; every segment carries the quotes it had.
    segments = matched.group(1).split(".")
    table = segments[-1].strip().strip("\"'`[]")
    # Column extraction, in three steps, each closing a bypass review found:
    # 1. comments out of the list (`band /* until (v2) */, student_name` — a naive
    #    comma-split truncates at the paren and hides every column after it);
    # 2. quoted/bracketed identifiers as atomic tokens (`"stu,dent_name"` survives a
    #    comma-split that would otherwise shatter it into fragments);
    # 3. a token that is not a plain bare identifier is checked on its word characters —
    #    `"stu)dent_name"` normalizes to `student_name` and is refused. Fail closed: a
    #    spelling that needs quoting is extraordinary on Tier D, and the ordinary cost of
    #    a false positive here is a loud refusal, not a silent name.
    body = re.sub(r"/\*(?:[^*]|\*(?!/))*\*/", " ", matched.group(2))
    body = re.sub(r"--[^\n]*", " ", body)
    tokens = re.findall(r"\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*", body)
    offenders: list[str] = []
    for token in tokens:
        bare = token.strip("\"'`[]")
        candidate = (
            bare
            if re.fullmatch(r"[A-Za-z_][\w$]*", bare)
            else re.sub(r"\W", "", bare, flags=re.UNICODE)
        )
        if candidate and is_student_name_column(candidate):
            offenders.append(bare)
    if offenders:
        raise StudentNameInTierDError(
            f"Tier D refused a write naming student-name column(s) "
            f"{', '.join(repr(c) for c in offenders)} on table {table!r}. FR-STORE-12: the "
            f"identity mapping exists only in Tier C; Tier D carries {TIER_D_IDENTITY_COLUMN} "
            f"and is pseudonymized (CT-STORE-09), and it is the one tier purge_cohort does "
            f"not touch — a name here would outlive every retention control in the system."
        )


# --- the Tier D schema authorizer (FR-STORE-12, CT-STORE-09) ------------------------------------
#
# The name guard above reads statements; this authorizer refuses to let a statement *become
# schema* on the one tier nothing can purge. The bypass review demonstrated end-to-end:
# `CREATE TABLE leak (student_name TEXT)` through a guarded `transaction()` — the guard only
# reads INSERT headers — followed by `INSERT INTO leak SELECT ...`, whose no-column-list
# shape names nothing the guard can check. Refusing DDL on Tier D's write connections closes
# the first half of every such chain.
#
# Schema belongs to migrations (`NFR-STORE-04`), and migrations run on the *open* connection
# (`_open_tier`), never on the lazily-opened write connection this authorizer guards — so
# refusing DDL here refuses no sanctioned path. A promotion-shaped `ALTER TABLE` a test
# wants to simulate goes through an independent `sqlite3` connection, exactly like the
# poisoned table `TC-STORE-12` creates behind the store's back.

#: Authorizer actions that create, change or drop persistent schema objects — plus
#: `ATTACH`/`DETACH`, which would let a write connection reach a second file from inside a
#: Tier D transaction. Resolved defensively over both of sqlite3's constant spellings, so
#: the set degrades to what this interpreter knows rather than raising at import.
_SCHEMA_DDL_ACTIONS: frozenset[int] = frozenset(
    code
    for code in (
        getattr(sqlite3, name, getattr(sqlite3, name.removeprefix("SQLITE_"), None))
        for name in (
            "SQLITE_CREATE_TABLE", "SQLITE_CREATE_INDEX", "SQLITE_CREATE_TRIGGER",
            "SQLITE_CREATE_VIEW", "SQLITE_ALTER_TABLE", "SQLITE_DROP_TABLE",
            "SQLITE_DROP_INDEX", "SQLITE_DROP_TRIGGER", "SQLITE_DROP_VIEW",
            "SQLITE_REINDEX", "SQLITE_ATTACH", "SQLITE_DETACH",
        )
    )
    if code is not None
)


_SQLITE_OK = getattr(sqlite3, "SQLITE_OK", getattr(sqlite3, "OK", 0))


_SQLITE_DENY = getattr(sqlite3, "SQLITE_DENY", getattr(sqlite3, "DENY", 1))


def _refuse_tier_d_schema(action: int, arg1: Any, arg2: Any, db_name: Any,
                          trigger_or_view: Any) -> int:
    """Deny schema DDL (and cross-database ATTACH) on a Tier D write connection.

    Installed via `set_authorizer` on the durable tier's write connections only — see the
    section comment above for why. Everything that is not schema DDL is allowed: rows,
    reads, pragmas, transactions.
    """
    if action in _SCHEMA_DDL_ACTIONS:
        return _SQLITE_DENY
    return _SQLITE_OK
