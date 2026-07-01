from __future__ import annotations
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportAny=false, reportExplicitAny=false, reportUnusedCallResult=false

"""
Poco 业务执行辅助模块。

这里封装了“怎么找控件、怎么点击、怎么截图、怎么导出节点树”这些通用能力，
让单模块脚本只需要关心自己的 YAML 步骤，而不用重复写底层 Poco 细节。

可以把它理解成：
单模块脚本负责“说要做什么”，这个文件负责“把动作真正执行出来”。
"""

import json
import os
import re
from pathlib import Path
from typing import Any

from airtest.core.api import sleep, snapshot, touch
from airtest.core.helper import log as airtest_log
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

from .screenshot_utils import normalize_image_file_for_landscape


def build_android_poco() -> AndroidUiautomationPoco:
    """
    【初始化函数】创建一个 Android Poco 驱动实例。
    驱动就像是我们的“眼睛”和“手”，用来查看手机屏幕上的控件并进行操作。
    """
    # 从环境变量读取配置，决定是否使用 Airtest 的输入系统（通常建议开启，兼容性更好）
    use_airtest_input = env_flag("POCO_USE_AIRTEST_INPUT", default=True)
    # 决定是否在每一步操作后都自动截一张图（测试排障很有用，但会运行慢一点）
    screenshot_each_action = env_flag("POCO_SCREENSHOT_EACH_ACTION", default=False)
    
    return AndroidUiautomationPoco(
        use_airtest_input=use_airtest_input,
        screenshot_each_action=screenshot_each_action,
    )


def env_flag(name: str, default: bool = False) -> bool:
    """
    【辅助工具】读取环境变量并转换为 True/False。
    比如环境变量设置了 POCO_USE_AIRTEST_INPUT=1，这里就会返回 True。
    """
    # 先把环境变量原始字符串拿出来。
    raw_value = os.environ.get(name, "")
    if not raw_value:
        # 如果完全没传这个环境变量，就使用函数调用时给的默认值。
        return default
    # 这里统一兼容几种常见“表示真”的写法。
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def dump_visible_nodes(
    poco: AndroidUiautomationPoco,
    output_path: Path,
    max_depth: int = 15,
) -> list[dict[str, Any]]:
    """
    【数据采集函数】采集当前屏幕上所有的控件信息（控件树）。
    这就像是给屏幕拍一个“X光片”，把每一个按钮、文字的位置和属性都记录下来。
    
    参数:
        poco: 已经初始化好的驱动
        output_path: 采集结果保存的文件路径（通常是 poco_nodes.json）
        max_depth: 采集的深度。深度越大，抓到的细节越多（比如嵌套很深的按钮）
    """
    # 让 Poco 吐出原始的层级数据
    root = poco.agent.hierarchy.dump()
    flattened: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], depth: int, path: str) -> None:
        """
        【内部递归工具】顺着控件树往下走，把每一个节点都“拉平”存到列表里。
        """
        if depth > max_depth:
            return

        # Poco 的属性有时在 payload 字段里，有时在外面，我们要兼容处理
        payload_data = node.get("payload", {})
        
        # 提取小白也能看懂的核心属性
        payload = {
            "path": path,                                 # 节点在树里的路径
            "name": payload_data.get("name", node.get("name", "")), # 节点的内部名称
            "type": payload_data.get("type", node.get("type", "")), # 控件类型（如 TextView, Button）
            "text": payload_data.get("text", node.get("text", "")), # 按钮上显示的文字
            "resourceId": payload_data.get("resourceId", node.get("resourceId", "")), # 程序员给按钮起的 ID
            "package": payload_data.get("package", ""),   # 属于哪个 App
            "visible": payload_data.get("visible", True), # 屏幕上是否看得见
            "clickable": payload_data.get("clickable", False) or payload_data.get("touchable", False), # 是否可以点击
            "enabled": payload_data.get("enabled", True), # 是否启用（没禁用的按钮才能点）
            "focusable": payload_data.get("focusable", False),
            "desc": payload_data.get("description", payload_data.get("desc", node.get("desc", ""))), # 隐藏的描述文字
            "pos": payload_data.get("pos", node.get("pos", [])), # 在屏幕上的坐标 [x, y] (范围 0-1)
            "size": payload_data.get("size", node.get("size", [])), # 按钮的大小 [宽, 高]
            "anchorPoint": payload_data.get("anchorPoint", node.get("anchorPoint", [])), # 锚点位置
        }

        # 过滤噪音：只有看得见、或者有名字/文字的节点才值得我们记录
        if payload["visible"] or payload["name"] or payload["text"]:
            flattened.append(payload)

        # 继续找这个节点的“孩子”们（下一层控件）
        children = node.get("children", []) or []
        for index, child in enumerate(children):
            # 给孩子起个带编号的路径，方便我们排查
            child_name = child.get("name", child.get("payload", {}).get("name", "node"))
            walk(child, depth + 1, f"{path}/{index}:{child_name}")

    # 从根节点开始“散步”采集
    walk(root, 0, "root")
    
    # 创建文件夹并把采集结果写成 JSON 文件
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(flattened, ensure_ascii=False, indent=2), encoding="utf-8")
    write_poco_nodes_field_guide(output_path)
    return flattened


