---
name: cpa-activity-block
description: Write or refresh the M2 activity metrics block (wRVUs, cFTE, Collections, Charges) on an existing P&L tab. Called by any skill writing a P&L, such as cpa-app-pnl, before it hands the workbook to cpa-verify, or when the user says "add the activity block" or "refresh M2".
---

# cpa-activity-block

## When to run
- Called by any skill that writes a P&L, after that P&L's own figures are on the tab and before it
  calls cpa-verify.
- The user asks to add or refresh the M2 block on a tab.

## Inputs
| Input | Where | Required |
|---|---|---|
| Target workbook | path given | yes |
| Target tab | sheet name given; must already exist on the workbook | yes |
| Metrics | a JSON file: wRVUs, cFTE, Charges, and one of "Collections (gross)" / "Collections (net)", each with value/period/status/source/as_of when supplied, or why/source when not | yes |
| Narrative-relevant metrics | comma-separated metric names (default: all four) | no |
| `brand.flag_yellow` | `reference/assumptions.yaml` | yes, only when a metric is missing |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. Build the metrics JSON file from the figures the caller already has. Never invent a `why` or
   `source` for a metric that was not supplied - leave those fields as the caller gave them.
3. Run `python -m cpa activity_block build --workbook <workbook> --tab <tab> --metrics
   <metrics.json> [--narrative-relevant <comma list>] [--anchor <A1 cell>] --json`.
   The command writes the fixed block (title, header row, one row per metric) at the tab's existing
   M2 title if there is one, else two rows below the last used row; a metric missing a value gets a
   yellow `MISSING: <metric> not supplied[; needed for <why>][; source <source>]` placeholder, never
   blank, never estimated.
4. Read the JSON result: which metrics, if any, were flagged missing.
5. If any metric is flagged: tell the caller which ones and why - this is a flag, not a stop; a P&L
   with no wRVU input still produces a workbook, just with that row flagged.
6. Run `python -m cpa state record --skill cpa-activity-block --input <metrics.json> --output
   <workbook> --verification <"ok" or "N flagged"> --duration <seconds>` to write the run record.

## Outputs
- `<workbook>` - the same workbook, with the M2 block written or refreshed on `<tab>`. The caller
  owns writing this workbook to outbox and runs cpa-verify on it afterward.
- `logs/runs/<timestamp>_cpa-activity-block.json` - the run record.

## Verify
- All four metrics have a row: wRVUs, cFTE, Charges, and Collections labelled gross or net.
- Every supplied metric's row carries period, status, source, and as-of date.
- Every missing metric's row reads `MISSING: ...`, filled yellow, never blank, never a number.

## If something is wrong
- `--tab` is not a sheet on the workbook -> the command exits 2; stop, report the error, and do not
  write a run record claiming success. This module never creates a tab.
- `brand.flag_yellow` is null in `reference/assumptions.yaml` and a metric is missing -> the command
  exits 2 (`MissingAssumption`); tell the analyst to supply it, or propose it with `python -m cpa
  config propose brand.flag_yellow "<hex>" --note "confirmed by analyst"` for her to paste in.
- The anchor area is already occupied by something other than an existing M2 block -> the command
  exits 2; stop and report the conflicting cells; never overwrite unrelated content.

## Never
- Never estimate a missing metric.
- Never write a bare "Collections" row when a value is supplied - always gross or net.
- Never invent a `why` or `source` for a missing metric.
- Never suppress a flag the command returned.
- Never create the target tab; it must already exist.
