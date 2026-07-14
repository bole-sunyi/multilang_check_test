# -*- coding: utf-8 -*-
"""
atw_test 模块入口。

新手可以把这个文件理解成“启动按钮”：
1. 这里不写具体点击步骤；
2. 具体步骤都在 `config/atw_test.yaml`；
3. 公共的连接设备、启动 App、初始化 Poco、截图、写表格、生成报告，
   都交给 `airtest_ai_runner.module_runner.run_module()` 处理。

平时如果只是改点击流程，请改 `config/atw_test.yaml`，不要改这个入口文件。
"""
import sys
from pathlib import Path

# `.air` 用例目录比项目根目录深两层，所以这里往上找两级得到项目根目录。
# 加入 `src` 后，直接运行本文件时也能导入项目里的公共工具包。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from airtest_ai_runner.module_runner import run_module



def main():
    """把 atw_test 的模块名和入口路径交给统一执行器。"""
    return run_module(
        module_name="atw_test",
        entry_file=__file__,
        project_root=PROJECT_ROOT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