def write_poco_nodes_field_guide(nodes_json_path: Path) -> Path:
    """在 nodes.json 旁边生成字段说明，避免把注释写进 JSON 破坏格式。"""
    guide_path = nodes_json_path.with_name(f"{nodes_json_path.stem}字段说明.md")
    guide_path.write_text(_POCO_NODES_FIELD_GUIDE, encoding="utf-8")
    return guide_path


_POCO_NODES_FIELD_GUIDE = """# Poco 节点字段说明

`poco_nodes.json` 是合法 JSON，不能直接写 `// 注释`。字段说明放在这个 Markdown 文件里，方便一边看 JSON 一边对照。

## 哪些字段可以写进 YAML selector

优先级建议：`resourceId` > `desc` > `text` > `name/type + index`。

### `text`

控件显示出来的文字，适合定位按钮、标题、文本。

```yaml
selector:
  text: "领取"
```

### `resourceId` / `resource_id`

Android 控件 ID，通常最稳定。如果节点里有这个字段，优先用它。

```yaml
selector:
  resourceId: "com.xxx:id/btn_close"
```

也可以写成：

```yaml
selector:
  resource_id: "com.xxx:id/btn_close"
```

### `desc`

控件的无障碍描述，也叫 `content-desc`。很多图片按钮可能没有文字，但会有 `desc`。

```yaml
selector:
  desc: "close"
```

### `name`

Poco 节点名。有些业务控件会有稳定 name，可以用来定位。

```yaml
selector:
  name: "目标节点名"
```

如果只是 `android.view.View`、`android.widget.FrameLayout` 这类通用名字，不建议单独使用。

### `type`

控件类型，例如 `android.widget.EditText`、`android.widget.Button`。

```yaml
selector:
  type: "android.widget.EditText"
  index: 0
```

`type` 通常比较泛，建议配合 `index` 使用。

### `index`

`index` 不是 JSON 原始字段，是 YAML 里支持的辅助字段。多个节点命中同一个 selector 时，用它指定第几个。

```yaml
selector:
  text: "领取"
  index: 1
```

`index: 0` 是第一个，`index: 1` 是第二个。

### `parent`

用于限定父节点，避免同名控件匹配错位置。

```yaml
selector:
  text: "领取"
  parent:
    resourceId: "com.xxx:id/reward_panel"
```

## 不能直接写进 selector，但很有用的字段

### `pos`

节点中心点坐标，范围是 `0 ~ 1`。不能写进 `selector`，但可以作为坐标兜底：

```yaml
fallback_pos: [0.5, 0.0377]
```

### `size`

节点宽高，范围也是 `0 ~ 1`。用来判断节点覆盖区域大小，一般不写进 YAML。

### `path`

节点在控件树里的路径，适合人工排查层级，不建议写进 YAML，因为 UI 层级变化后容易失效。

### `package`

节点所属 App 包名。用于确认节点是不是目标 App，一般不写进 YAML。

### `clickable`

是否可点击。`true` 更适合作为点击目标；`false` 可能只是容器。

### `visible`

是否可见。一般只考虑 `visible: true` 的节点。

### `enabled`

是否启用。`false` 的控件可能点不了。

### `focusable`

是否可聚焦，输入框常见为 `true`。

### `anchorPoint`

控件锚点，一般用于 Poco 内部计算，通常不需要改 YAML。

## 推荐 YAML 写法

```yaml
- name: "【操作】点击目标按钮"
  action: "click"
  selector:
    resourceId: "com.xxx:id/btn_target"
  fallback_pos: [0.62, 0.84]
  sleep_after: 1
  snapshot_after: true
```

如果节点树里没有稳定的 `resourceId/desc/text/name`，先用 `fallback_pos`，并保留 `poco_nodes.json` 和 `screen.png` 继续分析。
"""


