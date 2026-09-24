---
name: cpa-cag-match
description: Rerun the CAG-to-QGenda task matcher and refresh the cFTE calculators. Run when a QGenda tasks or sessions export lands, when her CAG masterlist is updated, or when the user says "rerun the matcher", "refresh cFTE" or "CAG task combined".
---

# cpa-cag-match

## When to run
- Task exports `inbox/qgenda/tasks_<dept>_<YYYY-MM-DD>.*` land (A13), or her CAG workbook is updated (B18).
- Sessions exports `inbox/qgenda/sessions_<dept>_<YYYY-MM-DD>.*` land and the cFTE calculators need
  refreshing (B19).
- The user asks to rerun the matcher, refresh cFTE, or rebuild the combined CAG workbook.

## Inputs
| Input | Where | Required |
|---|---|---|
| QGenda task exports | `inbox/qgenda/tasks_<dept>_<YYYY-MM-DD>.*` (A13), read only | yes |
| Her CAG workbook | `reference/Departmental_Overview_CAG_and_QGenda_SA.xlsx` - the CAG Masterlist, Task to CAG Link and Task to CAG Link II sheets | yes |
| TaskKey register | `reference/taskkey_register.csv` - updated by the run, never authored here | yes |
| QGenda sessions exports | `inbox/qgenda/sessions_<dept>_<YYYY-MM-DD>.*` | yes for the cFTE refresh |
| CU-per-session reference | `reference/cu_per_session.csv` | yes for the cFTE refresh |
| The matcher's workbook for this date | the path step 3 printed, or the newest one under `outbox/cag` when `--combined` is omitted | yes before the cFTE refresh, and never one from a run that reported a blocking issue |

## Steps
1. In the plugin checkout, resolve two absolute paths before running anything. The interpreter, by
   resolving `.venv\Scripts\python.exe` inside the checkout. The workspace, by reading `CPA_WORKSPACE` in
   cpa-core and running `.venv\Scripts\python.exe -m cpa config where` with that resolved interpreter.
   Every `.venv\Scripts\python.exe` below stands for the resolved executable, and every `inbox`,
   `staging`, `outbox`, `reference` and `logs` path below is relative to the workspace root the command
   printed, so run the rest of the steps from that root. Never hard-code either path.
2. Run `.venv\Scripts\python.exe -m cpa state ready --json`. When cpa-cag-match is not listed for this
   export date, say why - the task exports have not landed, or this date already ran - and continue only
   when the analyst asked for a rerun.
3. Match: run `.venv\Scripts\python.exe -m cpa cag_match run [--date <YYYY-MM-DD>] [--tasks <files>]
   [--masterlist <her workbook>]`. It writes the next version of `CAG_Task_Combined` and prints JSON with
   the coverage. Exit 0 clean, exit 1 written with blocking issues, exit 3 input error - read the message.
4. Read the JSON: the coverage, the per-tier counts, and the blocking issues printed below it. Report every
   blocking issue (a task linked into two CAGs, or an over-link across the Faculty and Clinical Associate
   rows) to the analyst. While any blocking issue stands, steps 5 and 6 still report but step 7 does not
   run: her CAG workbook is the fix, and the cFTE refresh resumes only after a rerun of the matcher exits 0.
5. Report the unmatched tasks. Each keeps a blank TaskKey, and every row - matched or not - is kept and
   flagged; nothing is dropped.
6. Run `.venv\Scripts\python.exe -m cpa verify <the CAG workbook path step 3 printed>` and read the
   result.
7. Refresh cFTE - only when the matcher run in step 3 exited 0: run `.venv\Scripts\python.exe -m cpa cfte
   refresh [--date <YYYY-MM-DD>] [--sessions <files>] [--combined <the CAG workbook path step 3 printed>]`.
   It writes the APP, Clinical Associate and Faculty calculators plus the consolidated reference with its
   Verification tab, and prints JSON with the row and blank-cFTE counts per calculator. Exit 3 input
   error. Omitting `--combined` is not a way to skip CAG enrichment - without the flag the command loads
   the newest combined workbook under `outbox/cag` itself, so a flagged workbook is read either way.
