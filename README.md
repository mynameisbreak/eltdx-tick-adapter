# eltdx-tick-adapter

将本地 eltdx 网关行情转换为 Tick Stock Panel 自定义数据源接口的 FastAPI 适配器。

## 功能概览

适配器通过本机 eltdx 网关提供以下数据：

| 数据集 | HTTP 接口 | 方法 | 说明 |
| --- | --- | --- | --- |
| 日线 | `/daily` | POST | 不复权日线数据 |
| 复权因子 | `/adj_factor` | POST | 复权因子历史数据 |
| 实时行情 | `/realtime` | GET | 全市场实时快照 |
| 分钟线 | `/minute` | POST | 指定周期分钟线 |
| 全量分钟线 | `/full_minute` | POST | 与分钟线相同的完整历史接口 |
| 财务数据 | `/financial` | POST | 按报表类型查询财务数据 |
| 五挡盘口 | `/depth5` | POST | 直接返回买卖各 5 档盘口 |

`/depth5` 是适配器的内部接口。Tick Stock Panel v0.3.2 的自定义数据源配置模型尚未接受 `depth5` 数据集，因此面板端应将「五挡盘口」能力路由到内置的 `tdxquant` provider；其余数据集可以继续使用 `eltdx_source`。

## 架构

```text
Tick Stock Panel
        │
        │ HTTP（容器通过 host.docker.internal 访问）
        ▼
 eltdx-tick-adapter :3021
        │
        │ JSON-RPC
        ▼
     eltdx-gateway :8001
        │
        ▼
   通达信 7709 服务
```

默认安全边界如下：

- 适配器监听 `127.0.0.1:3021`；Docker 场景通过宿主机网关地址访问。
- eltdx 网关监听 `127.0.0.1:8001`。
- 不需要将任何服务暴露到公网。

## 环境要求

- Python `>=3.10`
- 可用的 eltdx 网关，默认地址为 `http://127.0.0.1:8000`
- 网关能够正常访问通达信 7709 行情服务

## 安装

```bash
git clone <repository>
cd eltdx-tick-adapter
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
```

如使用 `uv`，也可以执行：

```bash
uv sync --extra test
```

## 本地运行

```bash
export ELTDX_GATEWAY_URL=http://127.0.0.1:8000
export HOST=127.0.0.1
export PORT=3021
.venv/bin/eltdx-tick-adapter
```

健康检查：

```bash
curl -sS http://127.0.0.1:3021/health
```

## 接口示例

### 日线

```bash
curl -sS -X POST http://127.0.0.1:3021/daily \
  -H 'content-type: application/json' \
  -d '{"symbols":["000001.SZ"]}'
```

### 分钟线

```bash
curl -sS -X POST http://127.0.0.1:3021/minute \
  -H 'content-type: application/json' \
  -d '{"symbols":["000001.SZ"],"period":"1m"}'
```

支持的 `period` 为 `1m`、`5m`、`15m`、`30m` 和 `60m`。

### 五挡盘口

```bash
curl -sS -X POST http://127.0.0.1:3021/depth5 \
  -H 'content-type: application/json' \
  -d '{"symbols":["000001.SZ"]}'
```

响应结构：

```json
{
  "data": [
    {
      "symbol": "000001.SZ",
      "asks": [[11.28, 83.0], [11.29, 1029.0]],
      "bids": [[11.27, 1632.0], [11.26, 8919.0]]
    }
  ]
}
```

`asks` 和 `bids` 实际最多各包含 5 档，数组元素依次为 `[价格, 数量]`。

### 财务数据

```bash
curl -sS -X POST http://127.0.0.1:3021/financial \
  -H 'content-type: application/json' \
  -d '{"symbols":["000001.SZ"],"report_type":"zcfzb"}'
```

## Tick Stock Panel 配置

仓库中的 `tick-stock-panel.yaml` 提供 `daily`、`realtime`、`minute`、`full_minute`、`financial` 和 `adj_factor` 六类自定义数据源配置。

容器部署时，将 URL 中的 `127.0.0.1` 替换为：

```text
http://host.docker.internal:3021
```

五挡盘口不应在 Tick Stock Panel v0.3.2 的 `eltdx_source` 中声明。请在面板设置中将以下能力路由到 `tdxquant`：

```text
depth5_data_provider = tdxquant
```

## systemd 部署

仓库提供 `eltdx-tick-adapter.service` 示例单元文件：

```bash
sudo cp eltdx-tick-adapter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now eltdx-tick-adapter
sudo systemctl status eltdx-tick-adapter
```

查看日志：

```bash
sudo journalctl -u eltdx-tick-adapter -f
```

## 测试

```bash
.venv/bin/pytest -q
```

测试覆盖请求参数、符号转换、行情字段规范化、时间范围过滤、网关错误处理和五挡盘口响应。

## 故障排查

### 网关返回 `7709 runtime command channel is closed`

先检查网关状态和方法调用：

```bash
sudo systemctl is-active eltdx-gateway
curl -sS -X POST http://127.0.0.1:8001/rpc \
  -H 'content-type: application/json' \
  -d '{"id":1,"method":"quotes.get_depth","params":{"codes":["sz000001"]}}'
```

如果通道仍然断开，查看网关日志和上游行情账号、地址、会话状态：

```bash
sudo journalctl -u eltdx-gateway -n 50 --no-pager
```

### `/depth5` 返回 502

这通常表示适配器无法从网关取得盘口数据。先单独验证上述 `quotes.get_depth` RPC，再检查适配器日志：

```bash
sudo journalctl -u eltdx-tick-adapter -n 50 --no-pager
```

### 页面仍未显示五挡盘口

确认面板偏好中存在：

```json
{
  "depth5_data_provider": "tdxquant"
}
```

然后重启面板或通过已登录的设置页重新加载数据源。

## 相关文件

- `app/main.py`：FastAPI 路由与网关调用。
- `app/eltdx_client.py`：eltdx 网关 JSON-RPC 客户端。
- `app/normalizers.py`：字段和符号规范化。
- `tests/`：自动化测试。
- `tick-stock-panel.yaml`：Tick Stock Panel 自定义数据源配置。
- `eltdx-tick-adapter.service`：systemd 服务单元示例。
