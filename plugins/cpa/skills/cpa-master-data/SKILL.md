---
name: cpa-master-data
description: Refresh the departmental master data workbook's Load tab from the Power BI export and reconcile it against Trend Department. Run when the fiscal month's departmental productivity export lands in inbox/powerbi, or the user says "refresh master data" or "rerun master data".
---

# cpa-master-data

## When to run
- `inbox/powerbi/dept_productivity_<FYMM>.*` lands (A4) and manifested.
- The user asks to refresh master data, or names a fiscal month for it.

## Inputs
| Input | Where | Required |
|---|---|---|
| Master data workbook (Load + Trend Department tabs) | `reference/master_data.xlsx`, or the path the analyst gives | yes |
| Power BI departmental export | `inbox/powerbi/dept_productivity_<FYMM>.*` (A4), manifested | yes |
| Shared key columns, measure columns, department key | given; the command requires all three and never infers them | yes |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. Run `.venv\Scripts\python.exe -m cpa state ready --json` and confirm cpa-master-data is ready for
   the fiscal month before starting.
3. Refresh: run `.venv\Scripts\python.exe -m cpa master_data refresh --workbook <workbook> --export
   inbox/powerbi/dept_productivity_<FYMM>.xlsx [--export-sheet <sheet>] --keys <k1,k2,...> --measures
   <m1,m2,...> --dept-key <key> [--crosswalk reference/dept_crosswalk.csv] [--tolerance-abs <n>]
   [--tolerance-pct <n>] [--period-start <YYYY-MM-DD> --period-end <YYYY-MM-DD>] [--no-recalc] --out
   staging/master_data/<fymm>_diff.csv --json`. It refuses to write past the Load tab refresh when a
   department label is unmatched (exit before comparing). Exit 0 tied, 1 differences or findings
   listed, 2 argument error.
4. Read the JSON result (`tied`, `differences`, `only_in_a`, `only_in_b`, `notes`, `paste_findings`,
   `date_findings`, `recalc_note`). When Load and Trend Department do not reconcile within tolerance,
   list every difference and one-sided row from `staging/master_data/<fymm>_diff.csv`, plus every note
   (blank-key or duplicate-key rows never joined); never resolve one silently or by editing the
   workbook by hand.
5. Run `.venv\Scripts\python.exe -m cpa verify <workbook>` and read the result.
6. Write the run record: `.venv\Scripts\python.exe -m cpa state record --skill cpa-master-data --input
   inbox/powerbi/dept_productivity_<FYMM>.xlsx --output <workbook> --verification "<tied|N
   differences>" --duration <seconds>`.

## Outputs
- `<workbook>` - Load tab refreshed in place; Trend Department unchanged.
- `staging/master_data/<fymm>_diff.csv` - every listed difference or one-sided row, when the tabs did
  not tie.
- `logs/runs/<timestamp>_cpa-master-data.json` - the run record.

## Verify
- `master_data refresh` exited 0 or 1 with every difference and every unmatched row listed; never a
  silent partial reconciliation.
- Every department label in the export matched the crosswalk before comparing.
- Verification tab on the workbook reads CLEAN, or every issue is reported.

## If something is wrong
- An unmatched department label -> `master_data refresh` prints the unmatched labels and exits 1
  before comparing anything (nothing past the Load tab refresh is written) -> stop; report them; the
  analyst adds the missing rows to `reference/dept_crosswalk.csv`; never guess a mapping.
- Exit 2 is an argument error (for example `--tolerance-abs` without `--tolerance-pct`) -> stop and
  report the exact message; do not write a run record claiming success.
- Load and Trend Department do not reconcile within tolerance -> report every listed difference from
  `staging/master_data/<fymm>_diff.csv`; never pick a side or average the two.
- Automatic recalculation is unsupported. Carry `recalc_note` in the run record warning and stop
  before relying on formula results. Never use an external engine or claim recalculation succeeded.

## Never
- Never resolve a Load-vs-Trend difference silently; every difference is listed, never picked or
  averaged.
- Never write past the Load tab refresh when a department label is unmatched.
- Never edit the Trend Department tab; it is the comparison baseline, not an output.
- Never hand-edit the workbook to make two tabs agree; only `master_data refresh` writes to it.
