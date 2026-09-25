---
name: cpa-je-refund
description: Handle requests for JE refunds by explaining the corrected COGNOS workflow and collecting missing requirements. Run when the analyst asks for a JE refund or Accounting report. The former SAP journal-entry drafting path is disabled.
---

# cpa-je-refund

## When to run
- The analyst asks for a JE refund or its report for Accounting.
- A scheduled task or dispatcher attempts the former SAP JE workflow: stop it.

## Inputs
- Analyst clarification: export one report from COGNOS, change font, highlight a cell, then
  the analyst sends it to Accounting. Handling is about two minutes; COGNOS pulls can take
  about twenty minutes. These are her observations, not automation timeouts.
- Still unconfirmed: saved report bookmark, exact report name, filters, export layout, font,
  highlight cell or selection rule, and whether that selection needs judgment.

## Steps
1. Use cpa-core to resolve the mounted launcher and run `python -m cpa config where`.
   If the real workspace is unavailable, stop; never create a substitute or request terminal setup.
2. Explain that the old SAP misposting and ready-to-post template workflow is incorrect and disabled.
   Do not call it or cpa-pull-sap. There is no validated COGNOS JE formatter or adapter yet.
3. Offer cpa-workflow-feedback for an attended walkthrough of her actual COGNOS report and formatting.
   Browser assistance is read/export only after her approval, using her named report and bookmark;
   she handles login. Do not treat an existing CRF or departmental report as the JE report.
4. Ask for an approved sanitized export and finished example, plus her font and highlighting rule.
   Do not change cells or send anything until the formatter is implemented and validated.
5. Write the run record: `python -m cpa state record --skill cpa-je-refund --verification
   "blocked: corrected COGNOS workflow needs validation" --warning "SAP JE drafting disabled"
   --needs-analyst`. If no workspace exists, report that no record was written.

## Outputs
- A clear blocked status, not a JE draft or a posting instruction.
- Reviewed local walkthrough notes via cpa-workflow-feedback, if she agrees.
- A `logs/runs/` record when the workspace exists.

## Verify
- No SAP lookup, JE template generation, posting, or sending occurred.
- The report and formatting requirements remain unconfirmed until she supplies them.

## If something is wrong
- An older skill says to use SAP or prepare a journal entry: stop and identify the stale version.
- A COGNOS pull is slow: do not click Run repeatedly or start another export job.
- A workbook needs recalculation: stop; automatic recalculation is unsupported.

## Never
- Never call the retired SAP-based JE draft or treat it as the analyst's workflow.
- Never send to Accounting, post, submit, or approve anything automatically.
- Never guess a report name, filter, font, highlight cell, or accounting recipient.
- Never record credentials, sensitive export contents, or screenshots in feedback.
