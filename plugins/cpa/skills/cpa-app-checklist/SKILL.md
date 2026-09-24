---
name: cpa-app-checklist
description: Regenerate the interactive APP submission checklist PDF from reference/checklist.yaml. Run when the user says "regenerate the checklist" or the checklist spec has changed.
---

# cpa-app-checklist

## When to run
- The user says "regenerate the checklist" or has just edited `reference/checklist.yaml`.

## Inputs
| Input | Where | Required |
|---|---|---|
| Checklist spec | `reference/checklist.yaml` | yes |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. Run `python -m cpa checklist_pdf build --spec reference/checklist.yaml --out templates/ --json`.
   The command renders one live AcroForm field per spec item (a checkbox for `input: checkbox`, a
   text field for `input: text`), version-stamps the filename one higher than the last checklist PDF
   in `templates/`, and refuses to build a PDF from a spec marked `placeholder: true` unless
   `--allow-placeholder` is also given.
3. Read the JSON result: the output path and the version number.
4. Run `python -m cpa state record --skill cpa-app-checklist --input reference/checklist.yaml
   --output <templates/APP_Submission_Checklist_v<N>.pdf> --verification "built" --duration
   <seconds>` to write the run record.
5. Report the new version number and path.

## Outputs
- `templates/APP_Submission_Checklist_v<N>.pdf` - the interactive checklist: one live form field per
  spec item.
- `logs/runs/<timestamp>_cpa-app-checklist.json` - the run record.

## Verify
- Every item in `reference/checklist.yaml` has a matching live form field in the PDF.
- The version number is exactly one higher than the previous checklist PDF in `templates/`.
- The field carries the item's `fix` text as its tooltip, so the field is self-explanatory without
  the spec open beside it.

## If something is wrong
- The spec is still marked `placeholder: true` (FIXTURE, not yet swapped for her real checklist) ->
  `checklist_pdf build` refuses without `--allow-placeholder`; stop and tell the analyst the spec
  needs confirming against her real checklist before a PDF is issued. Never pass
  `--allow-placeholder` to route around that on your own judgment.
- `checklist_pdf build` exits 2 (bad or unreadable spec) -> stop and report the error text; do not
  write a run record claiming success.
- Two items in the spec resolve to the same field name -> the command refuses; stop and report the
  colliding `id`s; never rename one yourself.

## Never
- Never hand-edit the PDF instead of regenerating it from `reference/checklist.yaml`.
- Never build from a placeholder spec without telling the analyst it is still a placeholder.
- Never skip the version stamp or overwrite a previous version's file.
- Never add a benchmark input field to the checklist - the department is never given a cell to enter
  its own benchmark.
