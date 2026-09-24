---
name: cpa-bog-refresh
description: Refresh the Board of Governors (BOG) deck and workbook from this month's exports, on the fixed slide set. Run when inbox/tableau/charges_by_day, inbox/powerbi/dept_productivity and inbox/cognos/dept_financials for the fiscal month have all landed, or the user says "refresh the BOG deck".
---

# cpa-bog-refresh

## When to run
- `inbox/tableau/charges_by_day_<FYMM>.*`, `inbox/powerbi/dept_productivity_<FYMM>.*` and
  `inbox/cognos/dept_financials_<FYMM>.*` have all landed and are manifested (B1).
- The user asks to refresh the BOG deck, or names a fiscal month for it.

## Inputs
| Input | Where | Required |
|---|---|---|
| Charges by day export | `inbox/tableau/charges_by_day_<FYMM>.*` | yes |
| Department productivity export | `inbox/powerbi/dept_productivity_<FYMM>.*` | yes |
| Department financials export | `inbox/cognos/dept_financials_<FYMM>.*` | yes |
| Last cycle's deck and workbook | `templates/bog/` (default), or given explicitly | yes |
| Template map | `reference/template_maps/bog.yaml` (FIXTURE - confirm against her file) | yes |
| Variance explanations | `staging/bog/<FYMM>/explain.yaml` (figure id -> why it moved) | no |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. Run `.venv\Scripts\python.exe -m cpa state ready --json` and confirm cpa-bog-refresh is ready for
   the fiscal month before starting; when a required export is missing, stop and say which one.
3. Run `.venv\Scripts\python.exe -m cpa deck_refresh run --deck BOG --month <FYMM> [--templates
   templates/bog] [--explain staging/bog/<FYMM>/explain.yaml] --json`. It normalizes every export
   through the crosswalk, refills every data tab, writes the Deck Figures tab, updates every mapped
   figure on the fixed slide set (never adding, removing or reordering slides - checked before and
   after), regenerates speaker notes, and writes `change_log.md`. Exit 1 produced with issues (read
   `issues`, `flags` and `unexplained` from the JSON result); exit 2 stopped before writing anything -
   the stderr line names the cause (most often a missing export, a malformed template map, or a Hopkins
   assumption she has not supplied yet).
4. Read `outbox/bog/<key>/change_log.md` and report every slide that changed, every yellow flag (a
   missing metric the exports could not supply), and every unexplained variance to the analyst.
5. Run `.venv\Scripts\python.exe -m cpa verify outbox/bog/<key>/BOG_<key>_workbook.xlsx` (the workbook
   path `deck_refresh run` reported in its JSON result) and read the result.
6. Write the run record: `.venv\Scripts\python.exe -m cpa state record --skill cpa-bog-refresh --input
   inbox/tableau/charges_by_day_<FYMM>.xlsx --input inbox/powerbi/dept_productivity_<FYMM>.xlsx --input
   inbox/cognos/dept_financials_<FYMM>.xlsx --output <the deck path from step 3> --output <the workbook
   path from step 3> --verification "<CLEAN|N ISSUES>" --duration <seconds> [--needs-analyst]`.

## Outputs
- `outbox/bog/<key>/` - refreshed deck (.pptx), workbook (.xlsx, Deck Figures tab, Verification tab),
  `change_log.md`.
- `logs/runs/<timestamp>_cpa-bog-refresh.json` - the run record.

## Verify
- `deck_refresh run` never changed the slide count or slide order from last cycle's deck.
- Every figure on the Deck Figures tab carries period, status, source system, as-of date, and traces to
  the export cell or range it came from.
- A figure the exports could not supply is a yellow flag on its slide and a yellow MISSING cell, never
  estimated and never silently dropped.
- Verification tab reads CLEAN, or every issue is reported to the analyst.

## If something is wrong
- `deck_refresh run` exits 2 -> stop; report the exact stderr line (usually a missing export or a
  malformed template map); do not write a run record claiming success.
- The slide-set check reports an added, removed or reordered slide -> stop; never change the slide set
  without asking the analyst first.
- A department label in an export is unmatched -> stop; report it; the analyst adds the row to
  `reference/dept_crosswalk.csv`; never guess a mapping.

## Never
- Never add, remove or reorder a slide without asking the analyst.
- Never estimate a figure the exports cannot supply; flag it yellow instead.
- Never send, post or email the refreshed deck; it goes to `outbox/` for the analyst to review and send.
- Never guess an unexplained variance; leave it unexplained and report it rather than inventing a
  reason.
