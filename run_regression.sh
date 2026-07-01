#!/usr/bin/env bash
# ------------------------------------------------------------
# 这是“整套回归一键启动脚本”。
#
# 注意：多语言自动截图现在推荐分别执行：
#   python cases/stamp_test.air/stamp_test.py
#   python cases/byd_test.air/byd_test.py
#   python cases/atw_test.air/atw_test.py
# 本脚本保留给旧的批量回归/基线 diff 场景使用。
#
# 小白可以把它理解成：
# 1. 使用项目自己的 .venv 隔离环境；
# 2. 检查并安装依赖；
# 3. 然后检查设备配置；
# 4. 最后调用 Python 批量执行器去跑全部模块。
# ------------------------------------------------------------
set -euo pipefail

# 项目根目录，也就是当前这个脚本所在的目录。
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"

# 第 1 步：创建/复用项目专用虚拟环境，避免影响本机其它 Python 项目。
if [ ! -d "${VENV_DIR}" ]; then
  python3 -m venv "${VENV_DIR}"
fi
PYTHON_BIN="${VENV_DIR}/bin/python"
if [ ! -x "${PYTHON_BIN}" ]; then
  echo "未找到项目虚拟环境 Python，请删除 .venv 后重试。"
  exit 1
fi

# 第 2 步：只在项目 .venv 内安装依赖。
"${PYTHON_BIN}" -m pip install --upgrade pip
"${PYTHON_BIN}" -m pip install -r "${PROJECT_DIR}/requirements.txt"

# 第 3 步：检查设备配置文件是否存在。
# 第一次运行时，如果还没有真实配置，就从示例文件复制一份出来让用户先改。
if [ ! -f "${PROJECT_DIR}/config/devices.yaml" ]; then
  cp "${PROJECT_DIR}/config/devices.example.yaml" "${PROJECT_DIR}/config/devices.yaml"
  echo "已生成 config/devices.yaml，请按实际设备修改后重新执行。"
  exit 0
fi

# 第 4 步：准备运行时环境变量。
# PYTHONPATH 让 Python 能找到我们自己写的 src/airtest_ai_runner 包。
export PYTHONPATH="${PROJECT_DIR}/src:${PYTHONPATH:-}"
# ARTIFACTS_ROOT 决定所有截图、日志、报告默认写到哪里。
export ARTIFACTS_ROOT="${ARTIFACTS_ROOT:-/Users/sunyi/Downloads/multilang_check_artifacts}"

# 默认执行包名。
# 如果你要临时改成别的游戏包名，可以在命令前面这样写：
# APP_PACKAGE_NAME="com.play2ever.megatycoon.android" bash run_regression.sh
export APP_PACKAGE_NAME="${APP_PACKAGE_NAME:-slots.pcg.casino.games.free.android}"

# 这里保留重试次数和截图差异阈值两个常用开关，方便新手在命令行里临时覆盖。
export RETRY_COUNT="${RETRY_COUNT:-1}"
export DIFF_THRESHOLD="${DIFF_THRESHOLD:-0.01}"

# 第 5 步：真正启动批量执行器。
# --clean 表示跑之前先清空旧产物目录；
# --auto-detect 表示当配置里没有设备时，可以尝试从 adb devices 自动识别。
"${PYTHON_BIN}" -m airtest_ai_runner.cli \
  --project-root "${PROJECT_DIR}" \
  --devices-config "config/devices.yaml" \
  --cases-dir "cases" \
  --output-dir "${ARTIFACTS_ROOT}" \
  --parallel-workers 4 \
  --retry-count "${RETRY_COUNT}" \
  --diff-threshold "${DIFF_THRESHOLD}" \
  --create-missing-baseline \
  --clean \
  --auto-detect
