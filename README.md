# CloakBrowser Orchestration Manager

这是一个面向公网 Master/Worker 部署的 CloakBrowser 编排管理服务。Master 负责服务器清单、批量初始化和全局任务分配；Worker 负责运行隔离浏览器 Profile，并通过 Worker UI/API、VNC 和 CDP 暴露执行能力。

本仓库作为独立项目维护：`gscr10/cloakbrowser-orchestration-manager`。项目使用 CloakBrowser 作为浏览器运行时，但目标不是简单复刻 Profile GUI，而是把 Docker 镜像作为稳定运行时，把公网 Worker、Profile、代理、任务调度和自动化接入通过外部配置、API 和 CLI 管理起来。

## 项目能力

- 浏览器 Profile 的创建、查询、更新、删除，用户数据持久化在 `/data/profiles/<profile-id>/`。
- Profile 启动、停止、状态查询 API，复用 CloakBrowser 生命周期、KasmVNC 显示和 CDP 代理。
- Web UI 支持手动管理 Profile，并通过 VNC 查看运行中的浏览器。
- HTTP API 覆盖 profiles、proxy endpoints、config import、scheduler tasks、runs、auth、VNC、clipboard 和 CDP。
- CLI 客户端 `python3 -m worker_backend.cli`，可在不打开 GUI 的情况下管理服务。
- Docker 运行时支持挂载 `/config/profiles.json` 和 `/config/proxies.csv` 进行外部配置导入。
- SQLite 本地存储位于 `/data`，保存 Profile、代理元数据、任务、运行记录和浏览器会话状态。
- 单机调度器按本地并发上限启动队列中的授权任务。
- 分布式 Master API（最小版）支持节点注册与心跳、全局任务分配、Provider 管理和批量初始化任务。

## 适用场景

本项目适用于授权范围内的浏览器自动化、内部测试环境、Profile 隔离、代理分配、多环境验证，以及需要通过公网 Worker 前端/VNC 观察浏览器行为的场景。

请不要将本项目用于凭据填充、垃圾信息、批量注册、未授权爬取、账号接管、验证码绕过、平台滥用或任何超出授权范围的活动。调度器包含基础的本地策略检查，用于拒绝明显不合规的任务描述，但最终使用责任仍由操作者承担。

## 上游参考项目

本项目已作为独立仓库维护，但实现上参考和依赖了以下项目：

- `CloakBrowser`: https://github.com/CloakHQ/CloakBrowser
- `CloakBrowser-Manager`: https://github.com/CloakHQ/CloakBrowser-Manager

当前仓库不会保留上游仓库的 Git 远端关系，也不会以 fork 形式维护。README 中的运行方式、API、CLI 和 Docker 配置均以本仓库当前实现为准。

## 架构概览

```text
Master Console / Master CLI / external client
  -> Master FastAPI on public port 8080
  -> Static server list + provision config
  -> SSH provision starts public Worker containers
  -> Workers register and heartbeat to Master
  -> Worker API/UI/VNC/CDP are exposed on each Worker port 8080
```

关键运行路径：

```text
/data
/data/profiles.db
/data/profiles/<profile-id>/
/config/profiles.json
/config/proxies.csv
```

## 目录约定（避免混淆）

- Worker 后端：`worker_backend/`
- Worker 前端：`worker-frontend/`
- Master 后端：`master_backend/`
- Master 前端：`master-frontend/`
- Worker 测试：`worker_backend/tests/`
- Master 测试：`master_backend/tests/`
- Master/Worker 联调示例：`examples/master-worker/`

约束：Worker 目录不承载 Master 控制面逻辑；Master 目录不承载 Worker 本地 Profile 管理逻辑。

## 公网 Master/Worker 快速部署

推荐从 GHCR 镜像启动公网 Master，再由 Master 通过 SSH provision 公网 Worker。每台服务器都只需要开放应用入口 `8080/tcp`；Worker 的 UI、API、VNC WebSocket 和 CDP 代理都走 Worker 的 `8080`。

镜像：

```text
ghcr.io/gscr10/cloakbrowser-orchestration-manager-master:latest
ghcr.io/gscr10/cloakbrowser-orchestration-manager-worker:latest
```

1. 在 Master 机器准备配置：

```bash
export MASTER_PUBLIC_IP=<master-public-ip>

cp config/servers.json.example config/servers.json
cp config/provision.json.example config/provision.json
# 如需标准清机并从 GitHub main 在 Worker 侧重新构建：
# cp config/provision.github-main.json.example config/provision.json

# config/servers.json 里填写 Worker 公网 IP、SSH 用户和端口。
# max_profiles 只作为 Master 调度容量提示；Worker 容器默认不注入 MAX_RUNNING_PROFILES，
# 会使用自身 auto/15 上限并在启动 Profile 时做资源压力检查。
export MASTER_PROVISION_MASTER_BASE_URL="http://${MASTER_PUBLIC_IP}:8080"
export MASTER_PROVISION_WORKER_API_BASE="http://{host}:8080"
```

