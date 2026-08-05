"""
analyze_diffs.py

Reads the diff log and produces a structured summary of which simulation files
have differences vs the baseline, and what changed in each.

Usage:
    python scripts/analyze_diffs.py
    python scripts/analyze_diffs.py --diff-log C:/path/to/diff.log
    python scripts/analyze_diffs.py --save-affected        # also writes affected_files.json

Exit code:
    0 = no differences found (clean run)
    1 = differences found
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Diff log parser
# ---------------------------------------------------------------------------
# TODO: Adjust parse_diff_log() to match your actual diff log format.
#
# The function should return a dict mapping each simulation filename to the
# list of diff lines that belong to it.
#
# Two common formats are handled below:
#
#  Format A — sectioned by file header:
#    === results/case01.out ===
#    - old value
#    + new value
#    === results/case02.out ===
#    ...
#
#  Format B — flat list of file references scattered through the log:
#    Diff found in case01.out: ...
#    Diff found in case02.out: ...
#
# If neither matches your format, replace the body of parse_diff_log()
# with custom parsing logic.
# ---------------------------------------------------------------------------

def parse_diff_log(diff_log_path: str) -> dict[str, list[str]]:
    """Return {filename: [diff_lines]}. Empty dict means no differences."""
    path = Path(diff_log_path)
    if not path.exists():
        print(f"ERROR: diff log not found: {diff_log_path}", file=sys.stderr)
        sys.exit(1)

    content = path.read_text(encoding="utf-8", errors="replace")
    if not content.strip():
        return {}

    # --- Format A: file-section headers ---------------------------------
    # Matches lines like:
    #   === some/file.out ===
    #   File: some/file.out
    #   >>> some/file.out
    header_re = re.compile(
        r"^(?:={3,}\s*(.+?)\s*={3,}|File:\s*(.+?)\s*|>{3,}\s*(.+?)\s*)$",
        re.MULTILINE,
    )
    matches = list(header_re.finditer(content))

    if matches:
        affected: dict[str, list[str]] = {}
        for i, m in enumerate(matches):
            filename = next(g for g in m.groups() if g is not None).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            lines = [ln for ln in content[start:end].splitlines() if ln.strip()]
            if lines:
                affected[filename] = lines
        return affected

    # --- Format B: flat — extract filenames from the log text -----------
    file_re = re.compile(r"[\w\-./\\]+\.(?:bkp|out|eorep)\b", re.IGNORECASE)
    found = list(dict.fromkeys(file_re.findall(content)))  # dedupe, preserve order
    if found:
        return {f: ["(see diff log for details)"] for f in found}

    # --- Fallback: unknown format — treat whole log as one block --------
    return {"(unknown files)": content.strip().splitlines()}


def print_summary(affected: dict[str, list[str]]) -> None:
    if not affected:
        print("\n  No differences found — regression is clean.")
        return

    width = 62
    print(f"\n{'=' * width}")
    print(f"  REGRESSION SUMMARY  —  {len(affected)} file(s) with differences")
    print(f"{'=' * width}")

    for filename, diffs in affected.items():
        print(f"\n  FILE : {filename}")
        print(f"  {'─' * (width - 2)}")
        preview = diffs[:20]
        for line in preview:
            print(f"    {line}")
        if len(diffs) > 20:
            print(f"    ... ({len(diffs) - 20} more lines — check diff log)")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze regression diff log")
    parser.add_argument("--diff-log", help="Override diff_log path from config.yaml")
    parser.add_argument(
        "--save-affected",
        action="store_true",
        help="Save affected filenames to affected_files.json (needed before bisect)",
    )
    args = parser.parse_args()

    config = load_config()
    diff_log_path = args.diff_log or config["diff_log"]

    affected = parse_diff_log(diff_log_path)
    print_summary(affected)

    if args.save_affected:
        cache_path = Path(__file__).parent.parent / config["affected_files_cache"]
        cache_path.write_text(
            json.dumps(sorted(affected.keys()), indent=2), encoding="utf-8"
        )
        print(f"  Affected files list saved to: {cache_path}")

    sys.exit(0 if not affected else 1)


if __name__ == "__main__":
    main()
