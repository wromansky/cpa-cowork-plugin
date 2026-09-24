"""cpa - deterministic script layer for the CPA automation plugin (guide section 1 layer 2).

Holds the workspace layout constants from Build List 0.1, the workspace ignore list from E3 and the
D07 LibreOffice location data, so config (U01), rollover (U16), consolidate/archive (U23), recalc (U07)
and tests/conftest.py share one copy of each.

Build-list items: 0.1 workspace layout (layout data only), E3 / R247 ignore list (data only),
D07 soffice names and default Windows install directory (data only).
Hard rules enforced: none here. D03: importing cpa never touches the filesystem, so this module
holds data only - no logic, no imports, no file access.
"""

__version__: str = "0.2.3"  # single source: pyproject reads it (dynamic version); plugin.json and CHANGELOG are test-guarded

# Build List 0.1: one inbox folder per source system.
INBOX_SYSTEMS: tuple[str, ...] = (
    "tableau",
    "powerbi",
    "cognos",
    "medvitals",
    "epic",
    "sap",
    "qgenda",
    "sullivancotter",
    "submissions",
    "email",
)

# Build List 0.1: top-level workspace folders.
WORKSPACE_TOP: tuple[str, ...] = (
    "inbox",
    "staging",
    "outbox",
    "archive",
    "reference",
    "templates",
    "requests",
    "logs",
)

# Build List 0.1 / D03: nested directories every consumer also creates (rollover init, config.propose,
# the conftest `workspace` fixture). Tuples of path parts, never "a/b" strings (test_no_posix_path_literals).
WORKSPACE_SUBDIRS: tuple[tuple[str, ...], ...] = (
    ("reference", "proposed"),  # D03: proposed assumption values she pastes in
    ("logs", "runs"),  # one JSON run record per skill run
)

# Retired D07 constants retained for compatibility tests only; no runtime discovery uses these.
# Historical executable names in shutil.which order, and the default Windows install directory as
# path parts (Path(*SOFFICE_WINDOWS_DIR) on her machine). U07's cpa.recalc.find_soffice and the
# tests/conftest.py fallback both read these; no other file spells the directory.
SOFFICE_NAMES: tuple[str, ...] = ("soffice", "soffice.com", "soffice.exe")
SOFFICE_WINDOWS_DIR: tuple[str, ...] = ("C:\\", "Program Files", "LibreOffice", "program")
SOFFICE_WINDOWS_EXES: tuple[str, ...] = ("soffice.com", "soffice.exe")  # D07 order inside that directory

# R247 / Build List E3: git-track the workspace excluding raw exports. This is the WORKSPACE ignore
# list, written into <workspace>/.gitignore by `python -m cpa rollover init` (U16) and re-asserted by
# archive (U23). The repository .gitignore is a different file and contains none of these entries.
# Never lists staging/, reference/, outbox/, templates/, requests/ or logs/ - those are what E3 tracks.
# staging/ in particular holds non-regenerable, cycle-recoverable artifacts (app/<position>/triage.md,
# brief.md, answers/, collection_rate.json, je/<id>/source.json, lookback/<cohort>/join_report.md)
# that C12 lineage and E3 recovery require. A narrower regenerable pattern (e.g. "staging/**/*.parquet")
# is added here only on request (U00 plan Q7), never the whole directory.
WORKSPACE_GITIGNORE: tuple[str, ...] = (
    "# written by `python -m cpa rollover init` from cpa.WORKSPACE_GITIGNORE; edit the constant, not this file",
    "inbox/",  # raw exports (Build List 0.1: single ingestion point)
    "archive/",  # processed raw inputs, never deleted (Build List 0.1)
    "~$*",  # Excel lock files
    "Thumbs.db",
    "desktop.ini",
)
