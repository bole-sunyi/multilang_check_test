"""
Airtest + AI 回归执行器主包。

这个包里的模块大致可以按职责理解成 4 类：
1. `module_runner.py`：stamp/byd/atw 独立截图入口共用的执行编排；
2. `cli.py`：旧批量回归总入口，负责调度设备、用例和报告生成；
3. `poco_utils.py` / `device_utils.py`：负责设备连接、坐标换算、Poco 操作；
4. `log_utils.py` / `image_diff.py` / `excel_export.py`：负责结果清洗、图片比对和 Excel 多 sheet 落地；
5. `report.py` / `single_run_report.py`：负责把运行结果整理成给人看的报告。

新手阅读建议：
先从 `cases/*_test.air/*.py` 或 `module_runner.py` 读起，再顺着调用链进入这些工具模块。
"""
