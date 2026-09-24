---
name: cpa-adhoc-comp
description: Build a compensation and SullivanCotter benchmark comparison workbook for an ad hoc request. Run when a request folder's brief.md reads as a comp or benchmark ask (requested_output mentions compensation, TCC, or a percentile), or when the user says "build the comp workbook" or "benchmark this comp" for a request.
---

# cpa-adhoc-comp

## When to run
- A request folder's `brief.md` has a `requested_output` that reads as a compensation or
  SullivanCotter benchmark comparison.
- The user says "build the comp workbook for <request id>" or "benchmark this comp".

## Inputs
| Input | Where | Required |
|---|---|---|
| `brief.md` | `requests/<id>/` | yes |
| `comp_inputs.json` (specialty, metric, survey_column, as_of, points, providers) | `requests/<id>/` | yes |
| SullivanCotter specialty map | `reference/sullivancotter_specialty_map.csv` | yes |

## Steps
1. Read `CPA_WORKSPACE` from `cpa-core`.
2. Confirm `requests/<id>/brief.md` exists and its `requested_output` names a comp or benchmark
   ask. If it names something else, stop and hand off to the matching cpa-adhoc-* skill instead.
3. If `requests/<id>/comp_inputs.json` is missing or incomplete, ask the analyst for the confirmed
   base, supplements, and SullivanCotter survey points — never invent a figure (hard rule 15).
4. Run `python -m cpa adhoc comp --brief requests/<id>/brief.md --inputs
   requests/<id>/comp_inputs.json`. The command computes TCC as base plus supplements (never
   fringe) via `cpa.benchmarks`, interpolates each provider's percentile against the 2025 AMC
   column, states a specific number unless every reported point is below the provider's TCC (then
   "greater than P<max>"), and cites the specialty and survey column on every row.
5. Run `python -m cpa verify requests/<id>/Comp.xlsx --sources requests/<id>/` and read the
   result. If not CLEAN, follow cpa-verify's "If something is wrong" before continuing.
6. Report each provider's TCC, percentile statement, and specialty.
7. Run `python -m cpa state record --skill cpa-adhoc-comp --input requests/<id>/comp_inputs.json
   --output requests/<id>/Comp.xlsx --verification <CLEAN or "N ISSUES"> --duration <seconds>` to
   write the run record.

## Outputs
- `requests/<id>/Comp.xlsx`

## Verify
- Verification tab CLEAN.
- No percentile statement is a range unless the provider's TCC is above every reported point.
- Specialty and survey column are present on every row.

## If something is wrong
- `comp_inputs.json` names a specialty with no row in
  `reference/sullivancotter_specialty_map.csv` → stop; ask the analyst which SullivanCotter
  specialty applies; add the mapping row; rerun.
- `comp_inputs.json` is missing a required key → the command names it; ask the analyst for that
  figure rather than filling in a placeholder value.
- `python -m cpa adhoc comp` exits 1 (`AdhocError`) → report the error text; do not run `state
  record` claiming success.
- `requests/<id>/Comp.xlsx` already exists → rerun with `--overwrite` only after confirming with
  the analyst that a rebuild is wanted; otherwise stop.

## Never
- Never include fringe in TCC.
- Never use any SullivanCotter column but the 2025 AMC column.
- Never state a percentile as a range unless the figure is above every reported point.
- Never omit the specialty or the survey column from a row.
