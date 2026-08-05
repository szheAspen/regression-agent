"""
bisect_test.py

Passed directly to "git bisect run":
    git bisect run python scripts/bisect_test.py

git bisect will call this script at each candidate commit.  The script must
return one of three exit codes (git bisect convention):

    0   — GOOD  : this commit produces results matching the baseline (no diff)
    1   — BAD   : this commit introduces differences vs the baseline
    125 — SKIP  : cannot test this commit (e.g. build failure); git bisect
                  will skip it and try a neighbouring commit instead

Workflow per bisect step:
    1. Read affected_files.json  (written by analyze_diffs.py --save-affected)
    2. Build the Aspen Plus engine  (Fortran compile)
    3. Run simulations for affected files only
    4. Run the comparison script to regenerate the diff log
    5. Check the diff log — empty → GOOD, non-empty → BAD
"""

import json
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


def run_step(cmd: list[str], timeout: int, label: str) -> int:
    """Run a subprocess step, stream its output, and return the exit code."""
    print(f"\n[bisect] ── {label} ──")
    print(f"[bisect] cmd: {' '.join(cmd)}")
    result = subprocess.run(cmd, timeout=timeout)
    print(f"[bisect] exit code: {result.returncode}")
    return result.returncode


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    config = load_config()
    repo_root = Path(__file__).parent.parent

    # ── 1. Load affected files ──────────────────────────────────────────────
    cache_path = repo_root / config["affected_files_cache"]
    if not cache_path.exists():
        print(
            "[bisect] ERROR: affected_files.json not found.\n"
            "         Run  python scripts/analyze_diffs.py --save-affected  first.",
            file=sys.stderr,
        )
        sys.exit(125)

    affected_files: list[str] = json.loads(cache_path.read_text(encoding="utf-8"))
    if not affected_files:
        print("[bisect] No affected files — nothing to test. Marking as GOOD.")
        sys.exit(0)

    print(f"\n[bisect] Testing {len(affected_files)} affected file(s):")
    for f in affected_files:
        print(f"  {f}")

    # ── 2. Build Aspen Plus engine ──────────────────────────────────────────
    rc = run_step(
        cmd=[config["build_script"]],
        timeout=config.get("build_timeout", 1800),
        label="Build Aspen Plus engine",
    )
    if rc != 0:
        print("[bisect] Build FAILED — skipping this commit (exit 125).")
        sys.exit(125)

    # ── 3. Run simulations for affected files only ──────────────────────────
    # TODO: Adjust this block to match how your run_script accepts file arguments.
    #
    # Option A — called once per file (default):
    #   run_step([config["run_script"], filepath], ...)
    #
    # Option B — called once with all files as a comma-separated list:
    #   run_step([config["run_script"], ",".join(affected_files)], ...)
    #
    # Option C — write a temp file list and pass its path:
    #   list_file = repo_root / "bisect_filelist.txt"
    #   list_file.write_text("\n".join(affected_files))
    #   run_step([config["run_script"], "--filelist", str(list_file)], ...)

    for filepath in affected_files:
        run_step(
            cmd=[config["run_script"], filepath],
            timeout=config.get("sim_timeout", 3600),
            label=f"Simulation: {Path(filepath).name}",
        )
        # We intentionally ignore non-zero exit codes here; a convergence failure
        # is itself a difference that the comparison step will catch.

    # ── 4. Run comparison to regenerate the diff log ────────────────────────
    rc = run_step(
        cmd=[config["compare_script"]],
        timeout=300,
        label="Compare results vs baseline",
    )
    if rc not in (0, 1):
        # Unexpected error in comparison script itself — skip this commit
        print(f"[bisect] Comparison script returned unexpected code {rc} — skipping.")
        sys.exit(125)

    # ── 5. Evaluate diff log ─────────────────────────────────────────────────
    diff_log = Path(config["diff_log"])
    if not diff_log.exists():
        print("[bisect] WARNING: diff log not found after comparison — treating as BAD.")
        sys.exit(1)

    content = diff_log.read_text(encoding="utf-8", errors="replace").strip()

    if content:
        print("\n[bisect] Differences FOUND — marking this commit as BAD.")
        sys.exit(1)
    else:
        print("\n[bisect] No differences — marking this commit as GOOD.")
        sys.exit(0)


if __name__ == "__main__":
    main()
