# 多语言 UI 检查辅助工具使用说明

这份文档按“完全没接触过代码的人也能照着跑”的标准来写。你可以把这个项目理解成一个自动化截图助手：它连接 Android 模拟器或手机，按 YAML 文件里写好的步骤点击游戏 UI，然后把关键页面截图整理到钉钉在线表格和 HTML 报告里，方便人工检查多语言文案和界面展示。

## 先记住这几句话

- 当前项目只使用 Poco selector 点击游戏节点，不使用坐标兜底。
- 日常最常用的工具是 `dump_current_screen.py`，它会导出当前页面截图、Poco 节点树和可复制执行的 `nodes_steps.yaml`。
- 日常最常改的是 `config/*.yaml`，不是 Python 代码。
- `atw_test`、`byd_test`、`stamp_test` 是三个独立模块，需要哪个就单独跑哪个。
- 当前已开启“方案 2（Cursor MCP 版）”：模块执行完成后生成待同步 JSON，不再生成本地 Excel；随后由 Cursor MCP 写入钉钉在线表格。
- 单模块执行前会列出默认产物目录内容，让你手动选择要删除哪些旧文件。
- 默认产物目录是 `/Users/sunyi/Downloads/multilang_check_artifacts`。
- 当前钉钉结果表使用你的模板：`https://alidocs.dingtalk.com/i/nodes/dpYLaezmVNLd17qQSPXQzPAq8rMqPxX6?utm_scene=team_space`。

## 项目目录怎么看

```text
multilang_check_test/
├── cases/
│   ├── atw_test.air/atw_test.py       # atw 模块入口
│   ├── byd_test.air/byd_test.py       # byd 模块入口
│   └── stamp_test.air/stamp_test.py   # stamp 模块入口
├── config/
│   ├── atw_test.yaml                  # atw 模块步骤配置
│   ├── byd_test.yaml                  # byd 模块步骤配置
│   ├── stamp_test.yaml                # stamp 模块步骤配置
│   ├── devices.example.yaml           # 旧批量回归设备配置示例
│   └── devices.yaml                   # 旧批量回归设备配置
├── src/airtest_ai_runner/             # 公共执行器和工具代码
├── dump_current_screen.py             # 最常用：导出当前页面节点和可复制 YAML
├── poco_hover_inspector.py            # 辅助：在截图上看鼠标位置和节点
├── README.md                          # 本说明文档
├── requirements.txt                   # Python 依赖
└── run_regression.sh                  # 旧批量回归入口，不是当前主入口
```

你平时主要会接触这三类文件：

- `dump_current_screen.py`：先手动把游戏停在目标页面，再运行它导出 `nodes_steps.yaml`。
- `config/*.yaml`：把 `nodes_steps.yaml` 里挑好的步骤复制到对应模块配置里。
- `cases/*.air/*.py`：真正执行模块时运行这些入口脚本。

## 当前点击策略

当前项目只走 Poco selector，不走坐标点击。

推荐 selector 格式是 `name + chain`：

```yaml
- name: "【操作】点击COLLECTIONS"
  action: "click"
  selector:
    name: "Lobby_Footer_Node"
    chain:
      - method: "child"
        name: "footer"
      - method: "child"
        name: "middle_node"
      - method: "child"
        name: "a_set_node"
  sleep_after: 1
  snapshot_after: true
```

这段的意思是：

- 先找名为 `Lobby_Footer_Node` 的 Poco 节点。
- 再往下找它的 `child("footer")`。
- 再往下找 `child("middle_node")`。
- 再往下找 `child("a_set_node")`。
- 找到后用 Poco 点击这个节点。
- 点击后等 `1` 秒。
- 等完后自动截图。

不要再写坐标字段。项目已经移除坐标兜底，配置里出现不支持字段时会提前报错。

## 第一次运行前准备

先确认你的电脑满足下面条件：

- 已安装 `Python 3`。
- 已安装 `adb`。
- 模拟器或 Android 真机能被 `adb devices` 识别。
- 游戏包是可被 Poco 读取节点树的 debug/test 包。

进入项目目录：

```bash
cd /Users/sunyi/Downloads/multilang_check_test
```