2. 启动 Master：

```bash
docker pull ghcr.io/gscr10/cloakbrowser-orchestration-manager-master:latest

docker run -d --name cloak-manager-master --restart unless-stopped \
  -p 8080:8080 \
  -v cloak-master-data:/data \
  -v "$PWD/config:/config:ro" \
  -e MASTER_SERVER_LIST_PATH=/config/servers.json \
  -e MASTER_PROVISION_CONFIG_PATH=/config/provision.json \
  -e MASTER_PROVISION_MASTER_BASE_URL="${MASTER_PROVISION_MASTER_BASE_URL}" \
  -e MASTER_PROVISION_WORKER_API_BASE="${MASTER_PROVISION_WORKER_API_BASE}" \
  ghcr.io/gscr10/cloakbrowser-orchestration-manager-master:latest
```

如果使用 Feishu OpenAPI provider 或回写，建议把 `FEISHU_*` 放在仅本机保存的 env 文件或部署密钥中，并用 `--env-file <local-env-file>` 传入 Master 容器。可参考 `examples/master-worker/env.local.sample` 的变量名，不要提交真实 secret。

3. 选择静态 Provider，先 dry-run，再真实 provision Worker：

```bash
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" providers
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" set-provider static
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" provision-run --dry-run
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" provision-run --no-dry-run
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" provision-jobs
```

默认 provision 模板会先尝试直接执行 `docker`，失败时自动回退到 `sudo -n docker`，并用 sudo-aware 方式创建/chown `/opt/cloak-manager-worker/config`。远端用户需要能无交互执行 Docker 或具备无交互 sudo 权限；失败信息会区分 Docker 权限、sudo NOPASSWD、git 缺失和 `/opt` 目录权限。

4. 创建任务并人工检查前端：

```bash
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" create-task \
  --authorized-target "internal test app" \
  --task-type open_url

python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" cluster
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" tasks
```

访问：

```text
Master Console: http://<master-public-ip>:8080
Worker UI/API:  http://<worker-public-ip>:8080
```

更完整的两机部署步骤见 `examples/master-worker/mvp.md`。如果 GHCR package 设置为 private，需要先在服务器上执行 `docker login ghcr.io`。

双 Worker 验收可运行：

```bash
python3 examples/master-worker/public_e2e.py \
  --master-url "http://${MASTER_PUBLIC_IP}:8080" \
  --double-worker-acceptance \
  --acceptance-task-count 6 \
  --require-balanced
```

输出会汇总 6 条任务的 3+3 分配和终态；Feishu 回写验收可追加使用 `--require-feishu-writeback`。

## 运行时环境变量

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `CONFIG_DIR` | `/config` | 外部配置文件目录。 |
| `CONFIG_IMPORT_ON_START` | `false` | 为 true 时启动阶段导入 `/config/profiles.json` 和 `/config/proxies.csv`。 |
| `MAX_RUNNING_PROFILES` | `auto` | 单个服务允许同时运行的 Profile 上限。默认自适应，硬上限为 15；也可以显式设置 1-15 的数字。该限制作用于 UI/API/CLI 手动启动和调度器启动。 |
| `DISABLE_RESOURCE_PRESSURE_CHECK` | `false` | 为 `true` 时跳过启动前的内存和 CPU 压力检查，仅保留 `MAX_RUNNING_PROFILES` 数量限制。适合受限测试环境或手动排障，不建议常规生产默认开启。 |
| `SCHEDULER_INTERVAL_SECONDS` | `5` | 后台调度器轮询间隔。 |

Chromium 运行需要足够的共享内存，建议启动容器时至少使用 `--shm-size=512m`。如果单机并发较高或页面较重，可以按服务器资源提高到 `1g`、`2g` 或更大。

## 外部配置

外部配置是可选能力，用于让运行时启动过程可复现，同时把浏览器状态继续保存在 `/data`。

支持的配置文件：

```text
/config/profiles.json
/config/proxies.csv
```

`profiles.json` 可以是数组，也可以是包含 `profiles` 数组的对象。Profile 按 `name` 匹配；已存在的 Profile 会原地更新，因此其 `/data/profiles/<profile-id>/` 目录保持稳定。

```json
{
  "profiles": [
    {
      "name": "worker-1",
      "fingerprint_seed": 12345,
      "platform": "windows",
      "proxy": "http://user:pass@proxy.example.com:8080",
      "timezone": "America/New_York",
      "locale": "en-US",
      "screen_width": 1920,
      "screen_height": 1080,
      "headless": false,
      "tags": [{"tag": "automation"}]
    }
  ]
}
```

`proxies.csv` 使用以下表头：

```csv
protocol,host,port,username,password,region,tags
http,proxy.example.com,8080,user,secret,us,residential
```

可以在启动时通过 `CONFIG_IMPORT_ON_START=true` 导入配置，也可以在服务运行中手动触发：

```bash
python3 -m worker_backend.cli config import
```

