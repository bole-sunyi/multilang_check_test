from __future__ import annotations

"""
设备连接辅助工具。

这个文件只负责“怎么找到并连接 Android 设备”：
1. 生成 Airtest 需要的 Android 连接串；
2. 自动发现常见本地模拟器 adb 端口；
3. 在多台设备同时在线时，让用户选择本次执行目标。

当前项目点击动作全部交给 Poco selector，不在这里处理坐标点击。
"""

import os
import re
import subprocess
import sys
from collections.abc import Sequence


DEFAULT_LOCAL_ADB_PORTS = (16448, 7555, 5555, 5554, 62001, 21503)


def build_android_device_uri(adb_host: str, adb_port: int, device_serial: str) -> str:
    """
    统一生成 Android 设备连接串。

    默认对齐游戏 Airtest 仓库已验证的连接方式：
    1. `cap_method=JAVACAP`：兼容当前 Cocos 游戏 Poco 截图链路；
    2. `touch_method=MINITOUCH`：保持游戏 UI 点击行为和主仓库一致。

    如果个别设备需要回退旧方式，可以通过环境变量临时覆盖：
    `AIRTEST_CAP_METHOD`、`AIRTEST_TOUCH_METHOD`、`AIRTEST_ORI_METHOD`。
    """
    cap_method = os.environ.get("AIRTEST_CAP_METHOD", "JAVACAP").strip() or "JAVACAP"
    touch_method = os.environ.get("AIRTEST_TOUCH_METHOD", "MINITOUCH").strip() or "MINITOUCH"
    ori_method = os.environ.get("AIRTEST_ORI_METHOD", "").strip()
    query_parts = [f"cap_method={cap_method}", f"touch_method={touch_method}"]
    if ori_method:
        query_parts.append(f"ori_method={ori_method}")
    query = "&".join(query_parts)
    return (
        f"Android://{adb_host}:{adb_port}/{device_serial}"
        f"?{query}"
    )


def select_android_device_serial(
    adb_host: str = "127.0.0.1",
    preferred_serial: str | None = None,
) -> str:
    """
    自动发现当前 adb 可用设备，并在多设备时让用户选择。

    发现流程：
    1. 先读取已经在线的 `adb devices`；
    2. 再尝试连接常见本地模拟器端口；
    3. 如果只有一台设备，自动选中；如果多台设备，交互选择。
    """
    serials = discover_android_device_serials(adb_host=adb_host)
    preferred = (preferred_serial or os.environ.get("DEVICE_SERIAL", "")).strip()
    if preferred and preferred in serials:
        print(f">>> 已使用指定设备: {preferred}")
        return preferred

    if not serials:
        raise RuntimeError("未发现可用设备，请确认模拟器/手机已启动，且 adb devices 能识别。")

    if len(serials) == 1:
        print(f">>> 已自动选择设备: {serials[0]}")
        return serials[0]

    print(">>> 发现多台可用设备，请选择本次连接目标：")
    for index, serial in enumerate(serials, start=1):
        print(f"    {index}. {serial}")

    while True:
        try:
            raw_choice = input("请输入序号（直接回车选择 1）: ").strip()
        except EOFError:
            raw_choice = ""
        if not raw_choice:
            print(f">>> 已选择设备: {serials[0]}")
            return serials[0]
        if raw_choice.isdigit():
            choice = int(raw_choice)
            if 1 <= choice <= len(serials):
                print(f">>> 已选择设备: {serials[choice - 1]}")
                return serials[choice - 1]
        print("输入无效，请重新输入设备序号。")


def discover_android_device_serials(adb_host: str = "127.0.0.1") -> list[str]:
    """
    返回当前可连接的 Android 设备 serial 列表。

    `adb devices` 只能看到已经连接的 TCP 模拟器。为减少手工指定端口，
    这里会额外尝试连接一组常见本地模拟器端口，再重新读取在线设备。
    可用环境变量 `ADB_DISCOVERY_PORTS=16448,7555` 覆盖候选端口。
    """
    serials = list_connected_adb_devices()
    _ = connect_local_adb_candidates(adb_host=adb_host)
    for serial in list_connected_adb_devices():
        if serial not in serials:
            serials.append(serial)
    return serials


def list_connected_adb_devices() -> list[str]:
    """读取当前 `adb devices` 中状态为 device 的设备。"""
    completed = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=False)
    serials: list[str] = []
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def connect_local_adb_candidates(adb_host: str = "127.0.0.1") -> list[str]:
    """尝试连接常见本地模拟器 adb 端口，并返回本轮尝试成功的 serial。"""
    connected: list[str] = []
    for port in _get_adb_candidate_ports():
        serial = f"{adb_host}:{port}"
        try:
            completed = subprocess.run(
                ["adb", "connect", serial],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except subprocess.TimeoutExpired:
            continue
        output = f"{completed.stdout}\n{completed.stderr}".lower()
        if "connected" in output or "already connected" in output:
            connected.append(serial)
    return connected


def _get_adb_candidate_ports() -> tuple[int, ...]:
    raw_ports = os.environ.get("ADB_DISCOVERY_PORTS", "").strip()
    if not raw_ports:
        return DEFAULT_LOCAL_ADB_PORTS

    ports: list[int] = []
    for raw_port in raw_ports.split(","):
        raw_port = raw_port.strip()
        if raw_port.isdigit():
            ports.append(int(raw_port))
    return tuple(ports) or DEFAULT_LOCAL_ADB_PORTS


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


