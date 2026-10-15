# eltdx-tick-adapter

eltdx 通达信行情适配器：把 [eltdx](https://github.com/electkismet/eltdx) 的行情能力通过 HTTP 暴露给 [Tick Stock Panel](https://github.com/shy3130/tick-stock-panel) 的自定义数据源契约。

# eltdx-tick-adapter (English)

An adapter that exposes [eltdx](https://github.com/electkismet/eltdx) market-data capabilities over HTTP for the custom data-source contract of [Tick Stock Panel](https://github.com/shy3130/tick-stock-panel).

---

## 中文

### 数据集与端点

| 数据集 | 端点 | 方法 | 说明 |
| --- | --- | --- | --- |
| realtime | `/realtime` | GET | 全市场快照（含名称、涨跌幅） |
| minute | `/minute` | POST | 分钟 K（1m/5m/15m/30m/60m） |
| full_minute | `/full_minute` | POST | 全量分钟（与 minute 同形） |
| daily | `/daily` | POST | 日 K |
| adj_factor | `/adj_factor` | POST | 除权因子 |
| financial | `/financial` | POST | 财务数据（按表名透传） |
| depth5 | `/depth5` | POST | 五挡盘口（asks/bids 各 5 档） |
| health | `/health` | GET | 健康检查 |

所有业务端点返回 `{"data": [...]}`，直接对应面板自定义数据源的 `response_path: data`。

### 部署

依赖：Python ≥ 3.10、运行中的 eltdx HTTP 网关（默认 `http://127.0.0.1:8001`）。

```bash
cd /opt/eltdx-tick-adapter
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/pytest -q
```

systemd 服务文件（`eltdx-tick-adapter.service` / `eltdx-gateway.service`）已在仓库内提供：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now eltdx-gateway eltdx-tick-adapter
```

关键环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ELTDX_GATEWAY_URL` | `http://127.0.0.1:8000` | 上游网关地址 |
| `HOST` / `PORT` | `127.0.0.1` / `3021` | 监听地址与端口 |

安全建议：仅监听回环或 Docker 网桥地址（如 `172.17.0.1`），不要暴露公网。

### Docker 容器内访问

面板在容器内通过 `host.docker.internal:3021` 访问本适配器。确保适配器监听在容器可路由的宿主机地址（如 `172.17.0.1`），并在面板 compose 中保留 `extra_hosts: ["host.docker.internal:host-gateway"]`。

### 数据源 YAML 示例（面板侧）

把 `tick-stock-panel.yaml` 复制到面板的 `data/data_sources/eltdx_source.yaml`，并把其中 `127.0.0.1` 全部替换为 `host.docker.internal`，然后在面板「设置 → 数据源」点击重新加载。

---

## English

### Datasets & Endpoints

| Dataset | Endpoint | Method | Description |
| --- | --- | --- | --- |
| realtime | `/realtime` | GET | Full-market snapshot (name, change%) |
| minute | `/minute` | POST | Minute bars (1m/5m/15m/30m/60m) |
| full_minute | `/full_minute` | POST | Full-market minute bars (same shape) |
| daily | `/daily` | POST | Daily bars |
| adj_factor | `/adj_factor` | POST | Adjustment factors |
| financial | `/financial` | POST | Financial statements (table passthrough) |
| depth5 | `/depth5` | POST | Five-level order book (asks/bids) |
| health | `/health` | GET | Health check |

All business endpoints return `{"data": [...]}`, matching the panel custom source `response_path: data`.

### Deployment

Requires Python ≥ 3.10 and a running eltdx HTTP gateway (default `http://127.0.0.1:8001`).

```bash
cd /opt/eltdx-tick-adapter
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/pytest -q
```

systemd units (`eltdx-tick-adapter.service` / `eltdx-gateway.service`) are provided in the repo:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now eltdx-gateway eltdx-tick-adapter
```

Key environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `ELTDX_GATEWAY_URL` | `http://127.0.0.1:8000` | Upstream gateway URL |
| `HOST` / `PORT` | `127.0.0.1` / `3021` | Listen address and port |

Security: bind to loopback or a Docker bridge address (e.g. `172.17.0.1`) only; never expose to the public internet.

### Access from Docker containers

The panel reaches this adapter via `host.docker.internal:3021` inside its container. Make sure the adapter listens on a host address routable from containers (`172.17.0.1` on `docker0`), and keep `extra_hosts: ["host.docker.internal:host-gateway"]` in the panel's compose file.

### Data-source YAML (panel side)

Copy `tick-stock-panel.yaml` to the panel's `data/data_sources/eltdx_source.yaml`, replace every `127.0.0.1` with `host.docker.internal`, then click Reload in Settings → Data sources.

---

## AI 自主部署提示词 / AI Self-Deployment Prompt

把下面这段话连同本仓库一起交给 AI Agent，即可自主完成部署 / Hand this prompt, together with this repository, to an AI agent:

```text
请在当前服务器部署 eltdx-tick-adapter 并接入 Tick Stock Panel。

前提检查：
1. 确认 Python >= 3.10 与 eltdx HTTP 网关（默认 127.0.0.1:8001，/health 应返回 ok）。
2. 确认面板项目目录与 Docker 容器（TickFlow_Stock_Panel，端口 3018）。

部署步骤：
1. cd 到适配器目录，创建虚拟环境并执行 .venv/bin/python -m pip install -e ".[test]"。
2. 运行 .venv/bin/pytest -q，必须全部通过；失败则停止并报告。
3. 检查/创建 systemd 服务：
   - eltdx-gateway: ExecStart=<venv>/bin/eltdx-http --host 127.0.0.1 --port 8001
   - eltdx-tick-adapter: Environment=ELTDX_GATEWAY_URL=http://127.0.0.1:8001
     Environment=HOST=<容器可路由的宿主机地址，如 172.17.0.1> Environment=PORT=3021
   修改后 sudo systemctl daemon-reload && sudo systemctl restart <服务名>。
4. 验证：curl http://<HOST>:3021/health 返回 {"status":"ok"}；
   curl http://127.0.0.1:8001/methods 应包含 quotes.get_depth、helpers.full_quotes、bars.get。
5. 把 tick-stock-panel.yaml 复制到面板 data/data_sources/eltdx_source.yaml，
   将其中 127.0.0.1:3021 替换为 host.docker.internal:3021；
   若宿主机无写入权限，用 sudo 并先做带时间戳的 .bak 备份。
6. 在面板容器内验证连通：
   docker exec TickFlow_Stock_Panel python3 -c "import urllib.request;print(urllib.request.urlopen('http://host.docker.internal:3021/health',timeout=10).read().decode())"
   若 Connection refused，说明适配器监听地址与容器内 host.docker.internal 解析值不一致：
   用 docker exec <容器> cat /etc/hosts 查看解析值，把适配器 HOST 改成该地址并重启。
7. 若面板版本的配置解析白名单缺少 full_minute/depth5，报告需升级面板，不要改面板核心代码。
8. 逐数据集试拉：POST /minute 与 /full_minute（body: symbols/start_time/end_time/period），
   GET /realtime，确认 data 数组非空；/daily、/adj_factor、/depth5、/financial 用小窗口验证。

安全约束：适配器只监听回环或 Docker 网桥地址，禁止 0.0.0.0 与公网暴露；
不删除任何已有 YAML/备份；不执行 git reset --hard、git clean、rm -rf；
不把密码/Token 写入命令或文件；失败时报告命令、完整错误与所在层级，不得伪装成功。
```
