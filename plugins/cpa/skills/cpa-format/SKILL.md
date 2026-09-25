---
name: cpa-format
description: Brand and format lint a deck or workbook, generate speaker notes, or diff two versions of a deck or workbook. Called by cpa-app-slide and cpa-app-deck before they return, or when the user says "brand check", "speaker notes", or "what changed in this deck".
---

# cpa-format

## When to run
- Called by any skill that builds or refreshes a deck, to self-check with a lint before returning.
- The user asks for a brand check, speaker notes, or what changed between two versions of a deck or
  workbook.

## Inputs
| Input | Where | Required |
|---|---|---|
| Deck or workbook to lint | path given | yes, for a lint |
| Audience | one of internal, committee, dean, board | yes, for a lint or notes |
| Deck kind | main (7-8 slide cap) or companion (no cap) | no (default: main) |
| Notes content | a JSON array, one object per slide: title, points, figures, flagged_metrics | yes, for notes |
| Earlier and later versions | two paths, both `.pptx` or both `.xlsx` | yes, for a diff |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. Load branding and read its complete analyst-authored reference before reviewing branding.
   It owns fonts, palette, logo placement, imagery and layout, including internal workbooks.
   It supersedes the old CPA plain/Calibri defaults. Apply the documented resolutions in branding/references/integration.md;
   ask only about ambiguities not covered there. Do not modify financial data or protected templates.
   Technical format diagnostics: run `python -m cpa pptx lint [--deck <deck>] [--workbook <workbook>
   --tab <tab>] --audience <internal|committee|dean|board> [--deck-kind <main|companion>]
   [--allow-freeze] --json` when asked to check brand or format, or called by another skill before
   it returns a deck or workbook. This lint checks approved fonts/fills, source notes and scoped
   slide geometry/placeholder conditions, not every layout or semantic color choice. No findings
   in checked scope is not visual approval. Geometry may need human interpretation; never shrink
   text or remove yellow missing-data flags just to pass. Review the actual output with branding;
   stop delivery on a mismatch.
3. Speaker notes: run `python -m cpa pptx notes --deck <deck> --audience
   <internal|committee|dean|board> --content <content.json> --json` when asked to generate or
   refresh speaker notes. Notes density follows audience: dean and board get the high-level story;
   committee and internal get the detail. `flagged_metrics` names metrics only, never their
   why/source text - a flag is never buried in notes.
4. Deck or workbook diff: run `python -m cpa pptx diff --a <earlier> --b <later> --json` when asked
   what changed between two versions.
5. Read the JSON result of whichever command ran. Keep package integrity, preservation, financial
   verification and visual review separate. Visual review remains NOT_REVIEWED until the analyst
   actually reviews the file. Where baseline attribution is present, report inherited and new
   findings separately without hiding either. Diffs can report both text and formatting changes.
6. If the lint reported issues: list each one with its location and the rule it broke. Do not fix
   any of them here; report them to the calling skill or the analyst.
7. Run `python -m cpa state record --skill cpa-format --input <deck-or-workbook-or-a> [--input <b>]
   --output <deck, when notes were written> --verification <"no format findings; visual NOT_REVIEWED" or "N issues"> --duration
   <seconds>` to write the run record.

## Outputs
- Lint issues, printed and returned to the caller.
- `<deck>` - the same deck, with speaker notes written onto every slide, when notes ran.
- A diff report between `<a>` and `<b>`, printed and returned.
- `logs/runs/<timestamp>_cpa-format.json` - the run record.

## Verify
- A lint run reports its technical findings; nothing was fixed automatically. A no-finding
  result is not a brand verdict or financial verification. branding governs visual compliance.
- A notes run writes notes text onto every slide in the deck, none skipped.
- A diff run separates numeric changes from format-only changes and never misreports one as the other.

## If something is wrong
- An Office safety/preservation check blocks a write -> stop, keep the original and report the
  error. Do not strip features, rebuild a template or install tools to bypass it. No updated file
  should be described as delivered. A rollback failure explicitly marked DO NOT SEND needs Billy's
  review; recovery copies stay in staging.
- `pptx lint` exits 2 (bad argument or unreadable file) -> stop and report the error text; do not
  write a run record claiming success.
- `pptx notes` exits 2 (slide-count mismatch between `--content` and the deck) -> stop; do not write
  partial notes onto some slides and leave others blank.
- `pptx diff` exits 2 (mismatched file kinds, or a file that will not open) -> stop and report which
  files were compared and why the diff could not run.

## Never
- Never fix a lint issue automatically - report it.
- Never allow body text below 18 points on a Dean or board deck; explicitly typed footnotes,
  data labels and page numbers follow their separate branding scales.
- Never bury a flag in speaker notes; a flagged metric belongs in the on-slide box, named only in
  notes.
- Never write notes onto some slides and skip others.
- Never report a content change as a format-only change, or a format change as a content change.
