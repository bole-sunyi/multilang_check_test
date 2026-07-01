from __future__ import annotations
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportAny=false, reportUnusedCallResult=false, reportImplicitStringConcatenation=false

"""
测试报告生成器。

它的输入是一批结构化执行结果，输出是 3 份报告：
1. `report.json`：最完整、最适合程序二次消费；
2. `report.md`：适合代码仓库、聊天工具或文档系统直接查看；
3. `report.html`：适合非技术同学直接点开浏览。

可以把这里理解成“把底层执行结果翻译成给人看的总结”。
"""

import html
import json
import os
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import NotRequired, TypedDict, cast


RuntimeOptions = dict[str, object]


class AttemptRecord(TypedDict):
    attempt_number: int
    status: str
    return_code: int
    started_at: str
    finished_at: str
    stdout_file: str
    stderr_file: str
    log_dir: str


class ImageDiffRecord(TypedDict, total=False):
    baseline: str
    current: str
    marked: str
    diff_ratio: float
    passed: bool
    status: str
    message: str


class CaseResult(TypedDict, total=False):
    device_name: str
    case_name: str
    status: str
    return_code: int
    stderr_file: str
    attempt_count: int
    retried: bool
    baseline_action: str
    image_diffs: list[ImageDiffRecord]
    attempts: list[AttemptRecord]
    log_dir: str


class FailureRecord(TypedDict):
    device: str
    case: str
    return_code: int
    stderr_file: str
    attempt_count: int


class DiffIssueRecord(TypedDict):
    device: str
    case: str
    image: str
    diff_ratio: float
    marked: str
    status: str
    message: str


class CompatibilityRow(TypedDict):
    device: str
    total: int
    passed: int
    failed: int
    pass_rate: float


class ReportSummary(TypedDict):
    generated_at: str
    runtime_options: RuntimeOptions
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    retried_cases: int
    total_attempts: int
    compatibility: list[CompatibilityRow]
    baseline_actions: dict[str, int]
    failures: list[FailureRecord]
    diff_issues: list[DiffIssueRecord]
    raw_results: list[CaseResult]
    ai_summary: NotRequired[str]


