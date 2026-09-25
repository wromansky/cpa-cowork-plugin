"""cpa - deterministic script layer for the CPA automation plugin (guide section 1 layer 2).

Holds workspace layout constants from Build List 0.1 and the workspace ignore list from E3,
shared by config, rollover, consolidation, archive and test fixtures.

Build-list items: 0.1 workspace layout (data only), E3 / R247 ignore list (data only).
Hard rules enforced: none here. D03: importing cpa never touches the filesystem, so this module
holds data only - no logic, no imports, no file access.
"""

__version__: str = "0.2.6"  # single source: pyproject reads it (dynamic version); plugin.json and CHANGELOG are test-guarded

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
