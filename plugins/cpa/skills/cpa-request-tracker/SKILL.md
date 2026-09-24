---
name: cpa-request-tracker
description: Produce the weekly aging digest of ad hoc CPA requests from logs/requests.csv. Run daily as a scheduled task, or when the user says "request digest", "what's outstanding", "what's overdue", or "what did I promise and when".
---

# cpa-request-tracker

## When to run
- Scheduled: weekly digest, Friday 16:30.
- The user says "request digest", "what's outstanding", "what's overdue", or asks what is due and when.
- `cpa-dashboard` reads this skill's output when it builds the daily dashboard (B22).

## Inputs
| Input | Where | Required |
|---|---|---|
| Request log | `logs/requests.csv`: id, requester, received, due, classification, status, artifact_path, sent_date | yes |
| Today's date | system date, or `--today` override for a rerun | yes |

## Steps
1. Read `CPA_WORKSPACE` from `cpa-core`.
2. Run `python -m cpa tracker digest --json`.
   The command reads `logs/requests.csv`, buckets every request whose status is not `closed` or
   `declined` by calendar days since `received` (0-3, 4-7, 8-14, 15+), lists every open request whose
   `due` date is before today as overdue regardless of bucket, and writes `logs/tracker_digest.md`.
3. Read the JSON result: `total_open`, the four age buckets, and `overdue`.
4. Scan `logs/requests.csv` for any row with status `closed` or `declined` and a blank
   `artifact_path`; the tracker module refuses to write a closed row without that cell filled (an
   artifact path for closed, the decline reason for declined), so a blank one means an earlier close
   attempt was rejected. Flag it for the analyst rather than filling it in.
5. Report: open count, the count in each age bucket, every overdue request with its requester and due
   date, and any flagged row from step 4. Silent about buckets and rows with nothing to flag.
6. Run `python -m cpa state record --skill cpa-request-tracker --output logs/tracker_digest.md
   --duration <seconds>` to write the run record.

## Outputs
- `logs/tracker_digest.md` — open requests by age bucket, plus the overdue list.
- The same result reported to the analyst as this run's message.

## Verify
- `total_open` in the JSON equals the sum of the four bucket counts.
- Every overdue row's `due` date is strictly before today.
- No row with status `closed` or `declined` has a blank `artifact_path`.

## If something is wrong
- `logs/requests.csv` is missing or unreadable -> stop and report; do not report a digest built on
  no data.
- A row's `received` or `due` date fails to parse -> report the row id and the bad value; do not
  guess a date to make it bucket.

## Never
- Never close (mark `closed` or `declined`) a request without an artifact path in the closed case or
  a decline reason in the declined case.
- Never invent a due date or artifact path for a row that is missing one; flag it instead.
- Never rewrite `logs/requests.csv` by hand; only the tracker module writes it.
