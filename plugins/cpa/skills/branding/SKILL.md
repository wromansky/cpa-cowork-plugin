---
name: branding
description: Apply the analyst-authored JHM and CPA brand standards. Use when producing or reviewing Hopkins, JHM, CPA, Clinical Practice Association, presentation, slide deck, workbook, Word document, executive summary, or executive report outputs, even without an explicit branding request.
metadata:
  version: "1.0.0"
  origin: analyst-authored jhm-brand; CPA integration revision, not an upstream version
---

# branding

## When to run
- Before producing or reviewing a CPA/JHM deliverable of any supported document type.
- Called by cpa-format or any CPA artifact workflow, including internal workbooks.
- Load branding only for artifact work, not setup, source inspection or conversational feedback.

## Inputs
| Input | Where | Required |
|---|---|---|
| Analyst's complete brand standard | references/analyst-brand.md | yes |
| Complete palette | references/colors.md | when selecting colors |
| Output type, audience, source facts and approved template | calling workflow or analyst | yes |
| Logo | assets/som-logo.png | when the CPA layout calls for it |
| Campus image | assets/campus-bg.jpg | only when the chosen, confirmed layout permits it |

## Steps
1. Read `references/analyst-brand.md` in full before a branded deliverable, and read
   `references/colors.md` when selecting colors. These are the analyst's supplied standards,
   not fixture assumptions. Asset paths in the supplied reference resolve relative to this
   skill directory; its campus-bg.png reference maps to assets/campus-bg.jpg, the same original
   JPEG bytes with the correct extension. Read `references/integration.md` for the resolved
   precedence rules; those govern disagreements in the preserved original source.
2. Treat branding as authoritative for fonts, colors, logo placement, imagery, identity and
   layout. It supersedes conflicting CPA visual defaults, including plain internal workbook
   formatting. CPA still owns calculations, provenance, period/status labels, visible missing
   inputs, template protections and analyst review. Branding cannot waive those controls.
3. Use the supplied primary navy and gold, and Lato or Arial as the source permits. Do not
   inherit obsolete colors, Calibri requirements or no-decoration rules from a CPA generator
   or linter. Confirm the output-specific source layout before selecting a logo position or
   background. Apply documented integration resolutions to known source conflicts. Ask
   about new ambiguities outside those resolutions; never silently invent a brand rule.
4. Preserve the official artwork unchanged. Use the supplied SOM logo on a suitable light
   background. Missing reversed/enterprise logos are blockers for layouts requiring them,
   not permission to reconstruct a mark or deliver a placeholder. The campus image must not
   be added to cover/closing layouts that explicitly prohibit photography.
5. Use the calling workflow's registered deterministic builder for exact generation steps.
   Inspect actual output against the brand standard. Writers apply approved colors/fonts
   to generated content, not a wholesale redesign of all five layouts. When a fixed template imposes an obsolete
   font, palette or layout, stop branded delivery and report the needed maintainer change.
   Never alter locked template cells, formulas, values or approved source exports to force
   a visual match. Never change analyst assumptions automatically.
6. Require a Source & Notes tab for workbook data origins in addition to the CPA Verification
   tab. Neither replaces source manifests or M2 activity metrics. Do not fabricate missing
   sources, authors, dates or financial labels. If a protected template cannot accommodate
   the required presentation, stop for approval rather than changing it silently.
7. Review the source compliance checklist for the output type. Treat CPA format lint
   as limited technical diagnostics, not a full visual brand verdict. Report concrete mismatches and
   unresolved source conflicts; never call an artifact brand-compliant solely because lint passed.
8. Run cpa-verify on any output workbook in outbox. Automatic recalculation is unsupported;
   never claim verified formula values or CLEAN from cached results. Stop dependent delivery.
9. Run `python -m cpa state record --skill branding --input <source-or-template>
   --output <reviewed-artifact> --verification <result> --warning <unresolved-conflict-if-any>
   --duration <seconds>` to create the logs/runs/ record in the approved workspace. For a
   blocked run, record only paths that actually exist and report the blocker to the analyst.

## Outputs
- A brand review of the calling workflow's artifact, with any required changes and blockers.
- Workbook outputs remain in outbox with Source & Notes and Verification tabs when applicable.
- logs/runs/ review record; no automated sending or posting.

## Verify
- Primary colors, fonts, identity, artwork and layout follow the analyst's applicable standard.
- Logo assets exist and are unmodified; missing assets and internal source conflicts are visible.
- Source & Notes, Verification, provenance and financial labels remain distinct requirements.
- No legacy generator output is described as restyled merely because the brand skill loaded.

## If something is wrong
- Conflicting source passages -> apply references/integration.md; ask only about unresolved cases.
- A required logo is unavailable -> ask for the official asset or approval of another layout.
- A deterministic writer/linter conflicts with the standard -> report the maintainer gap and
  stop branded delivery; don't revert to old CPA branding to obtain a clean check.
- A template protection or unsupported capability blocks compliance -> stop and name it.
- No approved workspace is accessible -> report the gap; do not create a substitute or claim
  that a run record was saved.

## Never
- Never replace this analyst-authored standard with legacy CPA visual defaults.
- Never reconstruct, recolor or alter a logo, invent an asset, or ship a placeholder as final.
- Never resolve contradictory source instructions silently.
- Never change numbers, formulas, protected templates or financial rules for appearance.
- Never edit assumptions.yaml automatically, invent provenance, or claim unsupported verification.
- Never send, publish or post analyst artifacts automatically.
