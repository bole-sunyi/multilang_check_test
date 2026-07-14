# -*- coding: utf-8 -*-
"""
stamp_test 模块入口。

入口文件保持很薄，方便新人理解：
1. 这里不维护 Poco selector；
2. 这里不维护截图文件名；
3. 这里只把模块名交给 `run_module()`；
4. 具体流程都在 `config/stamp_test.yaml`。
"""
import sys
from pathlib import Path

# 从 `.air` 用例目录定位项目根目录，并把 `src` 加入 import 路径。
# 这样不管是否设置 PYTHONPATH，直接运行本文件都能找到公共执行器。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from airtest_ai_runner.module_runner import run_module


def main():
    """调用公共执行器运行 stamp_test。"""
    return run_module(
        module_name="stamp_test",
        entry_file=__file__,
        project_root=PROJECT_ROOT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
