"""Run each experimental profile separately to avoid same-name module collisions."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
PROFILES = [
    ".",
    "surface",
    "separators",
    "dictionaries",
    "deltas",
    "integration",
    "lifecycle",
    "offshoots",
    "refinement",
    "planning",
    "session",
    "typed_rows",
]

if __name__ == "__main__":
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join([str(ROOT), str(REPO / "src")]),
    }
    failed = []
    for profile in PROFILES:
        print(f"\n=== {profile} ===", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"],
            cwd=ROOT / profile,
            env=env,
        )
        if result.returncode:
            failed.append(profile)
    if failed:
        raise SystemExit("Failed profiles: " + ", ".join(failed))