def execute_steps(
    poco: AndroidUiautomationPoco,
    steps: list[dict[str, Any]],
    snapshot_dir: Path,
    module_name: str = "",
) -> list[dict[str, Any]]:
    """
    【业务流执行函数】按照配置文件里的步骤，一个一个去执行。
    这是整个脚本的“指挥部”。
    
    参数:
        poco: Poco 驱动实例
        steps: 从 YAML 加载的步骤列表
        snapshot_dir: 截图存放的独立文件夹（例如 stamp_screen）。
                      遵循“一模块一文件夹”规则，让日志目录保持整洁。
    """
    # 确保截图文件夹存在，如果不存在就创建一个
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    total_steps = len(steps)
    snapshot_records: list[dict[str, Any]] = []
    click_order = 0
    
    # 循环遍历配置文件里的每一个 step
    for index, step in enumerate(steps, start=1):
        action = step["action"]      # 动作：click, wait, snapshot, sleep 等
        name = step.get("name", f"step_{index}") # 这一步叫什么名字
        selector = step.get("selector", {})      # 怎么找到目标控件
        _record_step_context(index=index, total_steps=total_steps, action=action, name=name)
        
        # 如果配置了 selector，就尝试在屏幕上定位这个控件
        target = resolve_target(poco, selector) if selector else None
        locate_method = "not_required"
        fallback_used = False

        # --- 逻辑分支判断：根据 action 决定做什么 ---
        
        if action == "wait":
            # 等待某个控件出现
            timeout = float(step.get("timeout", 15))
            if not target:
                raise ValueError(f"{name}: wait 动作缺少 selector (我不知道在等谁)")
            # 只要控件在超时时间内出现，就说明这一关通过。
            target.wait_for_appearance(timeout=timeout)
            locate_method = "poco"
            
        elif action == "click":
            # 点击操作
            click_order += 1
            if target and target.exists():
                # 情况 1: 找到了控件，直接点它
                timeout = float(step.get("timeout", 15))
                target.wait_for_appearance(timeout=timeout)
                _click_poco_target(target, step)
                locate_method = "poco"
            elif "fallback_pos" in step:
                # 情况 2: 没找到控件（可能是游戏贴图），但配置了备用坐标
                x, y = step["fallback_pos"]
                # 使用 Airtest 的 touch 命令点击百分比坐标 [0-1]
                touch((x, y))
                locate_method = "fallback_pos"
                fallback_used = True
                _record_locator_context(
                    index=index,
                    name=name,
                    locate_method=locate_method,
                    selector=selector,
                )
            else:
                # 既没控件又没坐标，报错提示
                raise ValueError(f"{name}: click 动作未通过 Poco 找到控件，也没有配置 fallback_pos 坐标")
                
        elif action == "snapshot":
            # 主动执行一张截图。
            # 如果 YAML 里没写 filename，就自动用步骤 name 作为文件名。
            filename = _build_ordered_snapshot_filename(
                index=index,
                raw_filename=step.get("filename", f"{name}.png"),
            )
            _capture_landscape_snapshot(
                image_path=snapshot_dir / filename,
                message=step.get("message", name),
            )
            snapshot_records.append(
                _build_snapshot_record(
                    module_name=module_name,
                    step_index=index,
                    step_name=name,
                    action=action,
                    image_name=filename,
                    image_path=snapshot_dir / filename,
                    locate_method=locate_method,
                    fallback_used=False,
                    click_order=None,
                    selector=selector,
                )
            )
            
        elif action == "sleep":
            # 强制等待几秒。
            # 这类步骤通常用于等动画、等网络、等页面稳定。
            sleep(float(step.get("seconds", 1)))
            
        elif action == "assert_exists":
            # 断言（检查）某个控件是否存在
            timeout = float(step.get("timeout", 15))
            if not target:
                raise ValueError(f"{name}: assert_exists 动作缺少 selector")
            target.wait_for_appearance(timeout=timeout)
            locate_method = "poco"
            
        else:
            raise ValueError(f"不支持的业务动作: {action} (请检查 yaml 拼写是否正确)")

        # 操作后如果配置了 snapshot_after，就再截一张图记录状态
        if step.get("snapshot_after", False):
            snapshot_delay_seconds = _get_snapshot_delay_seconds(step, action)
            if snapshot_delay_seconds > 0:
                # 点击后立刻截图经常会拿到动画中间态，这里先等界面稳定一下。
                sleep(snapshot_delay_seconds)
            # snapshot_after 属于“动作执行完后自动补一张图”。
            # 现在默认也走 name.png 规则，方便小白直接从文件名看出每张图的用途。
            snapshot_name = _build_ordered_snapshot_filename(
                index=index,
                raw_filename=step.get("snapshot_name", f"{name}.png"),
            )
            _capture_landscape_snapshot(
                image_path=snapshot_dir / snapshot_name,
                message=step.get("snapshot_message", name),
            )
            snapshot_records.append(
                _build_snapshot_record(
                    module_name=module_name,
                    step_index=index,
                    step_name=name,
                    action=action,
                    image_name=snapshot_name,
                    image_path=snapshot_dir / snapshot_name,
                    locate_method=locate_method,
                    fallback_used=fallback_used,
                    click_order=click_order if action == "click" else None,
                    selector=selector,
                )
            )

    return snapshot_records


