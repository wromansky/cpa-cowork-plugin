---
name: cpa-app-deck
description: Assemble the SOM Review Committee deck for a cycle from every position with a verified P&L and a built slide. Run the day before the meeting, or when the user says "assemble the SOM deck" or "build the deck for this cycle".
---

# cpa-app-deck

## When to run
- The SOM cycle date is within one business day and at least one position's committee slide has been
  built.
- The user says "assemble the SOM deck" or names a cycle date to build.

## Inputs
| Input | Where | Required |
|---|---|---|
| Committee and Q&A slides | `outbox/app/<cycle>/<position>/{slide.pptx,qa_slide.pptx}` | yes (at least one) |
| Verified PnL manifests | `outbox/app/<cycle>/<position>/PnL.xlsx` | yes |

## Steps
1. Read `CPA_WORKSPACE` from `cpa-core`.
2. Run `python -m cpa app_slides deck --cycle <YYYY-MM-DD> --json`.
   The command finds every position under this cycle in `outbox/app/<cycle>/` and `staging/app/`,
   includes only those with a verified P&L and a built `slide.pptx`, renders an agenda slide listing
   new requests and returning positions, assembles every included slide (and each returning position's
   `qa_slide.pptx` when present) into one deck, sets the page number on every slide, and writes
   `outbox/app/<cycle>/SOM_Review_<cycle>.pptx`. Every excluded position is listed with a reason in
   `outbox/app/<cycle>/SOM_Review_<cycle>_exclusions.md`.
3. Read the JSON result. Report the deck path, the new and returning position ids included, and every
   excluded position with its exclusion code and reason.
4. If any position is excluded for `NO_SLIDE`, name the exact command from the exclusions file to build
   it (`python -m cpa app_slides position --position <id>` or `... qa --position <id>`); do not rerun
   the deck automatically — the analyst decides whether to wait for it or proceed without it.
5. Run `python -m cpa state mark cpa-app-deck <cycle> done --output <deck path>`.
6. Run `python -m cpa state record --skill cpa-app-deck --input <cycle> --output <deck path>
   --warning "<N excluded>" --duration <seconds>` to write the run record.

## Outputs
- `outbox/app/<cycle>/SOM_Review_<cycle>.pptx` — the assembled deck.
- `outbox/app/<cycle>/SOM_Review_<cycle>_exclusions.md` — every excluded position and why.

## Verify
- The agenda slide lists every new position and every returning position included in the deck.
- No excluded position appears in the deck; every excluded position appears in the exclusions file with
  a reason and a fix-up command.
- Page numbers are set on every slide.

## If something is wrong
- `app_slides deck` exits 2 (stopped) → report the error text; do not run `state mark` or write a run
  record claiming success.
- No position has a verified P&L and a built slide for this cycle → stop; report that the deck cannot
  be assembled yet; do not write an empty deck.
- The cycle date cannot be confirmed → ask the analyst for the SOM cycle date; never guess it from the
  current date.

## Never
- Never include a position without a verified P&L.
- Never change slide order or add a slide the guide does not define, without asking the analyst first.
- Never silently drop an excluded position — it always appears in the exclusions file.
- Never assemble a deck for a cycle date the analyst has not confirmed.