导入逻辑对 Profile 按 `name` 幂等处理。代理导入会跳过协议、host、port、username 相同的重复记录。

## CLI 用法

CLI 是后端 HTTP API 的轻量客户端，和 Web UI 使用同一套服务接口。

```bash
python3 -m worker_backend.cli status
```

通过参数或环境变量指定目标服务：

```bash
export CLOAK_MANAGER_URL=http://localhost:8080

python3 -m worker_backend.cli profiles list
```

全局参数：

```text
--base-url http://localhost:8080
--timeout 30
--compact
```

Profile 管理命令：

```bash
python3 -m worker_backend.cli profiles list
python3 -m worker_backend.cli profiles create worker-1 --platform windows --screen-width 1920 --screen-height 1080
python3 -m worker_backend.cli profiles get <profile-id>
python3 -m worker_backend.cli profiles update <profile-id> --no-headless
python3 -m worker_backend.cli profiles launch <profile-id>
python3 -m worker_backend.cli profiles status <profile-id>
python3 -m worker_backend.cli profiles cdp <profile-id>
python3 -m worker_backend.cli profiles stop <profile-id>
```

代理管理命令：

```bash
python3 -m worker_backend.cli proxies list
python3 -m worker_backend.cli proxies template > proxies.csv
python3 -m worker_backend.cli proxies import proxies.csv
python3 -m worker_backend.cli proxies create --protocol socks5 --host proxy.example.com --port 1080 --username user --password secret --region us --tags residential,automation
```

任务和调度命令：

```bash
python3 -m worker_backend.cli tasks create --profile-id <profile-id> --authorized-target "internal test app" --task-type open_url --url https://example.com

# 如果省略 --url，服务端会默认打开 https://www.baidu.com
python3 -m worker_backend.cli tasks create --profile-id <profile-id> --authorized-target "internal test app" --task-type open_url
python3 -m worker_backend.cli tasks list
python3 -m worker_backend.cli tasks cancel <task-id>
python3 -m worker_backend.cli runs list
python3 -m worker_backend.cli scheduler status
python3 -m worker_backend.cli scheduler tick
```

高级字段可以通过 `--json` 传入内联 JSON 对象或 JSON 文件路径。`--json` 中的值会覆盖同名命令行参数。

## HTTP API 概览

核心接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/status` | 服务健康和状态摘要。 |
| `GET` | `/api/profiles` | 列出 Profile。 |
| `POST` | `/api/profiles` | 创建 Profile。 |
| `GET` | `/api/profiles/{profile_id}` | 查询 Profile。 |
| `PUT` | `/api/profiles/{profile_id}` | 更新 Profile。 |
| `DELETE` | `/api/profiles/{profile_id}` | 删除 Profile；若仍在运行会先自动停止。 |
| `POST` | `/api/profiles/{profile_id}/launch` | 启动 Profile。 |
| `POST` | `/api/profiles/{profile_id}/stop` | 停止 Profile。 |
| `GET` | `/api/profiles/{profile_id}/status` | 查询运行状态。 |
| `GET` | `/api/profiles/{profile_id}/cdp` | 查询 CDP 连接信息。 |
| `WS` | `/api/profiles/{profile_id}/vnc` | VNC WebSocket 代理。 |
| `POST` | `/api/profiles/{profile_id}/clipboard` | 向运行中的 Profile 写入剪贴板文本。 |
| `GET` | `/api/proxies` | 列出代理端点。 |
| `POST` | `/api/proxies` | 创建代理端点。 |
| `POST` | `/api/proxies/import` | 导入代理 CSV。 |
| `POST` | `/api/config/import` | 导入 `/config` 文件。 |
| `GET` | `/api/tasks` | 列出调度任务。 |
| `POST` | `/api/tasks` | 创建队列任务。 |
| `POST` | `/api/tasks/{task_id}/cancel` | 取消排队或运行中的任务；运行中会停止对应 Profile。 |
| `POST` | `/api/distributed/tasks/{master_task_id}/cancel` | Master 分布式模式下按全局任务 ID 取消 Worker 本地任务。 |
| `GET` | `/api/runs` | 列出 Profile 运行记录。 |
| `GET` | `/api/scheduler/status` | 查询调度器状态。 |
| `POST` | `/api/scheduler/tick` | 手动执行一次调度 tick。 |

Profile 启动示例：

```bash
curl -X POST http://localhost:8080/api/profiles \
  -H 'Content-Type: application/json' \
  -d '{"name":"worker-1","platform":"windows","headless":false}'

curl -X POST http://localhost:8080/api/profiles/<profile-id>/launch

curl http://localhost:8080/api/profiles/<profile-id>/cdp
```

任务队列示例：

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"profile_id":"<profile-id>","authorized_target":"internal test app","task_type":"open_url","url":"https://example.com"}'

curl http://localhost:8080/api/scheduler/status
```

## CDP 自动化

