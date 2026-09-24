---
name: cpa-reminders
description: Draft reminder emails to departments with an outstanding submission or an unanswered committee question. Run on the per-cycle reminder schedule (08:30 Mon and Thu), when the user asks who still owes materials, or when cpa-cycle-kickoff's reminder schedule calls for one.
---

# cpa-reminders

## When to run
- The scheduled reminder task (08:30 Mon and Thu) reaches a date on a cycle's
  `outbox/app/<cycle_date>/reminder_schedule.md` written by cpa-cycle-kickoff.
- The user asks who still owes materials or requests draft reminders.

## Inputs
| Input | Where | Required |
|---|---|---|
| Open SOM cycles and cycle dates | `logs/cycles.json` | yes |
| Reminder schedule | `outbox/app/<cycle_date>/reminder_schedule.md` (cpa-cycle-kickoff) | yes |
| Outstanding/submitted departments and cycle deadline | `python -m cpa dashboard outstanding --cycle <date> --committee som --json` | yes |
| Unanswered committee questions | Prior cycle's deck notes; ask the analyst if status is unclear | no |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core. Start a timer for the run.
2. Run `python -m cpa dashboard build --json` to refresh the dashboard summary, then read `logs/cycles.json` with the workspace file-read capability to enumerate registered SOM cycles whose meeting date has not passed. `dashboard build --json` reports summary counts, not a cycle list. Check each cycle's `reminder_schedule.md`; normally run only cycles whose schedule date has arrived. If the schedule is absent, continue from registered cycle data and report the missing schedule.
3. For each cycle, run `python -m cpa dashboard outstanding --cycle <cycle_date> --committee som --json`. If it exits nonzero, stop for this cycle and report the error. Save its complete stdout unchanged as UTF-8 at `staging/app/<cycle_date>/outstanding.json`, creating the parent folder with the workspace file-write capability. If that capability is unavailable, ask the analyst to save the output; do not invent an output flag or use code to write the file. Read the saved file back as JSON and confirm it parses to the same data as the command output. Do not alter or infer its `expected`, `submitted`, `outstanding`, `cycle`, or deadline fields.
4. Run `python -m cpa intake reminders --cycle <cycle_date> --outstanding staging/app/<cycle_date>/outstanding.json`. This validates outstanding and submitted department labels against `reference/dept_crosswalk.csv`, suppresses reminders for submitted departments, and writes submission reminder drafts only. Record each output path it prints or creates; do not hand-write submission reminder files.
5. Review the prior cycle's actual deck notes for unanswered committee questions. Use only a question explicitly present in those notes; ask the analyst if it is unclear whether it has been answered. For each confirmed unanswered question, resolve the note's department label through an exact `raw_label` entry in `reference/dept_crosswalk.csv` and check its canonical department against this cycle's `expected` and `submitted` lists. Do not fuzzy-match, draft if the department is submitted, or draft if it is not expected. Write a separate draft using the actual question and cycle deadline, with a filename distinct from `<department>_reminder.md`, such as `<department>_question_<note-stem>_<question-number>_followup.md`. Never overwrite an existing file; if that exact path exists, stop and ask the analyst how to retain both drafts.
6. If an unanswered question belongs to a submitted department, do not draft a reminder; report that conflict to the analyst for resolution. Do not reinterpret the no-reminder rule.
7. Run record: `python -m cpa state record --skill cpa-reminders --input staging/app/<cycle_date>/outstanding.json --output <each reminder path written> --verification "<N> reminders drafted, <N> submitted departments skipped" --duration <seconds>`. Repeat for each cycle processed, and include any blocked unanswered questions in the warning/report to the analyst.

## Outputs
- `outbox/app/<cycle_date>/emails/<department>_reminder.md` — submission reminder draft produced by `intake reminders`; not sent.
- `outbox/app/<cycle_date>/emails/<department>_question_<note-stem>_<question-number>_followup.md` — separate unanswered-question draft, based on actual notes; not sent.
- `staging/app/<cycle_date>/outstanding.json` — unchanged JSON stdout from `dashboard outstanding`, used as the validated CLI input.
- `logs/runs/<UTC timestamp>_cpa-reminders.json` — run record.

## Verify
- `dashboard outstanding` exited 0 for each processed cycle, and its JSON was saved without changing its data.
- The `intake reminders` command completed successfully; no submission reminder was drafted for a submitted department, and its labels passed the department crosswalk. Use the workspace folder-list capability to identify the actual reminder files created for the run; the CLI prints counts/skipped labels, not output paths, and the run record must list actual files rather than guessed paths.
- Every question follow-up is traceable to an unanswered question in the prior cycle's notes, names an expected non-submitted department, uses a distinct filename, and states the actual question and known deadline.
- All outputs remain drafts in outbox; nothing was sent.

## If something is wrong
- `dashboard outstanding` reports no expected departments → tell the analyst to re-run cpa-cycle-kickoff registration with `--department`; never guess the list.
- `intake reminders` rejects an unmatched department → report the exact label and ask the analyst to correct `reference/dept_crosswalk.csv`; do not draft around it.
- A department appears in both submitted and outstanding/question follow-up data → skip every reminder for that department and report the inconsistency.
- A question note uses a department alias not found in `reference/dept_crosswalk.csv` → ask the analyst to resolve the label; never guess or draft under an unmatched name.
- No `reminder_schedule.md` exists for an open cycle → continue from the successful outstanding JSON and tell the analyst the schedule file is missing so cpa-cycle-kickoff can be re-run.
- A question's answer status or source is unclear → ask the analyst; do not create a follow-up until confirmed unanswered.
- A separate question filename already exists → stop and ask before writing; preserve the existing draft.

## Never
- Never draft for a department that has submitted, even when its notes contain an unanswered question; report that case instead.
- Never guess expected departments, invent committee questions, or claim a question is unanswered without checking the actual notes and asking when uncertain.
- Never send a reminder; every draft waits in outbox for the analyst to review and send.
- Never invent CLI flags or alter the dashboard JSON to make the intake command accept it.
