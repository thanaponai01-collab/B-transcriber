"""Run the local Rough Cut retirement checks without depending on a shell glob."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", action="store_true")
    args = parser.parse_args()
    if args.acceptance:
        python_tests = ["tests/test_cutdeck_rough_cut_retirement.py"]
        node_tests = ["tests/cutdeck_native_cut.test.cjs", "tests/cutdeck_feature_rough_cut.test.cjs"]
    else:
        python_tests = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_cutdeck*.py")
                              if p.name != "test_cutdeck_live_premiere.py")
        python_tests += ["tests/test_clubfriday.py", "tests/test_pipeline_run_config_fallbacks.py",
                         "tests/test_job_resumability.py"]
        node_tests = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("*.cjs"))
    commands = [[sys.executable, "-m", "pytest", *python_tests, "-q", "-p", "no:cacheprovider"],
                ["node", "--test", *node_tests]]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
