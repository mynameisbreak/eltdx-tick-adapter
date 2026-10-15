# market-data-tick-adapter

把 Fuyao REST API、Stock SDK 和 ELTDX 行情能力转换为 [Tick Stock Panel](https://github.com/shy3130/tick-stock-panel) 可直接使用的 HTTP 数据源。

An HTTP adapter that prioritizes Fuyao REST, uses the Stock SDK bridge for uncovered capabilities, and falls back to ELTDX.

<p align="center">
  <img src="./assets/readme/data-flow.svg" width="100%" alt="Tick Stock Panel connects through market-data-tick-adapter on port 3021 to Fuyao REST, Stock SDK bridge and the ELTDX gateway." />
</p>

## 中文

### 快速部署

需要 Python 3.11+ 和 Node.js 18+。Fuyao 通过 REST API 访问；Stock SDK 使用仓库内的 Node bridge，不需要在 Python 中安装 JavaScript 包。

Fuyao Key 默认从 `config/data_sources.toml` 的 `fuyao.api_key_file` 读取：`.secrets/fuyao_api_key`。非空环境变量 `HITHINK_FINANCE_API_KEY` 会覆盖文件值。建议：

```bash
mkdir -p .secrets
printf '%s\n' '从 Fuyao 控制台获取的 key' > .secrets/fuyao_api_key
chmod 600 .secrets/fuyao_api_key
```

不要将真实 Key 写入项目配置、日志或 Git。当前工作区此前已用会话 Key 做过只读单证券 REST 验证，但没有保存 Key；由于 Key 已在聊天中暴露，验证完成后应在 Fuyao 控制台轮换。

安装项目与 Node bridge：

```bash
cd /opt/market-data-tick-adapter
python3.11 -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
npm install --prefix stock-sdk --ignore-scripts
.venv/bin/pytest -q
npm test --prefix stock-sdk
```

服务默认监听 `127.0.0.1:3021`，ELTDX Gateway 默认地址为 `http://127.0.0.1:8000`。systemd 示例为 `market-data-tick-adapter.service`，部署时按实际路径修改；服务会读取 `MARKET_DATA_CONFIG` 和可选的 `.secrets/fuyao.env`。

### 数据端点

| 数据集 | 端点 | 主数据源顺序 |
| --- | --- | --- |
| 全市场快照 | `GET /realtime` | Fuyao → Stock SDK → ELTDX |
| 分钟 K 线 | `POST /minute` | Stock SDK → ELTDX |
| 全量分钟 K 线 | `POST /full_minute` | Stock SDK → ELTDX |
| 日 K 线 | `POST /daily` | Fuyao → Stock SDK → ELTDX |
| 除权因子 | `POST /adj_factor` | ELTDX（Fuyao 事件流不能直接映射为 ex_factor） |
| 财务数据 | `POST /financial` | Fuyao → ELTDX |
| 五挡盘口 | `POST /depth5` | Stock SDK → ELTDX |
| 健康检查 | `GET /health` | 本地 |

Fuyao 已接入：

- 实时快照 `/api/a-share/prices/snapshot`，按接口分页获取全市场。
- 日期范围日线 `/api/a-share/prices/historical`，每只证券单独请求，跨度遵循 Fuyao 10 年限制。
- 利润表、资产负债表、现金流量表，分别映射 `lrb/zcfzb/xjllb` 和对应 Fuyao REST 路径。

Fuyao 复权接口返回除权事件（分红与送股比例），文档明确不返回 `adjust_factor`，因此当前 `/adj_factor` 保留 ELTDX，避免把事件数据误当作复权因子。

Stock SDK bridge 使用已发布的 `stock-sdk@2.4.6`，已确认接入 `quotes.cn`、`kline.cn`、`kline.cnMinute`。成交量单位为手、成交额单位为万元，适配器保留 provider 原始口径。

Fuyao 还提供交易日历、集合竞价、特色数据和高频动向接口；当前项目没有对应的既有面板端点，因此只记录为后续扩展，不新增未经面板契约确认的端点。

### 接入 Tick Stock Panel

把 [`tick-stock-panel.yaml`](./tick-stock-panel.yaml) 复制到面板的 `data/data_sources/market_data_source.yaml`，然后在「设置 → 数据源」重新加载。

面板容器通过 `host.docker.internal:3021` 访问适配器。确认 Compose 配置包含 `extra_hosts: ["host.docker.internal:host-gateway"]`，且适配器 `HOST` 绑定到容器可路由的宿主机地址。

### 数据源配置

`config/data_sources.toml` 集中配置 Fuyao、Stock SDK bridge、ELTDX Gateway、Key 文件、Key 环境变量、超时和数据源顺序。Key 读取优先级为：配置文件值，其次由非空 `HITHINK_FINANCE_API_KEY` 覆盖。`.secrets/` 已加入 `.gitignore`。

可通过环境变量覆盖：`FUYAO_BASE_URL`、`FUYAO_API_KEY_FILE`、`FUYAO_API_KEY_ENV`、`FUYAO_TIMEOUT`、`STOCK_SDK_ENABLED`、`STOCK_SDK_NODE`、`STOCK_SDK_BRIDGE`、`STOCK_SDK_TIMEOUT`、`ELTDX_GATEWAY_URL` 和 `ELTDX_GATEWAY_TIMEOUT`。

只有在需要比较实时请求速度时才设置 `DATA_SOURCE_BENCHMARK=true`；它会对每个可用来源执行一次小批量请求并在进程内固定较快来源。默认按 Fuyao 优先，避免额外探测请求。

Stock SDK 的成交量单位为手、成交额单位为万元；适配器保留该 provider 原始口径。Fuyao 快照不含中文名称，适配器会尝试使用 ELTDX 代码表补全名称。


## English

The adapter requires Python 3.11+ and Node.js 18+. Fuyao is called through REST and its key is read from `fuyao.api_key_file` first, then overridden by a non-empty `HITHINK_FINANCE_API_KEY`. Stock SDK `2.4.6` runs through the local Node bridge in `stock-sdk/`.

Fuyao handles realtime snapshots, date-bounded daily bars and the three documented financial statements. Its corporate-actions endpoint returns events rather than a direct adjustment factor, so `/adj_factor` remains on ELTDX. Stock SDK handles A-share quotes, K-lines, minute K-lines and five-level quotes. ELTDX remains the fallback.

Fuyao calendar, auction, special-data and high-frequency APIs are documented but have no existing panel endpoint in this project; they are not exposed speculatively.
