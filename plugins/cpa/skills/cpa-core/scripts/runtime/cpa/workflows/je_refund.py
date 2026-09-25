"""JE refund automation disabled pending confirmed COGNOS report formatting requirements.

Analyst correction: she exports a COGNOS report, fixes its font, highlights a cell, and sends
it to Accounting. The previous SAP misposting and ready-to-post draft workflow was incorrect.
B16 is withdrawn, not implemented against her actual workflow. Hard rule 13: never post.
Report name, export layout, font, and highlight rule still require confirmation. No files
are read or changed here. Use cpa-workflow-feedback for a supervised walkthrough.
"""
from __future__ import annotations
import argparse

DISABLED = ("JE refund automation is disabled: the analyst uses a COGNOS report, not the old SAP "
            "draft workflow. Confirm the report, font and highlight rule through cpa-workflow-feedback. "
            "Nothing was read, formatted, sent or posted.")


class JeError(RuntimeError):
    """The unconfirmed JE workflow cannot run."""


def draft(*args, **kwargs):
    """Refuse the retired workflow even for callers using its former Python API."""
    raise JeError(DISABLED)


def _disabled(args):
    print(DISABLED)
    return 1


def register(subparsers: argparse._SubParsersAction) -> None:
    """Keep the former command as an explicit refusal; there is no posting command."""
    top = subparsers.add_parser("je_refund", help=__doc__.splitlines()[0])
    sub = top.add_subparsers(dest="command", required=True)
    leaf = sub.add_parser("draft", help="Disabled: actual COGNOS workflow needs confirmation.")
    # Accept old flags solely to return the refusal, never to read a source or create a draft.
    for name in ("source", "template", "cost-structure", "root"):
        from pathlib import Path
        leaf.add_argument("--" + name, type=Path)
    for name in ("je-id", "from-cc", "to-cc", "requested-amount", "fymm", "reason", "template-map", "as-of"):
        leaf.add_argument("--" + name)
    leaf.add_argument("--json", action="store_true")
    leaf.set_defaults(func=_disabled)
