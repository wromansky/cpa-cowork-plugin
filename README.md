# CPA Cowork plugin

[Install CPA in Cowork (analyst quickstart)](quickstart.md).

This is a **public installation snapshot** of the `cpa` Cowork plugin, not its private
source/development repository. It contains the marketplace manifest, plugin skills,
and the self-contained Python runtime. No real exports, credentials, or analyst workspace
are shipped. The public bundle intentionally leaves all JHM rates unfilled; supply them
from approved sources in the analyst's private workspace. Never guess or publish them here.

## Version 0.2.7: new to Cowork?

After enabling CPA, ask:

> Use cpa-getting-started. I have only used chat before. Explain in plain language how to use
> this plugin, why it may help with my work, and one safe next step. Do not open files or run
> anything yet.

The lesson explains reusable CPA workflows, how to give a task, permissions, output review and
feedback. It accommodates both separate Chat/Cowork controls and the newer unified interface.
Teaching requires no workspace or setup. File access and setup are separate consent-based
steps, not automatic demonstrations. No guarantees of correctness, lower usage or local-only
processing are made. Official Claude documentation is linked in the bundled lesson references.

## Branding and workflow boundaries retained from 0.2.6

- Includes the analyst-authored **branding** skill and approved SOM logo/campus asset.
  Documented precedence resolves conflicting source instructions. Branding supersedes earlier
  CPA visual defaults, including internal workbooks; financial safeguards remain binding.
- Generated workbook writers use approved typography/palette, headers and neutral banding.
  Verification adds an absent **Source & Notes** tab from recorded provenance. Existing source
  notes and financial/template cells are preserved, not restyled wholesale.
- Generated slide helpers normalize fonts and widescreen dimensions. They are not complete
  implementations or visual validators of all five brand layouts. Real-file layout, artwork,
  spacing and readability acceptance belongs to the analyst in Cowork.
- Automatic workbook recalculation is unsupported; no backend is implemented. Workflows needing
  recalculated values must stop, and cached formulas cannot establish CLEAN.
- Setup, supervised browser trials and feedback guidance match the shipped capabilities.
  The incorrect SAP JE draft remains disabled; corrected COGNOS formatting is not yet implemented.

After syncing, start a fresh Cowork conversation and confirm the mounted bundle reports **0.2.7**.
Confirm the bundled **branding** skill loads before disabling the standalone brand skill.
Use actual approved files for a supervised review: fonts, header/tab colors, protected formulas,
source notes and Verification. Report concrete mismatches through **cpa-workflow-feedback**;
local note saving is optional. Nothing is sent or posted automatically.

CRF begins with approved manual exports and a sanitized finished example. Browser-assisted
pulls require approved connections and confirmed saved reports; the analyst handles login,
SSO and MFA. Setup success, synthetic tests and integrity checks are not real-file or Cowork
acceptance. Do not schedule unattended live pulls until separately validated.

For installation issues, report the Cowork setup readiness result. Do not install Python,
Git, or other local tools on the analyst's PC to work around a failure.