每个运行中的 Profile 都会通过 Manager 暴露 Chrome DevTools Protocol 端点。你可以用 Playwright 或 Puppeteer 连接同一个浏览器会话，同时也可以在 Web UI 中通过 VNC 观察该会话。

```python
from playwright.async_api import async_playwright

async with async_playwright() as pw:
    browser = await pw.chromium.connect_over_cdp(
        "http://localhost:8080/api/profiles/<profile-id>/cdp"
    )
    page = browser.contexts[0].pages[0]
    await page.goto("https://example.com")
```

```javascript
const { chromium } = require("playwright");

const browser = await chromium.connectOverCDP(
  "http://localhost:8080/api/profiles/<profile-id>/cdp"
);
const page = browser.contexts()[0].pages()[0];
await page.goto("https://example.com");
```

如果需要在 VNC 中看到浏览器窗口，请创建或更新 Profile 为 `headless=false`。`headless=true` 的 Profile 仍可运行并暴露 CDP，但 VNC 不会显示可见浏览器窗口。

### Worker 业务脚本结构

Worker 端将浏览器生命周期和业务自动化拆开维护：

- `worker_backend/browser_manager.py` 只负责 Profile、CloakBrowser、VNC、CDP 端口和资源限制。
- `worker_backend/automation/runner.py` 负责为一次业务执行创建 `AutomationContext`，默认通过 Playwright CDP 连接已启动的 Profile 并新建 page。
- `worker_backend/automation/context.py` 是业务脚本稳定依赖面，提供 `page`、`payload`、`params`、`target_url()`、`account()` 和 `artifact_path()`。
- `worker_backend/automation/registry.py` 负责脚本注册和能力上报。新增脚本时用 `register_template(script_key, version, handler)` 挂载。
- `worker_backend/automation/scripts/` 放具体业务脚本，例如 `nol_native_login.py`。

业务脚本不直接调用 `cloakbrowser.launch()`，也不管理 Profile 生命周期；它只使用 `AutomationContext.page` 上的 Playwright API 编写业务步骤。对 NOL 这类敏感登录流程，推荐参数是 `minimal_cloak=true`、`humanize=true`、`human_preset=careful`、`use_cdp_automation=true`，并让脚本每次新建 page。

## 调度器行为

调度器刻意保持轻量，并只面向单机运行：

- 调度器运行在 FastAPI 后端进程中。
- 每隔 `SCHEDULER_INTERVAL_SECONDS` 秒轮询排队任务。
- 默认最多同时启动 15 个 Profile，但每次启动前都会检查容器可见的内存余量和 CPU 压力；资源压力过高时会拒绝继续启动。该限制同样适用于 UI/API/CLI 的手动启动。
- 启动任务时复用 `BrowserManager.launch(profile)`，因此 VNC、CDP、display 分配和持久化用户数据都与手动启动保持一致。
- 可以从本地代理池选择代理并注入到运行时 Profile。
- `open_url` 任务会在启动后打开指定 URL；如果未提供 `url`，默认打开 `https://www.baidu.com`。
- `external_cdp` 任务用于启动 Profile，供外部自动化客户端通过 CDP 接入。

## 分布式 Master（最小实现）

> 说明：从当前版本开始，Master 支持独立服务入口 `master_backend.main:app`，可与 Worker 分离部署。

当前版本新增了轻量分布式控制面接口，目标是 `1 台服务器 = 1 个 Worker` 的场景。

- Worker 向 Master 注册并持续心跳上报资源。
- Master 维护全局任务队列，并将任务分配给目标 Worker。
- Worker 通过 `pull` 领取任务并上报执行结果。
- 支持 Provider 抽象：当前可用 `static`、`local_json` 与 `feishu_openapi`。其中 `feishu_openapi` 需要完整 `FEISHU_*` 配置后才能启用。

### 分层架构（非 AI 阶段）

当前分布式架构按三层建设，避免把 Worker 部署问题和浏览器业务失败混在一起：

- **基础设施控制面**：Worker 服务器清单、desired state、SSH/Docker provision、注册、心跳、资源、Profile 观测、Worker capabilities 和可调度 Worker 查询。
- **业务自动化控制面**：业务输入同步、`source_record_id + run_generation` 幂等、输入快照、业务任务状态机、调度请求、业务结果和事件。
- **Worker 执行运行时**：Profile 管理、浏览器运行、脚本模板 registry、自动化执行、日志/截图/URL/title 等结果回传。

```mermaid
flowchart TD
    feishuInfra["飞书基础设施表：服务器清单"] --> infraSync["基础设施同步器"]
    infraSync --> infraDb["基础设施状态库"]
    infraDb --> provisionSvc["部署管理：SSH 和 Docker"]
    infraDb --> monitorSvc["资源监控：心跳、资源、Profile"]

    feishuBiz["飞书业务表：账号和自动化输入"] --> bizSync["业务同步器"]
    bizSync --> bizDb["业务任务状态库"]
    bizDb --> bizScheduler["业务调度器"]

    monitorSvc --> scheduleContract["调度契约层"]
    bizScheduler --> scheduleContract
    scheduleContract --> workerSelect["选择可用 Worker"]

    provisionSvc --> workerInfra["Worker 基础代理"]
    workerSelect --> workerRuntime["Worker 自动化运行时"]
    workerRuntime --> profileRuntime["Profile 浏览器运行"]
    profileRuntime --> scriptTemplate["自动化脚本模板"]
    scriptTemplate --> bizResult["业务执行结果"]
    bizResult --> bizDb
```

