---
name: cpa-dispatcher
description: Scan the CPA workspace inbox and run whichever workflows are ready, in dependency order, then archive the inputs they consumed and rebuild the dashboard. Run as the scheduled task at 09:00, 11:00, 13:00, 15:00 and 17:00 on weekdays and 02:00 daily, or when the user says "process the inbox", "run the dispatcher" or "what's ready to run".
---

# cpa-dispatcher

## When to run
- The `CPA dispatcher` scheduled task fires (weekdays 09:00, 11:00, 13:00, 15:00, 17:00; and 02:00 daily).
- The user says "process the inbox", "run the dispatcher", "what's ready to run", or "what landed".
- A pull landed exports and the analyst wants the downstream chain run now.

## Inputs
| Input | Where | Required |
|---|---|---|
| Workspace root | `CPA_WORKSPACE`, read from cpa-core | yes |
| Landed inbox files | `inbox/<system>/` | no; an empty or unchanged inbox is a clean no-op |
| Dispatcher state | `logs/state.json` (file hashes; run statuses and outputs keyed `<workflow>:<key>`, where a slide run's key is a position and a deck run's key is a cycle; pulled systems) | no; `state scan` creates it on the first pass |
| Readiness rules | `cpa.state` base rules, plus each workflow module's own `READINESS_RULES` (D19) | yes |
| Dependency order | the dependency rules listed in step 4 below (guide 7.3) | yes |

## Steps
1. If the request is to learn Cowork or understand the plugin, hand off to cpa-getting-started
   and return without scanning files, resolving a workspace or starting workflows. Its lesson
   needs none of the operational inputs above. Otherwise read `CPA_WORKSPACE` from cpa-core. Every path below is workspace-relative under that root, and every
   path handed to a `cpa` command is spelled as an absolute path under `CPA_WORKSPACE`, because the commands
   record and resolve paths against the workspace rather than the shell's current directory.
2. Run `.venv\Scripts\python.exe -m cpa state scan` and read every line it prints. `new` and `changed` are
   the files this pass may act on; `unchanged` is a file whose hash is already recorded, so nothing queues it
   again. A file listed `unavailable` is one that is not downloaded yet (a cloud placeholder): report it and
   never treat it as new or as missing. A file listed `missing_manifest` has no sidecar, so any workflow whose
   rule requires a manifest is not ready for it.
3. Run `.venv\Scripts\python.exe -m cpa state ready --json` and read the rows. Each row is a workflow, its
   period key, a reason (`new`, `stale`, `retry`) and the input paths that satisfied its rule. That list is
   the whole work queue for this pass. `state ready` decides reruns; nothing else does.