创建并启用 Python 虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"
```

如果你看到终端前面有 `(.venv)`，说明虚拟环境已经启用。

## 钉钉表格同步配置

当前项目已经改成“方案 2（Cursor MCP 版）”。

这个版本不会在本地 Python 脚本里填写 `appKey`、`appSecret`、`accessToken`，也不会直接调用钉钉开放 API。脚本执行结束后会生成一份待同步 JSON 文件，然后由 Cursor 里已经授权的钉钉 MCP 工具把它写入在线表格。

钉钉结果表：

```text
https://alidocs.dingtalk.com/i/nodes/dpYLaezmVNLd17qQSPXQzPAq8rMqPxX6?utm_scene=team_space
```

表格列含义：

- A 列 `描述`：写 YAML 中的 `name`，也就是截图名称。
- B 列 `截图`：由 Cursor MCP 上传真实截图并插入图片，不写本地路径文本。

你的模板前两行已经有表头，所以 Cursor MCP 同步时从第 3 行开始写。

模块执行后会生成类似这样的文件：

```text
/Users/sunyi/Downloads/multilang_check_artifacts/YYYY-MM-DD/dingtalk_pending/20260714_204500_atw_test.json
```

然后在 Cursor 对话里说：

```text
把最新 dingtalk_pending 写入钉钉表格
```

Cursor 会读取最新 JSON，并使用已授权的 `user-dingtalk-sheets` / `user-dingtalk-docs` MCP 工具追加到钉钉表格。这样就完全复用 Cursor MCP 的授权，不需要你手动提供企业内部应用密钥。

注意：截图必须用 `write_image` 写入单元格，不能用 `create_float_image` 浮动图片。浮动图片会超出单元格，也容易和左侧描述错位。

说明：

- 本地脚本只负责跑游戏、截图、生成待同步 JSON。
- Cursor MCP 负责真正写入钉钉表格。
- Cursor MCP 同步时会把本地截图上传到钉钉，再用单元格图片方式插入模板 B 列。

## 最推荐的新手流程

### 1. 手动把游戏停在目标页面

先在模拟器或手机里手动操作游戏，让页面停在你想自动化点击的界面。

例如你想点击 `COLLECTIONS`，就先让游戏停在能看到 `COLLECTIONS` 的页面。

### 2. 导出当前页面 Poco 节点

运行：

```bash
cd /Users/sunyi/Downloads/multilang_check_test
source .venv/bin/activate
python dump_current_screen.py
```

如果有多台设备，脚本会让你选择；如果你想指定设备，可以这样：

```bash
DEVICE_SERIAL="127.0.0.1:16448" python dump_current_screen.py
```

执行成功后看这个目录：

```text
/Users/sunyi/Downloads/multilang_check_artifacts/current_dump/
```

里面会有这些文件：

```text
screen.png              # 当前页面截图，用来肉眼确认页面对不对
nodes.json              # 完整 Poco 节点树，内容比较多，主要用于排查
nodes字段说明.md         # nodes.json 字段说明
nodes_steps.yaml        # 最重要，可直接复制到 config/*.yaml 的步骤片段
```

### 3. 打开 `nodes_steps.yaml` 找目标节点

打开：

```text
/Users/sunyi/Downloads/multilang_check_artifacts/current_dump/nodes_steps.yaml
```

搜索你在页面上看到的节点名，例如 `COLLECTIONS`、`a_set_node`、`title_label` 等。

自动生成的步骤会带一段注释。注释用于人工识别节点，真正执行的是 `- name:` 开始的 YAML：

```yaml
  # ------------------------------------------------------------
  # 节点识别: a_set_node
  # 显示文本: COLLECTIONS
  # Poco中心点: [0.4049, 0.9543]
  # Poco大小: [0.1277, 0.0444]
  # Poco路径: root/1:<Node | Tag = -1/1:Lobby_Footer_Node/0:footer/2:middle_node/3:a_set_node
  # 复制建议: 优先复制下面从 '- name:' 开始的整个步骤到 config/*.yaml 的 steps 下。
  - name: 【操作】点击a_set_node
    action: click
    selector:
      name: Lobby_Footer_Node
      chain:
        - method: child
          name: footer
        - method: child
          name: middle_node
        - method: child
          name: a_set_node
    sleep_after: 1
    snapshot_after: true
```

这类结构已经带好缩进，可以直接复制到模块 YAML 的 `steps:` 下面。

怎么看这个节点是不是你要的：

- 先打开同目录下的 `screen.png`，确认当前页面和你想操作的页面一致。
- 看注释里的 `节点识别`，通常越像业务名越值得优先尝试，例如 `a_set_node`、`close_btn`、`confirm_button`。
- 看注释里的 `显示文本`，如果能看到 `COLLECTIONS`、`OK`、`领取` 这类文案，就能帮助你确认大概对应哪个 UI。
- 看注释里的 `Poco路径`，如果最后一段是 `title_label`，它可能只是文字；真正可点击的通常是它上一级的按钮容器。
- 看注释里的 `Poco中心点` 和 `Poco大小`，它们只用于人工核对位置，不要写成点击坐标。

### 4. 复制到对应模块配置

例如你要改 `atw_test`，打开：

```text
config/atw_test.yaml
```

把 `nodes_steps.yaml` 里选好的步骤复制到 `steps:` 下面。生成内容已经带两格缩进，复制时不要删掉 `- name:` 前面的空格。

复制后第一件事：手动改 `name`。

`nodes_steps.yaml` 自动生成的 `name` 可能是 Poco 内部节点名，例如：

```yaml
  - name: 【操作】点击timer_label
