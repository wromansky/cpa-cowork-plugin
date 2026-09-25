---
name: cpa-budget-workbook
description: Rebuild the budget workbook from the SAP CO line-item export, keeping every row and all ten cost structure columns. Run when the fiscal month's SAP CO line-item export lands in inbox/sap, or the user says "rebuild the budget workbook" or "budget workbook for this month".
---

# cpa-budget-workbook

## When to run
- `inbox/sap/co_lineitems_<FYMM>.*` lands (A11) and manifested.
- The user asks to rebuild the budget workbook, or names a fiscal month for it.

## Inputs
| Input | Where | Required |
|---|---|---|
| SAP CO line-item export | `inbox/sap/co_lineitems_<FYMM>.*` (A11), manifested | yes |
| Fiscal period | parsed from the export filename, or given explicitly | no |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. Run `.venv\Scripts\python.exe -m cpa state ready --json` and confirm cpa-budget-workbook is ready
   for the fiscal month before starting; when it is not, stop and say what is missing.
3. Build: run `.venv\Scripts\python.exe -m cpa budget_workbook build --export
   inbox/sap/co_lineitems_<FYMM>.xlsx [--fymm <yymm>] --json`. It streams the export (bigxlsx) and
   writes `outbox/budget/<fymm>/Budget_Workbook_<fymm>.xlsx` with Monthly Line Items and Year Line
   Items layouts, every row and all ten cost structure columns kept, plus its own Verification tab.
   Exit 1 stopped; read the JSON result and report the reason.
4. Check no row was dropped before verifying: run `.venv\Scripts\python.exe -m cpa bigxlsx count <the
   built workbook path from step 3> --sheet "Monthly Line Items"`. That tab holds one header row and
   then the `row_count` source rows step 3's JSON result reported, so it must count one row more than
   that `row_count`; a difference is a dropped row, never a rounding note.
5. Run `.venv\Scripts\python.exe -m cpa verify outbox/budget/<fymm>/Budget_Workbook_<fymm>.xlsx` and
   read the result.
6. Write the run record: `.venv\Scripts\python.exe -m cpa state record --skill cpa-budget-workbook
   --input inbox/sap/co_lineitems_<FYMM>.xlsx --output <the built workbook path from step 3>
   --verification "<CLEAN|N ISSUES>" --duration <seconds>`.

## Outputs
- `outbox/budget/<fymm>/Budget_Workbook_<fymm>.xlsx` - Monthly and Year Line Items, all ten cost
  structure columns, Verification tab.
- `logs/runs/<timestamp>_cpa-budget-workbook.json` - the run record.

## Verify
- `budget_workbook build` exited 0.
- The workbook's row count equals the export's row count; no row dropped. `Monthly Line Items` holds
  the `row_count` source rows `budget_workbook build` reported, above its one header row.
- All ten cost structure columns are present on both layouts.
- Verification tab reads CLEAN, or every issue is listed and reported to the analyst.

## If something is wrong
- `budget_workbook build` exits 1 -> stop; report the exact JSON `issues` list; do not write a run
  record claiming success.
- Row count in the workbook does not equal the export's row count -> stop; this is a dropped row, never
  a rounding note; report it and do not proceed to verify.
- A cost structure column is missing from the export -> stop and ask the analyst; never fabricate a
  column of zeros.

## Never
- Never drop a row from the export; the workbook's row count always equals the export's.
- Never drop or rename a cost structure column; all ten are kept on every layout.
- Never load the export whole; `budget_workbook build` streams it, and this skill never opens it in
  another tool first.
- Never report CLEAN without having actually read the Verification tab result.