第一版可以用 `config/infra_workers.json.example` 和 `config/biz_tasks.json.example` 模拟飞书表。字段保持 `source_record_id`、`run_generation`、`script_key`、`script_version`、`worker_tags` 等 Feishu OpenAPI 可替换结构；后续接入 Feishu 时只替换同步 adapter，不改变 infra/biz 内部状态机。

若需在 Worker 节点启用自动拉取执行循环，设置：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `DISTRIBUTED_WORKER_ENABLED` | `false` | 设为 `true` 时启动 Worker 拉任务循环。 |
| `MASTER_BASE_URL` | `http://127.0.0.1:8080` | Master API 地址。 |
| `WORKER_API_BASE` | `http://127.0.0.1:<WORKER_API_PORT>` | Worker 注册给 Master 的可访问 API 地址。公网或多机部署必须设为 `http://<worker-ip>:8080`。 |
| `WORKER_NODE_ID` | 主机名 | Worker 节点唯一标识。 |
| `WORKER_HOSTNAME` | 主机名 | Worker 对外展示主机名。 |
| `WORKER_POLL_INTERVAL_SECONDS` | `5` | 空队列轮询间隔。 |
| `WORKER_HEARTBEAT_INTERVAL_SECONDS` | `5` | 心跳上报间隔。 |

