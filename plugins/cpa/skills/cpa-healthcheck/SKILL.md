---
name: cpa-healthcheck
description: Report drift for every watched workflow and build the monthly effort report from the run logs. Run as the weekly drift pass and the monthly effort report, or when the user says "health check", "self-test", "did anything break", "is anything stale", or "effort report". The repository self-test is developer-only and needs a checked-out repository.
---

# cpa-healthcheck

## When to run
- Scheduled weekly, the drift pass (E5).
- Scheduled monthly, the effort report (E6), after that month's runs are logged.
- The user says "health check", "self-test", "did anything break", "is anything stale", or asks for the
  hours of automated work by workflow.
- `cpa-dispatcher` calls it at the end of a pass to surface drift before the notification.
- Only in a checked-out plugin repository, the self-test step below. A released plugin bundle ships no
  repository tests, so the self-test is developer-only and is never part of her scheduled tasks.

## Inputs
| Input | Where | Required |
|---|---|---|
| Watched workflows and their run state | `logs/state.json` read through the `cpa.state` readiness rules | yes for the drift step |
| Run records for one month | `logs/runs/*.json` | yes for the effort step |
| Report month | `--month` as a calendar month `YYYY-MM`, from the scheduled task or from her | yes for the effort step |
| Bundled runtime readiness | the cpa-core launcher's `--check` output (`scripts/run_cpa.py` beside the loaded cpa-core skill) | yes in a Cowork session |
| Repository tests | the plugin repository's own `tests/` directory - present only in a checkout, never in a release bundle | only for the self-test step |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core and resolve the workspace root; confirm the folder is visible in
   this environment before reporting anything about it.
2. Runtime readiness, in a Cowork session: run the cpa-core launcher's `--check` and report its exit
   code and JSON report as they came (0 = nothing to report, 1 = a missing or mismatched dependency,
   for example). Every `python -m cpa ...` call below is the same call through that launcher (cpa-core
   says how to resolve its per-session absolute path). `--check` asks whether the bundled runtime is
   complete; it does not run the tests.
3. Drift: run `python -m cpa healthcheck dryrun --json`. For every workflow with a registered readiness
   rule it reports last calendar month's status. A rule keyed to a fiscal month is looked up as
   `<workflow>:<FYMM>` in the run state; a folder- or date-keyed rule reports `n/a (key=...)` and no
   drift. The command exits 1 when any workflow shows drift.
4. Report every drift row by workflow and status. `no run recorded` is drift: it is the signal that a
   scheduled task did not fire, and it is reported as such.
5. Effort report: run `python -m cpa healthcheck effort --month <YYYY-MM> --json`. It reads
   `logs/runs/*.json`, sums each skill's recorded duration into hours, counts the warnings raised, and
   writes `outbox/healthcheck/<month>/Effort_Report_<month>.md` (plus its sidecar manifest), headed as a
   draft for her review.
6. Read the report path and the totals. The report states its own grain (a calendar month, which can
   differ from her fiscal month) and that `hygiene.effort_success_measures` is unconfirmed, so it
   carries no baseline to compare against.
7. Report: every drift row, and the hours by workflow and warning count for the month; in a checkout,
   also the self-test exit code and duration. This report is not a validation of the runtime or of her
   workspace.
8. Self-test, developer-only and only in a checked-out repository: run `python -m cpa healthcheck run`.
   It runs the repository test suite in a child interpreter and prints the tail of the output, the exit
   code and the duration; add `--json` for the exit code and the duration alone, and `--path <dir>` for a
   different tests directory. This is the only way a skill runs the suite; the test runner is never
   invoked directly (D12). A release bundle has no repository tests, so the command reports that the
   tests are not included and points at `--path`; that is expected, so this step is skipped there and
   its absence is reported, not treated as a failure.
9. Write the run record: `python -m cpa state record --skill cpa-healthcheck --output
   outbox/healthcheck/<month>/Effort_Report_<month>.md --verification "<self-test exit code, or
   developer-only; <n> drift rows>" --warning <each drift row> --duration <seconds>`.

## Outputs
- `outbox/healthcheck/<month>/Effort_Report_<month>.md` - the draft monthly effort report, plus its
  sidecar manifest.
- The drift list, the hours by workflow and the warning count, reported to the analyst; in a checkout
  the self-test exit code and output tail; in a Cowork session the launcher `--check` output.
- `logs/runs/<timestamp>_cpa-healthcheck.json` - the run record.
- This skill produces no workbook; the effort report is a draft document, not an artifact to send.

## Verify
- The launcher `--check` output is reported as it came and is never restated as a pass for the runtime,
  her workspace or any step.
- In a checkout the self-test step reports an exit code taken from the child test run; a non-zero code is
  reported as a failure, never restated as a pass. In a release bundle the absence of the self-test is
  stated, never dressed up as a pass.
- Every workflow the drift step returns is reported with its status; no drift row is dropped, and
  `no run recorded` is never reported as "fine".
- The effort report's header names its period and its calendar-month grain, and its hours come only from
  `logs/runs/*.json`.
- A green self-test is evidence about the repository's own fixture-based tests; it says nothing about her
  real workspace files and nothing about the packaged runtime, and the report does not claim otherwise.

## If something is wrong
- The launcher `--check` reports a missing dependency → report the missing dependency verbatim and stop
  the affected step; do not install or upgrade anything.
- The launcher cannot be resolved (no `scripts/run_cpa.py` beside the loaded cpa-core skill) → report the
  steps that need the runtime as blocked; do not fall back to installing the package.
- `healthcheck run` exits non-zero → report the failing test names and the output tail; a broken rule is
  exactly what this check exists to surface. Do not fix code from here and do not weaken a test.
- `healthcheck run` reports that the repository tests are not included and points at `--path` (a
  released bundle ships none) → report the self-test as developer-only and unavailable here; do not run
  a partial suite, and do not call the missing tests a failure of her workspace or of the runtime.
- `healthcheck run` cannot start at all (no interpreter, no dependency) → report the error verbatim; do
  not run a partial suite and call it a pass.
- `dryrun` exits 1 → list every drift row; a workflow with no run recorded is reported as `no run
  recorded`, never as healthy.
- `logs/runs/` holds no record for the month → the report says "no runs recorded for this month"; report
  zero hours rather than an estimate.
- The E5 half "verify the approved-site list and allow rules still hold" has no script in this build;
  report it as not covered by automation rather than checking it from memory and calling it passed.
- The run used a scratch workspace (`CPA_WORKSPACE` pointed at a temporary tree) → say so; a scratch run
  says nothing about her live workspace.

## Never
- Never invoke the test runner directly; the suite runs only as `python -m cpa healthcheck run`.
- Never present the self-test, the drift list or the effort report as a runtime readiness check; the
  launcher `--check` is the readiness check, and a green run does not validate the sandbox.
- Never claim the bundled runtime was validated when `--check` was not run or its output was not read.
- Never install, upgrade or vendor a package to make a step or the suite run; a missing dependency is
  reported as a blocker.
- Never soften a failing result: no test is deleted, skipped, marked as expected-to-fail or re-run until
  it passes.
- Never report a workflow as healthy when its drift row is `no run recorded`; a missing run record is
  drift.
- Never estimate hours, warning counts or a baseline; with nothing in `logs/runs/` for the month, the
  report says zero.
- Never assume a retention rule or a success measure is set; both ship unconfirmed and are reported as
  such.
- Never rerun a workflow to clear a drift flag; this skill reports drift and does not repair it.
- Never edit or delete a run record or a report; the effort report counts exactly what is in
  `logs/runs/`.
