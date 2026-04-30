# CloakBrowser Orchestration Manager

这是一个面向单机部署的 CloakBrowser 编排管理服务，用于运行隔离的浏览器 Profile，并提供 Web UI、HTTP API、CLI、持久化浏览器状态、代理池配置和轻量级本地任务调度能力。

本仓库作为独立项目维护：`gscr10/cloakbrowser-orchestration-manager`。项目使用 CloakBrowser 作为浏览器运行时，但目标不是简单复刻 Profile GUI，而是把 Docker 镜像作为稳定运行时，把 Profile、代理、任务调度和自动化接入通过外部配置、API 和 CLI 管理起来。

## 项目能力

- 浏览器 Profile 的创建、查询、更新、删除，用户数据持久化在 `/data/profiles/<profile-id>/`。
- Profile 启动、停止、状态查询 API，复用 CloakBrowser 生命周期、KasmVNC 显示和 CDP 代理。
- Web UI 支持手动管理 Profile，并通过 VNC 查看运行中的浏览器。
- HTTP API 覆盖 profiles、proxy endpoints、config import、scheduler tasks、runs、auth、VNC、clipboard 和 CDP。
- CLI 客户端 `python -m backend.cli`，可在不打开 GUI 的情况下管理服务。
- Docker 运行时支持挂载 `/config/profiles.json` 和 `/config/proxies.csv` 进行外部配置导入。
- SQLite 本地存储位于 `/data`，保存 Profile、代理元数据、任务、运行记录和浏览器会话状态。
- 单机调度器按本地并发上限启动队列中的授权任务。
- 可选 token 认证，用于保护 Web UI 和 API。

## 适用场景

本项目适用于授权范围内的浏览器自动化、内部测试环境、Profile 隔离、代理分配、多环境验证，以及需要通过 VNC 本地观察浏览器行为的调试场景。

请不要将本项目用于凭据填充、垃圾信息、批量注册、未授权爬取、账号接管、验证码绕过、平台滥用或任何超出授权范围的活动。调度器包含基础的本地策略检查，用于拒绝明显不合规的任务描述，但最终使用责任仍由操作者承担。

## 上游参考项目

本项目已作为独立仓库维护，但实现上参考和依赖了以下项目：

- `CloakBrowser`: https://github.com/CloakHQ/CloakBrowser
- `CloakBrowser-Manager`: https://github.com/CloakHQ/CloakBrowser-Manager

当前仓库不会保留上游仓库的 Git 远端关系，也不会以 fork 形式维护。README 中的运行方式、API、CLI 和 Docker 配置均以本仓库当前实现为准。

## 架构概览

```text
React UI / CLI / external client
  -> FastAPI backend on port 8080
  -> SQLite database under /data
  -> BrowserManager launches CloakBrowser profiles
  -> KasmVNC exposes live browser viewing
  -> CDP proxy exposes Playwright/Puppeteer automation access
  -> Scheduler consumes queued tasks and applies proxy/runtime settings
```

关键运行路径：

```text
/data
/data/manager.db
/data/profiles/<profile-id>/
/config/profiles.json
/config/proxies.csv
```

## Docker 快速启动

构建本地镜像：

```bash
docker build -t cloakbrowser-orchestration-manager:local .
```

启动服务，并挂载持久化数据和可选外部配置：

```bash
docker run --shm-size=512m \
  -p 8080:8080 \
  -v cloak-manager-data:/data \
  -v ./config:/config:ro \
  -e CONFIG_IMPORT_ON_START=true \
  -e CONFIG_DIR=/config \
  -e MAX_RUNNING_PROFILES=auto \
  -e SCHEDULER_INTERVAL_SECONDS=5 \
  cloakbrowser-orchestration-manager:local
```

打开 `http://localhost:8080` 访问 Web UI。

如果需要保护 API 和 Web UI，设置 `AUTH_TOKEN`：

```bash
docker run --shm-size=512m \
  -p 8080:8080 \
  -v cloak-manager-data:/data \
  -v ./config:/config:ro \
  -e AUTH_TOKEN=your-secret-token \
  -e CONFIG_IMPORT_ON_START=true \
  -e CONFIG_DIR=/config \
  cloakbrowser-orchestration-manager:local
```

## Docker Compose

仓库内的 `docker-compose.yml` 会构建本地镜像，将服务绑定到 `127.0.0.1:8080`，将数据保存到 `~/.cloakbrowser-manager`，并把 `./config` 挂载到容器内 `/config`。

```bash
docker compose up --build
```

如果环境里只有旧版 `docker-compose`，并且遇到 Python 包兼容问题，可以改用上面的 `docker build` 和 `docker run` 命令。

## GitHub Container Registry 镜像

仓库包含 GitHub Actions 工作流。每次推送到 `main`，或推送 `v*` tag 时，GitHub 会自动构建 Docker 镜像并推送到 GHCR：

```text
ghcr.io/gscr10/cloakbrowser-orchestration-manager:latest
```

其他 Linux 服务器可以直接拉取镜像运行，不需要在每台服务器上重新 `docker build`：

