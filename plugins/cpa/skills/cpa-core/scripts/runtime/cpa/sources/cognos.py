"""COGNOS adapter (A5, A6): departmental financials and recruitment cost (CRF) exports. Read only.

`CognosDeptFinancials` (A5, `dept_financials_<FYMM>`) never blocks on a prior-month comparison:
`validate(path, prior=...)` runs the totals through `cpa.reconcile.compare` (D05 tolerance) and
records the outcome in `Validation.extra["prior"]`; the acceptance line ("totals reconcile to the
prior month's file within expected movement", Build List A5) is reported, not enforced -- a real
drift is normal month to month and she reads the note, the file is never failed for it. `CognosCrf`
(A6, `crf_<FYMM>`) has no acceptance beyond non-empty plus manifest, so it adds nothing extra.

The header aliases are FIXTURE - confirm against her file: no COGNOS export has landed yet; the
swap step is `python -m cpa sources cognos validate <her export>` and correcting the aliases below.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from cpa.sources.base import Column, TabularAdapter, Validation, add_source_parser, register_adapter

__all__ = ["DEPT_FINANCIALS_COLUMNS", "CRF_COLUMNS", "CognosDeptFinancials", "CognosCrf", "register_under"]

# FIXTURE - confirm against her file (A5: department plus the report's numeric measure columns).
DEPT_FINANCIALS_COLUMNS: tuple[Column, ...] = (
    Column("department", ("department", "dept"), required=True, key=True),
    Column("measure_1", ("measure 1",), required=True, dtype="number"),
    Column("measure_2", ("measure 2",), dtype="number"),
    Column("measure_3", ("measure 3",), dtype="number"),
)

# FIXTURE - confirm against her file (A6: recruitment compensation package, startup funds, commitments).
CRF_COLUMNS: tuple[Column, ...] = (
    Column("provider", ("provider", "provider name"), required=True, key=True),
    Column("department", ("department", "dept"), dtype="str"),
    Column("compensation_package", ("compensation package",), dtype="number"),
    Column("startup_funds", ("startup funds",), dtype="number"),
    Column("commitment_amount", ("commitment amount",), dtype="number"),
)

_MEASURE_COLUMNS = tuple(c.name for c in DEPT_FINANCIALS_COLUMNS if c.dtype == "number")


@register_adapter
class CognosDeptFinancials(TabularAdapter):
    """A5 departmental financials, one row per department."""

    SOURCE = "cognos"
    DATASET = "dept_financials"
    PREFIX = "dept_financials_"
    COLUMNS = DEPT_FINANCIALS_COLUMNS
    ONE_ROW_PER = ("department",)

    def __init__(self) -> None:
        self._prior: Path | None = None

    def _reconcile_prior(self, path: Path, result: Validation) -> None:
        from cpa import reconcile

        prior_frame = self.load(self._prior)
        current_frame = self.load(path)
        tolerance = reconcile.tolerance_from_assumptions()
        keys = ["department"]
        measures = [m for m in _MEASURE_COLUMNS if m in prior_frame.columns and m in current_frame.columns]
        recon = reconcile.compare(current_frame, prior_frame, keys, measures, tolerance)
        result.extra["prior"] = {
            "path": str(self._prior),
            "tied": recon.tied,
            "notes": list(recon.notes),
            "differences": len(recon.differences),
            "only_here": len(recon.only_in_a),
            "only_prior": len(recon.only_in_b),
        }
        if not recon.tied:
            result.issues.append(f"totals differ from the prior month's file ({self._prior.name}); see "
                                 f"extra['prior'] -- reported only, not a validation failure (A5)")

    def after_validate(self, path: Path, result: Validation) -> Path | None:
        if self._prior is not None and result.status == "passed":
            self._reconcile_prior(path, result)
        return None

    def validate(self, path: Path, *, prior: Path | str | None = None) -> Validation:
        """Validate; with `prior`, also reconcile totals against that prior-month export (A5)."""
        self._prior = Path(prior) if prior is not None else None
        return super().validate(path)


@register_adapter
class CognosCrf(TabularAdapter):
    """A6 recruitment cost (CRF) export: compensation packages, startup funds, commitments."""

    SOURCE = "cognos"
    DATASET = "crf"
    PREFIX = "crf_"
    COLUMNS = CRF_COLUMNS


def register_under(sub: argparse._SubParsersAction) -> None:
    """`sources cognos validate <file> [--dataset] [--prior FILE] [--json]`. Import-cheap."""

    def args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--prior", type=Path, default=None,
                       help="A prior-month dept_financials export to reconcile totals against (A5).")

    def kwargs(a: argparse.Namespace) -> dict[str, Any]:
        return {"prior": a.prior} if a.prior is not None else {}

    add_source_parser(sub, "cognos", "COGNOS exports (A5, A6): departmental financials, CRF recruitment "
                                     "cost. Read only.", validate_args=args, validate_kwargs=kwargs)
