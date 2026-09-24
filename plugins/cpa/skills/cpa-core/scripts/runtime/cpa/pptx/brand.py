"""Brand constants and shared format helpers for the pptx package (C9): JHM colors and the CPA flag
convention text, shared by lint.py, notes.py, and diff.py, and by any later slide-building unit.

Build-list items: C9 brand and format skill (guide 5 cpa-format, guide 9 pptx/brand.py, build-list C9
row). Hard rules enforced: 15 (an unconfirmed color is never defaulted or guessed - gold, ice_blue and
flag_yellow raise MissingAssumption in production until she supplies them, DECISIONS D08).

Every color is read through cpa.config.assumption("brand", <key>) at call time, never cached at import
(D03): importing this module touches no file. Production reads reference/assumptions.yaml, where navy
and dark_green are already confirmed and gold/ice_blue/flag_yellow ship null (D04) until she supplies
them with the PowerPoint eyedropper (docs/SETUP.md). Tests and fixture decks read
tests/fixtures/brand_fixture.yaml via the CPA_ASSUMPTIONS override (D08), same pattern as
test_activity_block.py's _yellow() helper.
"""

from __future__ import annotations

import re
from pathlib import Path

from cpa import verify

__all__ = [
    "BRAND_KEYS", "ROLE", "HEX_RE", "BrandError", "InvalidColor",
    "color", "palette", "flag_text",
]

# R144/R187: JHM navy, gold, ice blue, dark green (CAG headers), yellow (flags) - the five brand.*
# keys (DECISIONS D04/D08), in the order the build list states them.
BRAND_KEYS: tuple[str, ...] = ("navy", "gold", "ice_blue", "dark_green", "flag_yellow")

# What each color is used for (FPA_Work_Inventory_CPA.md section M; R183/R216/R217). Reference only,
# for --help and docstrings; no code branches on it.
ROLE: dict[str, str] = {
    "navy": "slide header, footer divider, Division Surplus / Deficit row (R217)",
    "gold": "JHU Contribution Margin row (R216), gold divider line",
    "ice_blue": "cFTE mini-table",
    "dark_green": "CAG task headers",
    "flag_yellow": "flag box on a slide, flag cell in a workbook (R165)",
}

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class BrandError(ValueError):
    """Base for brand palette failures."""


class InvalidColor(BrandError):
    """A brand.* value is not a 6-digit hex color. Names the key and the offending value."""


def _normalize(key: str, value: object) -> str:
    text = str(value).strip()
    if not text.startswith("#"):
        text = f"#{text}"
    text = text.upper()
    if not HEX_RE.match(text):
        raise InvalidColor(f"brand.{key} = {value!r} is not a 6-digit hex color like '#1F4E79'")
    return text


def color(key: str, *, path: Path | str | None = None) -> str:
    """The normalized '#RRGGBB' hex for one brand.* key; raises MissingAssumption if null or absent
    (D08), InvalidColor if the stored value is not a 6-digit hex."""
    if key not in BRAND_KEYS:
        raise BrandError(f"{key!r} is not a brand color; expected one of {BRAND_KEYS}")
    from cpa import config

    value = config.assumption("brand", key, path=path)
    return _normalize(key, value)


def palette(*, path: Path | str | None = None) -> dict[str, str]:
    """Every brand.* color as {key: '#RRGGBB'}, in BRAND_KEYS order; raises on the first null one."""
    return {key: color(key, path=path) for key in BRAND_KEYS}


def flag_text(metric: str, why: str = "", source: str = "") -> str:
    """The CPA flag convention text (R165): states the metric, why it matters to the narrative, and
    the source that would supply it - the same wording cpa.activity_block writes into a workbook cell
    (DECISIONS D24), reused here so a slide's flag box and a workbook's flag cell read identically.
    Never invents `why`/`source` when the caller does not supply them (hard rule 15's spirit)."""
    text = f"{verify.M2_MISSING_MARKER}: {metric} not supplied"
    if why:
        text += f"; needed for {why}"
    if source:
        text += f"; source {source}"
    return text