```

这种名字能执行，但不方便最终核对。建议改成肉眼能看懂的页面文案或业务动作，例如：

```yaml
  - name: 【操作】点击83D 15H
```

为什么一定要改清楚：

- `atw_screen/` 里的截图文件名会使用这个 `name`。
- 钉钉表格 C 列的截图名称会使用这个 `name`。
- HTML 报告最后的截图名称也会使用这个 `name`。
- 名字写清楚后，检查截图、钉钉表格和报告时不用再反推 `timer_label` 到底是什么。

注意缩进很重要。`selector`、`name`、`chain` 必须在同一层级下。例如：

```yaml
steps:
  - name: "【准备】等待主界面完全加载"
    action: "sleep"
    seconds: 3

  - name: "【操作】点击COLLECTIONS"
    action: "click"
    selector:
      name: "Lobby_Footer_Node"
      chain:
        - method: "child"
          name: "footer"
        - method: "child"
          name: "middle_node"
        - method: "child"
          name: "a_set_node"
    sleep_after: 1
    snapshot_after: true
```

### 5. 执行模块

例如执行 `atw_test`：

```bash
cd /Users/sunyi/Downloads/multilang_check_test
source .venv/bin/activate
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"
python cases/atw_test.air/atw_test.py
```

如果要指定设备和包名：

```bash
DEVICE_SERIAL="127.0.0.1:16448" APP_PACKAGE_NAME="slots.pcg.casino.games.free.android" python cases/atw_test.air/atw_test.py
```

## 三个模块怎么跑

三个模块是独立入口，不会一条命令连续跑完。

```bash
python cases/atw_test.air/atw_test.py
python cases/byd_test.air/byd_test.py
python cases/stamp_test.air/stamp_test.py
```

当前已按 Poco selector 验证过的是 `atw_test` 里的 `COLLECTIONS` 示例链路。

`byd_test.yaml` 和 `stamp_test.yaml` 里原来依赖坐标的点击步骤已经改成“待补 selector 的截图步骤”。这样直接运行时不会因为缺 selector 报错，但也不会自动点击进入完整业务页面。如果要恢复完整业务点击，需要先在对应页面运行 `dump_current_screen.py`，再把生成的 `name + chain` selector 复制进对应步骤，并把 `action: "snapshot"` 改回 `action: "click"`。

## 配置文件字段解释

每个模块配置文件大致分两段：基础配置和步骤配置。

基础配置示例：

```yaml
package_name_env: "APP_PACKAGE_NAME"
startup_wait_seconds: 3
stop_app_after_run: false
dump_poco_tree: true
excel_sheet_name: "atw"
dingtalk_export:
  enabled: true
  workbook_id: "https://alidocs.dingtalk.com/i/nodes/dpYLaezmVNLd17qQSPXQzPAq8rMqPxX6?utm_scene=team_space"
  sheet_id: "kgqie6hm"