def _str_value(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _int_value(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _bool_value(value: object, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _diff_records(value: object) -> list[ImageDiffRecord]:
    if not isinstance(value, list):
        return []
    return [cast(ImageDiffRecord, cast(object, item)) for item in value if isinstance(item, dict)]


def _attempt_records(value: object) -> list[AttemptRecord]:
    if not isinstance(value, list):
        return []
    return [cast(AttemptRecord, cast(object, item)) for item in value if isinstance(item, dict)]


def _snapshot_records(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(cast(Mapping[str, object], item)) for item in value if isinstance(item, dict)]


def _snapshot_display_name(record: Mapping[str, object]) -> str:
    step_index = record.get("step_index")
    step_name = _str_value(record.get("step_name"))
    image_name = _str_value(record.get("image_name"))
    if isinstance(step_index, int) and step_name:
        return f"{step_index:02d}_{step_name}"
    return step_name or image_name or "unknown"


def generate_reports(
    results: list[CaseResult],
    output_dir: Path,
    runtime_options: RuntimeOptions | None = None,
) -> tuple[Path, Path, Path]:
    """
    基于统一结果结构，同时生成 JSON / Markdown / HTML 三种报告。

    这样一轮执行结束后，不同角色都能拿到自己习惯的阅读格式。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    # summary 是中间统一数据结构。
    # 后面的 3 种渲染函数都围绕它展开，避免 3 份报告各自重复统计。
    summary = build_summary(results, runtime_options or {})
    summary["ai_summary"] = generate_ai_summary(summary)

    json_path = output_dir / "report.json"
    markdown_path = output_dir / "report.md"
    html_path = output_dir / "report.html"

    _ = json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _ = markdown_path.write_text(render_markdown(summary), encoding="utf-8")
    _ = html_path.write_text(render_html(summary), encoding="utf-8")
    return json_path, markdown_path, html_path


def build_summary(
    results: list[CaseResult],
    runtime_options: RuntimeOptions,
) -> ReportSummary:
    """
    把原始运行结果压缩成“报告摘要对象”。

    这一步会统计：
    - 总通过/失败数量；
    - 每台设备的通过率；
    - 失败清单；
    - 截图差异清单；
    - 基线处理动作统计。
    """
    total_cases = len(results)
    passed_cases = sum(1 for item in results if _str_value(item.get("status")) == "passed")
    failed_cases = total_cases - passed_cases
    retried_cases = sum(1 for item in results if _bool_value(item.get("retried")))
    total_attempts = sum(_int_value(item.get("attempt_count"), 1) for item in results)

    per_device: defaultdict[str, Counter[str]] = defaultdict(Counter)
    failures: list[FailureRecord] = []
    diff_issues: list[DiffIssueRecord] = []
    baseline_actions: Counter[str] = Counter()

    for item in results:
        # 先聚合“按设备统计”的数据，后面表格直接用。
        device = _str_value(item.get("device_name"), "unknown")
        per_device[device]["total"] += 1
        baseline_actions[_str_value(item.get("baseline_action"), "skipped")] += 1

        if _str_value(item.get("status")) == "passed":
            per_device[device]["passed"] += 1
        else:
            # 失败项会单独整理成列表，方便报告直接展示重点问题。
            per_device[device]["failed"] += 1
            failures.append(
                {
                    "device": device,
                    "case": _str_value(item.get("case_name")),
                    "return_code": _int_value(item.get("return_code")),
                    "stderr_file": _str_value(item.get("stderr_file")),
                    "attempt_count": _int_value(item.get("attempt_count"), 1),
                }
            )

        for diff in _diff_records(item.get("image_diffs")):
            if _bool_value(diff.get("passed")):
                continue
            # 这里只保留“失败的截图比对项”，避免报告被大量正常项刷屏。
            current_path = _str_value(diff.get("current"))
            baseline_path = _str_value(diff.get("baseline"))
            diff_issues.append(
                {
                    "device": device,
                    "case": _str_value(item.get("case_name")),
                    "image": Path(current_path).name if current_path else Path(baseline_path).name,
                    "diff_ratio": float(diff.get("diff_ratio", 0.0)),
                    "marked": _str_value(diff.get("marked")),
                    "status": _str_value(diff.get("status")),
                    "message": _str_value(diff.get("message")),
                }
            )

    compatibility: list[CompatibilityRow] = []
    for device_name, stats in per_device.items():
        pass_rate = round((stats["passed"] / max(stats["total"], 1)) * 100, 2)
        compatibility.append(
            {
                "device": device_name,
                "total": stats["total"],
                "passed": stats["passed"],
                "failed": stats["failed"],
                "pass_rate": pass_rate,
            }
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runtime_options": runtime_options,
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": failed_cases,
        "pass_rate": round((passed_cases / max(total_cases, 1)) * 100, 2),
        "retried_cases": retried_cases,
        "total_attempts": total_attempts,
        "compatibility": sorted(compatibility, key=lambda item: item["device"]),
        "baseline_actions": dict(baseline_actions),
        "failures": failures,
        "diff_issues": diff_issues,
        "raw_results": results,
    }


def generate_ai_summary(summary: ReportSummary) -> str:
    """
    尝试调用大模型生成中文总结。

    如果环境变量里没有配置 API Key，或者远程请求失败，
    就自动退回到本地规则版摘要，保证报告始终可用。
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        return build_fallback_summary(summary)

    prompt = (
        "你是一名移动端测试分析助手。请根据以下 JSON 结果，输出中文结构化总结，"
        "要求包含：1. 总体结论 2. 重试观察 3. 兼容性观察 4. 截图差异风险 5. 建议优先处理项。\n\n"
        f"{json.dumps(summary, ensure_ascii=False)}"
    )
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "你擅长输出简洁、专业的测试报告总结。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url=f"{base_url}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_bytes = cast(bytes, cast(object, response.read()))
            response_text = response_bytes.decode("utf-8")
        data = cast(dict[str, object], json.loads(response_text))
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = cast(dict[str, object], cast(object, choices[0]))
            if isinstance(first_choice, dict):
                message = cast(object, first_choice.get("message"))
                if isinstance(message, dict):
                    content = cast(object, message.get("content"))
                    if isinstance(content, str) and content.strip():
                        return content.strip()
        raise ValueError("AI summary response is missing content")
    except Exception:
        # AI 总结失败不能拖垮整份报告，所以这里静默回退到本地摘要。
        return build_fallback_summary(summary)


def build_fallback_summary(summary: ReportSummary) -> str:
    """在没有 AI 能力时，按固定模板生成一段可读的中文摘要。"""
    lines = [
        f"本次共执行 {summary['total_cases']} 条用例，累计尝试 {summary['total_attempts']} 次，"
        + f"通过 {summary['passed_cases']} 条，失败 {summary['failed_cases']} 条，整体通过率 {summary['pass_rate']}%。"
    ]
    if summary["retried_cases"]:
        lines.append(f"其中有 {summary['retried_cases']} 条用例触发过失败重试，建议重点关注不稳定链路。")
    else:
        lines.append("当前未发生失败重试，执行稳定性表现正常。")
    if summary["diff_issues"]:
        lines.append(
            f"共发现 {len(summary['diff_issues'])} 处截图异常或基线问题，建议优先核查界面兼容性和基线准确性。"
        )
    else:
        lines.append("当前未发现超阈值截图差异，界面回归结果正常。")
    return "\n".join(lines)


def render_markdown(summary: ReportSummary) -> str:
    """把摘要对象渲染成 Markdown 报告。"""
    compatibility_lines = [
        "| 设备 | 总数 | 通过 | 失败 | 通过率 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    compatibility_lines.extend(
        [
            f"| {item['device']} | {item['total']} | {item['passed']} | {item['failed']} | {item['pass_rate']}% |"
            for item in summary["compatibility"]
        ]
    )
    baseline_lines = [f"- `{name}`: {count}" for name, count in sorted(summary["baseline_actions"].items())] or ["无"]
    failure_lines = (
        [
            f"- 设备 `{item['device']}` / 用例 `{item['case']}` / 尝试 `{item['attempt_count']}` 次 / 返回码 `{item['return_code']}` / 日志 `{item['stderr_file']}`"
            for item in summary["failures"]
        ]
        or ["无"]
    )
    diff_lines = (
        [
            "- "
            + " / ".join(
                [
                    f"设备 `{item['device']}`",
                    f"用例 `{item['case']}`",
                    f"图片 `{item['image']}`",
                    f"状态 `{item['status']}`",
                    f"差异率 `{item['diff_ratio']}`",
                    *( [f"标记图 `{item['marked']}`"] if item.get("marked") else [] ),
                    f"说明 `{item['message']}`",
                ]
            )
            for item in summary["diff_issues"]
        ]
        or ["无"]
    )
    snapshot_lines: list[str] = []
    for item in summary["raw_results"]:
        records = _snapshot_records(item.get("snapshot_records"))
        if not records:
            continue
        fallback_records = [record for record in records if _bool_value(record.get("fallback_used"))]
        excel_path = _str_value(item.get("excel_path"))
        snapshot_lines.append(
            f"- 设备 `{_str_value(item.get('device_name'))}` / 用例 `{_str_value(item.get('case_name'))}` / "
            + f"截图 `{len(records)}` 张 / fallback_pos `{len(fallback_records)}` 次"
            + (f" / 表格 `{excel_path}`" if excel_path else "")
        )
        for record in fallback_records:
            snapshot_lines.append(
                f"  - 需优化定位：`{_snapshot_display_name(record)}` / 图片 `{Path(_str_value(record.get('image_path'))).name}`"
            )
    if not snapshot_lines:
        snapshot_lines = ["无"]

    return "\n".join(
        [
            "# 自动化回归测试报告",
            "",
            f"- 生成时间：`{summary['generated_at']}`",
            f"- 用例总数：`{summary['total_cases']}`",
            f"- 通过数：`{summary['passed_cases']}`",
            f"- 失败数：`{summary['failed_cases']}`",
            f"- 累计尝试次数：`{summary['total_attempts']}`",
            f"- 触发重试用例：`{summary['retried_cases']}`",
            f"- 通过率：`{summary['pass_rate']}%`",
            "",
            "## AI总结",
            "",
            _str_value(summary.get("ai_summary")),
            "",
            "## 设备兼容性结果",
            "",
            *compatibility_lines,
            "",
            "## 基线处理结果",
            "",
            *baseline_lines,
            "",
            "## 失败清单",
            "",
            *failure_lines,
            "",
            "## 截图差异清单",
            "",
            *diff_lines,
            "",
            "## 多语言截图采集",
            "",
            *snapshot_lines,
            "",
        ]
    )


def render_html(summary: ReportSummary) -> str:
    """把摘要对象渲染成 HTML 报告，方便直接双击浏览。"""
    def escape(value: object) -> str:
        return html.escape(str(value))

    stats_cards: list[tuple[str, int | float | str]] = [
        ("总用例", summary["total_cases"]),
        ("通过", summary["passed_cases"]),
        ("失败", summary["failed_cases"]),
        ("累计尝试", summary["total_attempts"]),
        ("触发重试", summary["retried_cases"]),
        ("通过率", f"{summary['pass_rate']}%"),
    ]
    stats_html = "".join(
        f"<div class='card'><div class='label'>{escape(label)}</div><div class='value'>{escape(value)}</div></div>"
        for label, value in stats_cards
    )

    # 设备兼容性表格是 HTML 报告里最重要的“总体视图”，先单独准备好表格行。
    compatibility_rows = "".join(
        (
            "<tr>"
            + f"<td>{escape(item['device'])}</td>"
            + f"<td>{escape(item['total'])}</td>"
            + f"<td>{escape(item['passed'])}</td>"
            + f"<td>{escape(item['failed'])}</td>"
            + f"<td>{escape(item['pass_rate'])}%</td>"
            + "</tr>"
        )
        for item in summary["compatibility"]
    )

    case_cards: list[str] = []
    for item in summary["raw_results"]:
        # 每条用例生成一个卡片，里面展开重试历史和截图差异。
        attempts_html = "".join(
            (
                "<li>"
                + f"第 {escape(attempt['attempt_number'])} 次 / 状态 {escape(attempt['status'])} / 日志 "
                + f"{path_to_link(attempt['stderr_file'])}"
                + "</li>"
            )
            for attempt in _attempt_records(item.get("attempts"))
        )
        diff_html = "".join(
            "<li>"
            + " / ".join(
                part
                for part in [
                    escape(diff.get("status", "")),
                    escape(diff.get("message", "")),
                    f"差异率 {escape(diff.get('diff_ratio', ''))}",
                    path_to_link(diff.get("marked", "")),
                ]
                if part
            )
            + "</li>"
            for diff in _diff_records(item.get("image_diffs"))
            if not diff.get("passed", False)
        ) or "<li>无</li>"
        snapshot_records = _snapshot_records(item.get("snapshot_records"))
        fallback_count = sum(1 for record in snapshot_records if _bool_value(record.get("fallback_used")))
        snapshot_html = "".join(
            (
                "<li>"
                + f"{escape(_snapshot_display_name(record))} / 定位 {escape(record.get('locate_method', 'unknown'))}"
                + (" / <strong class='risk'>fallback_pos</strong>" if _bool_value(record.get("fallback_used")) else "")
                + f" / {path_to_link(_str_value(record.get('image_path')))}"
                + "</li>"
            )
            for record in snapshot_records
        ) or "<li>无</li>"
        case_cards.append(
            (
                "<div class='case-card'>"
                + f"<h3>{escape(_str_value(item.get('device_name')))} / {escape(_str_value(item.get('case_name')))}</h3>"
                + f"<p>状态：<strong>{escape(_str_value(item.get('status')))}</strong>，重试次数：{escape(item.get('attempt_count', 1))}</p>"
                + f"<p>截图：{escape(len(snapshot_records))} 张，fallback_pos：<strong>{escape(fallback_count)}</strong> 次，表格：{path_to_link(_str_value(item.get('excel_path')))}</p>"
                + f"<p>基线动作：{escape(item.get('baseline_action', 'skipped'))}</p>"
                + f"<p>日志目录：{path_to_link(item.get('log_dir', ''))}</p>"
                + "<h4>尝试明细</h4>"
                + f"<ul>{attempts_html or '<li>无</li>'}</ul>"
                + "<h4>截图差异</h4>"
                + f"<ul>{diff_html}</ul>"
                + "<h4>多语言截图</h4>"
                + f"<ul>{snapshot_html}</ul>"
                + "</div>"
            )
        )

    baseline_html = "".join(
        f"<li>{escape(name)}: {escape(count)}</li>"
        for name, count in sorted(summary["baseline_actions"].items())
    ) or "<li>无</li>"
    failure_html = "".join(
        (
            "<li>"
            + f"{escape(item['device'])} / {escape(item['case'])} / 尝试 {escape(item['attempt_count'])} 次 / "
            + f"返回码 {escape(item['return_code'])} / {path_to_link(item['stderr_file'])}"
            + "</li>"
        )
        for item in summary["failures"]
    ) or "<li>无</li>"
    diff_issue_html = "".join(
        "<li>"
        + " / ".join(
            part
            for part in [
                escape(item["device"]),
                escape(item["case"]),
                escape(item["image"]),
                escape(item["status"]),
                escape(item["message"]),
                path_to_link(item["marked"]),
            ]
            if part
        )
        + "</li>"
        for item in summary["diff_issues"]
    ) or "<li>无</li>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>自动化回归测试报告</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif; margin: 24px; background: #f7f8fa; color: #1f2937; }}
    h1, h2, h3, h4 {{ margin: 0 0 12px; }}
    section {{ background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }}
    .card {{ background: #eef3ff; border-radius: 10px; padding: 16px; }}
    .label {{ color: #6b7280; font-size: 14px; }}
    .value {{ font-size: 26px; font-weight: 700; margin-top: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 10px; text-align: left; }}
    .case-list {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .case-card {{ background: #fafafa; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; }}
    .risk {{ color: #b45309; }}
    code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 6px; }}
    a {{ color: #2563eb; text-decoration: none; }}
  </style>
</head>
<body>
  <section>
    <h1>自动化回归测试报告</h1>
    <p>生成时间：<code>{escape(summary["generated_at"])}</code></p>
    <div class="grid">{stats_html}</div>
  </section>
  <section>
    <h2>AI总结</h2>
    <pre>{escape(_str_value(summary.get("ai_summary")))}</pre>
  </section>
  <section>
    <h2>设备兼容性结果</h2>
    <table>
      <thead><tr><th>设备</th><th>总数</th><th>通过</th><th>失败</th><th>通过率</th></tr></thead>
      <tbody>{compatibility_rows}</tbody>
    </table>
  </section>
  <section>
    <h2>基线处理结果</h2>
    <ul>{baseline_html}</ul>
  </section>
  <section>
    <h2>失败清单</h2>
    <ul>{failure_html}</ul>
  </section>
  <section>
    <h2>截图差异清单</h2>
    <ul>{diff_issue_html}</ul>
  </section>
  <section>
    <h2>用例详情</h2>
    <div class="case-list">{''.join(case_cards)}</div>
  </section>
</body>
</html>
"""


def path_to_link(path: str) -> str:
    """把本地文件路径渲染成 HTML 可点击链接。"""
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return f"<a href='{html.escape(path)}'>{html.escape(path)}</a>"
    path_obj = Path(path)
    return f"<a href='file://{html.escape(str(path_obj.resolve()))}'>{html.escape(path_obj.name)}</a>"
