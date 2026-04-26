#!/usr/bin/env python3
"""
VoxDesk — Test Runner
Thin pytest wrapper — pyproject.toml is the source of truth.
Config values (markers, coverage threshold) come from pyproject.toml, not duplicated here.

Usage:
    python run_tests.py              # Full suite + coverage
    python run_tests.py --unit       # Unit tests only
    python run_tests.py --regress    # Regression tests only
    python run_tests.py --bench      # Benchmarks (report-only)
    python run_tests.py --quick      # Unit + regression, no coverage
"""

import sys
import subprocess


def main():
    args = sys.argv[1:]

    if "--unit" in args:
        cmd = ["pytest", "-m", "unit", "--cov=src", "--cov-report=term-missing", "-v"]
    elif "--regress" in args:
        cmd = ["pytest", "-m", "regression", "-v"]
    elif "--bench" in args:
        # Ensure benchmark output directory exists
        __import__("pathlib").Path(__file__).parent.joinpath(".benchmarks").mkdir(exist_ok=True)
        cmd = [
            "pytest", "-m", "benchmark",
            "--benchmark-only",
            "--benchmark-json=.benchmarks/latest.json",
            "-v",
        ]
    elif "--quick" in args:
        cmd = ["pytest", "-m", "unit or regression", "-v"]
    else:
        # Full suite — coverage from pyproject.toml
        cmd = [
            "pytest",
            "--cov=src",
            "--cov-report=term-missing",
            "-v",
        ]

    # Pass through any extra args (e.g., -k, --tb, -x)
    extra = [a for a in args if a not in ("--unit", "--regress", "--bench", "--quick")]
    cmd.extend(extra)

    print(f"▶ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(__import__("pathlib").Path(__file__).parent))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
