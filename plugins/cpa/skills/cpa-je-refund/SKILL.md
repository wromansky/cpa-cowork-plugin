---
name: cpa-je-refund
description: Draft a ready-to-post JE refund from a located SAP misposting. Run when the user says "JE refund", "reclass this amount" or "find this misposting", or when a locate result for an amount and cost center is ready. Nothing is ever posted here.
---

# cpa-je-refund

## When to run
- The analyst asks for a JE refund or a reclass, and gives the amount, the cost center it was posted to
  and the corrected cost center.
- A `sources sap locate` result is ready for that amount, cost center and period (A12).

## Inputs
| Input | Where | Required |
|---|---|---|
| Her request | the amount, the cost center it was posted to, the corrected cost center, the reason, the fiscal period | yes |
| SAP CO line-item export | `inbox/sap/co_lineitems_<yymm>.*` (A11), manifested | yes |
| Blank JE template | her template file kept under `templates/` | yes |
| JE template map | `reference/template_maps/je_refund.yaml` (FIXTURE - confirm against her file) | yes |

## Steps
1. In the plugin checkout, resolve two absolute paths before running anything. The interpreter, by
   resolving `.venv\Scripts\python.exe` inside the checkout. The workspace, by reading `CPA_WORKSPACE` in
   cpa-core and running `.venv\Scripts\python.exe -m cpa config where` with that resolved interpreter.
   Every `.venv\Scripts\python.exe` below stands for the resolved executable, and every `inbox`,
   `staging`, `outbox`, `reference` and `logs` path below is relative to the workspace root the command
   printed, so run the rest of the steps from that root. Never hard-code either path.
2. Locate the misposting: run `.venv\Scripts\python.exe -m cpa sources sap locate --amount <amount>
   --cc <cost center> --period <yymm> --export inbox/sap/co_lineitems_<yymm>.xlsx --out
   staging/je/<je_id>/locate.json --json`. Exit 0 means exactly one line matched; exit 1 means none or
   several did - stop and ask her which line, and never pick one by eye. This reads the landed export
   only and writes nothing to SAP.
3. Draft: run `.venv\Scripts\python.exe -m cpa je_refund draft --source staging/je/<je_id>/locate.json
   --template templates/<her JE template>.xlsx --je-id <je_id> --from-cc <cost center> --to-cc <corrected
   cost center> --requested-amount <amount> --fymm <yymm> [--reason "<reason>"] [--cost-structure
   inbox/sap/co_lineitems_<yymm>.xlsx] [--as-of <YYYY-MM-DD>] --json`. The requested amount must equal the
   located amount to the cent, both cost centers must be present in the cost structure reference, and the
   draft is written to `outbox/je/<je_id>/JE_<je_id>.xlsx`. Exit 1 stopped, with nothing written.
4. Read the JSON: the cost centers, the requested amount, the source reference (document and line item),
   and the `next_step` line. `posted` is false - the draft is ready to post and has not been posted.
5. Run `.venv\Scripts\python.exe -m cpa verify outbox/je/<je_id>/JE_<je_id>.xlsx` and read the result.
6. Write the run record: `.venv\Scripts\python.exe -m cpa state record --skill cpa-je-refund --input
   staging/je/<je_id>/locate.json --output <the draft path printed in step 3> --verification
   "<CLEAN|N ISSUES>" --duration <seconds>`.

## Outputs
- `outbox/je/<je_id>/JE_<je_id>.xlsx` - the filled JE template, her source reference, a balance cell that
  must read zero, and the Verification tab.
- `logs/runs/<timestamp>_cpa-je-refund.json` - the run record.

## Verify
- `je_refund draft` exited 0 and the result reported `posted` as false.
- The requested amount equals the located amount to the cent.
- Both cost centers are present in the SAP cost structure reference.
- The draft states the source document and line item and carries the ready-to-post note.
- The balance cell reads zero after recalculation, and the Verification tab reads CLEAN or lists every
  issue.

## If something is wrong
- `locate` exits 1 -> none or several lines matched; ask her to narrow the amount, cost center or period;
  never choose a line for her.
- The located cost center is not the one she gave -> stop and report both; never change `--from-cc` to
  match the export.
- A cost center is not in the cost structure reference -> stop and report the cost center and the file;
  never invent or guess one.
- `draft` exits 1 naming an amount -> report both amounts and ask which is right; never round the request
  to make it fit.
- The template is at or above the 15 MB streaming threshold, or its template map is unreadable -> stop and
  report; never hand-edit the template in place.
- The draft fails its own post-write check -> the module removes the file; fix the input and rerun; never
  recreate the draft by hand.
- No manifest on the cost structure export and no `--as-of` given -> stop and ask her for the as-of date;
  never default it.
- Automatic workbook recalculation is unsupported -> say so in the run record warning;
  never claim the balance cell was recalculated or that the draft is post-checked.

## Never
- Never post, submit or file the JE; posting is her own click in SAP, and this skill stops at a
  ready-to-post draft.
- Never change an amount, a cost center or a fiscal period to make a check pass.
- Never invent a document number, a line item, a cost center or a TaskKey.
- Never edit the landed SAP export or the template she keeps.
- Never treat a recorded figure as posted, and never describe the draft as posted.
- Never write a draft anywhere except the draft folder this skill names.
