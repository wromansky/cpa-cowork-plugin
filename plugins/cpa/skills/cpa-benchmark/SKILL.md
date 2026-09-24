---
name: cpa-benchmark
description: Resolve a SullivanCotter specialty and state a TCC or Work RVU value's 2025 AMC percentile. Called by cpa-app-pnl and cpa-app-slide, or when the user says "percentile", "SullivanCotter", "benchmark this comp", or "what percentile is this".
---

# cpa-benchmark

## When to run
- Called by any skill that needs a SullivanCotter percentile or specialty resolution (cpa-app-pnl,
  cpa-app-slide).
- The user asks for a percentile, a SullivanCotter benchmark, or "benchmark this comp".

## Inputs
| Input | Where | Required |
|---|---|---|
| Department, division, role | given, or read from the position record | yes, unless `--specialty` given |
| Specialty map | `reference/sullivancotter_specialty_map.csv` | yes |
| TCC or Work RVU value | given (as `--value`), or base + supplements | yes |
| 2025 AMC percentile points | given (P25/P50/P75/P90 for the specialty and metric) | yes |

## Steps
1. Read `CPA_WORKSPACE` from cpa-core.
2. If the specialty is not already known, run `python -m cpa benchmarks resolve --dept <dept> --div
   <div> --role <role> [--map <map>] --json` to resolve it against the specialty map.
3. Run `python -m cpa benchmarks percentile (--value <TCC or Work RVU value> | --base <base salary>
   [--supplement <name>=<amount> ...]) --metric ("TCC" | "Work RVUs") --points
   P25=<v>,P50=<v>,P75=<v>,P90=<v> --specialty "<specialty>" [--map <map>] --json`.
   The command interpolates linearly between the reported points, ignores any `--fringe` passed, and
   exits 3 when the specialty is not in the map.
4. Read the JSON result: `percentile`, whether it is an exact hit or above/below every point, and the
   `broader` flag from step 2.
5. State the percentile as the specific interpolated number, or "greater than P<max>" only when the
   value exceeds every reported point, or "below P<min>" only when it is under every reported point.
   Cite the specialty, the metric, and that the points are the 2025 AMC column. When `broader` is
   true, say so - the sub-specialty was not reported.
6. Run `python -m cpa state record --skill cpa-benchmark --input <map path> --verification
   <"resolved" or "N ISSUES"> --duration <seconds>` to write the run record.

## Outputs
- The percentile statement (specialty, metric, value, percentile), returned to the calling skill or
  printed to the user. This skill writes no workbook of its own; the caller writes any benchmark rows
  into its own artifact.
- `logs/runs/<timestamp>_cpa-benchmark.json` - the run record.

## Verify
- The stated percentile is a specific interpolated number, never a range, unless the value is above
  every reported point or below every reported point.
- TCC never includes a fringe amount.
- The specialty cited is the one the map resolved to, and the broader-category flag is stated when set.

## If something is wrong
- `python -m cpa benchmarks resolve` or `percentile` exits 3 (unmapped specialty) -> stop; ask the
  analyst which SullivanCotter specialty applies; she adds the row to
  `reference/sullivancotter_specialty_map.csv`; rerun. Never guess a specialty.
- `percentile` exits 2 (bad argument, for example points that do not rise strictly with the
  percentile) -> stop and report the error text; do not write a run record claiming success.
- A supplement name mentions fringe -> the command drops it from TCC automatically; do not remove it
  yourself or re-add it as a supplement.

## Never
- Never state a percentile as a range unless the value is above every reported point or below every
  reported point.
- Never include fringe in TCC.
- Never default to the broader specialty category without saying so on the artifact.
- Never fall back to a survey column other than the 2025 AMC column.
- Never invent a percentile point that was not supplied.