核心接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/master/nodes` | 列出已注册 Worker 节点。 |
| `POST` | `/api/master/nodes/register` | 注册 Worker 节点。 |
| `POST` | `/api/master/nodes/heartbeat` | 上报节点资源与运行状态。 |
| `GET` | `/api/master/cluster/status` | 查看节点与全局任务汇总。 |
| `POST` | `/api/master/tasks` | 创建全局任务并自动分配目标节点。 |
| `GET` | `/api/master/tasks` | 列出全局任务。 |
| `GET` | `/api/master/tasks/{task_id}` | 查询单个全局任务。 |
| `GET` | `/api/master/tasks/{task_id}/events` | 查询任务事件时间线。 |
| `POST` | `/api/master/tasks/pull` | Worker 拉取分配给自己的任务。 |
| `POST` | `/api/master/tasks/{task_id}/report` | Worker 回报 started/success/failed/cancelled。 |
| `GET` | `/api/master/providers` | 查看 Provider 列表与当前激活项。 |
| `PUT` | `/api/master/providers/active` | 切换当前 Provider。 |
| `POST` | `/api/master/providers/feishu-openapi/validate` | 检查 Feishu OpenAPI 必需环境变量与字段契约。 |
| `POST` | `/api/master/providers/feishu-openapi/smoke` | 使用真实 Feishu 配置读取 infra/biz 表，验证 OpenAPI 连通性。 |
| `GET` | `/api/master/sources` | 查看 infra/biz sources、writeback sinks 与当前 active sink。 |
| `PUT` | `/api/master/writeback/active` | 切换业务结果回写目标，例如 `noop` 或 `feishu_openapi`。 |
| `POST` | `/api/master/provision/run` | 按当前 Provider 执行批量或单 Worker 初始化，支持 `node_id`。 |
| `GET` | `/api/master/provision/jobs` | 列出初始化任务。 |
| `GET` | `/api/master/provision/jobs/{job_id}` | 查看初始化任务详情。 |
| `POST` | `/api/master/infra/sync` | 从基础设施数据源同步 Worker 服务器清单。 |
| `GET` | `/api/master/infra/workers` | 查看基础设施 Worker desired/actual 状态。 |
| `GET` | `/api/master/infra/capabilities` | 查看 Worker 上报的脚本能力。 |
| `GET` | `/api/master/infra/profiles` | 查看 Master 汇总的 Worker Profile 运行观测。 |
| `POST` | `/api/master/biz/sync` | 从业务数据源同步业务任务，可选择同步后调度。 |
| `GET` | `/api/master/biz/jobs` | 查看内部业务任务状态。 |
| `GET` | `/api/master/biz/input-schemas` | 查看当前 Master 认可的业务脚本输入 schema。 |
| `GET` | `/api/master/biz/runs` | 查看业务任务运行记录。 |
| `GET` | `/api/master/biz/events` | 查看业务事件。 |

### 静态服务器列表（Provider=static）

默认读取 `MASTER_SERVER_LIST_PATH`（默认 `/config/servers.json`）。

```json
{
  "servers": [
    {
      "node_id": "worker-a",
      "host": "10.0.0.10",
      "username": "root",
      "password": "replace-with-real-password",
      "port": 22,
      "max_profiles": 10,
      "tags": ["cn"],
      "enabled": true
    }
  ]
}
```

### Feishu OpenAPI Provider 与回写

当以下环境变量都配置后，可以将 `feishu_openapi` 同时用于 infra sync、biz sync、provision Provider 和业务结果回写：

| 变量 | 作用 |
| --- | --- |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 获取飞书 tenant access token。 |
| `FEISHU_INFRA_APP_TOKEN` / `FEISHU_INFRA_TABLE_ID` | 读取基础设施 Worker 表。 |
| `FEISHU_BIZ_APP_TOKEN` / `FEISHU_BIZ_TABLE_ID` | 读取业务任务表并回写业务结果。 |

建议先调用 `/api/master/providers/feishu-openapi/validate` 查看缺失配置，再调用 `/api/master/providers/feishu-openapi/smoke` 做真实读取验证。验证通过后，可切换 Provider 为 `feishu_openapi`，也可将 writeback sink 切换为 `feishu_openapi`。

Master 容器常用启动方式是保留 `config/` 只读挂载，再额外用 `--env-file` 注入本地 secret env 文件。`validate-feishu` 会返回缺失的变量名；`smoke-feishu` 会真实读取 infra/biz 表做连通性检查，但不会输出 secret 值。

### 批量初始化（non dry-run）

`/api/master/provision/run` 在 `dry_run=false` 时会通过 SSH 真实执行远程命令。为减少默认误操作，命令模板可通过环境变量配置：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `MASTER_PROVISION_TIMEOUT_SECONDS` | `120` | 单台服务器 SSH 执行超时时间（秒）。 |
| `MASTER_PROVISION_MAX_PARALLEL` | `4` | 批量初始化最大并发数。 |
| `MASTER_PROVISION_VERIFY_WAIT_SECONDS` | `30` | non dry-run 后等待 Worker 注册心跳的超时时间（秒）。 |
| `MASTER_PROVISION_VERIFY_INTERVAL_SECONDS` | `2` | 注册心跳校验轮询间隔（秒）。 |
| `MASTER_NODE_HEARTBEAT_TTL_SECONDS` | `30` | 节点心跳超时阈值，超时节点不会参与任务分配。 |
| `MASTER_PROVISION_WORKER_IMAGE` | `ghcr.io/gscr10/cloakbrowser-orchestration-manager-worker:latest` | Worker 部署镜像。 |
| `MASTER_PROVISION_REPO_URL` | `https://github.com/gscr10/cloakbrowser-orchestration-manager.git` | `github_main_clean_rebuild` 模式下用于 clone 的仓库地址。 |
| `MASTER_PROVISION_REPO_REF` | `main` | `github_main_clean_rebuild` 模式下 checkout 的分支或 tag。 |
| `MASTER_PROVISION_WORKER_SOURCE_DIR` | `/opt/cloakbrowser-orchestration-manager` | `github_main_clean_rebuild` 模式下的远端源码目录。 |
| `MASTER_PROVISION_WORKER_CONFIG_DIR` | `/opt/cloak-manager-worker/config` | Worker 远端只读配置目录。 |
| `MASTER_PROVISION_MASTER_BASE_URL` | `http://host.docker.internal:8080` | Worker 回连 Master 的地址模板值。默认值仅用于本地 Docker 特例；公网多机部署必须设为 `http://<master-ip>:8080`。 |
| `MASTER_PROVISION_WORKER_API_BASE` | `http://{host}:8080` | Worker 注册给 Master 的 API 地址模板值，支持 `{host}` 等占位符。 |
| `MASTER_PROVISION_BOOTSTRAP_CMD` | sudo-aware Docker pull 模板 | 初始化前置命令。 |
| `MASTER_PROVISION_START_CMD` | sudo-aware Docker run 模板 | 启动 Worker 命令。 |

模板支持占位符：`{node_id}`、`{host}`、`{username}`、`{max_profiles}`、`{master_base_url}`、`{worker_api_base}`、`{tags_csv}`、`{worker_image}`、`{repo_url}`、`{repo_ref}`、`{source_dir}`、`{config_dir}`。

默认模板会先尝试当前 SSH 用户直接访问 Docker daemon；如果失败，会自动改用 `sudo -n docker`。远端用户需要具备无交互 sudo 权限，否则 non dry-run 会失败并返回明确错误。模板还会用 sudo-aware 方式创建/chown `/opt/cloak-manager-worker/config`，便于 `ec2-user` 这类非 root 用户部署。
默认模板不会向 Worker 容器注入 `MAX_RUNNING_PROFILES`，因此 Worker 使用自身 `auto` 上限（最多 15）并在每次启动 Profile 前做资源压力检查。`servers.json` 中的 `max_profiles` 仅作为 Master 调度容量提示；如果需要硬性限制某台 Worker，可在自定义 `MASTER_PROVISION_START_CMD` 中显式增加 `-e MAX_RUNNING_PROFILES=<n>`。