4. Apply these dependency rules to the queue before running anything, so no dependent workflow is ever
   started on a prerequisite that failed or has not run yet:
   - Hard dependencies are read from the state file's own run keys, never guessed. The first three cases share
     one key: `state ready` and `state mark` key a run `<workflow>:<key>`, and because the downstream workflow's
     readiness rule names the prerequisite's output, that key is the same one - `cpa-budget-workbook` `done`
     for an FYMM before `cpa-fc-refresh` for that FYMM (FC's rule needs the budget workbook in outbox);
     `cpa-app-triage` `done` for a position before `cpa-app-pnl` for that position (its rule needs that
     position's `triage.md`); `cpa-app-pnl` `done` for a position before `cpa-app-slide` for it (a slide rule
     needs that position's P&L built and verified).
   - The deck's prerequisite is keyed differently and is mapped from paths, never assumed. `logs/state.json`
     keys the slide run by position - `cpa-app-slide:<position_id>`, because the slide rule reads
     `staging/app/<position_id>/` - and the deck run by cycle, `cpa-app-deck:<cycle>`. No
     `cpa-app-slide:<cycle>` run ever exists: never look for one, never record one, and never report a slide
     status under a cycle key. Assign each slide run to a cycle from that run's own paths: for a run recorded
     in `logs/state.json`, its `outputs` entry `outbox/app/<cycle>/<position_id>/slide.pptx` names the cycle;
     for the row this pass's `state ready --json` returned for `cpa-app-slide`, its `inputs` entry
     `outbox/app/<cycle>/<position_id>/PnL.xlsx` names it. In both, the first path segment under `outbox/app/`
     is the cycle and the next is the position.
   - Then, for the cycle a deck row names: `cpa-app-deck` may run only when at least one slide run assigned to
     that cycle is `done` with that cycle's `outbox/app/<cycle>/<position_id>/slide.pptx` among its outputs,
     which is the file the deck's own rule matches; a slide run for a different cycle never makes it ready. And
     the deck for that cycle is `blocked`, not run, when any slide run assigned to that cycle ended `failed` or
     `blocked`, in this pass or an earlier one, because a position of that cycle is then missing its slide:
     report that position, its slide status and the missing `outbox/app/<cycle>/<position_id>/slide.pptx`, and
     never substitute another cycle's slide, another position's slide, or a status you did not read.
   - Preferred order only, no dependency (guide 7.3): budget workbook, master data, then BOG refresh; the
     APP chain triage, P&L, slide, deck; a cag-match cFTE refresh for a period before a `cpa-app-pnl` for
     that period. `cpa-charge-forecast`, `cpa-crf` and `cpa-lookback` depend on nothing and may run at any
     point in the pass.
5. Take one workflow at a time and invoke the skill whose name is the workflow name
   (`cpa-budget-workbook`, `cpa-master-data`, `cpa-bog-refresh`, `cpa-fc-refresh`, `cpa-app-triage`,
   `cpa-app-pnl`, `cpa-app-slide`, `cpa-app-deck`, `cpa-cag-match`, `cpa-charge-forecast`, `cpa-crf`,
   `cpa-lookback`), giving it the key `state ready` used for that row - a period key for most workflows, a
   position for `cpa-app-slide` and a cycle for `cpa-app-deck`, the deck's own rule being the only one keyed
   by cycle. Record `running` for that key with
   `.venv\Scripts\python.exe -m cpa state mark <workflow> <key> running` first (guide 7.1 records a run's
   start and end), wait for it to report before starting the next one. A ready workflow whose skill is not
   on disk is reported by name and skipped; the workflow is never improvised here, and its dependents do not
   run either.
6. Read what the skill reported, then record one status with `.venv\Scripts\python.exe -m cpa state mark
   <workflow> <key> <status> --output <each path it wrote>`. `done` only when the skill's own exit code is
   success and its verification result is CLEAN. Any other outcome is `failed` (the run produced something
   with issues, or produced nothing) or `blocked` (it stopped for a missing assumption or a decision only
   she can make). A non-CLEAN verification is never recorded as `done`: the dispatcher does not acknowledge
   issues on her behalf. The `cpa-app-*` skills mark their own run; read the status they reported and never
   re-mark a run they reported failed as done.
7. When a workflow ends `failed` or `blocked`, its dependents for the affected key do not run in this pass,
   even if something already on disk would satisfy their own rule (a `triage.md` or a slide left by an
   earlier run): report each with the prerequisite that stopped it and the key its rule uses, and mark it
   `blocked` when it is itself in this pass's queue so the next pass re-evaluates it. For the APP chain name
   both keys, because they differ: the position whose slide ended `failed` or `blocked`, and the cycle whose
   deck that holds back, with the slide output path that is missing. Keep running only the
   workflows that have no dependency path to the failure, and never run a dependent to "catch up". One
   attempt per workflow per pass; a failure waits for the next pass or for her.
8. Archive only what every consumer has finished with: run `.venv\Scripts\python.exe -m cpa state archive
   <each processed inbox file>` for an input whose every workflow has a `done` run recorded for that key,
   and only then. One finished consumer is not enough: a shared input stays in `inbox/` while another
   workflow still needs it, otherwise that workflow's rule can never be satisfied again because the rule
   looks in `inbox/`. The files the readiness rules name for more than one workflow are
   `inbox/tableau/charges_by_day_<key>.*` (charge forecast, BOG refresh, FC refresh),
   `inbox/powerbi/dept_productivity_<key>.*` (master data, BOG refresh, FC refresh) and
   `inbox/cognos/dept_financials_<key>.*` (BOG refresh, FC refresh); when a file's consumers are not clear,
   keep it. `state archive` moves files from `inbox/` into `archive/<system>/<date>/`, never deletes, and
   refuses any path that is not under `inbox/`. Leave every other input where it is and name the reason
   and the workflow still waiting on it. Never archive an outbox artifact.
9. Run the cpa-dashboard skill so `logs/dashboard.md` and the morning message reflect this pass.
10. Write the run record: `.venv\Scripts\python.exe -m cpa state record --skill cpa-dispatcher --input
    <each input this pass read> --output logs/state.json --output logs/dashboard.md --verification "<ran>
    ran, <failed> failed, <waiting> waiting" --warning <each skipped or blocked workflow with its reason>
    --duration <seconds>`, adding `--needs-analyst` when anything is blocked or waiting on her.
11. Report one message: what ran, what landed in outbox, what verification flagged, what is waiting on which
    missing input, and which decision she must make. Stay silent when the pass found nothing ready and
    nothing blocked (R023) - the run record is still written.

## Outputs
- `logs/state.json` - updated file hashes, run statuses and outputs, and processed-input bookkeeping.
- `archive/<system>/<date>/` - the inbox inputs every consumer of which has finished, moved, never deleted;
  a shared input still needed by another workflow stays in `inbox/`.
- `logs/dashboard.md` - written by the cpa-dashboard skill this pass.
- `logs/runs/<timestamp>_cpa-dispatcher.json` - the run record.
- No workbook and no outbox artifact: the dispatcher writes neither. Every workbook in this pass belongs to
  the skill that produced it and is verified by that skill; when a workflow produced no workbook at all, the
  run record says so instead of reporting a verification that did not happen.

## Verify
- Every row `state ready` returned is either run in this pass or reported with the reason it was skipped.
- No dependent workflow was run while its prerequisite for the affected key was `failed`, `blocked`, absent
  or not yet `done`, and none was run after its prerequisite failed later in the same pass.
- Every `cpa-app-deck` run this pass had at least one slide run assigned to its own cycle recorded `done` with
  that cycle's `outbox/app/<cycle>/<position_id>/slide.pptx` among its outputs, and no deck ran while a slide
  run assigned to its cycle was `failed` or `blocked`; every slide status read came from a
  `cpa-app-slide:<position_id>` run, never from a cycle-keyed key and never from another cycle's slide.
- No workflow ran twice for the same period key unless its input hash changed (R055); `state ready` is the
  only thing that decides that, and neither `new`, `stale` nor `retry` rows were dropped silently.
- No `cpa-pull-*` or cpa-monthly-pull skill was invoked (R056).
- Every archived path was under `inbox/`, and every workflow whose rule names that file already had a `done`
  run for that key; every file another workflow still needs is still in `inbox/` and named with that
  workflow.
- Every `done` status corresponds to a skill that exited successfully with a CLEAN verification; no
  non-CLEAN result was recorded as `done`.
- Nothing was deleted, and nothing under `outbox/` was moved, edited or sent.
- The run record exists, and the message lists the same outcomes the run record holds.

## If something is wrong
- `state scan` or `state ready` exits non-zero, or names a rule whose module failed to import -> report the
  exact stderr line and the module, run nothing that depends on that workflow, and still write the run
  record with `--needs-analyst`.
- A ready workflow's skill is not on disk -> report the workflow and period key, skip it, and do not run its
  dependents either; only workflows with no dependency path to it continue. Never improvise the workflow or
  call a different skill for it.
- A position's slide ended `failed` or `blocked` and its cycle's deck is in this pass's queue -> mark the deck
  for that cycle `blocked` with `.venv\Scripts\python.exe -m cpa state mark cpa-app-deck <cycle> blocked` (the
  deck skill never ran, so no `cpa-app-deck` run exists to read), name that position, its slide status and the
  missing `outbox/app/<cycle>/<position_id>/slide.pptx`, and run neither the deck nor its dependents. Never
  read or invent a slide status under the cycle key, and never let another position's slide stand in for the
  missing one. That decision is hers: when she says so, she can run the deck herself and accept the exclusion;
  the pass does not decide it for her.
- A skill stops for a missing `reference/assumptions.yaml` key -> mark that workflow `blocked`, name the key
  for her, and continue only with the workflows that do not depend on it; never supply, guess or default the
  value (hard rule 15).
- `cpa-verify` returns "draft with issues" for a workbook in outbox -> leave the artifact for her review, mark
  that workflow `failed`, name the tab and cell of each issue, do not archive its inputs, and do not run its
  dependents. Her acknowledgment is not the dispatcher's to record: she re-runs the workflow, and a CLEAN
  result is what turns it `done`.
- A shared input's consumers disagree (one `done`, one `failed` or `blocked`) -> keep the file in `inbox/`,
  name the consumer still waiting, and archive nothing until the last consumer is `done`.
- A sign-in, SSO or MFA prompt appears in any step -> stop that workflow, name the system and the step, leave
  it for her, and continue only with the workflows that do not depend on it; the dispatcher never signs in and
  never retries a sign-in.
- An archive move fails because Excel or a file-sync client holds the file -> report the path and leave the
  file in `inbox/`; the next pass picks it up.
- `state ready` returns no rows while `state scan` reported new files -> report the files, since no readiness
  rule claims them yet, and ask her which workflow they feed; never hand a file to a workflow of your own
  choosing.
- The inbox holds a file whose period cannot be read from its name -> report the file path; the readiness
  rules list only keys they can read.

## Never
- Never run a browser pull skill (`cpa-pull-*`, including cpa-monthly-pull) from the dispatcher; pulls are
  interactive until the unattended pull trial passes, `cpa.state` refuses a readiness rule for them (R056),
  and a month whose export has not landed simply shows up as a workflow waiting on its input.
- Never run a workflow twice for the same period unless its input file hash changed (R055).
- Never run a workflow `state ready` did not return, and never run a workflow whose prerequisite for the
  affected key is not `done` even when a file left on disk would satisfy its rule (a workflow's own earlier
  run re-queued as `retry` is not a dependency). Never invoke the dispatcher itself.
- Never run two workflows at once, never run a dependent to catch up after a failure, and never retry a failed
  workflow inside the same pass.
- Never read, record or report a slide run under a cycle key: `cpa-app-slide` is keyed by position, the deck's
  cycle comes from the slide run's own `outbox/app/<cycle>/<position_id>/slide.pptx` output path (or, for this
  pass's ready row, from its `outbox/app/<cycle>/<position_id>/PnL.xlsx` input path), and no
  `cpa-app-slide:<cycle>` run exists to read.
- Never run `cpa-app-deck` for a cycle while a slide for a position of that cycle ended `failed` or `blocked`,
  and never treat a slide from another cycle as satisfying the deck's rule.
- Never archive an input that another workflow still needs, never archive one whose consumers have not all
  finished `done`, and never delete a file (R101, R102).
- Never poll mail or chat: the dispatcher has no connector, and cpa-intake files attachments on its own
  hourly task.
- Never move a file between workspace folders other than the `state archive` move of an input whose every
  consumer has finished; every other move, and every consolidation, waits for a plan she approves.
- Never send, post or write to a source system, and never move anything out of `outbox/`.
- Never fill or invent a missing assumption, department, report name, URL, period key or run status.
- Never record `done` for a run whose verification is not CLEAN, and never report a verification, a run or an
  archive that did not happen.
