---
name: cpa-rollover
description: Create the new fiscal month's folders, copy last period's templates forward, and advance the fiscal period. Run on the first business day of each fiscal month, when the user says "roll the month" or "start the new fiscal period", or when the month-start scheduled task calls it.
---

# cpa-rollover

## When to run
- Scheduled, first business day of each fiscal month.
- The user says "roll the month", "start the new fiscal period", or names a new FYMM to start.

## Inputs
| Input | Where | Required |
|---|---|---|
| Today's date (or the target period) | ask the analyst if not stated | yes |
| Committee lead-day assumptions | reference/assumptions.yaml | yes |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. Run `python -m cpa periods fymm <today>` to get this fiscal month's FYMM label; never guess it
   by hand.
3. Run `python -m cpa rollover run --fymm <FYMM> --json`. It creates this fiscal month's `inbox/`,
   `staging/`, `outbox/` folders for every monthly workflow, copies last period's bog/fc outputs
   into `templates/` only where no template exists there yet, and advances `current_fymm` in the
   cycle registry. It never deletes or overwrites an existing path.
4. Run `python -m cpa config check` and read the result. If a committee lead-day key due for
   quarterly review is listed, name it to the analyst; never propose a guessed value for it.
5. Run `python -m cpa dashboard build --json` so the new period's folders and any newly-missing
   inputs show up on today's dashboard.
6. Write the run record: `python -m cpa state record --skill cpa-rollover --input <today's date>
   --output <FYMM> --verification "rollover done for <FYMM>" --duration <seconds>`.

## Outputs
- `inbox/<system>/`, `staging/<workflow>/<FYMM>/`, `outbox/<workflow>/<FYMM>/` for the new fiscal
  month.
- `templates/<workflow>/` — last period's outputs copied forward where none existed.
- `logs/cycles.json` — `current_fymm` advanced.

## Verify
- `rollover run` exited 0 (done), not 1 (stopped).
- Every monthly workflow has a folder under this period's `inbox/`, `staging/`, and `outbox/`.
- No file that existed before this run was deleted or overwritten.

## If something is wrong
- `rollover run` exits 1 → report the exact stderr line to the analyst; do not write a run record
  claiming success.
- `config check` lists a stale committee lead-day key → tell the analyst which key and ask her to
  update `reference/assumptions.yaml` herself; never fill in a plausible lead time.
- The target FYMM already has folders from an earlier run → not an error, rollover never overwrites;
  report that the period was already rolled and move on.

## Never
- Never delete or overwrite a prior period's folders or files.
- Never guess a fiscal period by hand; always compute it with `python -m cpa periods fymm`.
- Never write to `reference/assumptions.yaml` directly; propose changes with `python -m cpa config
  propose` and let the analyst paste them in.
- Never fabricate a committee lead-day value when one is missing from `assumptions.yaml`.
