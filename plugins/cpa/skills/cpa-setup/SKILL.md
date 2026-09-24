---
name: cpa-setup
description: Provision the Cowork sandbox interpreter for the CPA runtime. Run when the user says "set up CPA" or "install CPA", or when the cpa-core runtime check reports missing or mismatched packages.
---

## When to run
- The user asks to set up or install the CPA runtime in this Cowork session.
- The cpa-core runtime check (the bundled launcher's `--check` report) exits nonzero on a
  dependency failure: a missing or mismatched pinned package.
- A workflow skill stops because a required package is unavailable in this session.

## Inputs
- The mounted `cpa-core` skill directory: resolve its path from where its SKILL.md was loaded,
  per the cpa-core launcher convention.
- No workspace inputs. No analyst files are read, written or sent.

## Steps
1. Run the runtime check documented in cpa-core (pass `--check` to the bundled launcher) and
   record the JSON report and exit code. Use only the runtime provided inside this Cowork
   session. The launcher selects an already-available compatible interpreter when necessary.
   Report its chosen executable, launcher path, and bundle version. Confirm the bundle version
   matches the selected plugin's manifest; stop on a mismatch, not a fallback to an older copy.
   Never use or install a runtime on the analyst's Windows PC.
2. If the check exits 0, the runtime is ready for workflow skills; go to step 5.
3. If the check fails on `dependencies` (missing or mismatched pinned packages), run
   `python -m cpa setup install` through the bundled launcher. It installs only exact pins into
   the versioned user-owned package target inside Cowork's sandbox (not OS-managed packages or the
   analyst's Windows PC); this target-based install works with OS-managed runtimes and does not require
   a local tool install or a `--break-system-packages` override.
4. Re-run the runtime check. It must exit 0 before any workflow skill runs in this session.
5. Write the run record: `python -m cpa state record --skill cpa-setup --verification "<ready:
   which pins were satisfied or installed; engine availability as reported>"`. If the workspace
   does not exist yet, say so in the reply instead; the first workflow run writes its own record.

## Outputs
- A ready session interpreter: every applicable pinned runtime package importable at the exact
  declared version.
- The final `--check` JSON report, quoted in the reply and recorded in `logs/runs/` when the
  workspace exists.

## Verify
- The final runtime check exits 0 with no missing or mismatched pins.
- The legacy `engine` report says unsupported. LibreOffice is excluded everywhere; never probe
  or invoke it, including through another skill. Setup can finish, but workflows requiring
  recalculated figures must stop until an approved backend is implemented.

## If something is wrong
- `python -m cpa setup install` exits nonzero (pip failed, timed out, or the re-check still
  shows missing pins): stop and report the printed JSON verbatim. Do not retry with different
  packages, versions or installers.
- The check fails on `bundle` integrity or no Cowork-provided interpreter meets the required
  minimum version: setup cannot fix those; report the failing key and stop. Never ask the analyst
  to install software on her Windows PC.
- pip is not importable in the session interpreter: report the controlled error; do not install
  a different interpreter.

## Never
- Never install, upgrade or remove any package other than through `python -m cpa setup install`
  with the payload's exact pins.
- Never install software on the user's machine (an interpreter, LibreOffice, Git or any add-on);
  setup provisions only this session's sandbox interpreter.
- Never change a pin, add a package, or use a version range to make the check pass.
- Never touch the workspace, assumptions or any analyst file during setup.
