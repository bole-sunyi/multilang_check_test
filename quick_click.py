# -*- coding: utf-8 -*-
# ---------------------------------------------------------------
# 【脚本用途】
# 这是“真实坐标快速采集工具”。
#
# 你可以把它理解成：
# 1. 监听你在模拟器/手机上的真实点击；
# 2. 把底层触摸坐标换算成 YAML 能直接使用的 0-1 百分比坐标；
# 3. 只在项目 coordinate_captures 下保存可直接粘贴的 YAML。
# ---------------------------------------------------------------
import os
import pty
import re
import select
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 项目根目录就是当前脚本所在目录。
PROJECT_ROOT = Path(__file__).resolve().parent
# 把 src 加到搜索路径里，确保能导入我们自己封装的工具包。
sys_path = PROJECT_ROOT / "src"
if str(sys_path) not in sys.path:
    sys.path.insert(0, str(sys_path))

from airtest_ai_runner.device_utils import (
    build_adb_command,
    get_touch_display_info,
    raw_touch_to_upright_normalized,
    select_android_device_serial,
)
from airtest_ai_runner.paths import get_coordinate_capture_dir


LATEST_YAML_FILE = "latest_quick_click.yaml"
HISTORY_YAML_FILE = "quick_click_history.yaml"


def copy_to_clipboard(text: str) -> None:
    """把文本复制到 macOS 剪贴板。"""
    _ = subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)


def start_getevent_process(device_path: str, serial: str) -> tuple[subprocess.Popen[bytes], int]:
    """
    用伪终端方式启动 getevent。
    这样 `adb shell getevent` 会把输出当成 TTY，能更稳定地实时刷出事件，
    避免普通 PIPE 读取时迟迟收不到数据。
    """
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        build_adb_command(serial) + ["shell", "getevent", "-lt", device_path],
        stdin=subprocess.DEVNULL,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)
    return process, master_fd


def iter_getevent_lines(process: subprocess.Popen[bytes], master_fd: int):
    """从伪终端中持续按行读取事件输出。"""
    # getevent 输出是持续流式刷新的，这里用 buffer 把零散字符拼成完整行。
    buffer = ""
    while process.poll() is None:
        ready, _, _ = select.select([master_fd], [], [], 0.5)
        if not ready:
            continue
        chunk = os.read(master_fd, 4096).decode("utf-8", errors="ignore")
        if not chunk:
            continue
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            yield line.strip()


def detect_touch_device(serial: str) -> tuple[str, int, int]:
    """
    自动找到触摸输入设备，并读取它的 X/Y 最大值。
    这样计算出的归一化坐标会比写死分辨率更准确。
    """
    output = subprocess.check_output(
        build_adb_command(serial) + ["shell", "getevent", "-p"],
        stderr=subprocess.STDOUT,
    ).decode("utf-8", errors="ignore")
    current_device = ""
    current_has_direct = False
    current_max_x = None
    current_max_y = None

    # getevent -p 会打印所有输入设备的能力信息。
    # 这里我们的目标是找出“真正负责触摸屏输入”的那一个设备。
    for raw_line in output.splitlines():
        line = raw_line.strip()
        device_match = re.match(r"add device \d+: (.+)", line)
        if device_match:
            if current_device and current_has_direct and current_max_x and current_max_y:
                return current_device, int(current_max_x), int(current_max_y)
            current_device = device_match.group(1)
            current_has_direct = False
            current_max_x = None
            current_max_y = None
            continue

        if "INPUT_PROP_DIRECT" in line:
            # INPUT_PROP_DIRECT 基本可以判断这是直接触摸屏输入，而不是键盘、音量键之类的设备。
            current_has_direct = True

        x_match = re.search(r"0035\s+: value \d+, min \d+, max (\d+)", line)
        if x_match:
            current_max_x = x_match.group(1)

        y_match = re.search(r"0036\s+: value \d+, min \d+, max (\d+)", line)
        if y_match:
            current_max_y = y_match.group(1)

    if current_device and current_has_direct and current_max_x and current_max_y:
        return current_device, int(current_max_x), int(current_max_y)

    raise RuntimeError("没有找到可用的触摸输入设备，无法开始坐标拾取。")


def ask_step_remark(index: int) -> str:
    """
    为单个坐标补备注。
    直接回车则使用默认备注，减少手工输入成本。
    """
    default_remark = f"第{index}步点击"
    try:
        user_input = input(f"\n请输入第 {index} 个坐标的备注（直接回车使用“{default_remark}”）: ").strip()
    except EOFError:
        user_input = ""
    return user_input or default_remark


