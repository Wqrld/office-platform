# The checks are scripts, not a package: put tests/ and the repo root on the path so the
# unit tests import them by module name.
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT)]
