<p align="center">
<img src="https://i.imgur.com/cqkp6fG.png" width="500" alt="CloakBrowser">
</p>

<h3 align="center">Browser Profile Manager for CloakBrowser</h3>

<p align="center">
Create, manage, and launch isolated browser profiles with unique fingerprints.<br>
Free, self-hosted alternative to Multilogin, GoLogin, and AdsPower.
</p>

<p align="center">
<a href="https://github.com/CloakHQ/CloakBrowser"><img src="https://img.shields.io/github/stars/cloakhq/cloakbrowser?label=CloakBrowser" alt="Stars"></a>
<a href="https://hub.docker.com/r/cloakhq/cloakbrowser-manager"><img src="https://img.shields.io/docker/pulls/cloakhq/cloakbrowser-manager?label=docker&logo=docker&logoColor=white" alt="Docker Pulls"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
</p>

---

<p align="center">
<img src="https://i.imgur.com/twdX81Q.png" width="800" alt="CloakBrowser Manager — Browser View">
<br>
<img src="https://i.imgur.com/XFYn1qY.png" width="800" alt="CloakBrowser Manager — Profile Settings">
</p>

Each profile is an isolated CloakBrowser instance with its own fingerprint, proxy, cookies, and session data. Profiles persist across restarts. Everything runs in one Docker container.

```bash
docker run -p 8080:8080 -v cloakprofiles:/data cloakhq/cloakbrowser-manager
```

Or build from source:

```bash
git clone https://github.com/CloakHQ/CloakBrowser-Manager.git
cd CloakBrowser-Manager
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080) in your browser. Create a profile. Click Launch. Done.

> **Early alpha** — this project is under active development. Expect bugs. If you find one, please [open an issue](https://github.com/CloakHQ/CloakBrowser-Manager/issues).

## Why Not Just Use a VPN?

A VPN only changes your IP. Incognito only clears cookies. Chrome profiles share the same hardware fingerprint underneath. Platforms use 50+ signals to link your accounts — canvas, WebGL, audio, GPU, fonts, screen size, timezone.

Each CloakBrowser profile generates a completely different device identity. To the website, each profile looks like a different computer.

| Solution | What it changes | Accounts linked? |
|----------|----------------|-----------------|
| VPN | IP address only | Yes — same fingerprint |
| Incognito | Clears cookies | Yes — same fingerprint |
| Chrome profiles | Separate bookmarks/cookies | Yes — same hardware fingerprint |
| **CloakBrowser** | **Everything — full device identity per profile** | **No** |

## Features

- **Profile management** — create, edit, delete browser profiles with unique fingerprints
- **Per-profile settings** — fingerprint seed, proxy, timezone, locale, user agent, screen size, platform
- **One-click launch/stop** — each profile runs as an isolated CloakBrowser instance
- **Session persistence** — cookies, localStorage, and cache survive browser restarts
- **In-browser viewing** — interact with launched browsers via noVNC, directly in the web GUI
- **Playwright/Puppeteer API** — connect to any running profile programmatically via CDP, while still watching it live in the browser
- **Proxy pool** — import and manage reusable proxy endpoints from CSV
- **Task scheduler** — queue authorized browser tasks and let the Manager launch profiles automatically within local concurrency limits
- **Optional authentication** — protect the web UI and API with a single token, or run wide open locally
- **Powered by CloakBrowser** — 32 source-level C++ patches, passes Cloudflare Turnstile, 0.9 reCAPTCHA v3 score

## Stack

- **Backend**: FastAPI (Python)
- **Frontend**: React + Tailwind CSS
- **Browser viewer**: noVNC (WebSocket-based VNC client)
- **Database**: SQLite
- **Browser engine**: [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) (stealth Chromium binary)

## Development

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Docker

```bash
docker compose up --build
```

## Requirements

- Docker (20.10+)
- ~2 GB disk (image + binary)
- ~512 MB RAM per running profile

## Updating

Pull the latest image and restart:

```bash
docker pull cloakhq/cloakbrowser-manager
docker stop <container-id>
docker run -p 8080:8080 -v cloakprofiles:/data cloakhq/cloakbrowser-manager
```

Your profiles and session data are stored in the `cloakprofiles` volume and persist across updates.

## Automation API

Every running profile exposes a CDP (Chrome DevTools Protocol) endpoint. Connect Playwright or Puppeteer to automate a profile while watching it live in the browser.

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

The CDP URL is available in the toolbar (code icon) when a profile is running. The same browser session is accessible both visually through VNC and programmatically through the API.

## Orchestration API

This build includes a single-node orchestration layer on top of the existing profile launcher. It reuses the same persistent profiles, KasmVNC viewer, and CDP proxy used by the manual Launch button.

## CLI Usage

The backend includes a lightweight CLI that calls the same HTTP API as the web UI. Use it when you want to manage profiles, proxies, tasks, and launched browsers without opening the GUI.

```bash
# Run from the repository root while the Manager API is running
python -m backend.cli status
```

Configure the target API and optional auth token with flags or environment variables:

```bash
export CLOAK_MANAGER_URL=http://localhost:8080
export CLOAK_MANAGER_TOKEN=your-secret-token

