#!/usr/bin/env python3
"""Standalone data validator for 三國志略 knowledge base.

Validates all JSON data files against schema.json.
No external dependencies — uses only Python stdlib.

Usage:
    python histrategy/knowledge/scripts/validate_data.py              # validate top-level data
    python histrategy/knowledge/scripts/validate_data.py --scenario 190  # validate scenario data
    python histrategy/knowledge/scripts/validate_data.py --all        # validate everything
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).parent.parent.parent
DATA_DIR = ROOT_DIR / "scenarios" / "three-kingdoms" / "knowledge"
SCHEMA_FILE = DATA_DIR / "schema.json"

DATA_FILES = ["characters.json", "factions.json", "regions.json", "events.json"]

# Mapping of file name → schema definition name
FILE_SCHEMA_MAP = {
    "characters.json": "Character",
    "factions.json": "Faction",
    "regions.json": "Region",
    "events.json": "HistoricalEvent",
}


def load_json(path: Path) -> tuple[Any, str | None]:
    """Load and parse a JSON file, returning (data, error_message)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"File not found: {path}"
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON in {path.name}: {e}"


def load_schema() -> dict | None:
    """Load the schema file."""
    schema_data, err = load_json(SCHEMA_FILE)
    if err:
        print(f"ERROR: Cannot load schema: {err}", file=sys.stderr)
        return None
    return schema_data


# ─── Lightweight schema validator ────────────────────────────────────
# No external dependencies — validates against the same JSON structure
# that jsonschema would use.


def _validate_type(value: Any, expected: Any, path: str) -> list[str]:
    """Validate a value against an expected type description."""
    errors: list[str] = []

    if isinstance(expected, str):
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": dict,
            "array": list,
            "null": type(None),
        }
        py_type = type_map.get(expected)
        if py_type is None:
            return errors
        if not isinstance(value, py_type):
            errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
        if expected == "integer" and isinstance(value, bool):
            errors.append(f"{path}: expected integer, got boolean")

    elif isinstance(expected, list):
        # Union type like ["integer", "null"]
        valid = False
        for t in expected:
            if t == "null" and value is None:
                valid = True
                break
            type_map = {
                "string": str,
                "integer": int,
                "number": (int, float),
                "boolean": bool,
                "object": dict,
                "array": list,
            }
            py_type = type_map.get(t)
            if py_type and isinstance(value, py_type):
                if t == "integer" and isinstance(value, bool):
                    continue
                valid = True
                break
        if not valid:
            types_str = " | ".join(expected)
            errors.append(f"{path}: expected {types_str}, got {type(value).__name__}")

    return errors


def validate_item(item: Any, schema: dict, path: str = "$") -> list[str]:
    """Recursively validate a single item against its schema definition."""
    errors: list[str] = []

    if "type" not in schema:
        return errors  # shouldn't happen for our schemas

    type_errors = _validate_type(item, schema["type"], f"{path}")
    errors.extend(type_errors)
    if type_errors:
        return errors  # can't validate properties if type is wrong

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    for field in required:
        if field not in item:
            errors.append(f"{path}.{field}: required field missing")

    for field, value in item.items():
        field_path = f"{path}.{field}"

        if field in properties:
            prop_schema = properties[field]

            # Validate type
            if "type" in prop_schema:
                errors.extend(_validate_type(value, prop_schema["type"], field_path))

            # Validate enum
            if "enum" in prop_schema and value not in prop_schema["enum"]:
                errors.append(f"{field_path}: '{value}' not in allowed values: {prop_schema['enum']}")

            # Validate integer constraints
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if "minimum" in prop_schema and value < prop_schema["minimum"]:
                    errors.append(f"{field_path}: {value} < minimum {prop_schema['minimum']}")
                if "maximum" in prop_schema and value > prop_schema["maximum"]:
                    errors.append(f"{field_path}: {value} > maximum {prop_schema['maximum']}")

            # Validate array items
            if isinstance(value, list) and "items" in prop_schema:
                item_schema = prop_schema["items"]
                for i, sub_item in enumerate(value):
                    sub_path = f"{field_path}[{i}]"
                    if "type" in item_schema:
                        errors.extend(_validate_type(sub_item, item_schema["type"], sub_path))

    return errors


def validate_cross_references(data_files: dict[str, list]) -> list[str]:
    """Validate cross-file references (faction IDs, character IDs, region IDs)."""
    errors: list[str] = []

    characters = {c["id"]: c for c in data_files.get("characters.json", [])}
    factions = {f["id"]: f for f in data_files.get("factions.json", [])}
    regions = {r["id"]: r for r in data_files.get("regions.json", [])}

    # Build a region name→id lookup since neighbors use Chinese names
    region_names = {r["name"]: r["id"] for r in regions.values()}

    # Characters reference valid factions
    for c in characters.values():
        if c["faction"] not in factions:
            errors.append(
                f"characters.json → {c['name']} (id={c['id']}): faction '{c['faction']}' not found in factions.json"
            )

    # Factions reference valid rulers
    for f in factions.values():
        if f["ruler_id"] and f["ruler_id"] not in characters:
            errors.append(
                f"factions.json → {f['name']} (id={f['id']}): ruler_id '{f['ruler_id']}' not found in characters.json"
            )

    # Faction starting_territories reference valid regions
    for f in factions.values():
        for t in f.get("starting_territories", []):
            if t not in regions:
                errors.append(f"factions.json → {f['name']} (id={f['id']}): territory '{t}' not found in regions.json")

    # Region neighbors reference valid regions (by pinyin ID or Chinese name)
    for r in regions.values():
        for n in r.get("neighbors", []):
            if n not in regions and n not in region_names:
                errors.append(
                    f"regions.json → {r['name']} (id={r['id']}): "
                    f"neighbor '{n}' not found in regions.json (neither ID nor name)"
                )

    return errors


