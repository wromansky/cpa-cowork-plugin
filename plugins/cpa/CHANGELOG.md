# Changelog

All notable changes to the `cpa` plugin and the `cpa-automation` Python package. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow semantic versioning.

The version lives in one place, `cpa/__init__.py` (`__version__`). `pyproject.toml` reads it, and
`plugin.json` must match it: Claude Code and Cowork deliver an update to her only when the
`plugin.json` version goes up. The first `## [x.y.z]` heading below must equal that version
(`tests/test_portability.py::test_package_importable_and_version`). Add a new heading on every bump.

## [0.2.5]

### Changed

- Workflow feedback defaults to a short analyst-reviewed message she sends directly to Billy.
  Notes alone need no workspace or browser; local saving is optional and requires consent.
- Cowork recordings may inform her description, but CPA does not request or import recordings
  or generated skills. No automatic uploads, sending, or plugin self-modification.
- Added feedback eval scenarios for notes-only operation and recording-derived descriptions.

## [0.2.4]

### Changed

- Disabled the incorrect SAP-based JE draft API and CLI. The analyst's actual workflow is a
  COGNOS report, font adjustment, cell highlighting, and manual handoff to Accounting; exact
  report and formatting requirements still need confirmation.
- Added cpa-workflow-feedback and a deterministic local note recorder: attended browser
  walkthroughs, explicit analyst review, no credential capture, uploads, or automatic path edits.
- Prioritized a CRF manual-export trial with sanitized source and finished examples. Browser
  pulls remain available for confirmed saved report paths; COGNOS waits must not create duplicate jobs.
- No new browser driver or desktop recorder is installed. Cowork must expose an approved browser
  connection; unvalidated navigation is demonstrated by the analyst. Recalculation remains unsupported.

## [0.2.3]

### Fixed

- Ignore incidental `__pycache__/*.pyc` during bundle inventory checks, but load bundled modules
  from verified source rather than cached bytecode. Unexpected source files still fail integrity.
- Select an already-available compatible sandbox interpreter when the default is too old;
  never download an interpreter. Report the chosen executable and absolute launcher path.
- Resolve the currently loaded skill rather than an older coexisting plugin copy.
- Separate dependency targets by plugin version and interpreter cache tag.

### Validation

- Billy's Cowork retest confirmed 0.2.2 installed all 16 pins on sandbox Python 3.12.3 and passed
  readiness. This is setup evidence only: workspace access and workflows remain untested.
- Automatic workbook recalculation remains unsupported. LibreOffice is excluded everywhere.

## [0.2.2]

### Changed

- Removed LibreOffice discovery and execution on all platforms, including Cowork sandboxes.
- Automatic recalculation reports unsupported; verification cannot claim CLEAN without it.
- Removed installation advice and updated skill instructions to stop recalculation-dependent
  workflows. No replacement backend is implemented.

## [0.2.1] - unreleased

### Fixed

- `cpa-setup` can now run while the runtime packages are missing and installs exact pins into a
  versioned Cowork-sandbox package target, avoiding PEP 668 host-package restrictions. The analyst
  does not need Python or pip installed on her Windows PC.

## [0.2.0] - unreleased

### Added

- Cowork sandbox provisioning: `python -m cpa setup check|install` (`cpa.setup`) reports and
  installs the exact pinned runtime packages declared by the payload, into the session
  interpreter's user site. It is the only place in the product that installs packages; the
  launcher still only reports. The new `cpa-setup` skill runs it, and `cpa-core` now points a
  dependency failure at it instead of stopping. Nothing installs on the analyst's machine.

## [0.1.0] - unreleased

Mid-build. Nothing in this version is proven against her real files: every workflow is built
against synthetic fixtures (`FIXTURE — confirm against her file`). Build state is recorded in
`docs/ARCHITECTURE.md` ("Build state"); the live module list is `python -m cpa registry`.

### Added

- Scaffold (U00): plugin and marketplace manifests, `python -m cpa` auto-discovering CLI registry,
  shared test fixtures, Windows-first bootstrap (`scripts\bootstrap.ps1`) with a dependency lock
  file (`constraints.txt`), and `cpa.fsutil` (Windows-safe atomic writes).
- `cpa.bigxlsx` (U05): streaming reads for workbooks above 15 MB (hard rule 11).

### Not yet built

- Plugin skills (`plugins/cpa/skills/`) and slash commands (`plugins/cpa/commands/`): the plugin
  loads no skills until these exist.
- Every other `cpa/` module in the ARCHITECTURE module table.