python -m backend.cli profiles list
```

Create and launch a fingerprinted browser profile from the CLI:

```bash
python -m backend.cli profiles create worker-1 \
  --platform windows \
  --proxy http://user:pass@proxy.example.com:8080 \
  --timezone America/New_York \
  --locale en-US \
  --screen-width 1920 \
  --screen-height 1080

python -m backend.cli profiles launch <profile-id>
python -m backend.cli profiles status <profile-id>
python -m backend.cli profiles cdp <profile-id>
python -m backend.cli profiles stop <profile-id>
```

Import or create proxies without using the GUI:

```bash
python -m backend.cli proxies template > proxies.csv
python -m backend.cli proxies import proxies.csv

python -m backend.cli proxies create \
  --protocol socks5 \
  --host proxy.example.com \
  --port 1080 \
  --username user \
  --password secret \
  --region us \
  --tags residential,automation
```

Submit scheduler tasks and inspect runs:

```bash
python -m backend.cli tasks create \
  --profile-id <profile-id> \
  --authorized-target "internal test app" \
  --task-type open_url \
  --url https://example.com

python -m backend.cli scheduler status
python -m backend.cli scheduler tick
python -m backend.cli tasks list
python -m backend.cli runs list
```

For advanced fields, pass an extra JSON object inline or as a file with `--json`. Values in `--json` override matching CLI flags.

Proxy endpoints can be imported from CSV with these columns:

```csv
protocol,host,port,username,password,region,tags
http,proxy.example.com,8080,user,secret,us,residential
```

Core endpoints:

```bash
# List proxy endpoints
curl http://localhost:8080/api/proxies

# Import proxy CSV
curl -X POST http://localhost:8080/api/proxies/import \
  -H 'Content-Type: application/json' \
  -d '{"csv":"protocol,host,port\nhttp,proxy.example.com,8080\n"}'

# Enqueue an authorized URL-open task
curl -X POST http://localhost:8080/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"profile_id":"<profile-id>","authorized_target":"internal test app","task_type":"open_url","url":"https://example.com"}'

# Check scheduler status
curl http://localhost:8080/api/scheduler/status
```

The scheduler runs automatically in the backend. Use `MAX_RUNNING_PROFILES` to control local concurrency and `SCHEDULER_INTERVAL_SECONDS` to control queue polling frequency.

```bash
# Run with three concurrent profiles and five-second queue polling
docker run -p 8080:8080 \
  -v cloakprofiles:/data \
  -e MAX_RUNNING_PROFILES=3 \
  -e SCHEDULER_INTERVAL_SECONDS=5 \
  cloakbrowser-manager
```

## Remote Access

The container binds to localhost only. To access from a remote server:

```bash
ssh -L 8080:localhost:8080 your-server
```

Then open `http://localhost:8080`.

## Authentication

By default, there is no authentication (ideal for local use). To protect the web UI and API when hosting on a network, set the `AUTH_TOKEN` environment variable:

```bash
docker run -p 8080:8080 -v cloakprofiles:/data -e AUTH_TOKEN=your-secret-token cloakhq/cloakbrowser-manager
```

Or in `docker-compose.yml`:

```yaml
environment:
  - AUTH_TOKEN=your-secret-token
```

When `AUTH_TOKEN` is set:

- The web UI shows a login page. Enter the token to unlock.
- API consumers pass the token via `Authorization: Bearer <token>` header.
- VNC WebSocket connections are authenticated via the login cookie.
- The `/api/status` endpoint remains unauthenticated (for Docker healthcheck).

> **Note**: The auth token is transmitted in cleartext over HTTP. If you expose the Manager to the internet, put it behind a reverse proxy with HTTPS (Caddy, nginx, Traefik).

## License

- **This application** (GUI source code) — MIT. See [LICENSE](LICENSE).
- **CloakBrowser binary** (compiled Chromium) — free to use, no redistribution. See [BINARY-LICENSE.md](BINARY-LICENSE.md).

The GUI application requires the CloakBrowser Chromium binary to function. The binary is automatically downloaded on first launch and is governed by its own license terms. If you fork or redistribute this application, your users must comply with the [CloakBrowser Binary License](BINARY-LICENSE.md).

## Contributing

Contributions are welcome. Please [open an issue](https://github.com/CloakHQ/CloakBrowser-Manager/issues) first to discuss what you'd like to change.

## Links

- **CloakBrowser** — [github.com/CloakHQ/CloakBrowser](https://github.com/CloakHQ/CloakBrowser)
- **Website** — [cloakbrowser.dev](https://cloakbrowser.dev)
- **Bug reports** — [GitHub Issues](https://github.com/CloakHQ/CloakBrowser-Manager/issues)
- **Contact** — cloakhq@pm.me
