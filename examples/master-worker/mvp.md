# 公网 Master + Worker MVP 部署手册

目标拓扑是 `1 台公网 Master + 1 台公网 Worker`。Master 负责控制面和任务分配，Worker 运行浏览器 Profile、VNC 和 CDP，并通过 `8080/tcp` 对外提供 Worker API。

以下命令默认在仓库根目录执行，可按实际路径设置 `REPO_DIR`：

```bash
export REPO_DIR="$PWD"
export MASTER_PUBLIC_IP=<master-public-ip>
export WORKER_PUBLIC_IP=<worker-public-ip>
```

## 1. 准备 Worker 服务器清单

```bash
cp config/servers.json.example config/servers.json
```

把 `config/servers.json` 里的 `host` 改为 Worker 的公网 IP 或 Master 可访问的内网 IP，`username`、`port`、`password` 或 SSH key 环境按实际服务器填写。`node_id` 建议使用稳定名称，例如 `worker-a`。

## 2. 准备公网 provision 配置

```bash
cp config/provision.json.example config/provision.json
```

默认模板会先尝试当前 SSH 用户直接执行 `docker`，失败时自动回退到 `sudo -n docker`。如果 Worker 用户需要 sudo 操作 Docker，请确保它具备无交互 sudo 权限。

公网部署必须明确这三个地址：

```bash
export MASTER_PROVISION_MASTER_BASE_URL="http://${MASTER_PUBLIC_IP}:8080"
export MASTER_PROVISION_WORKER_API_BASE="http://{host}:8080"
export WORKER_API_BASE="http://${WORKER_PUBLIC_IP}:8080"
```

- `MASTER_PROVISION_MASTER_BASE_URL`：Master 写入 Worker 容器的 `MASTER_BASE_URL`，Worker 用它回连 Master。
- `MASTER_PROVISION_WORKER_API_BASE`：Master 根据服务器清单渲染 Worker 的 `WORKER_API_BASE`，通常保持 `http://{host}:8080`。
- `WORKER_API_BASE`：手动启动 Worker 时使用；通过 Master provision 启动时由模板自动写入。

## 3. 启动公网 Master

Master 可以直接拉取 GHCR 镜像运行：

```bash
docker pull ghcr.io/gscr10/cloakbrowser-orchestration-manager-master:latest

docker run -d --name cloak-manager-master --restart unless-stopped \
  -p 8080:8080 \
  -v cloak-master-data:/data \
  -v "${REPO_DIR}/config:/config:ro" \
  -e MASTER_SERVER_LIST_PATH=/config/servers.json \
  -e MASTER_PROVISION_CONFIG_PATH=/config/provision.json \
  -e MASTER_PROVISION_MASTER_BASE_URL="${MASTER_PROVISION_MASTER_BASE_URL}" \
  -e MASTER_PROVISION_WORKER_API_BASE="${MASTER_PROVISION_WORKER_API_BASE}" \
  ghcr.io/gscr10/cloakbrowser-orchestration-manager-master:latest
```

确认 Master API 可访问：

```bash
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" cluster
```

## 4. 配置 Provider 并干跑

```bash
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" providers
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" set-provider static
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" provision-run --dry-run
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" provision-jobs
```

`feishu_cli` 目前只是预留 Provider，公网主流程使用 `static`。

## 5. Provision Worker

确认 Worker 的 SSH 登录、Docker 权限和安全组已就绪后执行真实部署：

```bash
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" provision-run --no-dry-run
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" provision-jobs
```

Provision 成功后，Worker 容器会带着以下关键环境变量启动：

```text
DISTRIBUTED_WORKER_ENABLED=true
MASTER_BASE_URL=http://<master-public-ip>:8080
WORKER_API_BASE=http://<worker-public-ip>:8080
WORKER_NODE_ID=<node_id>
```

## 6. 创建任务并观察执行

```bash
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" create-task \
  --authorized-target "internal test app" \
  --task-type open_url

python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" tasks
python3 -m master_backend.cli --base-url "http://${MASTER_PUBLIC_IP}:8080" cluster
```

Worker 拉取任务和回报状态由 Worker 进程自动完成，不需要手工模拟注册、心跳或 `tasks/pull`。

## 7. 人工检查前端和 VNC

公网入口：

```text
Master Console: http://<master-public-ip>:8080
Worker UI/API:  http://<worker-public-ip>:8080
```

VNC 通过 Worker 的 `8080` WebSocket 代理访问，不需要额外开放 KasmVNC 内部的 `6100+` 端口。打开 Worker UI 后启动一个 `headless=false` 的 Profile，即可在 Worker 前端里观察浏览器窗口。

## 附录：手动启动 Worker

如果暂时不通过 Master provision，也可以在 Worker 机器上手动启动：

```bash
docker pull ghcr.io/gscr10/cloakbrowser-orchestration-manager-worker:latest

docker run -d --name cloak-manager-worker --restart unless-stopped \
  --shm-size=512m \
  -p 8080:8080 \
  -v cloak-manager-data:/data \
  -v /opt/cloak-manager-worker/config:/config:ro \
  -e CONFIG_IMPORT_ON_START=true \
  -e CONFIG_DIR=/config \
  -e DISTRIBUTED_WORKER_ENABLED=true \
  -e MASTER_BASE_URL="http://${MASTER_PUBLIC_IP}:8080" \
  -e WORKER_API_BASE="http://${WORKER_PUBLIC_IP}:8080" \
  -e WORKER_NODE_ID=worker-a \
  ghcr.io/gscr10/cloakbrowser-orchestration-manager-worker:latest
```
