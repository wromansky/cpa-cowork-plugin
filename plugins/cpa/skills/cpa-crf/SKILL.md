---
name: cpa-crf
description: Build this period's CRF commitment report from the COGNOS CRF export and roll last period's commitments forward. Run when inbox/cognos/crf_<FYMM> lands, or the user says "CRF report", "CRF" or "roll the commitments forward".
---

# cpa-crf

## When to run
- The CRF export `inbox/cognos/crf_<FYMM>.*` lands (A6) and is manifested.
- The user asks for the CRF report, or to roll the commitments forward for a fiscal month.

## Inputs
| Input | Where | Required |
|---|---|---|
| COGNOS CRF export | `inbox/cognos/crf_<FYMM>.*` (A6) | yes |
| Last period's CRF report | `outbox/crf/<prior FYMM>/CRF_<prior FYMM>.xlsx`, or the path the analyst gives | yes when last period's report exists |
| Fiscal period | inferred from the export's filename, or given with `--period` | no |

## Steps
1. In the plugin checkout, resolve two absolute paths before running anything. The interpreter, by
   resolving `.venv\Scripts\python.exe` inside the checkout. The workspace, by reading `CPA_WORKSPACE` in
   cpa-core and running `.venv\Scripts\python.exe -m cpa config where` with that resolved interpreter.
   Every `.venv\Scripts\python.exe` below stands for the resolved executable, and every `inbox`,
   `staging`, `outbox`, `reference` and `logs` path below is relative to the workspace root the command
   printed, so run the rest of the steps from that root. Never hard-code either path.
2. Run `.venv\Scripts\python.exe -m cpa state ready --json`. When cpa-crf is not listed for this fiscal
   month, say why - the export has not landed, or this period has already been run against it - and
   continue only when the analyst asked for a rerun.
3. Validate the export before reading it: run `.venv\Scripts\python.exe -m cpa sources cognos validate
   inbox/cognos/crf_<FYMM>.xlsx --dataset crf --json`. Exit 1 is a failed layout or an unreadable file,
   exit 3 is a quarantine; stop on either and report the message.
4. Build: run `.venv\Scripts\python.exe -m cpa crf build --export inbox/cognos/crf_<FYMM>.xlsx
   [--prior outbox/crf/<prior FYMM>/CRF_<prior FYMM>.xlsx] [--period <yymm>] --json`. It rolls last
   period's Commitments sheet forward and writes this period's report with a Verification tab. Exit 1
   stopped; read the message before assuming anything was written.
5. Read the JSON: the period, the Open and Closed counts, the commitments that are newly closed, the new
   ones, and the Open total. Report every commitment that was Open last period and is absent from this
   period's export - it is marked Closed with a note saying why, never dropped.
6. Report every Open row whose amount this period's export did not supply: its amount cell is filled
   yellow, the row carries a missing note, and the row is left out of the total. It is not a zero.
7. Run `.venv\Scripts\python.exe -m cpa verify outbox/crf/<FYMM>/CRF_<FYMM>.xlsx` and read the result.
8. Write the run record: `.venv\Scripts\python.exe -m cpa state record --skill cpa-crf --input
   inbox/cognos/crf_<FYMM>.xlsx --output <the report path printed in step 4> --verification
   "<CLEAN|N ISSUES>" --warning "<missing commitment amounts: N>" --duration <seconds>`.

## Outputs
- `outbox/crf/<fymm>/CRF_<fymm>.xlsx` - the Commitments sheet (Provider, Department, Compensation Package,
  Startup Funds, Commitment Amount, Status, Note) and the Verification tab.
- `logs/runs/<timestamp>_cpa-crf.json` - the run record.

## Verify
- `crf build` exited 0.
- Every commitment in last period's report is present, or explicitly Closed with a note saying it left the
  export; none was dropped and none was closed for any other reason.
- The Open total is the sum of the Open rows whose amount the export supplied, and the count of rows
  missing an amount is reported separately.
- Every department label passed the crosswalk; no unmatched label was guessed.
- The Verification tab reads CLEAN, or every issue is listed and reported.

## If something is wrong
- The prior report is rejected -> it is not a report this tool wrote, or its Commitments header differs;
  report which; never rebuild the prior month by hand.
- The export fails validation -> stop and land a fresh A6 export; never edit or re-save the export file.
- An unmatched department label -> the analyst adds it to `reference/dept_crosswalk.csv`; never guess a
  mapping.
- No prior report is available for a month that has one -> stop and ask for it; without the prior file,
  last period's commitments are not represented in the roll-forward.
- An amount is missing for an Open row -> report it as missing; never enter an amount the export does not
  carry.
- An amount is missing and the build stops naming the brand flag-yellow key -> report that key and stop;
  never enter a value for it in `assumptions.yaml`, and never drop the row to get past it.
- The total does not tie to the export -> report both figures and the rows between them; never adjust a row
  to make the report tie.
- Automatic recalculation is unsupported -> say so in the run record warning; never claim a
  recalculated workbook.

## Never
- Never post, send or write to a source system.
- Never coerce a missing commitment amount to zero, and never estimate one.
- Never drop a prior commitment; it is present or explicitly closed.
- Never edit the COGNOS export or the prior report to make a figure tie.
- Never guess an unmatched department label.
- Never report CLEAN without having read the Verification tab result.
