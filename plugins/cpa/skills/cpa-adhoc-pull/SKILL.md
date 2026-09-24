---
name: cpa-adhoc-pull
description: Answer a data-pull request with a flat table and one-page summary. Run when a request folder's brief.md reads as a data-pull ask (requested_output mentions a data pull, an export, or "what were the numbers for"), or when the user says "pull the data for this request" or "answer this data question".
---

# cpa-adhoc-pull

## When to run
- A request folder's `brief.md` has a `requested_output` that reads as a raw data pull or a
  one-page summary answer, not a built workbook (P&L, comp, or allocation).
- The user says "pull the data for <request id>" or asks a data question tied to a request folder.

## Inputs
| Input | Where | Required |
|---|---|---|
| `brief.md` | `requests/<id>/` | yes |
| `pull_inputs.json` (question, answer, sources, rows, group_by, measures) | `requests/<id>/` | yes |

## Steps
1. Read `CPA_WORKSPACE` from `cpa-core`.
2. Confirm `requests/<id>/brief.md` exists and its `requested_output` names a data pull or a
   summary answer, not a built workbook. If it names a P&L, comp, or allocation workbook, stop and
   hand off to the matching cpa-adhoc-* skill instead.
3. From `brief.md`'s `requested_output` and `scope`, identify which system supplies the data
   (Tableau, Power BI, COGNOS, MedVitals, Epic, SAP, or QGenda) and run that system's cpa-pull-*
   skill to land the export, or ask the analyst to run the pull herself when it needs her login.
4. Normalize the landed rows through the crosswalk and write `requests/<id>/pull_inputs.json`:
   the requester's question, the rows answering it, the `group_by`/`measures` for the summary
   table, and one sources entry per pull (system, report, filters, as_of) — never a row without
   its source.
5. Run `python -m cpa adhoc summary --brief requests/<id>/brief.md --inputs
   requests/<id>/pull_inputs.json`. The command writes a `Data` tab with the normalized rows and a
   `Summary` tab with the question, a group-by table over the measures, and the sources block,
   writing `requests/<id>/summary.xlsx`.
6. Run `python -m cpa verify requests/<id>/summary.xlsx --sources requests/<id>/` and read the
   result. If not CLEAN, follow cpa-verify's "If something is wrong" before continuing.
7. Report the answer and the sources it came from.
8. Run `python -m cpa state record --skill cpa-adhoc-pull --input requests/<id>/pull_inputs.json
   --output requests/<id>/summary.xlsx --verification <CLEAN or "N ISSUES"> --duration
   <seconds>` to write the run record.

## Outputs
- `requests/<id>/summary.xlsx`

## Verify
- Verification tab CLEAN.
- The requester's question and a stated answer both appear on the Summary tab.
- Every row's source system, report, filters, and as-of date are listed.

## If something is wrong
- The pull skill for the needed system does not exist yet, or needs credentials only the analyst
  has → stop; ask the analyst to run the pull and drop the export in `inbox/`, then resume at
  step 4.
- A row's department does not match a `reference/dept_crosswalk.csv` row → the crosswalk step
  raises; stop and ask the analyst for the correct department label; never drop the row silently.
- `python -m cpa adhoc summary` exits 1 (`AdhocError`) → report the error text; do not run `state
  record` claiming success.
- `requests/<id>/summary.xlsx` already exists → rerun with `--overwrite` only after confirming
  with the analyst that a rebuild is wanted; otherwise stop.

## Never
- Never fabricate a row or an answer when a pull has not landed; wait for it or ask.
- Never drop an unmatched department label silently.
- Never take a write action in the pull system; read and export only.
- Never report the summary as verified when the Verification tab is not CLEAN.
