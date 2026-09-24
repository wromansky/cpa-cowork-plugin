---
name: cpa-core
description: Always load for any CPA analyst work - committee decks, APP positions, lookbacks, charge forecasts, SAP or Tableau or COGNOS or MedVitals or Epic or Power BI data, JHM department analyses, SullivanCotter benchmarks, Clinical Practice Association requests. Provides the workspace map, hard rules, and artifact standards every other cpa- skill depends on.
---

# cpa-core

## Workspace
Resolve the workspace root with `python -m cpa config where`; it prints the resolved
`CPA_WORKSPACE` folder and the assumptions file path. Never hard-code the workspace path in another
skill - it is machine-specific (env var, then a OneDrive-synced folder discovered by name).

Folders under the workspace root: `inbox/<system>`, `staging/<workflow>/<run>`, `outbox/<workflow>/<run>`,
`archive/<system>/<date>`, `reference`, `templates`, `requests/<id>`, `logs`.

Nothing leaves `outbox` by automation. The analyst reviews and sends every artifact.

## Recalculation limitation
LibreOffice is excluded everywhere, including the Cowork sandbox. Never discover, install, invoke,
or delegate to it through another skill. No replacement backend is implemented. Recalculation
reports unsupported; never claim CLEAN, verified formula values, or a delivery-ready workbook
when recalculation is required. Stop those workflows and report the blocker.

## Running in a Cowork session
Outside a checked-out developer repository there is no editable install of `cpa`, so a bare
`python -m cpa ...` step cannot assume the package is importable. Every `python -m cpa <args>` step in these skills means:
run the bundled launcher that ships beside this file, with the same arguments.

- Resolve the launcher per invocation, from where this file was actually loaded. The directory that
  holds the loaded `cpa-core/SKILL.md` (the session shows that path when the skill loads) also holds
  `scripts/run_cpa.py`. Never assume an environment variable such as `${CLAUDE_PLUGIN_ROOT}` and never
  reuse a path from an earlier session; resolve it again and use the absolute path you resolved.
- Run the launcher with the sandbox's interpreter for `.py` scripts, not as a standalone executable.
  Pass its resolved absolute path as a single argument, including when the path contains spaces.
  If the default runtime is too old, the launcher probes already-available interpreters on the
  sandbox PATH and delegates to a qualifying one; it never downloads an interpreter.
- Multiple installed copies may coexist (for example, an older plugin directory and a suffixed
  update directory). Use only the launcher beside the skill actually loaded for this session,
  never the first search result. Report `launcher`, `bundle_version`, and `python.executable`
  from the check. If the version differs from the selected plugin's manifest, stop and reload
  the updated plugin in a fresh session; do not mix files or guess another installation path.
- Readiness: pass `--check` to the launcher for a JSON report of the bundle, runtime version,
  dependencies, and recalculation engine. Required-check failures block execution. A `dependencies`
  failure is fixable in-session by the `cpa-setup` skill; a `bundle` or version failure is not. Engine
  availability is reported separately; exit 0 alone does not establish that recalculation is
  available. Run this once per session before the first `cpa` command, and report both the exit
  code and the full report.
- Arguments: the launcher takes the same CLI arguments as the `-m cpa` form, so
  `<resolved cpa-core dir>/scripts/run_cpa.py config where` is the sandbox form of
  `python -m cpa config where`.
- Working directory: the launcher keeps the current directory, so start it in the workspace root and
  workspace-relative paths (`inbox/...`, `outbox/...`, `logs/...`) still resolve.
- Workspace visibility: read the resolved root back in this environment with `python -m cpa config where`
  and confirm that the folder it prints exists. The path she uses on her Windows machine may not be
  visible in a sandbox; never assume it is. If the workspace is missing, empty, or a scratch tree, say
  so before producing any artifact.
- Bundled is not installed: the launcher ships the `cpa` source, not its dependencies. If the
  check reports a missing or mismatched package, run the `cpa-setup` skill: it runs
  `python -m cpa setup install`, which installs exactly the pinned versions the payload declares
  into a versioned user-owned package directory inside the Cowork sandbox, never OS-managed
  locations or the analyst's Windows PC, then re-runs the check with that target visible. No other skill installs,
  upgrades or removes a package; never use `pip`, `pipx`, `uv` or `winget` outside `cpa-setup`.
- The local developer setup (a checked-out repository on Windows, its virtualenv, its editable install)
  is not analyst setup and is never a step in a skill.
- This launcher is the documented interface between these skills and a packaged runtime; it is not yet
  validated in a live Cowork session. Report what `--check` prints; do not assume readiness.

## Fiscal calendar
Fiscal year starts July 1. Fiscal month 1 is July. SAP period label pattern: `001/2024 : July 2023`.
Use `python -m cpa periods fymm|sap-label|from-sap|workdays|prorate` for every conversion; no skill
computes a fiscal period, a workday count, or a proration by hand.

## Hard rules
1. TCC = base salary + supplements. Fringe is never in TCC.
2. SullivanCotter: 2025 AMC column only. TCC for compensation, Work RVUs for productivity. Most
   specific sub-specialty; broader category only when the sub-specialty is not reported, and say so
   on the slide.
3. Percentiles are specific interpolated numbers. "Greater than P75" only when the value exceeds
   every data point.
4. TaskKeys are Hopkins system-assigned. Never fabricate one. Blank when unmatched.
5. cFTE is left blank without proper inputs. cFTE and effort are synonyms.
6. Gross and net collections are distinct. Label which one every time.
7. Every figure carries period, status (actual, budget, forecast, projected, restated), source
   system, and as-of date.
8. A missing activity metric that matters is flagged visibly (yellow box on slide, yellow
   placeholder in workbook). Never omitted silently, never estimated.
9. Period mismatches are prorated explicitly with a label.
10. Department labels pass through `reference/dept_crosswalk.csv`. Unmatched fails loudly.
11. Workbooks above 15 MB stream through `cpa.bigxlsx` (`python -m cpa bigxlsx`). Never load whole.
12. SAP access goes through `cpa.sources.sap`. Workday replaces it mid-2027.
13. JE refunds stop at a ready-to-post draft. Never post.
14. Epic and SAP browser sessions are read and export only. Navigation is pinned to named reports.
15. Any value marked needs-you in `reference/assumptions.yaml` (`python -m cpa config check` lists
    the ones due for quarterly review) is required through `cpa.config.assumption()`. A missing key
    stops the run and names the key. Never default it. A skill that learns a value proposes it with
    `python -m cpa config propose <key> <value> --note "<source>"` and tells the analyst to paste it
    into `assumptions.yaml`; automation never edits that file directly.

## Artifact standards
- Every workbook gets a Verification tab (`cpa-verify`).
- Every P&L gets the M2 activity block (`cpa-activity-block`, once built).
- Live formulas, assumptions in labeled cells, recalculated with zero errors
  (`python -m cpa recalc`).
- Internal files: Calibri, flat, pivot-ready, no decoration, no freeze panes unless asked.
- Slides: see `cpa-format`, once built.

## Run records
Every skill writes its run record with `python -m cpa state record --skill <name> --input <path>
[--input <path> ...] --output <path> [--output <path> ...] --verification <summary>
[--warning <text> ...] --duration <seconds> [--needs-analyst]`. The command writes
`logs/runs/<UTC timestamp>_<skill>.json`; no skill hand-writes that file.

## Notification
At the end of any run, one message: what ran, what is in outbox, what is flagged, what is blocked.
Silent when clean and nothing needs her.
