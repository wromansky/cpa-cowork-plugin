---
name: cpa-lookback
description: Assemble a provider lookback cohort from its business plans, clinical actuals and salary extract, then build the variance workbook and the retention deck. Run when a cohort folder appears under staging/lookback with its inputs manifested, or the user says "run the lookback for <cohort>" or "lookback deck".
---

# cpa-lookback

## When to run
- A cohort folder is complete: `staging/lookback/<cohort>/cohort.csv` plus the business plan files, the
  Epic aggregate and the SAP salary extract for that cohort have landed and are manifested (A16).
- The user asks to run, rerun or rebuild the lookback for a named cohort.

## Inputs
| Input | Where | Required |
|---|---|---|
| Cohort list | `staging/lookback/<cohort>/cohort.csv` - record_id (the MedVitals record ID), provider_label, department, sap_provider_id, epic_provider_id and the plan and actual start and end dates | yes |
| Epic aggregate for the cohort | `inbox/epic/<report>_<cohort>.*` (A9) | yes |
| MedVitals business plan per provider | `inbox/medvitals/bp_<record_id>.*` (A8) | yes |
| SAP salary extract | `inbox/sap/salary_<cohort>.*` (A10) | yes |
| Sidecar manifest on every input | `<file>.manifest.json`, with the source system and the as-of date | yes |
| Offer letter PDFs | dropped by her in `staging/lookback/<cohort>/` | no |
| Prior lookback workbook | `staging/lookback/<cohort>/prior_lookback.xlsx`, or the path given with `--prior` | no |
| Provider narrative | `staging/lookback/<cohort>/narrative/<record_id>.md`, drafted from the recommendation letters | no |

## Steps
1. In the plugin checkout, resolve two absolute paths before running anything. The interpreter, by
   resolving `.venv\Scripts\python.exe` inside the checkout. The workspace, by reading `CPA_WORKSPACE` in
   cpa-core and running `.venv\Scripts\python.exe -m cpa config where` with that resolved interpreter.
   Every `.venv\Scripts\python.exe` below stands for the resolved executable, and every `inbox`,
   `staging`, `outbox`, `reference` and `logs` path below is relative to the workspace root the command
   printed, so run the rest of the steps from that root. Never hard-code either path.
2. Run `.venv\Scripts\python.exe -m cpa state ready --json`. When cpa-lookback is not listed for this
   cohort, say why - an input has not landed, or this cohort has already been run against these inputs -
   and continue only when the analyst asked for a rerun.
3. Validate the Epic aggregate before anything reads it: run
   `.venv\Scripts\python.exe -m cpa sources epic validate inbox/epic/<report>_<cohort>.xlsx --json`.
   Exit 3 means patient-level data was quarantined and exit 1 means the layout failed; stop on either
   and report the message.
4. Confirm every input carries its sidecar manifest with the source system and the as-of date. Write one
   for any input that landed without it: run `.venv\Scripts\python.exe -m cpa manifest write <file>
   --source <system> --report "<report>" --as-of <YYYY-MM-DD>`. The run stops without a manifest,
   because an as-of date is never invented.
5. When she has dropped offer letters, transcribe the compensation terms each letter states into
   `staging/lookback/<cohort>/letters.csv` (columns record_id, field, offer_value, source_file, page;
   field is the offer_base or offer_supplements line), then write its manifest with
   `.venv\Scripts\python.exe -m cpa manifest write staging/lookback/<cohort>/letters.csv --source
   "offer letter" --report "<provider> offer letter" --as-of <the letter's own date>`. A term the letter
   does not state gets no row and never a value.
6. Assemble: run `.venv\Scripts\python.exe -m cpa lookback assemble --cohort <cohort>
   [--prior <prior workbook>] --json`. It joins on the MedVitals record ID, detects the plan and actual
   periods, prorates with its label, and writes `joined.csv`, `findings.json` and `join_report.md` under
   `staging/lookback/<cohort>/`. Exit 2 is a null assumption, exit 3 a data stop; read the message.
