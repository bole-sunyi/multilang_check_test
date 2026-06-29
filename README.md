# 多语言 UI 检查辅助工具使用说明

这份 README 只保留“当前代码真实支持”的内容，目标是让第一次接手这个项目的人也能照着跑起来。

## 先记 6 句话

- 你最常改的是 `config/*.yaml`，不是 Python 源码。
- `stamp_test`、`byd_test`、`atw_test` 分别独立执行，不会一条命令连续跑三个。
- 单独运行某个模块前，程序会先清空默认产物目录。
- 产物默认写到 `/Users/sunyi/Downloads/artifacts`，也可以用 `ARTIFACTS_ROOT` 临时改掉。
- 当前执行策略是 Poco selector 优先；识别不到游戏贴图时才临时使用 `fallback_pos`。
- 每个模块会把截图写入同一个 Excel 的对应 sheet：`stamp`、`byd`、`atw`。

## 项目里有什么

```text
multilang_check_test/
├── cases/
│   ├── stamp_test.air/stamp_test.py
│   ├── byd_test.air/byd_test.py
│   └── atw_test.air/atw_test.py
├── config/
│   ├── stamp_test.yaml
│   ├── byd_test.yaml
│   ├── atw_test.yaml
│   ├── devices.example.yaml
│   └── devices.yaml
├── src/airtest_ai_runner/
├── quick_click.py
├── dump_current_screen.py
├── poco_hover_inspector.py
├── README.md
├── requirements.txt
└── run_regression.sh
```

你可以这样理解：

- `cases/*.air/*.py`：模块入口，负责连接设备、启动 App、执行步骤。
- `config/*.yaml`：步骤配置，定义 Poco selector、兜底坐标、等待时间、是否截图。
- `src/airtest_ai_runner/`：公共工具代码。
- `run_regression.sh`：旧批量回归入口，不作为多语言截图主入口。
- `quick_click.py`：采真实点击坐标。
- `dump_current_screen.py`：导出当前页面截图和节点树。
- `poco_hover_inspector.py`：看鼠标所在位置的大致归一化坐标。

当前保留的业务模块只有 3 个：

- `stamp_test`
- `byd_test`
- `atw_test`

## 运行前准备

先确认电脑已经具备下面这些条件：

- 安装了 `Python 3`
- 安装了 `adb`
- 模拟器或真机能被 `adb devices` 识别

如果你用的是当前项目默认的 MuMu 模拟器，常见设备串号是：

```text
127.0.0.1:16448
```

## 第一次跑通

下面是推荐的新手路径。

### 1. 进入项目目录

```bash
cd /Users/sunyi/Downloads/multilang_check_test
```

如果你的项目不在这个位置，把上面的路径换成你自己的项目目录即可。

