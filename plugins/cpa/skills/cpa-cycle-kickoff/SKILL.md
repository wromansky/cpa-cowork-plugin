---
name: cpa-cycle-kickoff
description: Register a new or changed SOM Review Committee, Board of Governors, Finance Committee, or Clinical Governance meeting and draft the call-for-submissions email. Run on the daily calendar poll when a new or updated committee invite appears, or when the user says "register this cycle" or "kick off the next SOM cycle".
---

# cpa-cycle-kickoff

## When to run
- The daily calendar poll finds a new or updated SOM Review Committee, Board of Governors, Finance
  Committee, or Clinical Governance invite.
- The user says "register this cycle" or "kick off the next SOM cycle" and names the meeting date.

## Inputs
| Input | Where | Required |
|---|---|---|
| Meeting date and committee | the calendar invite, or ask the analyst | yes |
| Expected departments (SOM only) | the invite's attendee list, or ask the analyst | yes for som |
| Committee lead days | reference/assumptions.yaml (read by the script, never by hand) | yes |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. Confirm the meeting date and committee from the invite; never substitute a guessed date.
3. Run `python -m cpa dashboard register-cycle --date <YYYY-MM-DD> --committee <bog|fc|gov|som>
   [--department <dept> ...] --json`. For a `som` cycle, pass `--department` once per department on
   the invite's attendee or roster list. The command reads the committee's lead days only from
   `reference/assumptions.yaml`; a missing or null key stops the run rather than guessing a lead
   time, and it creates `outbox/app/<meeting_date>/` for `som`.
4. Read the JSON result's `materials_deadline`. For a `som` cycle, draft the department
   call-for-submissions email naming the deadline and what to submit, and save it as
   `outbox/app/<cycle_date>/emails/call_for_submissions.md`; never send it.
5. Draft the reminder schedule (dates the department reminders will go out before the deadline) as
   `outbox/app/<cycle_date>/reminder_schedule.md` for cpa-reminders to read.
6. Run `python -m cpa dashboard build --json` so the newly registered cycle shows up on today's
   dashboard.
7. Write the run record: `python -m cpa state record --skill cpa-cycle-kickoff --input <invite date>
   --output <call-for-submissions path> --output <reminder schedule path> --verification "<cycle
   key> registered, due <materials_deadline>" --duration <seconds>`.

## Outputs
- `outbox/app/<cycle_date>/emails/call_for_submissions.md` — draft only, som cycles.
- `outbox/app/<cycle_date>/reminder_schedule.md` — dates cpa-reminders uses.
- `logs/cycles.json` — the cycle entry, with its computed materials deadline.

## Verify
- `dashboard register-cycle` exited 0.
- The cycle appears under Due on `logs/dashboard.md` with a materials deadline.
- A som cycle has a call-for-submissions draft in `outbox/app/<cycle_date>/emails/`.

## If something is wrong
- `register-cycle` exits 1 on a missing lead-day assumption → report the exact key to the analyst;
  never guess a lead time or fabricate a deadline.
- The invite gives no attendee/department list for a som cycle → ask the analyst for the expected
  department list before running `register-cycle`; never leave it unrecorded and never invent one.
- The same meeting is re-registered with a changed date → re-run `register-cycle` with the new date;
  the prior draft emails are left in place under the old cycle folder, never deleted.

## Never
- Never guess a lead time or a materials deadline; only `dashboard register-cycle` computes one.
- Never send the call-for-submissions email; it is a draft for the analyst to review and send.
- Never fabricate the expected department list for a som cycle.
- Never register a cycle from a guessed date when the invite is ambiguous; ask the analyst.
