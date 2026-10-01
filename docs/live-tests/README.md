# Live teacher test: start here

Everything needed to host, configure and run the first live teacher test of the grading system through OpenRouter, written for operators and teachers who are not programmers.

## The one-minute version

* **The part a teacher and operator touch (the console, review, finalize, amend, export, pause, recover) works today.** It was run, page by page and command by command, and the tutorial quotes what it really said.
* **A live OpenRouter run cannot be started with the shipped commands yet.** Eight gaps are documented, most with a command that shows them. The main ones: the profile meant for this test (`dev-ci`) replays recordings instead of calling OpenRouter; the profile that does call OpenRouter (`cloud-hosted`) is refused by the console and by a privacy check; nothing yet creates a class list or reads uploaded scans; and the console cannot show the blind-sample papers or record what an operator decides about a parked paper.
* **So the plan has stages.** Rehearse now with practice data. Close the gaps. Then run the live test with these materials.

## Read in this order

| # | Document | Read it if you are | What it gives you |
|---|---|---|---|
| 1 | [`02-live-readiness-and-blockers.md`](02-live-readiness-and-blockers.md) | Everyone, first | The verdict, the eight blockers with proof, what was and was not checked, and the work to do |
| 2 | [`01-hosting-and-configuration.md`](01-hosting-and-configuration.md) | Setting up the machine | Profiles, install, data folder, OpenRouter key and limits, the consent rule, every setting, a security checklist |
| 3 | [`../tutorials/operating-tutorial.md`](../tutorials/operating-tutorial.md) | The operator and the teacher | How the console works, all 14 pages, all 15 commands, and the six phases of the grading life cycle, with screenshots and real replies |
| 4 | [`03-sample-tests-and-answer-sheets.md`](03-sample-tests-and-answer-sheets.md) | Preparing the test | Two sample tests, rubrics, keys, ten answer sheets (including three awkward ones), expected results |
| 5 | [`04-test-day-plan.md`](04-test-day-plan.md) | Running the day | Three stages, roles, timeline, record sheet, pass criteria, teacher questions |

## What is in the other folders

| Path | What it is |
|---|---|
| [`config/live-test.dev-ci.toml`](config/live-test.dev-ci.toml) | The configuration for the test, with every line explained. The two model names are **unconfirmed** at OpenRouter. |
| [`sample-materials/pdf/`](sample-materials/pdf/) | The sample PDFs (18 files): tests, model answers, rubrics, blank answer sheets, finished answer sheets |
| [`sample-materials/build_sample_materials.py`](sample-materials/build_sample_materials.py) | Rebuilds those PDFs, identically every time (standard library only) |
| [`sample-materials/verify_sample_materials.py`](sample-materials/verify_sample_materials.py) | Runs every sample sheet through the system's real intake checks, with no network and no cost |
| [`sample-materials/check_config.py`](sample-materials/check_config.py) | Tells you whether a configuration file will be accepted, before you start anything |
| [`sample-materials/build_rehearsal_data.py`](sample-materials/build_rehearsal_data.py) | Builds a practice data folder (a finished run over three demo students) to rehearse the console on |
| [`../tutorials/images/`](../tutorials/images/) | Screenshots of the real console pages used in the tutorial |

## Four commands worth running first

From the project folder, with the Python environment active:

```bash
python docs/live-tests/sample-materials/check_config.py docs/live-tests/config/live-test.dev-ci.toml
python docs/live-tests/sample-materials/verify_sample_materials.py
python docs/live-tests/sample-materials/build_rehearsal_data.py
python -m aeh console --data-dir ~/aeh-rehearsal
```

The first two check the configuration and the sample sheets. The last two give you a working console to practise on.

## How this was checked

Written against the code in this repository (branch `refactor`), and checked by running it: the console and its 14 pages, all 15 commands, the intake gates on all ten sample sheets, the configuration rules, the start-up refusals, the install in a clean environment (`aeh --help` only), an independent line-by-line audit of these documents against the code, and the OpenRouter provider's outgoing request (captured on a stand-in server on the same machine).

**What could not be checked:** anything that needs OpenRouter itself. The environment these documents were written in could not reach it. So model names, the key, the account's credit, whether OpenRouter accepts the provider's request format, and real cost and run time are all marked unconfirmed wherever they appear.

The documents describe the system as it is. They do not change it: no code, safety check or configuration of the system was altered to write them.
