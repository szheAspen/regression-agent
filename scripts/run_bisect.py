"""
run_bisect.py

Orchestrates the full git bisect workflow to find the commit that introduced
a regression in Aspen Plus simulation results.

Usage:
    python scripts/run_bisect.py --good <commit-or-tag>
    python scripts/run_bisect.py --good <commit> --bad <commit>
    python scripts/run_bisect.py --good <commit> --repo C:/override/path

Arguments:
    --good   A known-good commit, tag, or branch (e.g. yesterday's baseline tag,
             or the last green commit SHA).  Required.
    --bad    The known-bad commit (default: HEAD — today's failing code).
    --repo   Override the fortran_repo path from config.yaml.

What this script does:
    1. Runs analyze_diffs.py to read the existing diff log and save
       affected_files.json (the list of .bkp files to re-run during bisect).
    2. Shows you how many commits will be tested and how many builds that needs.
    3. Initialises git bisect, marks good/bad, then runs:
           git bisect run python scripts/bisect_test.py
       Git automatically checks out candidate commits; bisect_test.py builds
       and runs simulations at each one and returns 0/1/125.
    4. Reports the first bad commit and resets the repository.
"""

import argparse
import math
import subprocess
import sys
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def git(args: list[str], repo: Path, check: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git"] + args,
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find the commit that introduced a regression using git bisect."
    )
    parser.add_argument(
        "--good",
        required=True,
        help="Known-good commit / tag (e.g. yesterday's HEAD or a baseline tag)",
    )
    parser.add_argument(
        "--bad",
        default="HEAD",
        help="Known-bad commit (default: HEAD)",
    )
    parser.add_argument(
        "--repo",
        help="Override fortran_repo path from config.yaml",
    )
    args = parser.parse_args()

    config = load_config()
    repo_path = Path(args.repo or config["fortran_repo"])
    scripts_dir = Path(__file__).parent

    # ── 1. Identify affected files ──────────────────────────────────────────
    print("\n" + "=" * 62)
    print("  Step 1 — Analysing diff log")
    print("=" * 62)

    result = subprocess.run(
        [sys.executable, str(scripts_dir / "analyze_diffs.py"), "--save-affected"]
    )
    if result.returncode == 0:
        print("\n  Diff log is empty — no regression to investigate. Exiting.")
        sys.exit(0)

    # ── 2. Validate git repo ────────────────────────────────────────────────
    if not (repo_path / ".git").exists():
        print(f"\nERROR: Not a git repository: {repo_path}", file=sys.stderr)
        sys.exit(1)

    # ── 3. Preview the commit range ─────────────────────────────────────────
    print("\n" + "=" * 62)
    print(f"  Step 2 — Commits between  {args.good}  and  {args.bad}")
    print("=" * 62)

    log_result = git(
        ["log", "--oneline", f"{args.good}..{args.bad}"],
        repo_path,
    )
    commits = [ln for ln in log_result.stdout.splitlines() if ln.strip()]

    if not commits:
        print(
            f"\n  No commits found between {args.good} and {args.bad}.\n"
            "  Check that --good and --bad are correct commit references.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\n  {len(commits)} commit(s) to test.")
    print(
        f"  git bisect will find the culprit in "
        f"~{math.ceil(math.log2(len(commits) + 1))} build(s)  "
        f"(vs {len(commits)} builds manually).\n"
    )

    # ── 4. Run git bisect ───────────────────────────────────────────────────
    print("=" * 62)
    print("  Step 3 — Running git bisect")
    print("=" * 62 + "\n")

    git(["bisect", "start"], repo_path, check=True)
    git(["bisect", "bad", args.bad], repo_path, check=True)
    git(["bisect", "good", args.good], repo_path, check=True)

    bisect_run = subprocess.run(
        [
            "git", "bisect", "run",
            sys.executable, str(scripts_dir / "bisect_test.py"),
        ],
        cwd=repo_path,
    )

    # ── 5. Report result ────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    if bisect_run.returncode == 0:
        print("  BISECT COMPLETE")
        print("  The first bad commit is shown above (look for 'is the first bad commit').")
    else:
        print("  BISECT ended with errors — review output above.")
    print("=" * 62)

    # ── 6. Restore the repository ───────────────────────────────────────────
    git(["bisect", "reset"], repo_path)
    print("\n  Repository restored to its original state.\n")


if __name__ == "__main__":
    main()
