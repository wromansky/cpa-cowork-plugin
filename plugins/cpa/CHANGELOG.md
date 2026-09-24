# Changelog

All notable changes to the `cpa` plugin and the `cpa-automation` Python package. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow semantic versioning.

The version lives in one place, `cpa/__init__.py` (`__version__`). `pyproject.toml` reads it, and
`plugin.json` must match it: Claude Code and Cowork deliver an update to her only when the
`plugin.json` version goes up. The first `## [x.y.z]` heading below must equal that version
(`tests/test_portability.py::test_package_importable_and_version`). Add a new heading on every bump.

## [0.2.2] - unreleased

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