8. Report the blank-cFTE counts and the missing input behind each blank: a cFTE stays blank without every
   one of its inputs, and the consolidated row count equals the union of the three calculators.
9. Run `.venv\Scripts\python.exe -m cpa verify <the cFTE workbook path step 7 printed>` and read the
   result.
10. Write the run record: `.venv\Scripts\python.exe -m cpa state record --skill cpa-cag-match --input
    inbox/qgenda/tasks_<dept>_<YYYY-MM-DD>.xlsx --output <the CAG workbook path printed in step 3>
    --output <the cFTE workbook path printed in step 7, only when step 7 ran> --verification "<CLEAN|N
    ISSUES>" --warning "<blocking issues or blank cFTE counts>" --duration <seconds>`.

## Outputs
- `outbox/cag/<date>/CAG_Task_Combined_v<N>.xlsx` - the Summary, Combined, Unmatched Tasks, Unlinked CAGs,
  Issues and Legend sheets, each row flagged with its match tier, plus the Verification tab.
- `outbox/cfte/<date>/CFTE_Calculators_v<N>.xlsx` - the APP, Clinical Associate and Faculty calculators,
  the consolidated reference, the Summary sheet and the Verification tab.
- `reference/taskkey_register.csv` - every TaskKey the QGenda exports carried, with its first and last
  seen date.
- `logs/runs/<timestamp>_cpa-cag-match.json` - the run record.

## Verify
- `cag_match run` exited 0, or exited 1 with every blocking issue reported; a blocking run still writes its
  workbook and flags the rows.
- Every TaskKey in the workbook exists in a QGenda export, and an unmatched row's TaskKey is blank.
- The coverage is reported for the run.
- The cFTE refresh ran only after a `cag_match run` that exited 0, and it used that run's workbook; the
  CAG lookup reads the Combined sheet's CAG column for every row and keeps one CAG per department, division
  and activity, last row winning, so no flagged row's CAG reached the cFTE workbook.
- No cFTE value is present without all of its inputs, and the blank counts are reported per calculator.
- The consolidated row count equals the union of the three calculators.
- Each Verification tab reads CLEAN, or every issue is listed and reported.

## If something is wrong
- Exit 3 naming an unmatched department label -> the analyst adds it to `reference/dept_crosswalk.csv`;
  never guess a mapping and never rename a department in the export.
- Her CAG workbook is missing a sheet or a column -> stop and report the file, the sheet and the column;
  never add or rename columns in her workbook.
- Exit 1 with blocking issues -> report each one and stop the chain before the cFTE refresh; an over-link
  and a task under two CAGs are questions for her, and her CAG workbook is the fix. Never remove a flag or a
  row to clear the run, and resume only after she has corrected her workbook and a fresh `cag_match run`
  exits 0. Running the refresh anyway is not an option: its default already loads the newest combined
  workbook under `outbox/cag`, so omitting `--combined` changes nothing.
- A report row has no matching task -> its TaskKey stays blank; never copy a TaskKey from a similar row and
  never invent one.
- A cFTE is blank -> say which input is missing (the session row, its CU-per-session key, or the target);
  never estimate one.
- A department's sessions export is missing -> report it; the departments that did land still compute, and
  the blank counts show what is not covered.
- No combined workbook exists under `outbox/cag` at all -> the cFTE refresh runs with a blank CAG column;
  say so. Never rely on a missing file to sidestep a flagged workbook, and never paste CAGs in by hand.
- LibreOffice is unavailable for the recalc step -> say so in the run record warning; never claim a
  recalculated workbook.

## Never
- Never fabricate a TaskKey; a TaskKey comes only from a QGenda export, and an unmatched row is blank.
- Never fill a cFTE without every one of its inputs; cFTE and effort are the same thing.
- Never treat a blank as zero.
- Never overwrite an earlier version; a rerun writes the next version.
- Never edit her CAG workbook, the TaskKey register or the crosswalk from this skill.
- Never clear a blocking flag by hand, and never drop a row to make the coverage look better.
- Never run the cFTE refresh while the matcher reports a blocking issue; its default already loads the
  newest combined workbook under `outbox/cag`, so omitting `--combined` protects nothing.
- Never rename, move, hide or delete a combined workbook to change what the cFTE refresh loads.
- Never guess an unmatched department label.
