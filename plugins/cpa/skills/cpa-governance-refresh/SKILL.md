---
name: cpa-governance-refresh
description: Refresh the Clinical Governance deck and workbook from the fiscal month's exports, on the fixed slide set, twice-monthly per the registered cycle. Run when the exports `reference/template_maps/gov.yaml` names have landed (B14's governance sources are [UNCONFIRMED]; while the map is still the fixture it reads inbox/tableau/charges_by_day and inbox/powerbi/dept_productivity) and the governance cycle is due, or the user says "refresh governance deck" or "refresh the governance deck".
---

# cpa-governance-refresh

## When to run
- The twice-monthly governance cycle registered in `logs/cycles.json` (cpa-cycle-kickoff /
  cpa-dashboard) is due and the exports `reference/template_maps/gov.yaml` names for the fiscal month
  have all landed and are manifested (B14). While that map is still the fixture it names
  `inbox/tableau/charges_by_day_<FYMM>.*` and `inbox/powerbi/dept_productivity_<FYMM>.*`.
- The user asks to refresh the governance deck, or names an output date for it.

## Inputs
| Input | Where | Required |
|---|---|---|
| Governance exports (fiscal month) | the paths `reference/template_maps/gov.yaml` names - in the shipped fixture map, `inbox/tableau/charges_by_day_<FYMM>.*` and `inbox/powerbi/dept_productivity_<FYMM>.*` | yes |
| Clinical Governance source systems | `[UNCONFIRMED]` (FPA inventory F8, build-list B14): read them from her recent governance deck and confirm the export list with her; never assume a source | no |
| Last cycle's deck and workbook | `templates/governance/` (default), or given explicitly | yes |
| Template map | `reference/template_maps/gov.yaml` (FIXTURE - confirm against her file) | yes |
| Output date (GOV only) | given, or today | no |
| Variance explanations | `staging/governance/<date>/explain.yaml` (figure id -> why it moved) | no |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. Run `.venv\Scripts\python.exe -m cpa state ready --json` and confirm the required exports for the
   fiscal month have landed before starting; when one is missing, stop and say which one.
3. Run `.venv\Scripts\python.exe -m cpa deck_refresh run --deck GOV --month <FYMM> [--date
   <YYYY-MM-DD>] [--templates templates/governance] [--explain
   staging/governance/<date>/explain.yaml] --json`. It normalizes every export through the crosswalk,
   refills every data tab, writes the Deck Figures tab, updates every mapped figure on the fixed slide
   set (never adding, removing or reordering slides - checked before and after), regenerates speaker
   notes, and writes `change_log.md`. Exit 1 produced with issues (read `issues`, `flags` and
   `unexplained` from the JSON result); exit 2 stopped before writing anything - the stderr line names
   the cause (most often a missing export, a malformed template map, or a Hopkins assumption she has
   not supplied yet).
4. Read `outbox/governance/<key>/change_log.md` and report every slide that changed, every yellow flag
   (a missing metric the exports could not supply), and every unexplained variance to the analyst.
5. Run `.venv\Scripts\python.exe -m cpa verify outbox/governance/<key>/Governance_<key>_workbook.xlsx`
   (the workbook path `deck_refresh run` reported in its JSON result) and read the result.
6. Write the run record: `.venv\Scripts\python.exe -m cpa state record --skill cpa-governance-refresh
   --input inbox/tableau/charges_by_day_<FYMM>.xlsx --input inbox/powerbi/dept_productivity_<FYMM>.xlsx
   --input <one more for every further export the confirmed map names> --output <the deck path from step
   3> --output <the workbook path from step 3> --verification "<CLEAN|N ISSUES>" --duration <seconds>
   [--needs-analyst]`.

## Outputs
- `outbox/governance/<key>/` - refreshed deck (.pptx), workbook (.xlsx, Deck Figures tab, Verification
  tab), `change_log.md`.
- `logs/runs/<timestamp>_cpa-governance-refresh.json` - the run record.

## Verify
- `deck_refresh run` never changed the slide count or slide order from last cycle's deck.
- Every figure on the Deck Figures tab carries period, status, source system, as-of date, and traces to
  the export cell or range it came from.
- A figure the exports could not supply is a yellow flag on its slide and a yellow MISSING cell, never
  estimated and never silently dropped.
- Verification tab reads CLEAN, or every issue is reported to the analyst.

## If something is wrong
- A source the refresh needs is not in `reference/template_maps/gov.yaml` yet (B14's governance sources
  are `[UNCONFIRMED]`) -> stop and ask her for the report and its inbox folder; never guess a source
  system, and never add one to the map yourself.
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
- Never run the refresh against exports from a fiscal month other than the one requested.