7. Read `join_report.md` and the findings, and list every gap, placeholder and discrepancy for the
   analyst. A difference between the business plan, the offer letter, the prior lookback and the
   department is listed - it is never resolved here.
8. Build the workbook: run `.venv\Scripts\python.exe -m cpa lookback workbook --cohort <cohort> --json`.
   It writes `Lookback_<cohort>.xlsx` with live variance formulas, yellow formula-ready placeholders that
   each carry a note, the M2 block and a Verification tab. Exit 2 - report the assumption key it names.
9. Build the deck: run `.venv\Scripts\python.exe -m cpa lookback deck --cohort <cohort> --json`. It reads
   every number from its workbook cell and writes `Lookback_<cohort>.pptx` with retention framing and one
   support-plan slide per provider.
10. Run `.venv\Scripts\python.exe -m cpa verify <the workbook path step 8 printed>` and read the result.
    Add `--prior <the prior lookback workbook step 6 used>` only when step 6 assembled against a prior
    lookback workbook - the staged `prior_lookback.xlsx` it picked up by default, or the one passed with
    `--prior`; omit the flag when there was none, so the variance column never compares against a prior
    that was not used.
11. Write the run record: `.venv\Scripts\python.exe -m cpa state record --skill cpa-lookback --input
    staging/lookback/<cohort>/cohort.csv --output <the workbook path printed in step 8> --output <the deck
    path printed in step 9> --verification "<CLEAN|N ISSUES>" --duration <seconds>`.

## Outputs
- `staging/lookback/<cohort>/joined.csv`, `findings.json`, `join_report.md` - the join, every open finding
  and the assembly report, each with its own manifest.
- `outbox/lookback/<cohort>/Lookback_<cohort>.xlsx` - plan versus actual per provider with the proration
  label, live variance formulas, the yellow placeholders, the M2 block and the Verification tab.
- `outbox/lookback/<cohort>/Lookback_<cohort>.pptx` - summary and one retention-support slide per provider.
- `logs/runs/<timestamp>_cpa-lookback.json` - the run record.

## Verify
- `lookback assemble` exited 0 and every provider on `cohort.csv` has rows in `joined.csv`.
- Every prorated figure carries its label, and a withheld proration states its reason.
- Every gap, placeholder and discrepancy is listed for the analyst; none was resolved or dropped.
- Every yellow placeholder has a note naming what is missing and which source supplies it.
- Every figure in the deck equals its workbook cell.
- The workbook Verification tab reads CLEAN, or every issue is listed and reported.

## If something is wrong
- An input has no sidecar manifest -> write it from the export's own provenance, then rerun; never
  invent an as-of date and never pass a guessed one.
- `assemble` exits 3 naming a file or a column -> fix or land that input; never edit `cohort.csv` to make
  a provider fit and never rename a column to match.
- An unmatched department label -> the analyst adds it to `reference/dept_crosswalk.csv`; never guess a
  mapping.
- A proration is withheld -> report the stated reason (a missing period bound, an end before its start, or
  an actual period longer than the plan); never cap or force a factor.
- `workbook` or `deck` exits 2 -> report the assumption key it names and stop; never enter a value for it
  in `assumptions.yaml` and never suggest one.
- The deck stops on framing or on a number that differs from its cell -> she rewrites the narrative as
  retention support; never reword it to get past the check.
- Automatic recalculation is unsupported -> say so in the run record warning; never claim a
  recalculated workbook or a clean verification.

## Never
- Never resolve a discrepancy silently; every one is listed open for the analyst.
- Never present the lookback as a performance review or an evaluation of a provider; it is retention
  support.
- Never estimate a missing metric; it stays a flagged yellow placeholder with its note.
- Never put fringe into TCC; TCC is base salary plus supplements.
- Never state a collections figure without saying whether it is gross or net.
- Never invent an as-of date, a period bound, a TaskKey or an offer letter term.
- Never guess an unmatched department label.
