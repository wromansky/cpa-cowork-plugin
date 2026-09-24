---
name: cpa-adhoc-pnl
description: Build a department or division P&L workbook for an ad hoc request. Run when a request folder's brief.md reads as a P&L ask (requested_output mentions a P&L, margin, or department/division financials), or when the user says "build the P&L for this request" or names a requests/<id> folder.
---

# cpa-adhoc-pnl

## When to run
- A request folder's `brief.md` (written by intake) has a `requested_output` that reads as a
  department or division P&L.
- The user says "build the P&L for <request id>" or pastes a request's brief and asks for a P&L.

## Inputs
| Input | Where | Required |
|---|---|---|
| `brief.md` | `requests/<id>/` | yes |
| `pnl_inputs.json` (period, status, source, as_of, departments, activity) | `requests/<id>/` | yes |

## Steps
1. Read `CPA_WORKSPACE` from `cpa-core`.
2. Confirm `requests/<id>/brief.md` exists and its `requested_output` names a P&L. If it names
   something else, stop and hand off to the matching cpa-adhoc-* skill instead.
3. If `requests/<id>/pnl_inputs.json` is missing or incomplete, ask the analyst for the confirmed
   revenue, compensation, expense, and tax figures for the period — never invent a figure
   (hard rule 15).
4. Run `python -m cpa adhoc pnl --brief requests/<id>/brief.md --inputs
   requests/<id>/pnl_inputs.json`. The command normalizes the department through the crosswalk,
   writes revenue/compensation/expense/tax as line items with `=SUM(...)` subtotal formulas and a
   `Margin` formula (never a value), labels collections gross or net, adds the M2 activity block,
   and attaches the Verification tab itself, writing `requests/<id>/PnL.xlsx`.
5. Run `python -m cpa verify requests/<id>/PnL.xlsx --sources requests/<id>/` and read the result.
   If not CLEAN, follow cpa-verify's "If something is wrong" before continuing.
6. Report the margin figure, the period, and any flags raised.
7. Run `python -m cpa state record --skill cpa-adhoc-pnl --input requests/<id>/pnl_inputs.json
   --output requests/<id>/PnL.xlsx --verification <CLEAN or "N ISSUES"> --duration <seconds>` to
   write the run record.

## Outputs
- `requests/<id>/PnL.xlsx`

## Verify
- Verification tab CLEAN.
- Margin and subtotal cells are formulas, not values.
- Every collections figure is labelled "Collections (gross)" or "Collections (net)".

## If something is wrong
- The department in `brief.md` does not match a `reference/dept_crosswalk.csv` row →
  `adhoc pnl` raises; stop and ask the analyst for the correct department label; never guess one.
- `pnl_inputs.json` is missing a required key → the command names it; ask the analyst for that
  figure rather than filling in a placeholder value.
- `python -m cpa adhoc pnl` exits 1 (`AdhocError`) → report the error text; do not run `state
  record` claiming success.
- `requests/<id>/PnL.xlsx` already exists → rerun with `--overwrite` only after confirming with the
  analyst that a rebuild is wanted; otherwise stop.

## Never
- Never include fringe in TCC-adjacent compensation figures.
- Never write a figure without its period, status, source system, and as-of date.
- Never estimate or omit a missing narrative-relevant metric; flag it yellow instead.
- Never report the margin as verified when the Verification tab is not CLEAN.
