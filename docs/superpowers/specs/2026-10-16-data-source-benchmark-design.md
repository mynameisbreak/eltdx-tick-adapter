# 双数据源测速脚本规格

## 目标

新增本地命令行脚本 `scripts/benchmark_data_sources.py`，分别测量 ELTDX Gateway 与 AkShare 对现有数据端点的响应耗时。脚本直接调用两个数据源，不经过适配器 HTTP 服务，避免把服务层开销混入数据源耗时。

## 覆盖接口

| 适配器端点 | ELTDX 方法 | AkShare 调用 | 默认参数 |
| --- | --- | --- | --- |
| `/realtime` | `codes.latest_stock_list` + `helpers.full_quotes` | `stock_zh_a_spot_tx` 快照与代码筛选 | 全市场快照 |
| `/daily` | `bars.get`，`period=day` | `stock_zh_a_hist` | `000001.SZ`，最近一个交易日 |
| `/minute` | `bars.get`，`period=1m` | `stock_zh_a_hist_min_em` | `000001.SZ`，最近 30 分钟 |
| `/full_minute` | `bars.get`，`period=1m`，较大 count | `stock_zh_a_hist_min_em` | `000001.SZ`，最近交易日 |
| `/adj_factor` | `corporate.adjustment_factors` | `stock_zh_a_daily(adjust="qfq-factor")` | `000001.SZ` |
| `/financial` | `f10.finance_report`，`report_type=zcfzb` | `stock_financial_report_sina` | `000001.SZ` |
| `/depth5` | `quotes.get_depth` | `stock_bid_ask_em` | `000001.SZ` |

`/health` 不计入数据源测速，因为它只报告适配器进程状态。实时端点按全市场快照能力计时；ELTDX 端的代码表和报价请求合并为一个端点结果。`/minute` 与 `/full_minute` 分别报告，且分别采用其请求窗口和数据量。

## 执行与结果

- 默认每个来源、每个端点执行 3 次，报告成功次数、返回记录数、中位耗时和错误摘要。
- 任一请求失败只标记该次结果并继续其他端点；某来源失败不阻断另一个来源。
- 命令行允许覆盖 ELTDX URL、证券代码、日期窗口、分钟周期、重复次数和 JSON 输出路径。
- 终端输出逐端点对比表；可选 JSON 文件保存完整原始测速结果，含耗时、记录数和错误，不保存行情明细。
- 不修改服务路由、数据源配置、依赖或默认路由策略。

## 验收

- 使用 mock 验证七个端点都被调度，两个来源各自独立计时，单次失败后继续，并正确汇总中位数/错误。
- `python scripts/benchmark_data_sources.py --help` 可运行，不要求 ELTDX 或外网可用。
- 在 ELTDX 和外网可达环境运行时，所有七个端点都显示结果；上游失败必须有明确错误记录，而不是脚本整体中止。
