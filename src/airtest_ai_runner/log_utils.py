from __future__ import annotations
# pyright: reportAny=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnusedCallResult=false

"""
Airtest 日志清洗工具。

原始 `log.txt` 对机器来说够用，但对新人阅读并不友好：
1. 会混入大量框架内部动作；
2. 业务步骤和真实截图文件名不容易直接对上；
3. 出问题时，常常要手工猜某次 touch 到底对应哪一步。

这个模块的目标就是把原始日志整理成“更像业务流水账”的格式。
"""

import json
from pathlib import Path
from typing import Any


def sanitize_airtest_log(log_file: Path) -> dict[str, int]:
    """
    清洗 Airtest 原始 log.txt，让最终日志更聚焦业务动作。

    这一步主要解决两个问题：
    1. Airtest 会把 `try_log_screen` 这种“内部截图日志动作”也写进 log.txt；
    2. 这些行既会让文件变大，也会把一堆无用截图引用混进来，阅读体验很差。

    当前策略：
    1. 直接移除 `try_log_screen` 日志行；
    2. 对 `snapshot` 日志保留“业务截图文件名”这个关键信息；
    3. 但把它内部返回的临时日志图引用清空，避免继续出现无用的 jpg 关联。

    返回值会给出清洗统计，便于以后如果想打印调试信息时复用。
    """
    if not log_file.exists():
        return {
            "removed_try_log_screen": 0,
            "normalized_snapshot_ret": 0,
            "annotated_records": 0,
            "fallback_annotated_touches": 0,
        }

    removed_try_log_screen = 0
    normalized_snapshot_ret = 0
    annotated_records = 0
    fallback_annotated_touches = 0
    parsed_items: list[dict[str, Any] | str] = []
    current_step_context: dict[str, Any] | None = None

    for raw_line in log_file.read_text(encoding="utf-8").splitlines():
        stripped_line = raw_line.strip()
        if not stripped_line:
            continue

        try:
            record = json.loads(stripped_line)
        except json.JSONDecodeError:
            # 如果某一行不是标准 JSON，就原样保留，避免误伤未知格式日志。
            parsed_items.append(raw_line)
            continue

        data = record.get("data", {})
        action_name = data.get("name")

        if record.get("tag") == "function" and action_name == "try_log_screen":
            removed_try_log_screen += 1
            continue

        if record.get("tag") == "function" and action_name == "snapshot":
            if data.get("ret") is not None:
                data["ret"] = None
                normalized_snapshot_ret += 1

        if record.get("tag") == "info" and data.get("name") == "STEP_CONTEXT":
            step_context = _parse_step_context(data.get("log"))
            if step_context:
                current_step_context = step_context
                data["name"] = "业务步骤"
                data["log"] = _build_step_label(step_context)
                data["traceback"] = None
                _attach_step_context(data, step_context)
                annotated_records += 1
            parsed_items.append(record)
            continue

        if record.get("tag") == "function" and current_step_context:
            _attach_step_context(data, current_step_context)
            _attach_friendly_log(data)
            annotated_records += 1

        parsed_items.append(record)

    fallback_annotated_touches = _apply_snapshot_fallback_annotations(parsed_items)

    cleaned_lines: list[str] = []
    for item in parsed_items:
        if isinstance(item, str):
            cleaned_lines.append(item)
        else:
            cleaned_lines.append(json.dumps(item, ensure_ascii=False))

    final_text = "\n".join(cleaned_lines)
    if final_text:
        final_text += "\n"
    log_file.write_text(final_text, encoding="utf-8")

    return {
        "removed_try_log_screen": removed_try_log_screen,
        "normalized_snapshot_ret": normalized_snapshot_ret,
        "annotated_records": annotated_records,
        "fallback_annotated_touches": fallback_annotated_touches,
    }


def _parse_step_context(raw_log: Any) -> dict[str, Any] | None:
    """解析业务步骤上下文日志。"""
    if not isinstance(raw_log, str):
        return None
    try:
        payload = json.loads(raw_log)
    except json.JSONDecodeError:
        return None
    if payload.get("kind") != "step_context":
        return None
    return payload