def validate_directory(data_dir: Path, schema_defs: dict) -> tuple[int, int]:
    """Validate all data files in a directory. Returns (file_count, error_count)."""
    total_files = 0
    total_errors = 0

    for filename in DATA_FILES:
        filepath = data_dir / filename
        if not filepath.exists():
            print(f"  SKIP {filename} — file not found")
            continue

        total_files += 1
        data, err = load_json(filepath)
        if err:
            print(f"  FAIL {filename}: {err}")
            total_errors += 1
            continue

        if not isinstance(data, list):
            print(f"  FAIL {filename}: root must be a JSON array, got {type(data).__name__}")
            total_errors += 1
            continue

        schema_name = FILE_SCHEMA_MAP.get(filename)
        item_schema = schema_defs.get(schema_name, {}) if schema_name else {}

        file_errors = 0
        for i, item in enumerate(data):
            result = validate_item(item, item_schema, f"$[{i}]")
            if result:
                file_errors += len(result)
                # Print first 5 errors per file to avoid flooding
                for e in result[:5]:
                    print(f"  FAIL {filename}: {e}")
                if len(result) > 5:
                    print(f"        ... and {len(result) - 5} more errors")

        if file_errors == 0:
            print(f"  OK   {filename} ({len(data)} items)")
        else:
            total_errors += 1
            print(f"       {file_errors} total error(s) in {filename}")

    return total_files, total_errors


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Validate 三國志略 knowledge base data files")
    parser.add_argument(
        "--scenario", type=str, default=None, help="Validate a specific scenario subdirectory (e.g. '190')"
    )
    parser.add_argument("--all", action="store_true", help="Validate top-level data AND all scenario subdirectories")
    parser.add_argument("--no-cross-ref", action="store_true", help="Skip cross-reference validation")
    args = parser.parse_args()

    schema_data = load_schema()
    if schema_data is None:
        sys.exit(1)

    schema_defs = schema_data.get("definitions", {})
    if not schema_defs:
        print("ERROR: No definitions found in schema.json", file=sys.stderr)
        sys.exit(1)

    def _load_data_files(dir_path: Path) -> dict[str, list]:
        """Load all data files from a directory into a dict."""
        result = {}
        for fn in DATA_FILES:
            fp = dir_path / fn
            if fp.exists():
                d, _ = load_json(fp)
                if d is not None:
                    result[fn] = d
        return result

    def _run_xref(data_files: dict) -> int:
        """Run cross-reference validation. Returns error count."""
        if args.no_cross_ref:
            return 0
        xref_errors = validate_cross_references(data_files)
        if xref_errors:
            print(f"\nCross-reference errors ({len(xref_errors)}):")
            for e in xref_errors:
                print(f"  XREF {e}")
            return len(xref_errors)
        else:
            print("\nCross-references: OK")
            return 0

    exit_code = 0

    if args.scenario:
        scenario_dir = DATA_DIR / args.scenario
        if not scenario_dir.is_dir():
            print(f"ERROR: Scenario directory not found: {scenario_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"Validating scenario '{args.scenario}': {scenario_dir}")
        print("-" * 50)
        files, errors = validate_directory(scenario_dir, schema_defs)
        if errors > 0:
            exit_code = 1
        xref_count = _run_xref(_load_data_files(scenario_dir))
        if xref_count > 0:
            exit_code = 1

    elif args.all:
        print("Validating ALL data (top-level + scenarios)")
        print("=" * 50)

        # Top-level
        print("\n[top-level]")
        files, errors = validate_directory(DATA_DIR, schema_defs)
        if errors > 0:
            exit_code = 1
        if _run_xref(_load_data_files(DATA_DIR)) > 0:
            exit_code = 1

        # Scenarios
        for subdir in sorted(DATA_DIR.iterdir()):
            if not subdir.is_dir() or subdir.name.startswith("."):
                continue
            if not any((subdir / fn).exists() for fn in DATA_FILES):
                continue
            print(f"\n[scenario {subdir.name}]")
            files, e = validate_directory(subdir, schema_defs)
            if e > 0:
                exit_code = 1
            if _run_xref(_load_data_files(subdir)) > 0:
                exit_code = 1

    else:
        # Default: validate top-level only
        print(f"Validating: {DATA_DIR}")
        print("-" * 50)
        files, errors = validate_directory(DATA_DIR, schema_defs)
        if errors > 0:
            exit_code = 1
        if _run_xref(_load_data_files(DATA_DIR)) > 0:
            exit_code = 1

    print()
    if exit_code == 0:
        print("Validation PASSED.")
    else:
        print("Validation FAILED — see errors above.")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
