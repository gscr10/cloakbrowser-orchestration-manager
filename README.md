# CloakBrowser Orchestration Manager

Single-node orchestration service for running isolated CloakBrowser profiles with a web UI, HTTP API, CLI, persistent browser state, reusable proxy configuration, and a lightweight local task scheduler.

This repository is maintained as an independent project at `gscr10/cloakbrowser-orchestration-manager`. It builds on CloakBrowser as the browser runtime, but the operational focus here is different from a plain profile GUI: the Docker image is treated as a reusable runtime, while profiles, proxies, task execution, and automation access are managed through external config, API, and CLI.

## What This Project Provides

- Browser profile CRUD with persistent per-profile user data under `/data/profiles/<profile-id>/`.
- Profile launch/stop/status APIs backed by the existing CloakBrowser lifecycle, KasmVNC display, and CDP proxy.
- Web UI for manual profile management and live VNC viewing.
- HTTP API for profiles, proxy endpoints, config import, scheduler tasks, runs, auth, VNC, clipboard, and CDP.
- CLI client at `python -m backend.cli` for headless administration without opening the GUI.
- Docker runtime configuration through mounted `/config/profiles.json` and `/config/proxies.csv`.
- Local SQLite storage under `/data` for profiles, proxy metadata, tasks, runs, and persisted browser sessions.
- Single-node scheduler that starts queued authorized tasks within a configurable local concurrency limit.
- Optional token authentication for the web UI and API.

## Intended Use

Use this service for authorized browser automation, internal test environments, profile isolation, proxy assignment, multi-environment verification, and local/manual debugging through VNC.

Do not use this project for credential stuffing, spam, bulk signups, unauthorized scraping, account takeover, CAPTCHA bypass, platform abuse, or other activity outside your authorization boundary. The scheduler includes a small local policy guard for obvious disallowed task descriptions, but operational responsibility remains with the operator.

## Architecture

```text
React UI / CLI / external client
  -> FastAPI backend on port 8080
  -> SQLite database under /data
  -> BrowserManager launches CloakBrowser profiles
  -> KasmVNC exposes live browser viewing
  -> CDP proxy exposes Playwright/Puppeteer automation access
  -> Scheduler consumes queued tasks and applies proxy/runtime settings
```

Key runtime paths:

```text
/data
/data/manager.db
/data/profiles/<profile-id>/
/config/profiles.json
/config/proxies.csv
```

## Quick Start With Docker

Build the local image:

```bash
docker build -t cloakbrowser-orchestration-manager:local .
```

Run the service with persistent state and optional external config:

```bash
docker run --shm-size=2g \
  -p 8080:8080 \
  -v cloak-manager-data:/data \
  -v ./config:/config:ro \
  -e CONFIG_IMPORT_ON_START=true \
  -e CONFIG_DIR=/config \
  -e MAX_RUNNING_PROFILES=3 \
  -e SCHEDULER_INTERVAL_SECONDS=5 \
  cloakbrowser-orchestration-manager:local
```

Open `http://localhost:8080`.

If you need API/UI protection, set `AUTH_TOKEN`:

```bash
docker run --shm-size=2g \
  -p 8080:8080 \
  -v cloak-manager-data:/data \
  -v ./config:/config:ro \
  -e AUTH_TOKEN=your-secret-token \
  -e CONFIG_IMPORT_ON_START=true \
  -e CONFIG_DIR=/config \
  cloakbrowser-orchestration-manager:local
```

## Docker Compose

The included `docker-compose.yml` builds the local image, binds the service to `127.0.0.1:8080`, stores data in `~/.cloakbrowser-manager`, and mounts `./config` into `/config`.

```bash
docker compose up --build
```

If your environment only has the legacy `docker-compose` binary and it fails due to Python package compatibility, use the `docker build` and `docker run` commands above.