```

字段解释：

- `package_name_env`：从哪个环境变量读取 App 包名，通常不用改。
- `startup_wait_seconds`：启动 App 后先等几秒，避免游戏还没加载完就开始点。
- `stop_app_after_run`：跑完后是否关闭 App，通常设为 `false`，方便你继续看现场。
- `dump_poco_tree`：每次运行时是否导出 Poco 节点树，建议保留 `true`，方便排查。
- `excel_sheet_name`：只有关闭钉钉导出时才会用到，表示本地 Excel 的 sheet 名。
- `dingtalk_export.enabled`：是否启用钉钉 MCP 待同步文件生成，当前三个模块都设为 `true`。
- `dingtalk_export.workbook_id`：钉钉在线表格链接或文档 ID。
- `dingtalk_export.sheet_id`：钉钉在线表格里的工作表 ID。

步骤配置常用字段：

- `name`：步骤名称，也是截图文件名的一部分，建议写清楚你在做什么。
- `action`：动作类型，常用 `sleep`、`click`、`snapshot`。
- `selector`：Poco 定位信息，点击和等待节点时必须有。
- `chain`：沿着 Poco 节点树一层层往下找子节点。
- `relative_pos`：可选，点击控件内部某个相对位置，例如 `[0.5, 0.5]` 表示控件中心。
- `sleep_after`：点击后等几秒再继续。
- `snapshot_after`：这个步骤执行后是否自动截图。

## 两个辅助工具

### `dump_current_screen.py`

这是最重要的辅助工具。

适合场景：

- 你不知道某个按钮的 Poco selector 怎么写。
- 你想导出当前页面所有 Poco 节点。
- 你想得到可以直接复制到模块 YAML 的 `name + chain` 步骤。

运行：

```bash
python dump_current_screen.py
```

输出：

```text
/Users/sunyi/Downloads/multilang_check_artifacts/current_dump/screen.png
/Users/sunyi/Downloads/multilang_check_artifacts/current_dump/nodes.json
/Users/sunyi/Downloads/multilang_check_artifacts/current_dump/nodes_steps.yaml
```

优先看 `nodes_steps.yaml`，不要优先手写 `nodes.json`。

### `poco_hover_inspector.py`

这是辅助核对工具，不是主流程。

适合场景：

- 你想在截图上移动鼠标，看当前位置大概是多少归一化坐标。
- 你想知道鼠标当前位置覆盖到了哪个 Poco 节点。

运行：

```bash
python poco_hover_inspector.py
```

它会弹出一个截图窗口。鼠标移动时，窗口左上角会显示当前坐标和命中的节点信息。这个工具只用于辅助观察，不建议把它的坐标写进模块 YAML。

## 运行结果去哪里看

默认产物根目录：

```text
/Users/sunyi/Downloads/multilang_check_artifacts
```

模块脚本启动时会先检查这个目录下已有内容，并提示你选择要清理的文件或目录：

```text
请输入要删除的编号，例如 1,3,5-7；直接回车表示不删除；输入 all 删除全部。
```

常用选择：

- 直接回车：什么都不删，保留旧报告和 `current_dump`。
- 输入 `1,3`：删除列表里的第 1 项和第 3 项。
- 输入 `2-4`：删除列表里的第 2 到第 4 项。
- 输入 `all`：删除列表里的全部内容。

单模块运行会创建当天目录，例如：

```text
/Users/sunyi/Downloads/multilang_check_artifacts/2026-07-14/
```

常见文件：

```text
atw_screen/
2026-07-14_atw_test_执行报告.html
```

说明：

- `dingtalk_pending/`：模块执行结束后生成的待同步 JSON，用 Cursor MCP 写入钉钉在线表格。
- `atw_screen/`：模块截图目录。
- `执行报告.html`：本次执行报告，双击可以打开。

## 常见错误和排查方法

### 报错：`click 动作未通过 Poco 找到控件，请检查 selector`

意思是：YAML 里写的 Poco selector 在当前运行页面上没找到节点。

常见原因：

- 运行时页面和你导出 `nodes_steps.yaml` 时不是同一个页面。
- 游戏启动等待时间太短，页面还没加载完。
- 复制 YAML 时缩进错了。
- 复制到了文字 Label 节点，但真正能点的是父级按钮容器。

处理顺序：

1. 先看本次截图目录，确认起始页面是不是你想要的页面。
2. 手动把游戏停到目标页面，重新跑 `python dump_current_screen.py`。
3. 在新的 `nodes_steps.yaml` 里重新复制 `name + chain`。
4. 如果节点是 `title_label` 这类文字节点，优先尝试它的父级按钮节点，例如 `a_set_node`。

### 报错：找不到配置文件

检查模块名和配置文件是否对应：

```text
cases/atw_test.air/atw_test.py -> config/atw_test.yaml
cases/byd_test.air/byd_test.py -> config/byd_test.yaml
cases/stamp_test.air/stamp_test.py -> config/stamp_test.yaml
```

### 报错：Poco 控件树读取失败

优先确认：

- 当前 App 是 debug/test 包。
- 游戏内已启用 Cocos2d-x Lua Poco SDK 服务。
- 设备连接正常。
- 终端里能看到 `adb devices`。

### 终端能跑，编辑器报红

优先检查：

```bash
source .venv/bin/activate
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"
python -m pip show airtest pocoui
```

如果依赖缺失，重新安装：

```bash
python -m pip install -r requirements.txt
```

## 给新人的推荐工作方式

1. 先不要改 Python。
2. 手动把游戏停到目标页面。
3. 跑 `python dump_current_screen.py`。
4. 打开 `nodes_steps.yaml`。
5. 复制目标节点的 `name + chain` 到 `config/atw_test.yaml`。
6. 跑 `python cases/atw_test.air/atw_test.py`。
7. 看截图目录和 HTML 报告。
8. 如果点不到，重新导出节点，优先找父级按钮节点。

## 最后再记一次

- 主流程只用 Poco selector。
- `nodes_steps.yaml` 是复制步骤的首选来源。
- 不要在模块 YAML 里写坐标点击。
- 页面不对时，先重新导出当前页面节点。
- 新人第一次调试，建议只跑 `atw_test`，不要同时处理多个模块。
