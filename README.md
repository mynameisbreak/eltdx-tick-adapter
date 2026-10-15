# eltdx-tick-adapter

把 [eltdx](https://github.com/electkismet/eltdx) 的行情能力转换为 [Tick Stock Panel](https://github.com/shy3130/tick-stock-panel) 可直接使用的 HTTP 数据源。

An HTTP adapter that makes [eltdx](https://github.com/electkismet/eltdx) market data available to [Tick Stock Panel](https://github.com/shy3130/tick-stock-panel).

<p align="center">
  <img src="./assets/readme/data-flow.svg" width="100%" alt="Tick Stock Panel connects through eltdx-tick-adapter on port 3021 to the ELTDX gateway on port 8000. The adapter normalizes market data into JSON responses." />
</p>

## 中文

### 快速部署

需要 Python 3.10+ 和运行中的 ELTDX HTTP 网关。默认网关地址为 `http://127.0.0.1:8000`，与仓库提供的 systemd 服务配置一致。

```bash
cd /opt/eltdx-tick-adapter
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/pytest -q
sudo systemctl daemon-reload
sudo systemctl enable --now eltdx-gateway eltdx-tick-adapter
```

适配器默认监听 `127.0.0.1:3021`。若面板运行在 Docker 容器中，将 `HOST` 设为容器可访问的宿主机网桥地址（例如 `172.17.0.1`），不要绑定公网地址。

### 数据端点

业务端点均返回 `{"data": [...]}`；`/health` 返回服务状态。

| 数据集 | 端点 | 请求参数 |
| --- | --- | --- |
| 全市场快照 | `GET /realtime` | 可选 `symbols`（适配器返回全市场） |
| 分钟 K 线 | `POST /minute` | `symbols`, `start_time`, `end_time`, `period` |
| 全量分钟 K 线 | `POST /full_minute` | 同 `/minute` |
| 日 K 线 | `POST /daily` | `symbols`, `start_time`, `end_time` |
| 除权因子 | `POST /adj_factor` | `symbols`, `start_time`, `end_time` |
| 财务数据 | `POST /financial` | `symbols`, `report_type` |
| 五挡盘口 | `POST /depth5` | `symbols` |
| 健康检查 | `GET /health` | 无 |

### 接入 Tick Stock Panel

把 [`tick-stock-panel.yaml`](./tick-stock-panel.yaml) 复制到面板的 `data/data_sources/eltdx_source.yaml`，然后在「设置 → 数据源」重新加载。示例 YAML 已配置 `realtime`、`minute` 和 `full_minute`；其他端点可按面板版本支持情况加入。

面板容器通过 `host.docker.internal:3021` 访问适配器。确认面板的 Compose 配置包含 `extra_hosts: ["host.docker.internal:host-gateway"]`，且适配器 `HOST` 绑定到容器可路由的宿主机地址。

## English

### Quick start

Requires Python 3.10+ and a running ELTDX HTTP gateway. The default gateway URL is `http://127.0.0.1:8000`, matching the included systemd unit.

```bash
cd /opt/eltdx-tick-adapter
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/pytest -q
sudo systemctl daemon-reload
sudo systemctl enable --now eltdx-gateway eltdx-tick-adapter
```

The adapter listens on `127.0.0.1:3021` by default. For Docker access, set `HOST` to a host bridge address reachable from the panel container (for example, `172.17.0.1`). Do not bind it to a public interface.

### Endpoints

Business endpoints return `{"data": [...]}`. `/health` returns service status.

| Dataset | Endpoint | Request fields |
| --- | --- | --- |
| Full-market snapshot | `GET /realtime` | Optional `symbols` (the adapter returns the full market) |
| Minute bars | `POST /minute` | `symbols`, `start_time`, `end_time`, `period` |
| Full minute bars | `POST /full_minute` | Same as `/minute` |
| Daily bars | `POST /daily` | `symbols`, `start_time`, `end_time` |
| Adjustment factors | `POST /adj_factor` | `symbols`, `start_time`, `end_time` |
| Financial data | `POST /financial` | `symbols`, `report_type` |
| Five-level order book | `POST /depth5` | `symbols` |
| Health check | `GET /health` | None |

### Connect the panel

Copy [`tick-stock-panel.yaml`](./tick-stock-panel.yaml) to the panel's `data/data_sources/eltdx_source.yaml`, then reload data sources in Settings. The sample config wires `realtime`, `minute`, and `full_minute`; add other endpoints only if supported by your panel version.

The panel container reaches the adapter at `host.docker.internal:3021`. Ensure its Compose config includes `extra_hosts: ["host.docker.internal:host-gateway"]` and that the adapter binds to a host address reachable from the container.

## AI 自主安装提示词 / AI Deployment Prompt

将下面提示词连同仓库交给 Agent。它会检查环境、部署服务、接入面板并验证结果。

```text
在当前 Linux 服务器上自主部署本仓库，并接入现有 Tick Stock Panel。先检查 Python 3.10+、ELTDX 网关、面板目录和容器；默认网关端口为 8000，适配器端口为 3021，以仓库配置和实际环境为准，不要猜路径或容器名。

创建或复用虚拟环境，安装项目并运行 pytest；测试失败就停止。检查 systemd 和面板 YAML，修改前先备份；部署适配器时确保面板容器能访问它。安装数据源 YAML，确认 host.docker.internal 可解析。

验证网关方法、适配器 /health、至少一个行情端点的数据，以及面板容器到适配器的连通性。全部通过后再报告完成，并列出改动与验证结果；失败时报告具体命令和错误。

安全边界：只监听回环或 Docker 网桥地址，不暴露公网；不泄露凭据，不覆盖或删除现有数据，不运行破坏性命令，也不修改面板核心代码。未经验证不得声称部署成功。
```
