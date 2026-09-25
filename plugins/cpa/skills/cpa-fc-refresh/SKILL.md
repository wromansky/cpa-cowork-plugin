---
name: cpa-fc-refresh
description: Refresh the Finance Committee (FC) deck and workbook from this month's exports plus the budget workbook, on the fixed slide set. Run when inbox/tableau/charges_by_day, inbox/powerbi/dept_productivity, inbox/cognos/dept_financials and the budget workbook under outbox/budget for the fiscal month have all landed, or the user says "refresh the FC deck".
---

# cpa-fc-refresh

## When to run
- `inbox/tableau/charges_by_day_<FYMM>.*`, `inbox/powerbi/dept_productivity_<FYMM>.*`,
  `inbox/cognos/dept_financials_<FYMM>.*` and `outbox/budget/<FYMM>/Budget_Workbook_<FYMM>.xlsx` (B17,
  built by cpa-budget-workbook) have all landed and are manifested (B2).
- The user asks to refresh the FC deck, or names a fiscal month for it.

## Inputs
| Input | Where | Required |
|---|---|---|
| Charges by day export | `inbox/tableau/charges_by_day_<FYMM>.*` | yes |
| Department productivity export | `inbox/powerbi/dept_productivity_<FYMM>.*` | yes |
| Department financials export | `inbox/cognos/dept_financials_<FYMM>.*` | yes |
| Budget workbook | `outbox/budget/<FYMM>/Budget_Workbook_<FYMM>.xlsx` (built by cpa-budget-workbook) | yes |
| Last cycle's deck and workbook | `templates/fc/` (default), or given explicitly | yes |
| Template map | `reference/template_maps/fc.yaml` (FIXTURE - confirm against her file) | yes |
| Variance explanations | `staging/fc/<FYMM>/explain.yaml` (figure id -> why it moved) | no |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. Run `.venv\Scripts\python.exe -m cpa state ready --json` and confirm cpa-fc-refresh is ready for the
   fiscal month before starting; when a required export or the budget workbook is missing, stop and say
   which one - run cpa-budget-workbook first when it is the budget workbook that is missing.
3. Run `.venv\Scripts\python.exe -m cpa deck_refresh run --deck FC --month <FYMM> [--templates
   templates/fc] [--explain staging/fc/<FYMM>/explain.yaml] --json`. It normalizes every export through
   the crosswalk, refills every data tab (including the budget line from
   `outbox/budget/<FYMM>/Budget_Workbook_<FYMM>.xlsx`), writes the Deck Figures tab, updates every
   mapped figure on the fixed slide set (never adding, removing or reordering slides - checked before
   and after), regenerates speaker notes, and writes `change_log.md`. Exit 1 produced with issues (read
   `issues`, `flags` and `unexplained` from the JSON result); exit 2 stopped before writing anything -
   the stderr line names the cause (most often a missing export, a missing budget workbook, a malformed
   template map, or a Hopkins assumption she has not supplied yet).
4. Read `outbox/fc/<key>/change_log.md` and report every slide that changed, every yellow flag (a
   missing metric the exports could not supply), and every unexplained variance to the analyst.
5. Run `.venv\Scripts\python.exe -m cpa verify outbox/fc/<key>/FC_<key>_workbook.xlsx` (the workbook
   path `deck_refresh run` reported in its JSON result) and read the result.
6. Write the run record: `.venv\Scripts\python.exe -m cpa state record --skill cpa-fc-refresh --input
   inbox/tableau/charges_by_day_<FYMM>.xlsx --input inbox/powerbi/dept_productivity_<FYMM>.xlsx --input
   inbox/cognos/dept_financials_<FYMM>.xlsx --input <the budget workbook from Inputs> --output <the deck
   path from step 3> --output <the workbook path from step 3> --verification "<CLEAN|N ISSUES>"
   --duration <seconds> [--needs-analyst]`.

## Outputs
- `outbox/fc/<key>/` - refreshed deck (.pptx), workbook (.xlsx, Deck Figures tab, Verification tab),
  `change_log.md`.
- `logs/runs/<timestamp>_cpa-fc-refresh.json` - the run record.

## Verify
- `deck_refresh run` never changed the slide count or slide order from last cycle's deck.
- Every figure on the Deck Figures tab carries period, status, source system, as-of date, and traces to
  the export cell or range it came from, including the budget line traced to the budget workbook.
- A figure the exports could not supply is a yellow flag on its slide and a yellow MISSING cell, never
  estimated and never silently dropped.
- Verification tab reads CLEAN, or every issue is reported to the analyst.

## If something is wrong
- The budget workbook for the fiscal month is missing -> stop; run cpa-budget-workbook first; never
  refresh FC against a stale or missing budget workbook.
- `deck_refresh run` exits 2 -> stop; report the exact stderr line; do not write a run record claiming
  success.
- The slide-set check reports an added, removed or reordered slide -> stop; never change the slide set
  without asking the analyst first.
- A department label in an export is unmatched -> stop; report it; the analyst adds the row to
  `reference/dept_crosswalk.csv`; never guess a mapping.

## Never
- Never refresh FC without the current fiscal month's budget workbook already built.
- Never add, remove or reorder a slide without asking the analyst.
- Never estimate a figure the exports cannot supply; flag it yellow instead.
- Never send, post or email the refreshed deck; it goes to `outbox/` for the analyst to review and send.
