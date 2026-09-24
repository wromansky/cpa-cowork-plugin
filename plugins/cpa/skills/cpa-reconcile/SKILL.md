---
name: cpa-reconcile
description: Normalize department labels, compare two tables within tolerance, and catch paste errors or out-of-period dates. Called by cpa-bog-refresh, cpa-fc-refresh, cpa-governance-refresh, cpa-master-data and cpa-budget-workbook, or when the user says "reconcile", "why don't these tie", or "check this against that".
---

# cpa-reconcile

## When to run
- Called by any skill that needs two tables tied out (cpa-bog-refresh, cpa-fc-refresh,
  cpa-governance-refresh, cpa-master-data, cpa-budget-workbook).
- The user asks to reconcile two files, asks "why don't these tie", or asks for a paste-error or
  date-range check on an export.

## Inputs
| Input | Where | Required |
|---|---|---|
| Table A, table B (or one table plus expected shape) | given paths, workspace-relative | yes |
| Shared key columns, measure columns | given, or read from the calling skill's template map | yes |
| Department crosswalk | `reference/dept_crosswalk.csv` | yes, when a key is a department column |
| Tolerance | `reference/assumptions.yaml` `reconcile.tolerance_abs`/`tolerance_pct` (D05); override only when the analyst gave a different number | no |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. When a department column is one of the keys, normalize it first: run `.venv\Scripts\python.exe -m
   cpa crosswalk normalize --input <table> --column <dept column> [--sheet <sheet>] [--crosswalk
   reference/dept_crosswalk.csv] --out <normalized>.csv`. Exit 1 lists every unmatched label; stop and
   report them, do not proceed.
3. When the caller flagged a possible paste error, run `.venv\Scripts\python.exe -m cpa reconcile
   paste-errors --input <table> --expected-columns <col1,col2,...> [--expected-rows <n>]` first and
   report any finding before comparing.
4. When the caller gave a date column and an expected period, run `.venv\Scripts\python.exe -m cpa
   reconcile check-dates --input <table> --column <col> --start <YYYY-MM-DD> --end <YYYY-MM-DD>` and
   report any out-of-range or unparseable value.
5. Compare: run `.venv\Scripts\python.exe -m cpa reconcile compare --a <A> --b <B> --keys
   <k1,k2,...> --measures <m1,m2,...> [--dept-key <key>] [--crosswalk reference/dept_crosswalk.csv]
   [--tolerance-abs <n>] [--tolerance-pct <n>] [--sheet-a <s>] [--sheet-b <s>] --out
   staging/reconcile/<label>_diff.csv --json`. Exit 1 lists every difference and every one-sided
   (unmatched) row in the JSON result and the CSV; exit 2 is an argument error, fix and rerun.
6. Read the JSON result and report tie/no-tie, the count of differences, the count of unmatched rows on
   each side, and every note (blank-key or duplicate-key rows that were never joined), to the calling
   skill or the analyst. Never drop an unmatched row from the report.
7. Write the run record: `.venv\Scripts\python.exe -m cpa state record --skill cpa-reconcile --input
   <A> --input <B> --output staging/reconcile/<label>_diff.csv --verification "<tied|N differences,
   M unmatched>" --duration <seconds>`.

## Outputs
- `staging/reconcile/<label>_diff.csv` - every listed difference and unmatched row, when `--out` was
  given.
- The tie/no-tie statement, returned to the calling skill or printed to the user. This skill writes no
  workbook of its own.
- `logs/runs/<timestamp>_cpa-reconcile.json` - the run record.

## Verify
- `reconcile compare` exited 0 (tied) or 1 with every difference, every one-sided row and every note
  (blank-key or duplicate-key rows never joined) listed in the output; never silently dropped.
- Every department key was normalized through the crosswalk before comparing; an unmatched label
  stopped the run rather than being compared as-is.
- The tolerance used (explicit flag or the assumptions default) is stated in the report.

## If something is wrong
- `crosswalk normalize` exits 1 -> stop; list the unmatched labels and the crosswalk path; the analyst
  adds the missing rows to `reference/dept_crosswalk.csv`; never guess a mapping.
- `reconcile compare` exits 1 with a message and no JSON result (a crosswalk file that is not there, no
  tolerance in `reference/assumptions.yaml`, or an unmatched department label) -> stop and report the
  message; the analyst supplies the file, the tolerance value or the missing crosswalk row; never invent
  one.
- `reconcile compare` exits 2 -> stop and report the exact argument error; do not write a run record
  claiming success.
- A period mismatch between the two tables (different month spans) -> do not compare as-is; ask
  whether to prorate via `.venv\Scripts\python.exe -m cpa periods prorate <value> <plan_months>
  <actual_months>` and label the result explicitly.

## Never
- Never drop an unmatched row from the report; every one-sided row is listed, never silently ignored.
- Never compare a department key that has not gone through the crosswalk first.
- Never invent a tolerance value; use the assumptions default or the value the analyst gave.
- Never compare two tables covering different fiscal spans without an explicit, labeled proration.