def _click_poco_target(target: Any, step: dict[str, Any]) -> None:
    """用 Poco 点击控件，支持在控件内部指定相对点击点。"""
    relative_pos = step.get("relative_pos")
    if relative_pos is None:
        target.click()
        return
    if not isinstance(relative_pos, (list, tuple)) or len(relative_pos) != 2:
        raise ValueError(f"{step.get('name', 'unknown')}: relative_pos 必须是 [x, y]")
    target.click([float(relative_pos[0]), float(relative_pos[1])])


def _build_snapshot_record(
    *,
    module_name: str,
    step_index: int,
    step_name: str,
    action: str,
    image_name: str,
    image_path: Path,
    locate_method: str,
    fallback_used: bool,
    click_order: int | None,
    selector: dict[str, Any],
) -> dict[str, Any]:
    """生成表格/报告共用的截图记录。"""
    record: dict[str, Any] = {
        "module_name": module_name,
        "step_index": step_index,
        "step_name": step_name,
        "action": action,
        "image_name": image_name,
        "image_path": str(image_path.resolve()),
        "locate_method": locate_method,
        "fallback_used": fallback_used,
        "selector": _selector_summary(selector),
    }
    if click_order is not None:
        record["click_order"] = click_order
    return record


def _record_locator_context(
    *,
    index: int,
    name: str,
    locate_method: str,
    selector: dict[str, Any],
) -> None:
    """把定位方式写入 Airtest 日志，方便后续排查 Poco 覆盖率。"""
    airtest_log(
        json.dumps(
            {
                "kind": "locator_context",
                "step_index": index,
                "step_name": name,
                "locate_method": locate_method,
                "selector": _selector_summary(selector),
            },
            ensure_ascii=False,
        ),
        desc="LOCATOR_CONTEXT",
        snapshot=False,
    )


def _selector_summary(selector: dict[str, Any]) -> str:
    if not selector:
        return ""
    safe_selector = {
        key: value
        for key, value in selector.items()
        if key in {"name", "text", "text_matches", "type", "resourceId", "resource_id", "desc", "name_matches", "index"}
    }
    return json.dumps(safe_selector, ensure_ascii=False, sort_keys=True)


def _build_ordered_snapshot_filename(index: int, raw_filename: str) -> str:
    """
    为截图文件名补一个固定宽度的步骤序号前缀。

    这样无论是在日志目录里按文件名看，还是在某些按文件名展示的面板里看，
    截图顺序都会稳定对齐到实际执行顺序。
    """
    path = Path(raw_filename)
    prefix = f"{index:02d}_"
    if re.match(r"^\d{2}_", path.name):
        return path.name
    return f"{prefix}{path.name}"