`host.docker.internal` 只适合 Master/Worker 在本地 Docker 环境互访的调试场景；公网部署应始终显式设置 `MASTER_PROVISION_MASTER_BASE_URL`。

也支持配置文件模式（推荐）：设置 `MASTER_PROVISION_CONFIG_PATH`（默认 `/config/provision.json`），格式可参考 `config/provision.json.example`。当配置文件存在时优先使用配置文件中的 `timeout_seconds`、`max_parallel`、`bootstrap_cmd`、`start_cmd`。`mode=image` 使用 GHCR 镜像；`mode=github_main_clean_rebuild` 会清理旧 Worker 容器、本地 Worker 镜像、`cloak-manager-data` volume 和远端源码目录，再从 GitHub `main` clone、build、run，示例见 `config/provision.github-main.json.example`。

前端可通过 `GET /api/master/provision/servers` 获取当前 Provider 的服务器清单，并结合 `POST /api/master/provision/run` 实现一键部署。

在 non dry-run 下，Master 会在远程命令执行成功后等待节点注册心跳，并校验 Worker API base、tags 和 capabilities；若在超时内未收到新心跳或能力信息，该节点会被标记为初始化失败。

全局任务在 Worker 回报 `failed` 时会按 `max_retries` 自动重排入队，并增加 `retry_count`。当超过重试上限后，任务才会保持最终失败状态。

当前实现支持 SSH key 和 `username/password` 两种登录方式。出于安全性与可审计性考虑，生产环境建议优先使用 SSH key，仅在受控内网环境临时使用密码登录。

### CLI 示例（Master）

Master CLI 已独立为 `master_backend.cli`（不再通过 `worker_backend.cli master` 调用）：

```bash
python3 -m master_backend.cli cluster
python3 -m master_backend.cli nodes
python3 -m master_backend.cli providers
python3 -m master_backend.cli set-provider static
python3 -m master_backend.cli sources
python3 -m master_backend.cli validate-feishu
python3 -m master_backend.cli set-writeback-sink noop
python3 -m master_backend.cli create-task --authorized-target "internal test app" --task-type open_url
python3 -m master_backend.cli task <task-id>
python3 -m master_backend.cli task-events <task-id>
python3 -m master_backend.cli cancel-task <task-id>
python3 -m master_backend.cli requeue-task <task-id>
python3 -m master_backend.cli provision-run --dry-run
python3 -m master_backend.cli provision-jobs
python3 -m master_backend.cli provision-job <job-id>
```

完整联调步骤可参考：`examples/master-worker/mvp.md`。

### 独立部署（推荐）

生产建议采用 `1 台 Master + N 台 Worker`：

- Master 机器仅启动 Master 控制面服务（不启动 Worker loop）
- Worker 机器仅启动 Worker 服务，并通过 `MASTER_BASE_URL` 回连 Master

Master 后端启动示例（同端口同时提供 API + Master 前端页面）：

```bash
python3 -m uvicorn master_backend.main:app --host 0.0.0.0 --port 8080
```

说明：

- 访问 `http://127.0.0.1:8080` 会返回 Master 前端页面。
- 访问 `http://127.0.0.1:8080/api/...` 使用 Master API。
- 该模式依赖 `master-frontend/dist`，若前端有更新需先执行一次构建：

```bash
cd master-frontend
npm install
npm run build
```

如果你在开发模式下需要热更新，再单独启动 Master 前端：

```bash
cd master-frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5174
```

Worker 服务启动示例（保留现有后端）：

```bash
export DISTRIBUTED_WORKER_ENABLED=true
export MASTER_BASE_URL=http://<master-host>:8080
export WORKER_API_BASE=http://<worker-host>:8080
python3 -m uvicorn worker_backend.main:app --host 0.0.0.0 --port 8080
```

公网两机调试时，Master 和 Worker 前端/API 都通过 `8080/tcp` 暴露：

```text
Master: http://<master-public-ip>:8080
Worker: http://<worker-public-ip>:8080
```

VNC 也通过 Worker 的 `8080` WebSocket 代理访问，不需要在安全组额外开放 KasmVNC 内部的 `6100+` 端口。通过 Master provision 部署公网 Worker 时，至少设置：

```bash
export MASTER_PROVISION_MASTER_BASE_URL=http://<master-public-ip>:8080
export MASTER_PROVISION_WORKER_API_BASE=http://{host}:8080
```

本地一键联调脚本 `examples/master-worker/run_local.sh` 仅用于开发调试，不是公网部署主流程。

## 访问控制

当前阶段 Master API、Worker API 和两个 Web UI 默认开放，公网联调先不内置 token 鉴权。Worker 管理通过服务器 IP、用户名和密码或 SSH key 完成，相关凭据只用于 Master provision 的 SSH 登录流程。

如果服务暴露到 localhost 之外，应在前面放置 HTTPS 终止层，并根据部署环境做好网络访问控制。Manager 本身提供 HTTP 服务。