## Runtime Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTH_TOKEN` | unset | Optional bearer token and UI login token. When unset, API and UI are open. |
| `CONFIG_DIR` | `/config` | Directory containing external config files. |
| `CONFIG_IMPORT_ON_START` | `false` | Import `/config/profiles.json` and `/config/proxies.csv` during startup when true. |
| `MAX_RUNNING_PROFILES` | `3` | Local concurrency limit used by the scheduler. |
| `SCHEDULER_INTERVAL_SECONDS` | `5` | Background scheduler polling interval. |

The container should run with enough shared memory for Chromium. `--shm-size=2g` is the recommended starting point.

## External Config

External config is optional. It is intended for reproducible runtime bootstrapping while keeping browser state persistent in `/data`.

Supported files:

```text
/config/profiles.json
/config/proxies.csv
```

`profiles.json` can be either a list or an object with a `profiles` list. Profiles are matched by `name`; existing profiles are updated in place so their `/data/profiles/<profile-id>/` directories remain stable.

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

`proxies.csv` uses this header:

```csv
protocol,host,port,username,password,region,tags
http,proxy.example.com,8080,user,secret,us,residential
```

Import config at startup with `CONFIG_IMPORT_ON_START=true`, or trigger it while the service is running:

```bash
python -m backend.cli config import
```

The import endpoint is idempotent for profiles by `name`. Proxy import skips duplicates based on protocol, host, port, and username.

## CLI Usage

The CLI is a thin HTTP client for the same backend API used by the UI.

```bash
python -m backend.cli status
```

Configure the target API with flags or environment variables:

```bash
export CLOAK_MANAGER_URL=http://localhost:8080
export CLOAK_MANAGER_TOKEN=your-secret-token

python -m backend.cli profiles list
```

Global options:

```text
--base-url http://localhost:8080
--token <token>
--timeout 30
--compact
```

Profile commands:

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

Proxy commands:

```bash
python -m backend.cli proxies list
python -m backend.cli proxies template > proxies.csv
python -m backend.cli proxies import proxies.csv
python -m backend.cli proxies create --protocol socks5 --host proxy.example.com --port 1080 --username user --password secret --region us --tags residential,automation
```

Task and scheduler commands:

```bash
python -m backend.cli tasks create --profile-id <profile-id> --authorized-target "internal test app" --task-type open_url --url https://example.com
python -m backend.cli tasks list
python -m backend.cli tasks cancel <task-id>
python -m backend.cli runs list
python -m backend.cli scheduler status
python -m backend.cli scheduler tick
```

For advanced fields, pass `--json` with an inline JSON object or a JSON file path. Values from `--json` override matching flags.

## HTTP API Overview

Core endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/status` | Health/status summary. |
| `GET` | `/api/profiles` | List profiles. |
| `POST` | `/api/profiles` | Create profile. |
| `GET` | `/api/profiles/{profile_id}` | Get profile. |
| `PUT` | `/api/profiles/{profile_id}` | Update profile. |
| `DELETE` | `/api/profiles/{profile_id}` | Delete stopped profile. |
| `POST` | `/api/profiles/{profile_id}/launch` | Launch profile. |
| `POST` | `/api/profiles/{profile_id}/stop` | Stop profile. |
| `GET` | `/api/profiles/{profile_id}/status` | Runtime status. |
| `GET` | `/api/profiles/{profile_id}/cdp` | CDP connection information. |
| `WS` | `/api/profiles/{profile_id}/vnc` | VNC websocket proxy. |
| `POST` | `/api/profiles/{profile_id}/clipboard` | Push clipboard text to a running profile. |
| `GET` | `/api/proxies` | List proxy endpoints. |
| `POST` | `/api/proxies` | Create proxy endpoint. |
| `POST` | `/api/proxies/import` | Import proxy CSV. |
| `POST` | `/api/config/import` | Import `/config` files. |
| `GET` | `/api/tasks` | List scheduler tasks. |
| `POST` | `/api/tasks` | Queue task. |
| `POST` | `/api/tasks/{task_id}/cancel` | Cancel queued task. |
| `GET` | `/api/runs` | List profile runs. |
| `GET` | `/api/scheduler/status` | Scheduler status. |
| `POST` | `/api/scheduler/tick` | Run one scheduler tick. |

Example profile launch flow:

```bash
curl -X POST http://localhost:8080/api/profiles \
  -H 'Content-Type: application/json' \
  -d '{"name":"worker-1","platform":"windows","headless":false}'

