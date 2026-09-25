---
name: cpa-app-slide
description: Build the APP committee slide for a new position, or the returning-position Q&A slide, from a verified P&L. Run after cpa-app-pnl builds and verifies a position's P&L, or when the user says "build the slide for this position" or "build the Q&A slide for this position".
---

# cpa-app-slide

## When to run
- cpa-app-pnl marks a position's P&L done and verified CLEAN.
- The analyst supplies the business need statement for a new position, or answers to a returning
  position's standing questions.
- The user says "build the slide for <position>" or "build the Q&A slide for <position>".

## Inputs
| Input | Where | Required |
|---|---|---|
| Verified `PnL.xlsx` | `outbox/app/<cycle>/<position>/` | yes |
| `pnl_flags.json`, `pnl_inputs.json` | `staging/app/<position>/` | yes |
| `slide_inputs.json` (business_need) | `staging/app/<position>/` | yes for a new-position slide |
| `qa_inputs.json` (questions, each with status and summary) | `staging/app/<position>/` | yes for a Q&A slide |

## Steps
1. Read `CPA_WORKSPACE` from `cpa-core`.
2. Confirm `outbox/app/<cycle>/<position>/PnL.xlsx` exists and its manifest carries a verification
   record. If not, stop and run cpa-app-pnl first.
3. For a new-position committee slide: ask the analyst for the business need statement and write
   `staging/app/<position>/slide_inputs.json` as `{"business_need": "<her exact wording>"}` — never
   paraphrase or infer it (hard rule 15).
4. Run `python -m cpa app_slides position --position <position_id>`.
   The command reads the PnL's own manifest figures for JHU Contribution Margin and Division
   Surplus/Deficit, every SullivanCotter statement and flag from `pnl_flags.json`, builds the
   committee slide with a yellow flag box for anything missing, writes speaker notes naming only the
   flagged metrics, self-checks the format lint, and writes `outbox/app/<cycle>/<position>/slide.pptx`.
5. For a returning position: ask the analyst for the status (ANSWERED, PARTIAL, NOT ANSWERED, or
   PENDING) and summary of every standing question — never infer status from reply text (hard rule 15)
   — and write `staging/app/<position>/qa_inputs.json`. Then run `python -m cpa app_slides qa
   --position <position_id>`, which writes `outbox/app/<cycle>/<position>/qa_slide.pptx`.
6. Run `python -m cpa state mark cpa-app-slide <position_id> done --output <slide path>`.
7. Report the slide's path and every flag it carries.
8. Run `python -m cpa state record --skill cpa-app-slide --input <slide_inputs.json or qa_inputs.json
   path> --output <slide path> --duration <seconds>` to write the run record.

## Outputs
- `outbox/app/<cycle>/<position>/slide.pptx` — committee slide (new positions).
- `outbox/app/<cycle>/<position>/qa_slide.pptx` — returning-position Q&A slide.

## Verify
- The generated slide passed its own format lint (the command raises rather than writing an unclean
  file).
- Every named row and benchmark statement on the slide matches the PnL's own manifest figures or
  `pnl_flags.json` verbatim — never recomputed here.
- Every question on a Q&A slide appears exactly once, tagged with its status.

## If something is wrong
- `app_slides position` or `qa` exits 2 (stopped) → report the error text; do not run `state mark` or
  write a run record claiming success.
- `slide_inputs.json` is missing or `business_need` is blank → stop; ask the analyst for the exact
  wording; never fabricate it.
- A question's `question_id` repeats in `qa_inputs.json` → stop; ask the analyst to correct the file;
  never silently drop the duplicate.
- A named row or benchmark is missing from the PnL manifest → it renders as a yellow flag box on the
  slide, never as a blank space or an estimated number.

## Never
- Never bury a flag in speaker notes; every flag gets a yellow box on the slide itself.
- Never recompute a figure the PnL manifest already recorded; read it verbatim.
- Never infer a Q&A status or summary from a department's reply text; the analyst supplies it.
- Never build a slide for a position whose P&L manifest has no verification record.