def _capture_landscape_snapshot(image_path: Path, message: str) -> None:
    """
    保存业务截图，并在落盘后统一修正成横版。

    当前项目的业务页面是横屏为主，所以这里把竖版截图统一旋转成横版，
    避免日志目录和表格里看到的图片方向不一致。
    """
    _ = snapshot(filename=str(image_path), msg=message)
    _ = normalize_image_file_for_landscape(image_path)


def _get_snapshot_delay_seconds(step: dict[str, Any], action: str) -> float:
    """
    计算 `snapshot_after` 前需要等待多久。

    规则：
    1. 优先使用显式配置的 `snapshot_delay_seconds`；
    2. 兼容沿用现有 YAML 里的 `sleep_after`；
    3. 对 click 动作，如果都没配，默认等待 1 秒再截图。
    """
    if "snapshot_delay_seconds" in step:
        return float(step.get("snapshot_delay_seconds", 0) or 0)
    if "sleep_after" in step:
        return float(step.get("sleep_after", 0) or 0)
    if action == "click":
        return 1.0
    return 0.0


def _record_step_context(index: int, total_steps: int, action: str, name: str) -> None:
    """
    在 Airtest 的原始 log.txt 里插入一条“业务步骤上下文”。

    后续日志清洗阶段会利用这条上下文，把 step 名称补到 touch/snapshot/sleep 等动作上，
    让最终日志更适合人工直接阅读。
    """
    airtest_log(
        json.dumps(
            {
                "kind": "step_context",
                "step_index": index,
                "step_total": total_steps,
                "step_action": action,
                "step_name": name,
            },
            ensure_ascii=False,
        ),
        desc="STEP_CONTEXT",
        snapshot=False,
    )


def resolve_target(
    poco: AndroidUiautomationPoco,
    selector: dict[str, Any],
):
    """
    【定位工具】把配置文件里的 selector 翻译成 Poco 驱动能懂的查询语句。
    支持按 text, resourceId, type 等各种属性找人。
    """
    attrs: dict[str, Any] = {}
    name = str(selector.get("name") or "") # 控件的名字（对应 Poco 的第一个参数）

    # 把我们熟悉的属性名映射到 Poco 的内部参数
    if selector.get("text"):
        attrs["text"] = selector["text"]
    if selector.get("text_matches"):
        attrs["textMatches"] = selector["text_matches"]
    if selector.get("type"):
        attrs["type"] = selector["type"]
    if selector.get("resourceId"):
        attrs["resourceId"] = selector["resourceId"]
    if selector.get("resource_id"):
        attrs["resourceId"] = selector["resource_id"]
    if selector.get("desc"):
        attrs["desc"] = selector["desc"]
    if selector.get("name_matches"):
        attrs["nameMatches"] = selector["name_matches"]

    # 构造 Poco 查询对象
    # 这里先按“当前节点条件”查一次。
    target = poco(name, **attrs)

    # 如果配置了 parent，说明这个控件在某个特定的父节点下面
    parent = selector.get("parent")
    if parent:
        # 先找到爸爸，再在爸爸的“后代”(offspring) 里找这个控件
        parent_target = resolve_target(poco, parent)
        target = parent_target.offspring(name, **attrs)

    if "index" in selector:
        target = target[int(selector["index"])]

    return target


def load_steps(flow_path: Path) -> dict[str, Any]:
    """
    【配置加载器】把 YAML 文件读进内存，变成 Python 字典。
    """
    import yaml
    # safe_load 比较安全，适合读这种“纯配置型 YAML”。
    # 如果文件里什么都没有，就返回空字典，避免后面直接报 NoneType 错误。
    loaded = yaml.safe_load(flow_path.read_text(encoding="utf-8")) or {}
    validate_flow_config(loaded, flow_path)
    return loaded


