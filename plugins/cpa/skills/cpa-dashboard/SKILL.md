---
name: cpa-dashboard
description: Build the daily cycle-and-deadline dashboard - what is due, what is missing, what is ready in outbox, and which verification flags are open. Run daily after the dispatcher, when the user asks "what's due" or "what's outstanding", or when the 07:30 weekday scheduled task calls it.
---

# cpa-dashboard

## When to run
- Scheduled, 07:30 weekdays, after the dispatcher has run.
- The user asks "what's due", "what's outstanding", or "build today's dashboard".

## Inputs
| Input | Where | Required |
|---|---|---|
| Registered cycles | logs/cycles.json (written by cpa-cycle-kickoff / cpa-rollover) | yes |
| Holidays reference | reference/holidays_jhm.csv | no |
| Business-day horizon for "due soon" | ask the analyst; default 10 | no |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. Run `python -m cpa dashboard build --json`. It writes `logs/dashboard.md` with four sections
   (Due, Missing, Ready, Open verification flags) built from the cycle registry, `cpa.state`'s
   readiness rules for the current fiscal period, submitted-vs-outstanding by department for every
   registered SOM cycle, `outbox/` contents, and every workbook whose Verification tab is missing or
   not CLEAN. Pass `--horizon <business days>` when the analyst gave one, else the default applies.
3. If the JSON result's holiday note is present (holidays file missing a fiscal year), tell the
   analyst which fiscal year is missing from `reference/holidays_jhm.csv`; "due soon" is unknown
   until it is added.
4. Read `logs/dashboard.md` and compose the morning message: what is due (with deadlines), what is
   missing, what departments have not submitted, what is ready in outbox, what verification flags
   are open. Silent on nothing when the analyst is not expecting a message; otherwise send it.
5. Write the run record: `python -m cpa state record --skill cpa-dashboard --input logs/cycles.json
   --output logs/dashboard.md --verification "<N> due, <N> ready, <N> flags open" --duration
   <seconds>`.

## Outputs
- `logs/dashboard.md` — Due / Missing / Ready / Open verification flags, one place for all four.
- The morning message (chat or notification), not a file.

## Verify
- `dashboard build` exited 0.
- Every registered cycle with a meeting date on or after today appears under Due with its materials
  deadline.
- Every SOM cycle with departments recorded appears under Missing when any of them has not
  submitted; a cycle with no departments recorded is listed as "expected departments not recorded",
  never silently skipped.

## If something is wrong
- `dashboard build` exits 1 → report the exact stderr line (usually a missing/null committee
  lead-day assumption); do not write a run record claiming success.
- A cycle shows "expected departments not recorded" → tell the analyst to re-run
  `python -m cpa dashboard register-cycle` with `--department` for that cycle; never guess the list.
- The holidays file has no rows for the current fiscal year → report it under Missing; "due soon" is
  unknown until she adds the year's observed holidays.

## Never
- Never compute a due-soon or deadline date by hand; only `cpa dashboard build` and
  `cpa dashboard register-cycle` compute those.
- Never invent a department as submitted or outstanding; read it from `dashboard outstanding`.
- Never send a message when the dispatcher has already reported the same run this cycle.
- Never edit `logs/dashboard.md` by hand; it is fully rebuilt by `dashboard build` every run.