```bash
docker pull ghcr.io/gscr10/cloakbrowser-orchestration-manager:latest

docker run --shm-size=512m \
  -p 8080:8080 \
  -v cloak-manager-data:/data \
  -v ./config:/config:ro \
  -e CONFIG_IMPORT_ON_START=true \
  -e CONFIG_DIR=/config \
  -e MAX_RUNNING_PROFILES=auto \
  ghcr.io/gscr10/cloakbrowser-orchestration-manager:latest
```

如果 GHCR package 设置为 private，需要先在服务器上执行 `docker login ghcr.io`。如果设置为 public，服务器可以直接拉取。

## 运行时环境变量

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `AUTH_TOKEN` | 未设置 | 可选 Bearer token 和 Web UI 登录 token。未设置时 API 和 UI 默认开放。 |
| `CONFIG_DIR` | `/config` | 外部配置文件目录。 |
| `CONFIG_IMPORT_ON_START` | `false` | 为 true 时启动阶段导入 `/config/profiles.json` 和 `/config/proxies.csv`。 |
| `MAX_RUNNING_PROFILES` | `auto` | 单个服务允许同时运行的 Profile 上限。默认自适应，硬上限为 15；也可以显式设置 1-15 的数字。该限制作用于 UI/API/CLI 手动启动和调度器启动。 |
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
python -m backend.cli config import
```

导入逻辑对 Profile 按 `name` 幂等处理。代理导入会跳过协议、host、port、username 相同的重复记录。

## CLI 用法

CLI 是后端 HTTP API 的轻量客户端，和 Web UI 使用同一套服务接口。

```bash
python -m backend.cli status
```

通过参数或环境变量指定目标服务：

```bash
export CLOAK_MANAGER_URL=http://localhost:8080
export CLOAK_MANAGER_TOKEN=your-secret-token

python -m backend.cli profiles list
```

全局参数：

```text
--base-url http://localhost:8080
--token <token>
--timeout 30
--compact
```

Profile 管理命令：

```bash
python -m backend.cli profiles list
python -m backend.cli profiles create worker-1 --platform windows --screen-width 1920 --screen-height 1080
python -m backend.cli profiles get <profile-id>
python -m backend.cli profiles update <profile-id> --no-headless
python -m backend.cli profiles launch <profile-id>
python -m backend.cli profiles status <profile-id>
python -m backend.cli profiles cdp <profile-id>
python -m backend.cli profiles stop <profile-id>
```

代理管理命令：

```bash
python -m backend.cli proxies list
python -m backend.cli proxies template > proxies.csv
python -m backend.cli proxies import proxies.csv
python -m backend.cli proxies create --protocol socks5 --host proxy.example.com --port 1080 --username user --password secret --region us --tags residential,automation
```

任务和调度命令：

```bash
python -m backend.cli tasks create --profile-id <profile-id> --authorized-target "internal test app" --task-type open_url --url https://example.com
python -m backend.cli tasks list
python -m backend.cli tasks cancel <task-id>
python -m backend.cli runs list
python -m backend.cli scheduler status
python -m backend.cli scheduler tick
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
| `DELETE` | `/api/profiles/{profile_id}` | 删除已停止的 Profile。 |
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
| `POST` | `/api/tasks/{task_id}/cancel` | 取消排队中的任务。 |
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

## 调度器行为

调度器刻意保持轻量，并只面向单机运行：

- 调度器运行在 FastAPI 后端进程中。
- 每隔 `SCHEDULER_INTERVAL_SECONDS` 秒轮询排队任务。
- 默认最多同时启动 15 个 Profile，但每次启动前都会检查容器可见的内存余量和 CPU 压力；资源压力过高时会拒绝继续启动。该限制同样适用于 UI/API/CLI 的手动启动。
- 启动任务时复用 `BrowserManager.launch(profile)`，因此 VNC、CDP、display 分配和持久化用户数据都与手动启动保持一致。
- 可以从本地代理池选择代理并注入到运行时 Profile。
- `open_url` 任务会在启动后打开指定 URL。
- `external_cdp` 任务用于启动 Profile，供外部自动化客户端通过 CDP 接入。

## 认证

默认情况下认证关闭，适合本地使用。设置 `AUTH_TOKEN` 后，将启用登录和 API Bearer Token 校验。

设置 `AUTH_TOKEN` 后：

- Web UI 会显示登录流程。
- API 客户端需要发送 `Authorization: Bearer <token>`。
- VNC 和 CDP WebSocket 路由需要同一认证上下文。
- `/api/status`、`/api/auth/status` 和 `/api/auth/login` 会保留给健康检查和登录流程使用。

如果服务暴露到 localhost 之外，应在前面放置 HTTPS 终止层，并根据部署环境做好访问控制。Manager 本身提供 HTTP 服务。

## 开发

后端开发环境：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8080
```

前端开发环境：

```bash
cd frontend
npm install
npm run dev
```

后端测试：

```bash
python -m pytest backend/tests
```

前端生产构建：

```bash
cd frontend
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
