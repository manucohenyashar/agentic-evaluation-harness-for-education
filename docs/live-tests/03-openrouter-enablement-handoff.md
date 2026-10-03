# OpenRouter enablement — hand-off for the next session

Branch `claude/bold-cerf-vg9kme`, PR #612. This page says what is done, what is verified, and
exactly what is left, so a new session can finish without the old conversation.

## Done on this branch (all with tests)

| Blocker | What now works | Tests |
|---|---|---|
| B1 | `dev-ci` calls OpenRouter (recordings only when `HARNESS_FIXTURE_DIR` is set); providers bound before `create_run`; unit pricing adapter for the cost ceiling | TC-PIPE-24..26, TC-PROV-64 |
| B6 | Every OpenRouter request carries `provider: {zdr: true, data_collection: "deny"}` | TC-PROV-64 |
| B3 | `aeh cohort create / add-students / show` | TC-ORCH-59/60 |
| B5 | `aeh package build --spec <toml>` (sample: `docs/live-tests/config/ps9-forces-01.package.toml`) | TC-PIPE-27..29 |
| B4 | `aeh ingest`: reads test paper + answer sheets; skips scans already read; parks a read cut off by Ctrl-C; exits 1 when no sheet could be read (key/credit/model) | TC-PIPE-30..32 |
| B8 | `resolve quarantine item` accepts only `matched` / `unresolvable`; refuses releasing a paper with no matched student or never read | TC-CONSOLE-51/52 |
| Escalation seats | A live run never sends `escalation-arm-<k>` as a model. Extra judges come from `[[profiles.<name>.escalation_judge]]` tables; when seats run out the score stays provisional (to review) and the trace says *no real judge for seats …*. A live run with the random-arm sample on but fewer than `min(3, panel) + 2` real judge models is refused before it starts | TC-PIPE-33 |

Comparison runs against `main` (same suites, same order) showed no new failures; `main` itself
has ~100 pre-existing failures in these suites.

## Left to do, in order

1. **Re-run the comparison** for the last commit (escalation seats + hook change), which was
   pushed under time pressure with only targeted suites run:
   `tests/unit/pipe tests/integration/pipe tests/integration/console tests/integration/ingest
   tests/contract` on the branch and on `main` (a worktree), `TMPDIR` outside `/tmp`
   (the store refuses world-writable dirs), compare FAILED/ERROR *names*, not counts.
   Also read TC-REQ-90's allowlist directly (it is red on main, so a diff can't show a new
   violation). Run the `reviewer` subagent on `src/aeh/pipeline/{hooks,executor,runtime,driver,
   background,cli}.py`.
2. **Finish the deployment walkthrough** (`docs/tutorials/deployment-tutorial.md` §8.4): it is
   committed as a draft. Make it say:
   * `$env:HARNESS_ORCH_ESCALATION_BUDGET = "1.0"` for a small class (the 0.30 default stalls a
     6-paper class: exit 3, "no progress after 4 passes").
   * Either `$env:HARNESS_ORCH_RANDOM_ARM_RATE = "0"` with the one-judge shipped config, **or**
     add `escalation_judge` tables (one-judge panel: 2 for the random arm, 3 for every seat).
   * Add commented `escalation_judge` examples to `docs/live-tests/config/live-test.dev-ci.toml`.
3. **Pick real judge models (the user's step).** Each extra judge must be a different model and
   must answer under zero retention. Check each one before adding it:
   ```powershell
   curl.exe https://openrouter.ai/api/v1/chat/completions -H "Authorization: Bearer $env:OPENROUTER_API_KEY" -H "Content-Type: application/json" -d '{\"model\":\"<vendor/model>\",\"messages\":[{\"role\":\"user\",\"content\":\"Say ready\"}],\"provider\":{\"zdr\":true,\"data_collection\":\"deny\"}}'
   ```
   Already confirmed this way: `qwen/qwen3-30b-a3b` (DeepInfra), `qwen/qwen3-vl-8b-instruct`
   (Parasail).
4. **First live run** (the user's machine; this sandbox cannot reach openrouter.ai unless the
   environment's network policy allows it and `OPENROUTER_API_KEY` is set as an environment
   secret — never paste the key into chat):
   `aeh cohort create` → `aeh package build` → `aeh ingest` → `aeh run`, as in the
   deployment tutorial §8. Watch for:
   * **Judge field order.** The judge reply must list its fields in the pinned order
     (`cited_spans, evidence_assessment, evidence_sufficient, band, self_confidence`,
     FR-JUDGE-09); a reordered reply is refused 3 times and the unit quarantined. A real model
     may reorder keys — if many judge units quarantine with "not the pinned order", that is the
     cause (a design question for `/detailed-design-generator`, not a code tweak).
   * **Page markup.** Whether a real vision model writes the region markup the intake checks
     parse is untested.
   * Cost: the ceiling counts claim-time estimates (`HARNESS_PIPE_UNIT_TOKENS_IN/OUT`, 4000/1500),
     far above real spend; raise `HARNESS_COST_CEILING` if a run stops early.

## Still open (not for this PR)

* B7 console pages; B8 *recording the decision* (which tick/student/test) is a design decision
  for `/detailed-design-generator`.
* Console uploads over 4 MiB cannot be reassembled (only the first chunk is recorded).
* FR-PROV-11 upstream pinning; criterion-level text missing from packages.
* The written privacy decision for real student work is the user's.
