# -*- coding: utf-8 -*-
"""
byd_test 模块入口。

这个文件只负责把“我要跑 byd_test”告诉统一执行器。
真正的业务步骤写在 `config/byd_test.yaml` 里。

如果后续要恢复完整 byd 自动点击链路，请先用 `dump_current_screen.py`
导出目标页面的 `nodes_steps.yaml`，再把 `name + chain` 复制到配置文件。
"""
import sys
from pathlib import Path

# 允许用户直接运行 `python cases/byd_test.air/byd_test.py`，
# 不需要额外安装本项目为 Python 包。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from airtest_ai_runner.module_runner import run_module


def main():
    """调用公共执行器运行 byd_test。"""
    return run_module(
        module_name="byd_test",
        entry_file=__file__,
        project_root=PROJECT_ROOT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
