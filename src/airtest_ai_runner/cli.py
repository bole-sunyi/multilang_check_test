from __future__ import annotations

"""
批量回归执行器命令行入口。

如果把整个项目想成一条流水线，这个文件就是“总调度台”：
1. 读取设备和用例配置；
2. 分发任务到不同设备；
3. 收集每次执行的日志、截图差异和基线处理结果；
4. 最后生成统一报告。
"""

import argparse
import json
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml

from .image_diff import compare_directories, refresh_baseline_from_current
from .log_utils import sanitize_airtest_log
from .report import generate_reports


def main() -> int:
    """
    整套回归执行器的总入口。

    你可以把这个函数理解成“批量调度总控台”：
    1. 先读命令行参数和设备配置；
    2. 再找出要跑的设备、要跑的用例；
    3. 然后并行分发给不同设备执行；
    4. 最后把所有结果汇总成报告。
    """
    # 第 1 步：解析命令行参数。
    # 例如 --project-root、--clean、--retry-count 这些开关都会在这里读进来。
    parser = build_parser()
    args = parser.parse_args()

    # 第 2 步：定位项目根目录和设备配置文件。
    # 这里统一转成绝对路径，避免从不同目录启动时找不到文件。
    project_root = Path(args.project_root).resolve()
    config_path = project_root / args.devices_config
    config = load_config(config_path)

    # 第 3 步：根据命令行参数 + YAML 配置，推导出真正要使用的目录。
    # cases_dir: 放用例 .air 目录的位置
    # output_dir: 本次回归产物输出目录
    # baseline_dir: 基线图目录
    cases_dir = project_root / config.get("cases_dir", args.cases_dir)
    output_dir = project_root / config.get("output_dir", args.output_dir)
    baseline_dir = project_root / config.get("baseline_dir", "baselines")

    # 第 4 步：如果用户要求 clean，就先把旧产物清空。
    # 这样本次输出目录里只会保留最新一轮回归结果。
    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 第 5 步：准备执行名单。
    # devices 是“哪些设备要跑”
    # cases 是“哪些用例要跑”
    devices = resolve_devices(config, args.auto_detect)
    cases = discover_cases(cases_dir)
    if not devices:
        print("未找到可用设备，请检查 config/devices.yaml 或 adb devices。", file=sys.stderr)
        return 1
    if not cases:
        print(f"未在 {cases_dir} 发现 .air 用例目录。", file=sys.stderr)
        return 1

    # 第 6 步：把这轮运行的关键配置整理成统一字典。
    # 后面子进程执行时、最终生成报告时，都会复用这份参数。
    runtime_options = build_runtime_options(config, args)
    worker_count = min(len(devices), runtime_options["parallel_workers"])
    run_started_at = datetime.now().isoformat(timespec="seconds")

    # 第 7 步：并行跑设备。
    # 一个设备会拿到完整的 cases 列表，并按顺序逐个执行。
    # 如果设备比设置的并行数少，就按设备数量来决定并发上限。
    all_results: list[dict] = []
    with ProcessPoolExecutor(max_workers=max(worker_count, 1)) as executor:
        futures = [
            executor.submit(
                run_device_cases,
                device,
                cases,
                output_dir,
                baseline_dir,
                runtime_options,
            )
            for device in devices
        ]
        for future in as_completed(futures):
            all_results.extend(future.result())

    # 第 8 步：把最原始的执行结果保存成 raw_results.json。
    # 这份文件最适合后面做二次分析，或者排查“报告里为什么是这个结果”。
    result_bundle = {
        "started_at": run_started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "runtime_options": runtime_options,
        "results": all_results,
    }
    (output_dir / "raw_results.json").write_text(
        json.dumps(result_bundle, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 第 9 步：基于全部结果生成给人看的报告文件。
    report_json, report_md, report_html = generate_reports(
        all_results,
        output_dir,
        runtime_options=runtime_options,
    )
    print(f"执行完成，HTML 报告：{report_html}")
    print(f"Markdown 报告：{report_md}")
    print(f"结构化结果：{report_json}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """
    定义命令行支持哪些参数。

    这一层主要服务两类人：
    1. 写脚本的人，可以通过参数临时覆盖配置；
    2. 小白用户，可以直接运行 run_regression.sh，不必手工记这些参数。
    """
    parser = argparse.ArgumentParser(description="Airtest 多设备并行回归执行器")
    parser.add_argument("--project-root", default=".", help="项目根目录")
    parser.add_argument("--devices-config", default="config/devices.yaml", help="设备配置文件")
    parser.add_argument("--cases-dir", default="cases", help="Airtest 用例目录")
    parser.add_argument("--output-dir", default="artifacts", help="输出目录")
    parser.add_argument("--parallel-workers", type=int, default=4, help="最大并行设备数")
    parser.add_argument("--retry-count", type=int, default=1, help="失败重试次数")
    parser.add_argument("--diff-threshold", type=float, default=0.01, help="截图差异阈值")
    parser.add_argument("--auto-detect", action="store_true", help="当配置为空时自动读取 adb devices")
    parser.add_argument("--clean", action="store_true", help="执行前清理 artifacts 目录")
    parser.add_argument("--refresh-baseline", action="store_true", help="执行成功后覆盖更新基线图")
    parser.add_argument(
        "--create-missing-baseline",
        action="store_true",
        help="若基线缺失且用例通过，则自动创建基线图",
    )
    return parser


def build_runtime_options(config: dict, args: argparse.Namespace) -> dict:
    """
    把“配置文件里的值”和“命令行里的值”合并成最终运行参数。

    合并规则很简单：
    - 如果 config/devices.yaml 里写了，就优先用 YAML；
    - 如果 YAML 没写，就退回命令行默认值。
    """
    return {
        "adb_host": config.get("adb_host", "127.0.0.1"),
        "adb_port": int(config.get("adb_port", 5037)),
        "parallel_workers": int(config.get("parallel_workers", args.parallel_workers)),
        "retry_count": int(config.get("retry_count", args.retry_count)),
        "diff_threshold": float(config.get("diff_threshold", args.diff_threshold)),
        "refresh_baseline": bool(config.get("refresh_baseline", args.refresh_baseline)),
        "create_missing_baseline": bool(
            config.get("create_missing_baseline", args.create_missing_baseline)
        ),
    }


def load_config(path: Path) -> dict:
    """
    读取设备配置文件。

    如果文件不存在，不直接报错，而是返回空字典。
    这样 run_regression.sh 第一次执行时，仍然能先走“自动生成配置文件”的流程。
    """
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def resolve_devices(config: dict, auto_detect: bool) -> list[dict]:
    """
    决定“这次到底用哪些设备跑”。

    规则：
    1. 如果 YAML 里已经配置了 devices，就直接用配置；
    2. 如果 YAML 里没写，且命令行开了 --auto-detect，就读取 adb devices；
    3. 两边都没有，就返回空列表。
    """
    devices = [item for item in config.get("devices", []) if item.get("enabled", True)]
    if devices:
        return devices
    if auto_detect:
        return [
            {"name": serial, "serial": serial, "platform": "android", "enabled": True}
            for serial in adb_devices()
        ]
    return []


def adb_devices() -> list[str]:
    """
    读取当前 adb 已连接设备列表。

    输出示例：
    - 127.0.0.1:16448
    - emulator-5554
    - 真机序列号
    """
    completed = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=False)
    serials = []
    for line in completed.stdout.splitlines():
        if "\tdevice" in line:
            serials.append(line.split("\t")[0].strip())
    return serials


def discover_cases(cases_dir: Path) -> list[Path]:
    """
    扫描 cases 目录，找出所有 `.air` 用例目录。

    这里返回的是目录路径列表，而不是 Python 文件路径。
    因为 Airtest 本身就是按 `.air` 目录来执行用例的。
    """
    if not cases_dir.exists():
        return []
    return sorted([item for item in cases_dir.iterdir() if item.is_dir() and item.suffix == ".air"])


def run_device_cases(
    device: dict,
    cases: list[Path],
    output_dir: Path,
    baseline_dir: Path,
    runtime_options: dict,
) -> list[dict]:
    """
    在单台设备上顺序执行所有用例。

    注意：
    - “设备之间”可以并行；
    - “同一台设备上的多个用例”按顺序执行，避免互相抢焦点。
    """
    device_results = []
    device_name = device.get("name") or device["serial"]
    serial = device["serial"]

    for case_dir in cases:
        case_name = case_dir.stem
        # 每个设备、每个用例都有自己独立的输出目录。
        # 这样就算多设备并行，也不会把日志混在一起。
        case_output_dir = output_dir / device_name / case_name
        case_output_dir.mkdir(parents=True, exist_ok=True)

        attempts = []
        final_result: dict | None = None
        max_attempts = runtime_options["retry_count"] + 1
        for attempt_number in range(1, max_attempts + 1):
            # 如果某次执行失败，且允许重试，就继续跑下一次 attempt。
            attempt_result = run_single_attempt(
                case_dir=case_dir,
                case_output_dir=case_output_dir,
                case_name=case_name,
                device=device,
                serial=serial,
                baseline_dir=baseline_dir / case_name,
                runtime_options=runtime_options,
                attempt_number=attempt_number,
            )
            attempts.append(attempt_result)
            final_result = attempt_result
            if attempt_result["status"] == "passed":
                # 只要有一次通过，就不再继续重试。
                break

        assert final_result is not None
        # 对外暴露的是“最终结论 + 完整尝试历史”。
        # 这样报告层既能看最终状态，也能展开查看每次重试发生了什么。
        final_result = dict(final_result)
        final_result["attempts"] = attempts
        final_result["attempt_count"] = len(attempts)
        final_result["retried"] = len(attempts) > 1
        device_results.append(final_result)
    return device_results


def run_single_attempt(
    case_dir: Path,
    case_output_dir: Path,
    case_name: str,
    device: dict,
    serial: str,
    baseline_dir: Path,
    runtime_options: dict,
    attempt_number: int,
) -> dict:
    """
    执行“某台设备上的某个用例的某一次尝试”。

    这是最细粒度的执行单元。
    你可以把它理解成：
    “在某台设备上，真正跑一遍 Airtest 命令，并把日志、截图、差异结果都收集回来。”
    """
    attempt_dir = case_output_dir / f"attempt_{attempt_number}"
    if attempt_dir.exists():
        shutil.rmtree(attempt_dir)
    attempt_dir.mkdir(parents=True, exist_ok=True)

    # stdout.log / stderr.log 保存命令行输出；
    # log_dir 保存 Airtest 自己落地的截图和日志。
    stdout_file = attempt_dir / "stdout.log"
    stderr_file = attempt_dir / "stderr.log"
    log_dir = attempt_dir / "log"
    log_dir.mkdir(exist_ok=True)

    # 真正构造 airtest run 命令并执行。
    command = build_airtest_command(
        case_dir=case_dir,
        serial=serial,
        adb_host=runtime_options["adb_host"],
        adb_port=runtime_options["adb_port"],
        log_dir=log_dir,
    )
    started_at = datetime.now().isoformat(timespec="seconds")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    finished_at = datetime.now().isoformat(timespec="seconds")

    # 无论成功失败，都先把标准输出和错误输出落盘。
    # 这样一旦脚本中途报错，排查时不会只剩一个返回码。
    stdout_file.write_text(completed.stdout, encoding="utf-8")
    stderr_file.write_text(completed.stderr, encoding="utf-8")
    # Airtest 原始 log.txt 里会混入内部截图动作记录。
    # 这里统一做一次清洗，让最终落地日志更聚焦业务步骤本身。
    sanitize_airtest_log(log_dir / "log.txt")

    # 只有脚本运行成功时，才进一步处理基线图和截图差异。
    image_diffs = []
    baseline_action = "skipped"
    baseline_files: list[str] = []
    if completed.returncode == 0:
        if runtime_options["refresh_baseline"]:
            baseline_files = refresh_baseline_from_current(log_dir, baseline_dir)
            baseline_action = "refreshed"
        elif baseline_dir.exists():
            diff_output_dir = attempt_dir / "diff"
            image_diffs = [
                item.to_dict()
                for item in compare_directories(
                    baseline_dir=baseline_dir,
                    current_dir=log_dir,
                    output_dir=diff_output_dir,
                    threshold=runtime_options["diff_threshold"],
                )
            ]
            baseline_action = "compared"
        elif runtime_options["create_missing_baseline"]:
            baseline_files = refresh_baseline_from_current(log_dir, baseline_dir)
            baseline_action = "created"

    # 最终状态不只看 return code。
    # 就算脚本执行成功，只要截图差异里有失败项，整体也算 failed。
    status = "passed"
    if completed.returncode != 0 or any(not item["passed"] for item in image_diffs):
        status = "failed"

    return {
        "device_name": device.get("name") or serial,
        "serial": serial,
        "platform": device.get("platform", "android"),
        "case_name": case_name,
        "case_path": str(case_dir),
        "status": status,
        "return_code": completed.returncode,
        "attempt_number": attempt_number,
        "started_at": started_at,
        "finished_at": finished_at,
        "stdout_file": str(stdout_file),
        "stderr_file": str(stderr_file),
        "log_dir": str(log_dir),
        "attempt_dir": str(attempt_dir),
        "image_diffs": image_diffs,
        "baseline_action": baseline_action,
        "baseline_files": baseline_files,
    }


def build_airtest_command(
    case_dir: Path,
    serial: str,
    adb_host: str,
    adb_port: int,
    log_dir: Path,
) -> list[str]:
    """
    拼接 Airtest 原生命令。

    最终会长得像：
    python -m airtest run cases/xxx.air --device Android://... --log ...
    """
    device_uri = (
        f"Android://{adb_host}:{adb_port}/{serial}"
        "?cap_method=MINICAP&&ori_method=MINICAPORI&&touch_method=ADBTOUCH"
    )
    return [
        sys.executable,
        "-m",
        "airtest",
        "run",
        str(case_dir),
        "--no-image",
        "--device",
        device_uri,
        "--log",
        str(log_dir),
    ]


if __name__ == "__main__":
    raise SystemExit(main())
