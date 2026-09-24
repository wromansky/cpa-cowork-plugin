# CPA Cowork plugin

[Install CPA in Cowork (analyst quickstart)](quickstart.md).

This is a **public installation snapshot** of the `cpa` Cowork plugin, not its private
source/development repository. It contains the marketplace manifest, plugin skills,
and the self-contained Python runtime. No real exports, credentials, or analyst workspace
are shipped. The public bundle intentionally leaves all JHM rates unfilled; they must
be supplied from approved sources in the analyst's own workspace, never guessed or
posted to this repository.

**Version 0.2.2:** LibreOffice is excluded everywhere, including Cowork sandboxes. No engine
is discovered or executed. Automatic workbook recalculation is unsupported; workflows needing
recalculated results must stop. No replacement backend is implemented.

Local fixture tests and bundle-integrity checks do **not** prove that the plugin works
inside Cowork on the analyst's machine. The first run must be watched; do not schedule
live system pulls or rely on workbook recalculation until validated there.

For installation issues, report the Cowork setup readiness result to the maintainer.
Do not install Python or other tools on the analyst's PC to work around a failure.