## 附录：本地开发

后端开发环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r worker_backend/requirements.txt
python3 -m uvicorn worker_backend.main:app --host 0.0.0.0 --port 8080
```

### 本地开发矩阵（Master + Worker）

该矩阵仅用于本机源码调试。公网部署请使用上面的 Master 镜像和 provision 流程。

可先参考集中式样例文件：`examples/master-worker/env.local.sample`。

1. Master 后端（控制面）

```bash
python3 -m uvicorn master_backend.main:app --host 0.0.0.0 --port 8080
```

2. Worker 后端（执行面）

```bash
export DISTRIBUTED_WORKER_ENABLED=true
export MASTER_BASE_URL=http://127.0.0.1:8080
export WORKER_NODE_ID=worker-local
export WORKER_HOSTNAME=worker-local
python3 -m uvicorn worker_backend.main:app --host 0.0.0.0 --port 8081
```

3. Worker 前端（对应 Worker 后端）

```bash
cd worker-frontend
npm install
# Optional: set API proxy target for Worker backend
cp .env.example .env
npm run dev -- --host 0.0.0.0 --port 5173
```

4. Master 前端（对应 Master 后端）

```bash
cd master-frontend
npm install
# Optional: set API proxy target for Master backend
cp .env.example .env
npm run dev -- --host 0.0.0.0 --port 5174
```

访问建议：

- Worker UI: `http://127.0.0.1:5173`
- Master UI: `http://127.0.0.1:5174`
- Master API: `http://127.0.0.1:8080`
- Worker API: `http://127.0.0.1:8081`

若需快速联调 Master+Worker 并同时启动 Master 前端，也可直接运行：

```bash
./examples/master-worker/run_local.sh

# 或指定环境变量文件
./examples/master-worker/run_local.sh --env-file ./examples/master-worker/env.local.sample
```

Master 前端 API 代理环境变量：

- `master-frontend/.env.example` 使用 `VITE_API_PROXY_TARGET=http://127.0.0.1:8080`
- 两个前端的 Vite `allowedHosts` 可用 `VITE_ALLOWED_HOSTS=.example.com,localhost` 覆盖；默认保留 `.monkeycode-ai.online`。

如果不设置该变量，两个前端都默认代理到 `http://localhost:8080`。

后端与端口相关变量也可参考：`examples/master-worker/env.local.sample`。

### 本地单机 Docker Compose

`docker-compose.yml` 保留为本地单机 Worker Manager 开发辅助，会构建本地镜像、绑定 `127.0.0.1:8080`，并把数据保存到 `~/.cloakbrowser-manager`。它不启动公网 Master/Worker 编排流程。

```bash
docker compose up --build
```

前端开发环境：

```bash
cd worker-frontend
npm install
npm run dev
```

后端测试：

```bash
python3 -m pytest worker_backend/tests master_backend/tests
```

前端生产构建：

```bash
cd worker-frontend
npm run build
```

## 运维注意事项

- 将可变运行时状态保存在 `/data`，不要写入镜像。
- 将期望的启动配置放在 `/config`，生产运行时尽量只读挂载。
- 不要把 cookies、cache、localStorage 或浏览器 Profile 状态写进 `profiles.json`；这些状态保存在 `/data/profiles/<profile-id>/`。
- 需要通过 VNC 可视化的 Profile 应保持 `headless=false`。
- CLI 需要机器可读的单行 JSON 输出时可使用 `--compact`。
- Dockerfile 默认设置 `TARGETARCH=amd64`，因此即使使用经典 `docker build`，没有 BuildKit 注入平台参数时也能构建 KasmVNC 下载路径。
- 每台 Linux 服务器可以用同一镜像独立运行一个控制单元，通过不同 `/config` 控制该节点的 Profile 和代理。并发默认自适应，最多 15 个；需要固定上限时再设置 `MAX_RUNNING_PROFILES=1..15`。

## 运行要求

- 推荐使用 Docker 20.10 或更新版本运行服务。
- 镜像层和浏览器二进制文件大约需要 2 GB 磁盘空间。
- 需要为后端和每个运行中的 Chromium Profile 预留足够内存。
- 本地后端开发和测试建议使用 Python 3.11+。
- 前端开发和生产构建建议使用 Node.js 20+。

## 许可证和运行时依赖

- 应用源码：MIT，见 [LICENSE](LICENSE)。
- CloakBrowser 二进制和运行时：单独授权，见 [BINARY-LICENSE.md](BINARY-LICENSE.md)。

本应用需要 CloakBrowser Chromium 运行时才能启动 Profile。运行时可能按需下载浏览器二进制文件，该部分受其自身许可证约束。

## 仓库信息

- 当前项目仓库：https://github.com/gscr10/cloakbrowser-orchestration-manager
- 上游参考项目 `CloakBrowser`：https://github.com/CloakHQ/CloakBrowser
- 上游参考项目 `CloakBrowser-Manager`：https://github.com/CloakHQ/CloakBrowser-Manager
