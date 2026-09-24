---
name: cpa-app-triage
description: Check an APP hire submission from an academic department against the CPA submission checklist and audit its P&L formulas before the analyst touches it. Run when a new folder lands in inbox/submissions, when cpa-intake classifies an email as an APP submission, or when the user says "triage this submission" or "check this department's P&L".
---

# cpa-app-triage

## When to run
- A new folder appears under `inbox/submissions/<dept>_<position>_<date>/`.
- cpa-intake classifies an inbound email as an APP submission.
- The user says "triage this submission" or names a department and position to check.

## Inputs
| Input | Where | Required |
|---|---|---|
| Submission files | `inbox/submissions/<dept>_<position>_<date>/` | yes |
| Checklist spec | `reference/checklist.yaml` | yes |
| Assumptions (rate keys) | `reference/assumptions.yaml` | yes |
| Received date | ask the analyst if not stated | yes |
| SOM cycle date | ask the analyst if not stated | yes |

## Steps
1. Read `CPA_WORKSPACE` from `cpa-core`.
2. Confirm the received date and the SOM cycle date with the analyst; never substitute today's date
   for either (hard rule 15 — there is no landed sidecar that names them yet).
3. Run `python -m cpa app_triage run <folder> --cycle <YYYY-MM-DD> --received <YYYY-MM-DD> --json`.
   The command identifies department, division, position title and requester from the files and any
   email manifest; audits the P&L for hard-coded values in formula cells, broken references,
   department-entered benchmark cells, rate mismatches against `assumptions.yaml`, three-year structure
   violations and sign errors; checks every checklist item present, missing or unclear; classifies
   COMPLETE, FIXABLE or RETURN; and writes `staging/app/<position>/{brief.md,triage.md}`. When the
   class is RETURN, or questions remain for the department, it also drafts (never sends) a return email
   under `outbox/app/<cycle>/emails/`.
4. Read the JSON result. Report the position id, classification, and every finding's sheet and cell.
5. If RETURN: tell the analyst the draft return email's path; she reviews and sends it herself.
6. If COMPLETE or FIXABLE: run `python -m cpa state mark cpa-app-triage <position_id> done --output
   <triage.md path>`, then hand off to cpa-app-pnl for this position (after cpa-pull-medvitals and
   cpa-pull-tableau land the division's CPT profile and collection rate).
7. Run `python -m cpa state record --skill cpa-app-triage --input <folder> --output <brief.md path>
   --output <triage.md path> --verification <classification> --duration <seconds>` to write the run
   record.

## Outputs
- `staging/app/<position>/brief.md` — identification and classification.
- `staging/app/<position>/triage.md` — full checklist and audit findings.
- `outbox/app/<cycle>/emails/<dept>_<position>_return.md` — draft only, when RETURN or questions remain.

## Verify
- Every checklist item has a status: PRESENT, MISSING, or UNCLEAR.
- Every formula finding cites the sheet and cell it came from.
- The classification is one of COMPLETE, FIXABLE, RETURN.

## If something is wrong
- `app_triage run` exits 2 (stopped) → report the error text; do not write a run record claiming
  success, and do not draft a return email from a partial result.
- The submission folder has more than one candidate P&L workbook → stop; ask the analyst which one is
  the real submission, then pass `--pnl <path>`.
- A rate in the P&L cannot be checked because the matching `assumptions.yaml` key is null → the finding
  is `RATE_UNVERIFIED` in triage.md; never fill in a plausible rate.

## Never
- Never correct the department's P&L in place. The rebuilt workbook is cpa-app-pnl's job.
- Never send the return email — it is a draft for the analyst to review and send herself.
- Never fabricate a received date, cycle date, department, division, position title or requester.
- Never write a run record for a run that stopped with an error.
