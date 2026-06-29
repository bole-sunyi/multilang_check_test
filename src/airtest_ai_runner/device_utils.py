from __future__ import annotations

"""
设备层辅助工具。

这个文件负责处理“脚本怎么理解设备坐标”这件事，主要包括：
1. 生成 Airtest 设备连接串；
2. 运行 adb 命令读取设备信息；
3. 把 getevent 原始触摸坐标换算成 YAML / Airtest 能直接使用的 0-1 坐标。

对新手来说，可以把这里理解成“坐标翻译器”。
"""

import os
import re
import subprocess
import sys
from collections.abc import Sequence


def build_android_device_uri(adb_host: str, adb_port: int, device_serial: str) -> str:
    """
    统一生成 Android 设备连接串。

    这里强制带上 3 个关键参数：
    1. `cap_method=MINICAP`：截图继续使用当前项目里兼容性较好的 minicap；
    2. `ori_method=MINICAPORI`：让 Airtest 感知当前横竖屏方向，避免横屏内容被保存成竖版语义；
    3. `touch_method=ADBTOUCH`：保持与批量执行器一致的点击方式，减少坐标语义分叉。
    """
    return (
        f"Android://{adb_host}:{adb_port}/{device_serial}"
        "?cap_method=MINICAP&&ori_method=MINICAPORI&&touch_method=ADBTOUCH"
    )


def resolve_airtest_devices(
    default_device_uri: str,
    argv: Sequence[str] | None = None,
) -> list[str]:
    """
    统一决定 Airtest `auto_setup()` 本次应该连接哪台设备。

    优先级：
    1. 如果是 `airtest run ... --device xxx` 启动，就优先使用命令行里的设备；
    2. 如果显式传了 `AIRTEST_DEVICE_URI` 环境变量，就使用环境变量；
    3. 都没有时，再退回脚本里的默认设备。
    """
    args = list(argv or sys.argv)
    for index, arg in enumerate(args):
        if arg == "--device" and index + 1 < len(args):
            resolved = args[index + 1].strip()
            if resolved:
                return [resolved]

    for arg in args:
        if re.match(r"^(Android|Windows|iOS)://", arg):
            return [arg.strip()]

    env_device_uri = os.environ.get("AIRTEST_DEVICE_URI", "").strip()
    if env_device_uri:
        return [env_device_uri]
    return [default_device_uri]


def build_adb_command(serial: str | None = None) -> list[str]:
    """
    构造 adb 基础命令。

    如果显式传了 serial，就优先使用；
    否则退回 `ANDROID_SERIAL` 环境变量；
    两边都没有时，就走 adb 默认当前设备。
    """
    resolved_serial = (serial or os.environ.get("ANDROID_SERIAL", "")).strip()
    command = ["adb"]
    if resolved_serial:
        command.extend(["-s", resolved_serial])
    return command


def run_adb_text(shell_command: str, serial: str | None = None) -> str:
    """执行 adb shell 命令并返回文本输出。"""
    # 统一通过 build_adb_command 组装基础 adb 命令，避免 serial 处理逻辑分散。
    command = build_adb_command(serial) + ["shell", shell_command]
    return subprocess.check_output(command, stderr=subprocess.STDOUT).decode("utf-8", errors="ignore")


def get_touch_display_info(serial: str | None = None) -> dict[str, int]:
    """
    获取“触摸原始坐标 -> Airtest 横屏坐标”转换所需的全部信息。

    返回值包含：
    - `physical_width` / `physical_height`: 设备物理坐标系尺寸（通常是竖屏基准）
    - `orientation`: 当前显示方向，和 Airtest/Android 一致，取值 0/1/2/3
    - `max_x` / `max_y`: getevent 上报触摸坐标的最大量程
    - `upright_width` / `upright_height`: 当前界面实际可见方向下的宽高
    """
    # 这 3 份信息分别来自不同 adb 命令：
    # - wm size：真实分辨率
    # - dumpsys input：当前横竖屏方向
    # - getevent -p：底层触摸量程
    physical_width, physical_height = _parse_physical_size(run_adb_text("wm size", serial))
    orientation = _parse_orientation(run_adb_text("dumpsys input", serial))
    max_x, max_y = _parse_max_xy(run_adb_text("getevent -p", serial))

    if orientation in (1, 3):
        # 横屏时，当前“正向界面”的宽高会和物理方向互换。
        upright_width, upright_height = physical_height, physical_width
    else:
        upright_width, upright_height = physical_width, physical_height

    return {
        "physical_width": physical_width,
        "physical_height": physical_height,
        "orientation": orientation,
        "max_x": max_x,
        "max_y": max_y,
        "upright_width": upright_width,
        "upright_height": upright_height,
    }


