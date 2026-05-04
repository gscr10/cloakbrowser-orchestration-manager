# Master + Worker MVP 联调说明

## 1. 准备服务器清单

```bash
# 复制模板
cp config/servers.json.example config/servers.json
```

按实际环境修改 `config/servers.json` 中的 `host`、`username`、`port`、`max_profiles`。

## 2. 启动 Master（本机）

```bash
# 使用独立 master 后端服务
MASTER_SERVER_LIST_PATH=/workspace/manager/config/servers.json \
python3 -m uvicorn master_backend.main:app --host 0.0.0.0 --port 8080
```

## 3. 配置 Provider 并做干跑

```bash
python3 -m master_backend.cli --base-url http://127.0.0.1:8080 providers
python3 -m master_backend.cli --base-url http://127.0.0.1:8080 set-provider static
python3 -m master_backend.cli --base-url http://127.0.0.1:8080 provision-run --dry-run
python3 -m master_backend.cli --base-url http://127.0.0.1:8080 provision-jobs
```

## 3.1 配置 non dry-run 模板（推荐配置文件）

```bash
# 复制初始化命令模板
cp config/provision.json.example config/provision.json
```

按目标环境修改 `config/provision.json` 中的 `bootstrap_cmd` 和 `start_cmd`。

如需调整注册校验窗口，可同时修改 `verify_wait_seconds` 和 `verify_interval_seconds`。

然后使用：

```bash
MASTER_SERVER_LIST_PATH=/workspace/manager/config/servers.json \
MASTER_PROVISION_CONFIG_PATH=/workspace/manager/config/provision.json \
python3 -m master_backend.cli --base-url http://127.0.0.1:8080 provision-run --no-dry-run
```

## 4. 节点注册与心跳（模拟 2 台 Worker）

```bash
curl -sS -X POST http://127.0.0.1:8080/api/master/nodes/register \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"worker-a","hostname":"worker-a.local","max_profiles":10}'

curl -sS -X POST http://127.0.0.1:8080/api/master/nodes/register \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"worker-b","hostname":"worker-b.local","max_profiles":10}'

curl -sS -X POST http://127.0.0.1:8080/api/master/nodes/heartbeat \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"worker-a","running_profiles":6,"cpu_percent":50,"mem_total_mb":8192,"mem_used_mb":4096,"status":"online"}'

curl -sS -X POST http://127.0.0.1:8080/api/master/nodes/heartbeat \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"worker-b","running_profiles":1,"cpu_percent":25,"mem_total_mb":8192,"mem_used_mb":2048,"status":"online"}'
```

## 5. 创建任务并由 Worker 拉取

```bash
python3 -m master_backend.cli --base-url http://127.0.0.1:8080 create-task \
  --authorized-target "internal test app" \
  --task-type open_url

curl -sS -X POST http://127.0.0.1:8080/api/master/tasks/pull \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"worker-b"}'
```

如果 `worker-b` 更空闲，任务会优先分配到 `worker-b`。

## 6. Worker 回报执行状态

将 `TASK_ID` 替换为上一步 pull 返回任务 ID。

```bash
curl -sS -X POST http://127.0.0.1:8080/api/master/tasks/TASK_ID/report \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"worker-b","status":"started"}'

curl -sS -X POST http://127.0.0.1:8080/api/master/tasks/TASK_ID/report \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"worker-b","status":"success"}'
```

## 7. 查看全局状态

```bash
python3 -m master_backend.cli --base-url http://127.0.0.1:8080 cluster
python3 -m master_backend.cli --base-url http://127.0.0.1:8080 tasks
```