curl -X POST http://localhost:8080/api/profiles/<profile-id>/launch

curl http://localhost:8080/api/profiles/<profile-id>/cdp
```

Example task queue flow:

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"profile_id":"<profile-id>","authorized_target":"internal test app","task_type":"open_url","url":"https://example.com"}'

curl http://localhost:8080/api/scheduler/status
```

## CDP Automation

Every running profile exposes a Chrome DevTools Protocol endpoint through the manager. Use it with Playwright or Puppeteer while optionally watching the same browser session in the web UI through VNC.

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

For a visible VNC session, create or update the profile with `headless=false`. A headless profile can still run and expose CDP, but VNC will not show a visible browser window.

## Scheduler Behavior

The scheduler is intentionally small and local:

- It runs inside the FastAPI backend.
- It polls queued tasks every `SCHEDULER_INTERVAL_SECONDS` seconds.
- It starts at most `MAX_RUNNING_PROFILES` profiles concurrently.
- It reuses `BrowserManager.launch(profile)` so VNC, CDP, display allocation, and persistent user data follow the same path as manual launches.
- It can assign a proxy endpoint from the local proxy pool at runtime.
- `open_url` tasks open a URL after launch.
- `external_cdp` tasks reserve/start a profile for an external automation client to connect over CDP.

## Authentication

Authentication is disabled by default for local-only usage. Set `AUTH_TOKEN` to require login/API bearer auth.

When `AUTH_TOKEN` is set:

- The web UI shows a login flow.
- API clients must send `Authorization: Bearer <token>`.
- VNC and CDP websocket routes require the same auth context.
- `/api/status`, `/api/auth/status`, and `/api/auth/login` remain available for health/login flows.

If the service is exposed beyond localhost, terminate HTTPS in front of it and protect the deployment appropriately. The manager itself serves HTTP.

## Development

Backend setup:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8080
```

Frontend setup:

```bash
cd frontend
npm install
npm run dev
```

Backend tests:

```bash
python -m pytest backend/tests
```

Frontend production build:

```bash
cd frontend
npm run build
```

## Operational Notes

- Store mutable runtime state in `/data`, not in the image.
- Store desired bootstrap config in `/config`, mounted read-only when possible.
- Do not put cookies, cache, localStorage, or browser profile state into `profiles.json`; those live under `/data/profiles/<profile-id>/`.
- Keep `headless=false` for profiles that must be viewed through VNC.
- Use `--compact` with the CLI when machine-readable one-line JSON output is preferred.
- The Dockerfile sets a default `TARGETARCH=amd64` so classic `docker build` works even without BuildKit-provided platform args.

## Requirements

- Docker 20.10 or newer for the recommended runtime.
- Around 2 GB of disk for image layers and browser binaries.
- Enough memory for the backend plus each running Chromium profile.
- Python 3.11+ for local backend development and tests.
- Node.js 20+ for frontend development and production builds.

## License And Runtime Dependency

- Application source code: MIT, see [LICENSE](LICENSE).
- CloakBrowser binary/runtime: governed separately, see [BINARY-LICENSE.md](BINARY-LICENSE.md).

This application requires the CloakBrowser Chromium runtime to launch profiles. The binary may be downloaded by the runtime as needed and is governed by its own license terms.

## Repository

- Project repository: https://github.com/gscr10/cloakbrowser-orchestration-manager
- CloakBrowser runtime project: https://github.com/CloakHQ/CloakBrowser