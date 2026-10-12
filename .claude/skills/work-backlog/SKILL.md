---
name: work-backlog
description: Pick the next unblocked story or test issue and implement it. Meant to be paired with /goal for a local session that works through the whole backlog.
disable-model-invocation: true
---

Find the next ready issue and implement it, then stop — the `/goal` loop (or whoever is
running this) decides whether to continue.

This is the dispatcher for this repo. Work runs on your machine — GitHub hosts the repo and
the issue graph but never picks anything up on its own, so an issue sits ready until this
skill claims it.

## 1. Find the ready set

```bash
./scripts/ready-issues.sh 1
```

It returns a JSON array of unblocked, unclaimed issues and prints skip reasons to stderr —
read those, since a malformed `Depends on:` line or a `status:needs-attention` label is a
real finding, not noise.

**Use the script; don't reimplement its logic.** Readiness is defined in exactly one place,
so a rule change lands everywhere at once. If the script is missing or `gh`/`jq` aren't
available, say so and stop rather than approximating it by hand — an approximation that
treats a blocked issue as ready starts work against an interface that hasn't been built
yet.

If the array is empty, report which it is — the backlog is finished, or it's fully blocked,
or everything ready is parked on `status:needs-attention` — and stop.

**Write the result down before going any further.** Put the JSON array and the stderr skip
reasons in `.claude/backlog/work-backlog-state.md`, overwriting whatever the last run left
there. One issue takes a lot of context, so this session will likely be compacted before it
reaches step 4 — and a compacted summary is a lossy place to keep the one fact this skill
must not lose. `backlog/` is gitignored, so the file survives a dead session without ever
showing up in `git status` or tripping the `verify.sh` Stop hook.

## 2. Claim it

```bash
gh issue edit <number> --add-label "status:in-progress"
```

Append the number, its `type:` label and the branch to the state file the moment that
succeeds. From here to step 4 the issue is claimed, and an issue left on
`status:in-progress` because the session lost track of it is invisible to
`ready-issues.sh` on every subsequent run — it filters claimed issues out, so nothing ever
picks it up again and nothing reports it as stuck. If the state file already names a
claimed issue when you reach step 1, that is a run that died mid-issue: say so and check
whether its labels need releasing before starting anything new.

## 3. Implement it

- `type:story` → `/fix-issue <number>`
- `type:test` → `/write-tests <number>`

The label decides, not the title. Nothing here hardcodes "tests come after code": a test
issue may depend on its implementation story or have no dependency at all, and
`/write-tests` handles both — see the `Written ahead of implementation` field in the issue.

## 4. Release the claim

On success the PR is open and review is what happens next. Take the number from the state
file rather than from memory — by now the claim may be several compactions old:

```bash
gh issue edit <number> --remove-label "status:in-progress" --add-label "status:in-review"
```

If the work failed or you're stopping partway, use `status:needs-attention` instead of
`status:in-review`. `ready-issues.sh` skips `needs-attention` issues, which is what keeps a
failing issue from being picked up again on every loop iteration and failing the same way.

## 5. Report

Say which issue you completed, whether a PR was opened, and what the ready set looked like
— so the loop's next iteration is predictable rather than surprising. The ready set comes
from the state file; a report that says "the ready set was probably" is a report that has
already lost it.

## Running this unattended

For goal-setting, auto mode, the `/autocompact 500k` window, and how this skill survives
compaction (it cannot perform it — the state file is what carries a claim across), read
`references/unattended-runs.md` when setting up an unattended run.
