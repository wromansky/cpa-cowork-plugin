"""Run the bundled CPA CLI without installing packages or depending on the repository.

Interface: `python run_cpa.py --check` prints JSON bundle-integrity, Python, exact pinned runtime
requirements (including import viability), and unsupported recalculation status. Exit 1 means
bundle, Python, or dependency validation failed; an unavailable optional engine is reported but
is not claimed validated. Normal usage is `python run_cpa.py <cpa CLI arguments>`; the launcher
uses sibling runtime/cpa and runtime/reference, preserves the caller's working directory, and
never installs or contacts a package index. Healthcheck's default test suite is not shipped: pass
`--path` to an explicit tests directory or it fails with an actionable message.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import platform
import re
import site
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
METADATA = RUNTIME / "dependencies.json"
REQUIRED = ("cpa/__init__.py", "cpa/cli.py", "cpa/config.py", "cpa/periods.py", "reference/assumptions.yaml")


def _version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value):
        raise ValueError(f"invalid dotted version: {value!r}")
    return tuple(int(part) for part in value.split("."))


def _metadata_and_integrity():
    errors = []
    try:
        if RUNTIME.is_symlink():
            raise ValueError("runtime directory may not be a symlink")
        if METADATA.is_symlink():
            raise ValueError("dependency metadata may not be a symlink")
        with METADATA.open("r", encoding="utf-8") as stream:
            metadata = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return None, [f"dependency metadata unavailable or malformed: {type(exc).__name__}: {exc}"]

    schema_errors = []
    if not isinstance(metadata, dict):
        return None, ["dependency metadata must be a JSON object"]
    for key in ("cpa_version", "python_minimum", "requirements", "imports", "files"):
        if key not in metadata:
            schema_errors.append(f"dependency metadata is missing {key!r}")
    if "cpa_version" in metadata and (not isinstance(metadata["cpa_version"], str) or
                                       not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", metadata["cpa_version"])):
        schema_errors.append("dependency metadata cpa_version must be a version string")
    if "python_minimum" in metadata:
        try:
            _version_tuple(metadata["python_minimum"])
        except (TypeError, ValueError) as exc:
            schema_errors.append(f"dependency metadata python_minimum is invalid: {exc}")

    requirements = metadata.get("requirements")
    if not isinstance(requirements, list):
        schema_errors.append("dependency metadata requirements must be a list")
    else:
        for index, requirement in enumerate(requirements):
            if not isinstance(requirement, dict):
                schema_errors.append(f"dependency requirement {index} must be an object")
                continue
            name, version, marker = requirement.get("name"), requirement.get("version"), requirement.get("marker")
            if not isinstance(name, str) or not name.strip():
                schema_errors.append(f"dependency requirement {index} has an invalid name")
            if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version):
                schema_errors.append(f"dependency requirement {index} has an invalid exact version")
            if marker not in (None, "win32", "not-win32"):
                schema_errors.append(f"dependency requirement {index} has an invalid marker")

    imports = metadata.get("imports")
    if not isinstance(imports, dict):
        schema_errors.append("dependency metadata imports must be an object")
    else:
        for name, module in imports.items():
            if (not isinstance(name, str) or not name.strip() or not isinstance(module, str) or
                    not module or any(not part.isidentifier() for part in module.split("."))):
                schema_errors.append(f"dependency metadata import entry {name!r} is invalid")

    files = metadata.get("files")
    if not isinstance(files, dict):
        schema_errors.append("dependency metadata files must be an object")
    else:
        for relative, digest in files.items():
            if (not isinstance(relative, str) or not relative or "\\" in relative or
                    relative.startswith("/") or any(part in ("", ".", "..") for part in relative.split("/"))):
                schema_errors.append(f"invalid bundle path in metadata: {relative!r}")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                schema_errors.append(f"invalid SHA-256 digest for bundle path {relative!r}")
        for name in REQUIRED:
            if name not in files:
                schema_errors.append(f"required bundled file is not declared: {name}")
        if not any(name.startswith("reference/template_maps/") and name.endswith((".yaml", ".yml"))
                   for name in files if isinstance(name, str)):
            schema_errors.append("bundled reference template maps are missing")
    if schema_errors:
        return None, schema_errors

    present = set()
    for path in RUNTIME.rglob("*"):
        if path.is_symlink():
            errors.append(f"runtime contains a symlink: {path.relative_to(RUNTIME).as_posix()}")
        elif path.is_file() and path != METADATA:
            present.add(path.relative_to(RUNTIME).as_posix())
    declared = set(files)
    for extra in sorted(present - declared):
        errors.append(f"unlisted file in runtime bundle: {extra}")
    for missing in sorted(declared - present):
        errors.append(f"bundled file is missing: {missing}")
    for relative, digest in files.items():
        path = RUNTIME / relative
        try:
            actual = path.read_bytes()
        except OSError:
            errors.append(f"bundled file is missing: {relative}")
            continue
        if hashlib.sha256(actual).hexdigest() != digest:
            errors.append(f"bundled file integrity mismatch: {relative}")
    return metadata, errors


def _environment():
    metadata, bundle_errors = _metadata_and_integrity()
    sys.path.insert(0, str(RUNTIME))
    if metadata is not None:
        target = Path(site.getuserbase()) / "cpa-cowork" / str(metadata.get("cpa_version", "unknown"))
        if str(target) not in sys.path:
            sys.path.insert(0, str(target))
    if metadata is not None and not bundle_errors:
        try:
            import cpa
            origin = Path(cpa.__file__).resolve()
            if not origin.is_relative_to(RUNTIME.resolve()):
                bundle_errors.append(f"CPA import did not resolve inside bundled runtime: {origin}")
        except Exception as exc:
            bundle_errors.append(f"CPA import did not resolve inside bundled runtime: {type(exc).__name__}: {exc}")
    bundle = {"available": not bundle_errors, "errors": bundle_errors}
    minimum_text = metadata.get("python_minimum") if metadata else None
    python_ok = False
    if minimum_text:
        try:
            python_ok = sys.version_info[:3] >= _version_tuple(minimum_text)
        except (TypeError, ValueError):
            bundle["available"] = False
            bundle["errors"].append(f"invalid Python minimum in dependency metadata: {minimum_text!r}")
    python_report = {"version": platform.python_version(), "minimum": minimum_text, "available": python_ok}

    missing, mismatch, import_errors = [], [], []
    if metadata is not None:
        for requirement in metadata.get("requirements", []):
            try:
                marker = requirement.get("marker")
                if marker == "win32" and sys.platform != "win32":
                    continue
                if marker == "not-win32" and sys.platform == "win32":
                    continue
                name, expected = requirement["name"], requirement["version"]
                installed = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                missing.append(requirement.get("name", "unknown"))
                continue
            except (AttributeError, KeyError, TypeError) as exc:
                bundle["available"] = False
                bundle["errors"].append(f"invalid requirement metadata: {type(exc).__name__}: {exc}")
                continue
            if installed != expected:
                mismatch.append({"name": name, "expected": expected, "installed": installed})
        for name, module in (metadata.get("imports", {}).items()
                             if isinstance(metadata.get("imports"), dict) else ()):
            try:
                importlib.import_module(module)
            except Exception as exc:
                import_errors.append({"distribution": name, "module": module,
                                      "error": f"{type(exc).__name__}: {exc}"})
    dependencies = {"missing": sorted(set(missing)), "mismatch": sorted(mismatch, key=lambda x: x["name"]),
                    "import_errors": import_errors,
                    "available": metadata is not None and not missing and not mismatch and not import_errors}

    engine = {"available": False, "path": None, "reason": "not checked because bundled runtime is invalid"}
    if bundle["available"]:
        try:
            from cpa.recalc import UNSUPPORTED_REASON
            engine = {"available": False, "path": None, "status": "unsupported",
                      "reason": UNSUPPORTED_REASON}
        except Exception as exc:
            engine = {"available": False, "path": None,
                      "reason": f"engine probe unavailable: {type(exc).__name__}: {exc}"}
    return {"bundle": bundle, "python": python_report, "dependencies": dependencies,
            "engine": engine, "bundle_version": metadata.get("cpa_version") if metadata else None}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    report = _environment()
    if argv == ["--check"]:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["bundle"]["available"] and report["python"]["available"] and report["dependencies"]["available"] else 1
    if not report["bundle"]["available"]:
        print("Bundled CPA runtime is invalid; see `python run_cpa.py --check`. No command was run.", file=sys.stderr)
        return 2
    if not report["python"]["available"]:
        print(f"Python {report['python']['minimum']} or newer is required; found {report['python']['version']}.", file=sys.stderr)
        return 2
    install_request = len(argv) >= 2 and argv[:2] == ["setup", "install"]
    if not report["dependencies"]["available"] and not install_request:
        print("CPA runtime dependencies do not match this bundle; run `setup install` through cpa-setup. "
              "This launcher will not run workflows until dependencies are ready. See `--check`.", file=sys.stderr)
        return 2
    if len(argv) >= 2 and argv[:2] == ["healthcheck", "run"] and "--path" not in argv:
        print("The default repository tests are not included in this plugin payload; pass healthcheck run --path <tests-dir>. "
              "No tests were run.", file=sys.stderr)
        return 2
    from cpa.cli import main as cpa_main
    return cpa_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