def raw_touch_to_upright_normalized(
    raw_x: int,
    raw_y: int,
    display_info: dict[str, int],
) -> tuple[float, float]:
    """
    把 getevent 原始触摸坐标转换成 Airtest/YAML 使用的 0-1 坐标。

    转换过程完全对齐 Airtest 的思路：
    1. 先把 raw_x/raw_y 按触摸量程缩放到“物理显示坐标系”；
    2. 再按当前 orientation 从“原始物理方向”旋转到“当前正向界面”；
    3. 最后再除以正向界面的宽高，得到 YAML 里的 fallback_pos。
    """
    # 先把触摸驱动上报的整数坐标，缩放回“设备物理像素坐标”。
    physical_x = _scale_raw_to_physical(raw_x, display_info["max_x"], display_info["physical_width"])
    physical_y = _scale_raw_to_physical(raw_y, display_info["max_y"], display_info["physical_height"])

    upright_x, upright_y = ori_to_upright(
        (physical_x, physical_y),
        (display_info["physical_width"], display_info["physical_height"]),
        display_info["orientation"],
    )

    # 最后把像素坐标再压回 0-1 区间，供 YAML 里的 fallback_pos 直接使用。
    x_norm = round(_clamp(upright_x / max(display_info["upright_width"], 1), 0.0, 1.0), 4)
    y_norm = round(_clamp(upright_y / max(display_info["upright_height"], 1), 0.0, 1.0), 4)
    return x_norm, y_norm


def ori_to_upright(
    point_xy: tuple[float, float],
    physical_wh: tuple[int, int],
    orientation: int,
) -> tuple[float, float]:
    """
    把“设备原始物理方向”的坐标，转换成“当前正向界面”的坐标。

    这里直接复刻 Airtest 的 `XYTransformer.ori_2_up` 规则，
    保证 quick_click 采到的坐标与脚本 touch((x, y)) 的语义一致。
    """
    x, y = point_xy
    width, height = physical_wh

    if orientation == 1:
        x, y = y, width - x
    elif orientation == 2:
        x, y = width - x, height - y
    elif orientation == 3:
        x, y = height - y, x
    return x, y


def _parse_physical_size(raw_text: str) -> tuple[int, int]:
    """从 `adb shell wm size` 输出中提取物理分辨率。"""
    match = re.search(r"Physical size:\s*(\d+)x(\d+)", raw_text)
    if not match:
        raise RuntimeError("无法从 `adb shell wm size` 中解析物理分辨率。")
    return int(match.group(1)), int(match.group(2))


def _parse_orientation(raw_text: str) -> int:
    """从 dumpsys input 输出中提取当前方向。"""
    match = re.search(r"SurfaceOrientation:\s+(\d+)", raw_text)
    if match:
        return int(match.group(1))

    # 不同 Android / 模拟器版本的 dumpsys 输出格式可能略有差异，
    # 所以这里补一个兼容性兜底解析。
    match = re.search(r"Viewport .* orientation=(\d+)", raw_text)
    if match:
        return int(match.group(1))

    raise RuntimeError("无法从 `adb shell dumpsys input` 中解析当前屏幕方向。")


def _parse_max_xy(raw_text: str) -> tuple[int, int]:
    """从 `adb shell getevent -p` 输出中提取触摸量程。"""
    x_match = re.search(r"0035\s+: value \d+, min \d+, max (\d+)", raw_text)
    y_match = re.search(r"0036\s+: value \d+, min \d+, max (\d+)", raw_text)
    if not x_match or not y_match:
        raise RuntimeError("无法从 `adb shell getevent -p` 中解析触摸量程。")
    return int(x_match.group(1)), int(y_match.group(1))


def _scale_raw_to_physical(raw_value: int, raw_max: int, physical_size: int) -> float:
    """把原始触摸量程映射到物理像素坐标。"""
    if raw_max <= 0:
        raise RuntimeError("触摸量程异常，raw_max 不能小于等于 0。")
    return (raw_value / raw_max) * physical_size


def _clamp(value: float, min_value: float, max_value: float) -> float:
    """把浮点数限制在指定范围内。"""
    return max(min_value, min(max_value, value))
