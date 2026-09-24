---
name: cpa-adhoc-allocation
description: Build a cost allocation and funds flow workbook with live weight cells for an ad hoc request. Run when a request folder's brief.md reads as an allocation ask (requested_output mentions cost allocation, funds flow, or split), or when the user says "build the allocation model" or "rerun the split" for a request.
---

# cpa-adhoc-allocation

## When to run
- A request folder's `brief.md` has a `requested_output` that reads as a cost allocation or funds
  flow model.
- The user says "build the allocation model for <request id>" or "rerun the split with new
  weights".

## Inputs
| Input | Where | Required |
|---|---|---|
| `brief.md` | `requests/<id>/` | yes |
| `allocation_inputs.json` (period, status, source, as_of, departments, variants) | `requests/<id>/` | yes |

## Steps
1. Read `CPA_WORKSPACE` from `cpa-core`.
2. Confirm `requests/<id>/brief.md` exists and its `requested_output` names an allocation or
   funds-flow ask. If it names something else, stop and hand off to the matching cpa-adhoc-* skill
   instead.
3. If `requests/<id>/allocation_inputs.json` is missing or incomplete, ask the analyst for the
   confirmed pool, weights, and (for a net-basis variant) the collection definition — never invent
   a weight or a definition (hard rule 15).
4. Run `python -m cpa adhoc allocation --brief requests/<id>/brief.md --inputs
   requests/<id>/allocation_inputs.json`. The command writes one unlocked weight cell per
   department per variant and one unlocked pool cell; every department's allocation cell is a
   live formula dividing that department's weight by the sum over the variant's whole weight
   range, so changing any weight cell recalculates every department; a tech-transfer or
   drug-revenue adjustment term is folded into the same formula when the variant carries one; each
   collections column header states "Net collections (<definition>)" or "Gross collections
   (<definition>)".
5. Run `python -m cpa verify requests/<id>/Allocation.xlsx --sources requests/<id>/` and read the
   result. If not CLEAN, follow cpa-verify's "If something is wrong" before continuing.
6. Report each variant's departments, the pool amount, and each collections definition.
7. Run `python -m cpa state record --skill cpa-adhoc-allocation --input
   requests/<id>/allocation_inputs.json --output requests/<id>/Allocation.xlsx --verification
   <CLEAN or "N ISSUES"> --duration <seconds>` to write the run record.

## Outputs
- `requests/<id>/Allocation.xlsx`

## Verify
- Verification tab CLEAN.
- Every department's allocation cell is a formula referencing the variant's shared weight range,
  not a value.
- Every collections column header states its definition.

## If something is wrong
- A variant has `basis: net` and no `definition` → `adhoc allocation` raises `InputSpecError`;
  stop and ask the analyst for the net collection definition; never guess one.
- A department in `allocation_inputs.json` does not match a `reference/dept_crosswalk.csv` row →
  the command raises; stop and ask the analyst for the correct department label.
- `python -m cpa adhoc allocation` exits 1 (`AdhocError`) → report the error text; do not run
  `state record` claiming success.
- `requests/<id>/Allocation.xlsx` already exists → rerun with `--overwrite` only after confirming
  with the analyst that a rebuild is wanted; otherwise stop.

## Never
- Never write a department's allocation as a fixed value instead of a live formula.
- Never leave a net collections figure without stating its definition.
- Never resolve a weight or pool disagreement between stakeholders silently; ask.
- Never report the model as verified when the Verification tab is not CLEAN.