def _attach_step_context(data: dict[str, Any], step_context: dict[str, Any]) -> None:
    """把步骤信息挂到当前日志记录上。"""
    data["step_index"] = step_context.get("step_index")
    data["step_total"] = step_context.get("step_total")
    data["step_action"] = step_context.get("step_action")
    data["step_name"] = step_context.get("step_name")
    data["step_label"] = _build_step_label(step_context)


def _build_step_label(step_context: dict[str, Any]) -> str:
    """生成统一的步骤标签文本。"""
    step_index = step_context.get("step_index")
    step_total = step_context.get("step_total")
    step_action = step_context.get("step_action", "")
    step_name = step_context.get("step_name", "")
    if isinstance(step_index, int) and isinstance(step_total, int):
        return f"步骤 {step_index:02d}/{step_total:02d} | {step_action} | {step_name}"
    return f"步骤 | {step_action} | {step_name}"


def _attach_friendly_log(data: dict[str, Any]) -> None:
    """为常见动作补一条更适合肉眼阅读的 friendly_log。"""
    action_name = data.get("name")
    step_label = data.get("step_label") or data.get("step_name") or ""
    call_args = data.get("call_args", {})

    if action_name == "touch":
        coords = call_args.get("v")
        data["friendly_log"] = f"{step_label} | 点击坐标 {coords}"
        return

    if action_name == "snapshot":
        filename = Path(call_args.get("filename", "")).name if call_args.get("filename") else ""
        data["friendly_log"] = f"{step_label} | 业务截图 {filename}".strip()
        return

    if action_name == "sleep":
        seconds = call_args.get("secs")
        data["friendly_log"] = f"{step_label} | 等待 {seconds} 秒"
        return

    if action_name == "wait":
        data["friendly_log"] = f"{step_label} | 等待目标出现"
        return

    if step_label:
        data["friendly_log"] = step_label


def _apply_snapshot_fallback_annotations(parsed_items: list[dict[str, Any] | str]) -> int:
    """
    兜底补全旧日志。

    对于历史日志，它们还没有 STEP_CONTEXT 记录。
    这时如果发现 snapshot 紧跟在 touch 后面，就用 snapshot 文件名反推这次 touch 属于哪一步。
    """
    fallback_annotated_touches = 0

    for index, item in enumerate(parsed_items):
        if not isinstance(item, dict):
            continue
        if item.get("tag") != "function":
            continue

        data = item.get("data", {})
        if data.get("name") != "snapshot":
            continue

        step_name = _extract_snapshot_step_name(data)
        if not step_name:
            continue

        if not data.get("step_name"):
            data["step_name"] = step_name
            data["step_action"] = "snapshot"
            data["step_label"] = f"步骤 | snapshot | {step_name}"
            _attach_friendly_log(data)

        previous_touch = _find_previous_touch_record(parsed_items, index)
        if previous_touch is None:
            continue

        touch_data = previous_touch.get("data", {})
        if touch_data.get("step_name"):
            continue

        touch_data["step_name"] = step_name
        touch_data["step_action"] = "click"
        touch_data["step_label"] = f"步骤 | click | {step_name}"
        _attach_friendly_log(touch_data)
        fallback_annotated_touches += 1

    return fallback_annotated_touches


def _extract_snapshot_step_name(data: dict[str, Any]) -> str:
    """从 snapshot 记录中提取业务步骤名。"""
    call_args = data.get("call_args", {})
    filename = call_args.get("filename")
    if isinstance(filename, str) and filename.strip():
        return Path(filename).stem
    msg = call_args.get("msg")
    if isinstance(msg, str):
        return msg.strip()
    return ""


def _find_previous_touch_record(
    parsed_items: list[dict[str, Any] | str],
    snapshot_index: int,
) -> dict[str, Any] | None:
    """向前找离当前 snapshot 最近的一条 touch 记录。"""
    for cursor in range(snapshot_index - 1, -1, -1):
        item = parsed_items[cursor]
        if not isinstance(item, dict):
            continue
        if item.get("tag") != "function":
            continue
        action_name = item.get("data", {}).get("name")
        if action_name == "snapshot":
            return None
        if action_name == "touch":
            return item
    return None
