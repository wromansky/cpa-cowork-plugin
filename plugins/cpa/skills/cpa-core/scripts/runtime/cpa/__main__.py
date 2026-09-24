"""Entry point for `python -m cpa` (and `py -3 -m cpa` on Windows).

Build-list items: guide section 9 cli.py dispatch. Hard rules enforced: none (dispatch only).
"""
from cpa.cli import main

raise SystemExit(main())