def collect_step_remarks(collected_points: list[str]) -> list[dict[str, str]]:
    """
    在坐标采集结束后，再统一补备注。

    这样用户可以先连续点击多个位置，不会被每一步的输入提示打断，
    更适合双击、连点两个节点之类需要连续操作的场景。
    """
    if not collected_points:
        return []

    print("\n>>> 开始为本次采集的坐标补备注。")
    print(">>> 如果某一步没有特殊说明，直接回车即可使用默认备注。")
    points_with_notes: list[dict[str, str]] = []
    for index, point in enumerate(collected_points, start=1):
        print(f">>> 第 {index:02d} 个坐标: {point}")
        try:
            remark = ask_step_remark(index)
        except KeyboardInterrupt:
            print("\n>>> 备注输入被中断，剩余步骤将自动使用默认备注。")
            remark = f"第{index}步点击"
            points_with_notes.append({"point": point, "remark": remark})
            for rest_index, rest_point in enumerate(collected_points[index:], start=index + 1):
                points_with_notes.append({"point": rest_point, "remark": f"第{rest_index}步点击"})
            return points_with_notes
        points_with_notes.append({"point": point, "remark": remark})
        print(f"    已记录备注: {remark}")
    return points_with_notes


def build_yaml_snippet(points_with_notes: list[dict[str, str]]) -> str:
    """
    生成可以直接粘贴到模块 YAML 配置文件里的 steps 片段。
    现在项目里主要给 stamp_test / byd_test / atw_test 这三类模块复用。
    """
    lines: list[str] = []
    for index, item in enumerate(points_with_notes, start=1):
        lines.extend(
            [
                f'  - name: "【操作】{item["remark"]}"',
                '    action: "click"',
                f"    fallback_pos: {item['point']}",
                f"    sleep_after: 1  # 第 {index} 步点击后等待 1 秒，再截图，便于观察界面反馈",
                "    snapshot_after: true",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def save_coordinate_capture_files(
    points_with_notes: list[dict[str, str]],
    serial: str,
    yaml_text: str,
) -> tuple[Path, Path]:
    """只保存本次最新 YAML，并把本次 YAML 追加到历史记录。"""
    output_dir = get_coordinate_capture_dir()
    cleanup_coordinate_capture_outputs(output_dir)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    latest_yaml_path = output_dir / LATEST_YAML_FILE
    history_yaml_path = output_dir / HISTORY_YAML_FILE
    _ = latest_yaml_path.write_text(yaml_text, encoding="utf-8")

    history_entry = build_history_entry(
        generated_at=generated_at,
        serial=serial,
        point_count=len(points_with_notes),
        yaml_text=yaml_text,
    )
    with history_yaml_path.open("a", encoding="utf-8") as fp:
        _ = fp.write(history_entry)
    return latest_yaml_path, history_yaml_path


def cleanup_coordinate_capture_outputs(output_dir: Path) -> None:
    """删除旧的单次产物，只保留总历史记录。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    for item in output_dir.iterdir():
        if not item.is_file() or item.name == HISTORY_YAML_FILE:
            continue
        item.unlink()


def build_history_entry(
    *,
    generated_at: str,
    serial: str,
    point_count: int,
    yaml_text: str,
) -> str:
    """生成追加到历史 YAML 的分段内容。"""
    return (
        "\n"
        "# ======================================================================\n"
        f"# 运行时间: {generated_at}\n"
        f"# 连接设备: {serial}\n"
        f"# 坐标数量: {point_count}\n"
        "# ======================================================================\n"
        f"{yaml_text.rstrip()}\n"
    )


def append_debug_log(message: str) -> None:
    """保留调试调用入口，但不再写额外文件。"""
    _ = message


def is_touch_down(line: str) -> bool:
    """兼容文本格式和十六进制格式的按下事件判断。"""
    return (
        "BTN_TOUCH" in line and (" DOWN" in line or line.endswith("00000001"))
    ) or (
        "ABS_MT_TRACKING_ID" in line and not line.endswith("ffffffff")
    )


def is_touch_up(line: str) -> bool:
    """
    兼容文本格式和十六进制格式的抬起事件判断。
    当前 MuMu 模拟器最关键的是 `BTN_TOUCH UP`，之前脚本就是漏判了这个分支。
    """
    return (
        "BTN_TOUCH" in line and (" UP" in line or line.endswith("00000000"))
    ) or (
        "ABS_MT_TRACKING_ID" in line and line.endswith("ffffffff")
    )


def capture_multiple_coordinates() -> None:
    """
    【多点连续拾取工具】
    运行一次后可以连续点击多个位置。
    - 每点一次，立即记录 1 个坐标
    - 最新坐标会立即复制到剪贴板
    - 先连续点完，再统一输入每一步备注
    - 按 Ctrl+C 手动结束
    - 结束后只会在 coordinate_captures 下生成最新 YAML 和历史 YAML
    """
    print(">>> 正在初始化极速拾取...")
    print(">>> 初始化完成后，请直接在模拟器/手机界面连续点击多个位置。")
    print(">>> 每点击一次，就会新增一个坐标，并立即复制最新坐标。")
    print(">>> 本次改为先连续采集，等你按 Ctrl+C 结束后，再统一补备注。")
    print(">>> 按 Ctrl+C 停止，停止后会自动保存最新 YAML，并追加到历史 YAML。")

    try:
        serial = select_android_device_serial()
        device_path, max_x, max_y = detect_touch_device(serial)
        display_info = get_touch_display_info(serial)
    except Exception as exc:
        print(f"错误: {exc}")
        return

    print(f">>> 当前连接设备: {serial}")
    print(f">>> 监听设备: {device_path}")
    print(f">>> 触摸量程: x=0~{max_x}, y=0~{max_y}")
    print(
        f">>> 屏幕方向: {display_info['orientation']} "
        + f"(物理分辨率 {display_info['physical_width']}x{display_info['physical_height']} "
        + f"-> 当前正向分辨率 {display_info['upright_width']}x{display_info['upright_height']})"
    )

    process, master_fd = start_getevent_process(device_path, serial)

    last_x = None
    last_y = None
    touch_active = False
    collected_points: list[str] = []

    try:
        for line_str in iter_getevent_lines(process, master_fd):

            if is_touch_down(line_str):
                # 只要识别到按下，就进入“正在触摸”状态。
                touch_active = True
                append_debug_log(f"TOUCH_DOWN: {line_str} => touch_active={touch_active}")

            if is_touch_up(line_str):
                # 一旦识别到抬起，就说明这次点击动作结束了。
                touch_active = False
                append_debug_log(f"TOUCH_UP: {line_str} => touch_active={touch_active}")

            if "ABS_MT_POSITION_X" in line_str or "0035" in line_str:
                match = re.search(r"([0-9a-fA-F]{1,8})$", line_str)
                if match:
                    last_x = int(match.group(1), 16)
                    append_debug_log(f"X: raw={last_x}")

            if "ABS_MT_POSITION_Y" in line_str or "0036" in line_str:
                match = re.search(r"([0-9a-fA-F]{1,8})$", line_str)
                if match:
                    last_y = int(match.group(1), 16)
                    append_debug_log(f"Y: raw={last_y}")

            # 在手指抬起时输出最终落点，避免一次点击被重复记录多次。
            if not touch_active and last_x is not None and last_y is not None:
                # 这里不能再直接用 raw/max 了。
                # 因为很多模拟器底层触摸坐标仍以“竖屏物理方向”为基准，
                # 但你眼前看到的界面已经是横屏。
                # 如果不先按 orientation 旋转到当前正向界面，
                # 最终写进 YAML 的 fallback_pos 就会和实际截图方向对不上。
                x_norm, y_norm = raw_touch_to_upright_normalized(last_x, last_y, display_info)
                result = f"[{x_norm}, {y_norm}]"
                append_debug_log(
                    f"COMMIT: raw=({last_x}, {last_y}) "
                    + f"orientation={display_info['orientation']} "
                    + f"upright=({x_norm}, {y_norm})"
                )

                # 不再过滤“和上一条相同”的坐标。
                # 因为双击或连续点击同一位置，本来就应该保留成两步独立操作。
                collected_points.append(result)
                copy_to_clipboard(result)
                print(f"{len(collected_points):02d}. {result}  <- 已复制最新坐标")

                last_x = None
                last_y = None

    except KeyboardInterrupt:
        # 用户按 Ctrl+C 表示“采集结束，开始收口整理结果”。
        process.terminate()
        os.close(master_fd)
        points_with_notes = collect_step_remarks(collected_points)
        yaml_text = build_yaml_snippet(points_with_notes)

        if collected_points:
            latest_yaml_path, history_yaml_path = save_coordinate_capture_files(
                points_with_notes,
                serial,
                yaml_text,
            )
            copy_to_clipboard(yaml_text or "\n".join(collected_points))
            print("\n>>> 已停止监听。")
            print(f">>> 共采集 {len(collected_points)} 个坐标。")
            print(f">>> 最新模块 YAML 片段已保存到: {latest_yaml_path}")
            print(f">>> 历史 YAML 记录已追加到: {history_yaml_path}")
            print(">>> 已将模块 YAML 片段复制到剪贴板。")
        else:
            cleanup_coordinate_capture_outputs(get_coordinate_capture_dir())
            print("\n>>> 已停止监听，但本次没有采集到坐标。")


if __name__ == "__main__":
    capture_multiple_coordinates()
