---
name: cpa-app-pnl
description: Build the three-year APP position P&L from the version 5 template using a triaged department submission, the MedVitals CPT Billing Profile, the Tableau collection rate, and SullivanCotter benchmarks. Run after cpa-app-triage marks a position COMPLETE or FIXABLE and the pulls have landed, or when the user says "build the P&L for this position".
---

# cpa-app-pnl

## When to run
- cpa-app-triage marks a position COMPLETE or FIXABLE and the division's CPT profile and collection
  rate have landed.
- The user says "build the P&L for <position>" or names a position to build.

## Inputs
| Input | Where | Required |
|---|---|---|
| `brief.md`, `triage.md` | `staging/app/<position>/` | yes |
| `pnl_inputs.json` (position, cycle, department, division, role, plan_period, as_of, base_salary, supplements, cfte) | `staging/app/<position>/` | yes |
| `collection_rate.json` | `staging/app/<position>/` | no (flag, continue) |
| `sc_points.json` (SullivanCotter points) | `staging/app/<position>/` | yes |
| CPT Billing Profile | `inbox/medvitals/cpt_profile_<division>_*.xlsx` | yes |
| Template | `templates/APP_PnL_v5.xlsx` | yes |
| Assumptions (rates, brand) | `reference/assumptions.yaml` | yes |

## Steps
1. Read `CPA_WORKSPACE` from `cpa-core`.
2. Confirm `staging/app/<position>/triage.md` classifies the position COMPLETE or FIXABLE. If it does
   not exist yet or classifies RETURN, stop and run cpa-app-triage first.
3. If `pnl_inputs.json` or `sc_points.json` is missing, ask the analyst for the confirmed figures
   (base salary, supplements, plan period, SullivanCotter survey points) and write them there — never
   invent a figure (hard rule 15).
4. Run `python -m cpa app_pnl build --position <position_id> [--cycle <YYYY-MM-DD>] --json`.
   The command copies the template; writes only into unlocked, yellow-filled input cells; populates
   salary, supplements, and fringe from `assumptions.yaml`; pulls ProFee billing from the CPT profile
   and the collection rate; adds Dean's Tax and DoM Clinical Tax where applicable; adds SullivanCotter
   rows via `cpa.benchmarks` (TCC and Work RVUs, interpolated percentiles, specialty and survey column
   named); builds the M2 activity block, pulling cFTE from the consolidated reference when the provider
   or role exists there and leaving it blank otherwise; recalculates; diffs every locked cell against
   the template; attaches the Verification tab itself; writes `outbox/app/<cycle>/<position>/PnL.xlsx`.
5. Read the command's JSON result and the workbook's manifest verification field. If it is not CLEAN,
   run `python -m cpa verify <workbook path> --sources inbox/medvitals/` and follow cpa-verify's
   "If something is wrong" before continuing.
6. Run `python -m cpa state mark cpa-app-pnl <position_id> done --output <workbook path>`.
7. Report: JHU Contribution Margin and Division Surplus/Deficit for each of the three years, the two
   SullivanCotter percentile statements, and any M2 or benchmark flags.
8. Run `python -m cpa state record --skill cpa-app-pnl --input <pnl_inputs.json path> --output
   <workbook path> --verification <CLEAN or "N ISSUES"> --duration <seconds>` to write the run record.

## Outputs
- `outbox/app/<cycle>/<position>/PnL.xlsx`

## Verify
- No locked cell changed from the template (the build itself diffs and stops on a mismatch after
  recalculation, renaming the output `PnL.LOCKED_CELLS_CHANGED.xlsx`).
- Verification tab CLEAN.
- Both percentile statements are specific numbers, or a justified "greater than the top point."
- M2 activity block present.

## If something is wrong
- `app_pnl build` exits 3 (unmapped specialty) → stop; ask the analyst which SullivanCotter specialty
  applies; add the mapping row to `reference/sullivancotter_specialty_map.csv`; rerun.
- `app_pnl build` exits 2 (stopped) → report the error text; do not run `state mark` or write a run
  record claiming success.
- Locked cells changed after recalculation → the output is `PnL.LOCKED_CELLS_CHANGED.xlsx`, flagged
  "do not send"; keep the failed copy in `staging/app/<position>/work/`, report the diff, do not mark
  the position done.
- `collection_rate.json` is missing → a yellow flag placeholder is written into the input cell; report
  the flag and continue; never estimate the rate.

## Never
- Never give the department a cell to enter its own benchmark.
- Never include fringe in TCC.
- Never write into a locked template cell, even to "fix" a formula.
- Never mark the position done, or claim it verified, when the output is `PnL.LOCKED_CELLS_CHANGED.xlsx`.