### 2. 准备 Python 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"
```

### 3. 分别执行模块

多语言截图工具不做“一键连续跑三个模块”，需要哪个模块就执行哪个入口：

```bash
python cases/stamp_test.air/stamp_test.py
python cases/byd_test.air/byd_test.py
python cases/atw_test.air/atw_test.py
```

每个模块运行时会自动做这些事：

- 清空默认产物目录
- 重新启动 App
- 读取对应 `config/*_test.yaml`
- 使用 Poco selector 优先执行步骤
- 自动截图并修正为横版
- 把截图写入 Excel 对应 sheet
- 生成当前模块自己的 `report.md`、`report.html`、`report.json`

### 4. 设备和包名

默认设备串号是 `127.0.0.1:16448`，默认包名是 `slots.pcg.casino.games.free.android`。如果要覆盖，可以这样：

```bash
DEVICE_SERIAL="你的设备串号" APP_PACKAGE_NAME="你的真实包名" python cases/atw_test.air/atw_test.py
```

`config/devices.yaml` 仍保留给旧批量回归入口使用。当前项目可用的配置长这样：

```yaml
adb_host: "127.0.0.1"
adb_port: 5037
parallel_workers: 4
retry_count: 1
cases_dir: "cases"
output_dir: "/Users/sunyi/Downloads/artifacts"
baseline_dir: "baselines"
diff_threshold: 0.01
refresh_baseline: false
create_missing_baseline: true

devices:
  - name: "emulator-local"
    serial: "127.0.0.1:16448"
    platform: "android"
    enabled: true
```

你最需要确认的是 `devices[].serial`：

- 模拟器一般像 `127.0.0.1:16448`
- 真机一般是 `adb devices` 看到的设备序列号
- 写错就会连不上

## 单独运行某一个模块

例如只跑 `atw_test`：

```bash
cd /Users/sunyi/Downloads/multilang_check_test
source .venv/bin/activate
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"
python cases/atw_test.air/atw_test.py
```

`byd_test` 和 `stamp_test` 也是同样写法：

```bash
python cases/byd_test.air/byd_test.py
python cases/stamp_test.air/stamp_test.py
```

### 单模块运行和 Excel

单模块脚本默认会更新这个 Excel 模板：

```text
/Users/sunyi/Downloads/多语测试模板.xlsx
```

如果这个文件不存在，脚本会自动创建一份最小可用工作簿。`stamp_test` 写入 `stamp` sheet，`byd_test` 写入 `byd` sheet，`atw_test` 写入 `atw` sheet。每个 sheet 从 A3/B3/C3 开始写入步骤名称、截图、定位方式。

如果你想写入别的模板，可以用环境变量覆盖：

```bash
EXCEL_TEMPLATE_PATH="/Users/sunyi/Downloads/我的多语模板.xlsx" python cases/atw_test.air/atw_test.py
```

也可以使用语义更明确的变量名：

```bash
MULTILANG_EXCEL_TEMPLATE_PATH="/Users/sunyi/Downloads/我的多语模板.xlsx" python cases/atw_test.air/atw_test.py
```

## 最常用的环境变量

下面几个最常用：

- `APP_PACKAGE_NAME`：覆盖目标 App 包名。
- `ARTIFACTS_ROOT`：覆盖产物输出目录。
- `DEVICE_SERIAL`：单脚本和辅助脚本使用的默认设备串号。
- `AIRTEST_DEVICE_URI`：高级用法，直接覆盖 Airtest 设备连接串。

例如单跑某个模块并指定设备：

```bash
cd /Users/sunyi/Downloads/multilang_check_test
source .venv/bin/activate
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"
DEVICE_SERIAL="127.0.0.1:16448" python cases/atw_test.air/atw_test.py
```

## 结果去哪里看

默认产物目录：

```text
/Users/sunyi/Downloads/artifacts
```

如果你在执行前传了 `ARTIFACTS_ROOT`，实际输出位置会改成你指定的目录。

### 旧批量回归后

如果你仍然使用 `run_regression.sh`，通常先看这些：

- `report.md`
- `report.html`
- `report.json`
- `raw_results.json`

也就是：

```text
/Users/sunyi/Downloads/artifacts/report.md
/Users/sunyi/Downloads/artifacts/report.html
/Users/sunyi/Downloads/artifacts/report.json
/Users/sunyi/Downloads/artifacts/raw_results.json
```

### 单跑某个模块后

例如单跑 `atw_test`，常看这些：

```text
/Users/sunyi/Downloads/artifacts/atw_test_logs/
/Users/sunyi/Downloads/artifacts/atw_test_logs/report.md
/Users/sunyi/Downloads/artifacts/atw_test_logs/report.html
/Users/sunyi/Downloads/artifacts/atw_test_logs/report.json
/Users/sunyi/Downloads/artifacts/atw_test_logs/atw_screen/
```

另外两个模块同理：

- `byd_test` 对应 `byd_test_logs/byd_screen`
- `stamp_test` 对应 `stamp_test_logs/stamp_screen`

## 你最常改什么

平时通常只要改 YAML：

- `config/stamp_test.yaml`
- `config/byd_test.yaml`
- `config/atw_test.yaml`

最常改的字段：

- `selector`：Poco 定位信息，优先填写
- `relative_pos`：可选，指定控件内部的相对点击点
- `fallback_pos`：Poco 识别不到时的临时兜底坐标
- `sleep_after`：点击后额外等待多久
- `snapshot_after`：这一步后是否自动截图
- `startup_wait_seconds`：App 启动后等待多久再开始执行

一个最常见的步骤长这样：

```yaml
- name: "【操作】点击目标按钮"
  action: "click"
  selector:
    text: "目标按钮"
    index: 0
  relative_pos: [0.5, 0.5]
  fallback_pos: [0.62, 0.84]
  sleep_after: 1
  snapshot_after: true
```

## 截图命名规则

当前已经统一成“默认按步骤 `name` 自动命名”。

例如：

```yaml
- name: "【操作】点击底部入口按钮"
  action: "click"
  selector:
    desc: "入口按钮"
  fallback_pos: [0.082, 0.383]
  snapshot_after: true
```

如果你没有手工写 `snapshot_name`，程序会自动生成类似下面这种文件名：

```text
01_【操作】点击底部入口按钮.png
```

这样做的好处是：

- 一眼能看出这是哪一步
- 文件名天然按执行顺序排序
- YAML 不需要再维护一堆额外截图名

## 3 个辅助工具怎么用

### 1. 重新采坐标：`quick_click.py`

```bash
cd /Users/sunyi/Downloads/multilang_check_test
source .venv/bin/activate
python quick_click.py
```

它会：

- 监听你在设备上的真实点击
- 自动换算成 `0-1` 百分比坐标
- 保存到 `/Users/sunyi/Downloads/artifacts/quick_click/`
- 生成可直接粘贴到 YAML 的步骤片段

### 2. 导出当前页面：`dump_current_screen.py`

```bash
cd /Users/sunyi/Downloads/multilang_check_test
source .venv/bin/activate
python dump_current_screen.py
```

如果要指定设备串号：

```bash
DEVICE_SERIAL="127.0.0.1:16448" python dump_current_screen.py
```

它会导出：

- 当前截图 `screen.png`
- 当前页面节点树 `nodes.json`
- 默认输出到 `/Users/sunyi/Downloads/artifacts/current_dump/`

### 3. 鼠标悬停看坐标：`poco_hover_inspector.py`

```bash
cd /Users/sunyi/Downloads/multilang_check_test
source .venv/bin/activate
python poco_hover_inspector.py
```

如果要指定设备串号：

```bash
DEVICE_SERIAL="127.0.0.1:16448" python poco_hover_inspector.py
```

它会弹出当前截图窗口，鼠标移动时终端会实时显示当前位置的大概归一化坐标。

### 4. 导出 Poco 节点树：`poco_inspector.py`

```bash
cd /Users/sunyi/Downloads/multilang_check_test
source .venv/bin/activate
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"
python -m airtest_ai_runner.poco_inspector
```

如果要手工指定输出目录：

```bash
python -m airtest_ai_runner.poco_inspector --output-dir /Users/sunyi/Downloads/artifacts/manual_inspect
```

## 如果按钮点不准

建议按这个顺序排查：

1. 先看截图目录，确认当前页面是不是你以为的页面。
2. 再看同目录下的 `poco_nodes.json`，确认 Poco 有没有识别到节点。
3. 如果能在节点树里找到目标，优先把 `text`、`resourceId`、`desc`、`name` 等写进 `selector`。
4. 如果节点树完全没有目标，再用 `quick_click.py` 重新采 `fallback_pos` 临时兜底。

## 如果终端能跑、编辑器报红

优先检查下面 3 件事：

1. 终端提示符前是否有 `(.venv)`。
2. `python -m pip show airtest pocoui` 是否能看到依赖。
3. 需要导入项目自定义包时，是否设置了 `PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"`

如果依赖不完整，可以重新安装：

```bash
cd /Users/sunyi/Downloads/multilang_check_test
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 最后记住

- 新人第一次跑，优先单独跑一个模块，例如 `python cases/atw_test.air/atw_test.py`
- 日常改步骤，优先改 `config/*.yaml`
- 默认产物看 `/Users/sunyi/Downloads/artifacts`
- 能用 Poco selector 就先用 Poco，坐标只作为临时兜底
