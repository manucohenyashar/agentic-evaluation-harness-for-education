# Running /work-backlog unattended

Session-setup guidance for the unattended loop. Not part of the per-invocation procedure in
`SKILL.md` — read this when setting up a long-running backlog run, not on every dispatch.

## Set a goal before the first invocation

So the session keeps picking up the next issue instead of stopping after one:

```text
/goal every open type:story and type:test issue is closed or labeled
status:needs-attention, or nothing is unblocked; stop after 40 turns
```

Then run `/work-backlog`. The evaluator re-checks the condition after each issue and starts
another `/work-backlog` turn until the backlog is empty or genuinely stuck. Pair with auto
mode (`claude --permission-mode auto`) so each turn's tool calls don't need per-command
approval.

## Set the auto-compact window once

One issue fills a lot of the window — a design section, a test plan section, the suite, the
mutation runs and the review — so a loop left alone will hit the limit partway through the
second or third. Set the window once, in the same session you set the goal:

```text
/autocompact 500k
```

`/autocompact` needs Claude Code v2.1.221 or later and writes the window to user settings,
so it is set once rather than per session; `/autocompact auto` returns to the default.

## The skill survives compaction; it does not perform it

**This skill does not compact and cannot.** Compaction is a built-in the model has no tool
for, so nothing written in a `SKILL.md` can trigger it — a step that told you to compact
here would just be the manual step again, wearing a different hat. What the dispatcher steps
do instead is *survive* it: the ready set and the claimed issue number live in
`.claude/backlog/work-backlog-state.md`, so a compaction landing mid-issue costs a re-read
rather than a claim stranded on `status:in-progress`.