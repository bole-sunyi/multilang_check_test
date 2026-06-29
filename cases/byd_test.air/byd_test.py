# -*- coding: utf-8 -*-
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from airtest_ai_runner.module_runner import run_module


def main():
    return run_module(
        module_name="byd_test",
        entry_file=__file__,
        project_root=PROJECT_ROOT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
