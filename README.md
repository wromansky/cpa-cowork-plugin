# CPA Cowork plugin

[Install CPA in Cowork (analyst quickstart)](quickstart.md).

This is a **public installation snapshot** of the `cpa` Cowork plugin, not its private
source/development repository. It contains the marketplace manifest, plugin skills,
and the self-contained Python runtime. No real exports, credentials, or analyst workspace
are shipped. The public bundle intentionally leaves all JHM rates unfilled; they must
be supplied from approved sources in the analyst's own workspace, never guessed or
posted to this repository.

**Version 0.2.5:** Use **cpa-workflow-feedback** to prepare a short reviewed message the analyst
sends directly to Billy. Local saving is optional; notes alone need no workspace or browser.
Do not send recordings or generated skill exports. The incorrect SAP-based JE draft remains disabled.
CRF starts with approved manual exports and a sanitized finished example. Browser-assisted
pulls require an approved connection and confirmed saved report paths; the analyst handles
login, SSO and MFA. This is not screen recording or automatic plugin self-modification.
After updating, start a fresh session and confirm the mounted bundle reports 0.2.5.

LibreOffice is excluded everywhere, including Cowork sandboxes. No engine
is discovered or executed. Automatic workbook recalculation is unsupported; workflows needing
recalculated results must stop. No replacement backend is implemented.

Local fixture tests and bundle-integrity checks do **not** prove that the plugin works
inside Cowork on the analyst's machine. The first run must be watched; do not schedule
live system pulls or rely on workbook recalculation until validated there.

For installation issues, report the Cowork setup readiness result to the maintainer.
Do not install Python or other tools on the analyst's PC to work around a failure.
