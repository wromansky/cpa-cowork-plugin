"""cpa.pptx: brand and format (C9), speaker notes (C10), deck and workbook diff (C11).

Guide section 9 pptx package - `python -m cpa pptx lint|notes|diff`. This __init__.py owns the
"pptx" top-level subcommand (cpa/cli.py rule 1: a package registers its own name once) and
dispatches to each leaf module's register_under(sub); brand.py exposes no subcommand of its own
(constants and helpers only), so it never defines register_under.
"""

from __future__ import annotations

import argparse

__all__ = ["register"]


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register `pptx lint|notes|diff`. Import-cheap: the leaf modules touch no file at import time
    (D03); each reads or writes only when its own function or CLI command runs."""
    top = subparsers.add_parser(
        "pptx", help="Brand and format lint, speaker notes, and deck/workbook diff."
    )
    sub = top.add_subparsers(dest="command", required=True, title="commands")

    from cpa.pptx import diff, lint, notes

    lint.register_under(sub)
    notes.register_under(sub)
    diff.register_under(sub)