def validate_flow_config(flow: Any, flow_path: Path) -> None:
    """运行前校验 YAML 业务流，尽早暴露配置问题。"""
    if not isinstance(flow, dict):
        raise ValueError(f"【配置格式错误】{flow_path.resolve()} 顶层必须是 YAML 对象。")

    steps = flow.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"【配置为空】{flow_path.resolve()} 里没有可执行 steps。")

    errors: list[str] = []
    for index, raw_step in enumerate(steps, start=1):
        if not isinstance(raw_step, dict):
            errors.append(f"第 {index} 步必须是 YAML 对象。")
            continue
        errors.extend(_validate_step(raw_step, index))

    if errors:
        joined_errors = "\n".join(f"- {item}" for item in errors)
        raise ValueError(f"【配置校验失败】{flow_path.resolve()}\n{joined_errors}")


def _validate_step(step: dict[str, Any], index: int) -> list[str]:
    errors: list[str] = []
    name = str(step.get("name") or f"第 {index} 步")
    action = step.get("action")
    supported_actions = {"sleep", "click", "snapshot", "wait", "assert_exists"}

    if not isinstance(action, str) or not action.strip():
        errors.append(f"{name}: 缺少 action。")
        return errors

    action = action.strip()
    if action not in supported_actions:
        errors.append(f"{name}: 不支持的 action `{action}`，可选值为 {sorted(supported_actions)}。")
        return errors

    selector = step.get("selector")
    if selector is not None and not isinstance(selector, dict):
        errors.append(f"{name}: selector 必须是对象。")
    elif isinstance(selector, dict):
        errors.extend(_validate_selector(selector, f"{name}.selector"))

    if action == "click" and not selector and "fallback_pos" not in step:
        errors.append(f"{name}: click 必须配置 selector 或 fallback_pos。")
    if action in {"wait", "assert_exists"} and not selector:
        errors.append(f"{name}: {action} 必须配置 selector。")
    if action == "sleep":
        errors.extend(_validate_non_negative_number(step.get("seconds", 1), f"{name}.seconds"))

    if "fallback_pos" in step:
        errors.extend(_validate_normalized_point(step.get("fallback_pos"), f"{name}.fallback_pos"))
    if "relative_pos" in step:
        errors.extend(_validate_normalized_point(step.get("relative_pos"), f"{name}.relative_pos"))
    if "sleep_after" in step:
        errors.extend(_validate_non_negative_number(step.get("sleep_after"), f"{name}.sleep_after"))
    if "snapshot_delay_seconds" in step:
        errors.extend(_validate_non_negative_number(step.get("snapshot_delay_seconds"), f"{name}.snapshot_delay_seconds"))
    if "timeout" in step:
        errors.extend(_validate_non_negative_number(step.get("timeout"), f"{name}.timeout"))

    snapshot_after = step.get("snapshot_after")
    if snapshot_after is not None and not isinstance(snapshot_after, bool):
        errors.append(f"{name}: snapshot_after 必须是 true 或 false。")

    return errors


def _validate_selector(selector: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    supported_keys = {
        "name",
        "text",
        "text_matches",
        "type",
        "resourceId",
        "resource_id",
        "desc",
        "name_matches",
        "index",
        "parent",
    }
    unknown_keys = sorted(set(selector) - supported_keys)
    if unknown_keys:
        errors.append(f"{prefix}: 包含暂不支持的字段 {unknown_keys}。")
    if "index" in selector:
        index_value = selector.get("index")
        if not isinstance(index_value, int) or isinstance(index_value, bool) or index_value < 0:
            errors.append(f"{prefix}.index 必须是大于等于 0 的整数。")
    parent = selector.get("parent")
    if parent is not None:
        if not isinstance(parent, dict):
            errors.append(f"{prefix}.parent 必须是对象。")
        else:
            errors.extend(_validate_selector(parent, f"{prefix}.parent"))
    return errors


def _validate_normalized_point(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return [f"{field_name} 必须是 [x, y] 二维坐标。"]
    errors: list[str] = []
    for axis, raw_number in zip(("x", "y"), value):
        if not isinstance(raw_number, (int, float)) or isinstance(raw_number, bool):
            errors.append(f"{field_name}.{axis} 必须是数字。")
            continue
        if not 0 <= float(raw_number) <= 1:
            errors.append(f"{field_name}.{axis} 必须在 0 到 1 之间。")
    return errors


def _validate_non_negative_number(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return [f"{field_name} 必须是数字。"]
    if float(value) < 0:
        return [f"{field_name} 必须大于等于 0。"]
    return []
