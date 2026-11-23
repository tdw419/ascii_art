#!/usr/bin/env python3
"""Create candidate reports or the curated showcase animations."""

import argparse
import json
from pathlib import Path
import sys

from example_pipeline import (
    THEMES, generate_showcase, load_showcase, validate_showcase,
    write_candidate_report,
)


PROJECT_ROOT = Path(__file__).resolve().parent


def _load_entries(clean_root):
    manifest = clean_root / "manifest.jsonl"
    if not clean_root.is_dir():
        raise FileNotFoundError(
            f"missing clean corpus: {clean_root}; run python3 build_clean_set.py")
    if not manifest.is_file():
        raise FileNotFoundError(
            f"missing clean manifest: {manifest}; run python3 build_clean_set.py")
    entries = []
    with manifest.open() as lines:
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{manifest}:{line_number}: invalid JSON: {error.msg}") from error
    return entries


def _parser():
    parser = argparse.ArgumentParser(
        description="Generate curated ASCII examples or a candidate report.")
    parser.add_argument(
        "--report", metavar="PATH",
        help="write ranked candidates only; PATH is relative to the project root",
    )
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        clean_root = PROJECT_ROOT / "corpus" / "clean"
        entries = _load_entries(clean_root)
        if args.report is None:
            showcase_path = PROJECT_ROOT / "examples" / "showcase.json"
            showcase = load_showcase(showcase_path)
            showcase_entries = validate_showcase(showcase, clean_root)
            generate_showcase(showcase_entries, PROJECT_ROOT / "examples")
            return 0
        output_path = Path(args.report)
        if output_path.is_absolute():
            raise ValueError("--report path must be project-relative")
        project_root = PROJECT_ROOT.resolve()
        output_path = (project_root / output_path).resolve(strict=False)
        try:
            output_path.relative_to(project_root)
        except ValueError as error:
            raise ValueError(
                "--report path must resolve inside the project root") from error
        write_candidate_report(entries, clean_root, output_path, THEMES)
        return 0
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
