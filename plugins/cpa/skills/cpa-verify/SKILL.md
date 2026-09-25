---
name: cpa-verify
description: Attach or refresh the Verification tab on any CPA workbook. Run automatically at the end of every cpa- skill that writes a workbook, or when the user says "verify", "check this workbook", "tie out", or drops a workbook and asks if the numbers are right.
---

# cpa-verify

## When to run
- Called by every cpa- skill after it writes a workbook.
- The user asks to verify, check, or tie out a workbook.

## Inputs
| Input | Where | Required |
|---|---|---|
| Target workbook | path given | yes |
| Source manifests | sidecar `.manifest.json` next to each input file | yes when present |
| Prior version | `outbox/<workflow>/<previous run>/` | no |
| Threshold | `reference/assumptions.yaml`: `verification.variance_threshold_pct` | yes |

## Steps
1. Read `CPA_WORKSPACE` from `cpa-core`.
2. Run `python -m cpa verify <workbook> [--prior <prior>] [--sources <dir>]`.
   Automatic recalculation is unsupported; the command flags NOT_RECALCULATED, reads reported figures (tagged cells from the
   template map, or every numeric cell on output tabs), builds one row per figure with value,
   source file, source cell or row, as-of date, status label, recalculation check, tie-out to the
   source total, variance vs. the prior version, and a threshold flag; checks the M2 block on any
   tab whose name contains "P&L"; writes the Verification tab as the first tab; and prints a JSON
   summary whose top line reads CLEAN or N ISSUES.
3. Read the JSON result the command printed, including the separate acceptance dimensions.
   Package/preservation checks do not verify calculations or appearance. NOT_RECALCULATED remains
   a financial blocker; visual review remains NOT_REVIEWED until the analyst reviews the artifact.
   For a large workbook, read the reported sibling verification-file path; the source is not edited.
4. If CLEAN: say so in one line and continue.
5. If there are issues: list each one with tab, cell, what was expected, what was found. Do not fix
   any figure. Stop the calling workflow at "draft with issues" and notify.
6. Run `python -m cpa state record --skill cpa-verify --input <workbook> --output <workbook>
   --verification <CLEAN or "N ISSUES"> --duration <seconds>` to write the run record.

## Outputs
- A supported small workbook with a Verification tab; large workbooks get the reported sibling
  Verification workbook. Unsafe/unsupported edits stop without replacing the original.
- `logs/runs/<timestamp>_cpa-verify.json` - the run record.

## Verify
- The Verification tab's summary cell reads CLEAN or N ISSUES.
- Automatic recalculation is unsupported. Cached values and successful package checks do not
  establish zero formula errors or CLEAN; keep NOT_RECALCULATED visible.
- Every output-tab figure has a row.

## If something is wrong
- An Office preflight or preservation error -> stop and report it. Keep the original file; never
  remove macros, links, comments, signatures or controls to bypass a safety gate. Ask Billy about
  a supported export or tested template adaptation, not an analyst software installation.
- Recalculation reports formula errors -> report the cells; do not deliver the workbook.
- A figure has no source manifest -> its row shows SOURCE UNKNOWN and counts as an issue.
- The prior version is missing -> variance columns show n/a; this alone is not an issue.
- `python -m cpa verify` exits 2 (could not verify) -> stop, report the error text, and do not write
  a run record claiming success.

## Never
- Never alter a figure to make it tie.
- Never suppress a flag.
- Never mark a workbook CLEAN by hand when the command reported issues.
