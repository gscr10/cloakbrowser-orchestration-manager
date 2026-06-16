# CloakBrowser Orchestration Manager 架构深度 Review

Review 日期：2026-05-08

分析范围：源代码、配置示例、Docker/CI 文件、examples、测试文件。已排除 `.git`、`node_modules`、`dist`、`__pycache__`、`.pytest_cache` 等生成目录。本地存在 `.env.feishu.local`，该文件已被 Git 忽略，未读取其内容，避免暴露密钥。

## 验证结果

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| Git 状态 | 干净 | 生成本报告前，`main...origin/main`，没有已跟踪的本地改动。当前新增了本报告所在的 `docs/` 目录。 |
| Worker 前端测试 | 通过 | `npm test`，共 `18 passed`。 |
| Worker 前端构建 | 通过 | `npm run build` 成功。 |
| Master 前端构建 | 通过 | `npm run build` 成功。 |
| 后端 pytest | 未执行 | 当前 Python 环境没有安装 `pytest`，项目下也没有可直接使用的 `.venv`。 |
| 后端测试库存 | 279 个测试函数 | 从测试文件看覆盖面较广，但本地未实际执行。 |

## 总体结论

| 维度 | 结论 | 评估 |
| --- | --- | --- |
| 整体架构方向 | Master/Worker、基础设施/业务、全局调度/本地执行的拆分方向是正确的。 | 合理 |
| 当前边界清晰度 | 命名和意图比较清楚，但很多边界靠约定维持，还没有形成强约束。 | 中风险 |
| 短期可扩展性 | 能支撑 MVP 到中小规模的 Master/Worker 公网部署。 | 可用 |
| 长期可维护性 | 需要拆大模块、集中编排状态机、补认证、补 CI 质量门禁。 | 需要治理 |
| 最高风险 | Master/Worker API 和 UI 默认没有内建认证，但 Worker 暴露了浏览器控制能力。 | 高 |
| 最大技术债 | `master_control.py`、`master_backend/main.py`、`worker_backend/main.py` 过大，职责混杂。 | 高优先级 |

整体判断：这是一个方向合理、但边界还不够硬的架构。它不是随意堆功能的项目，已经有清晰的 Master 控制面、Worker 执行面，也在 Master 侧显式拆出了 `infra_*` 和 `biz_*` 模块。当前主要问题不是“方向错”，而是“关键状态流和控制流还散在多个模块里”，导致后续扩展基础设施、业务流程、调度策略时容易互相影响。

## 分层架构评估

| 层级 | 主要文件 | 优点 | 主要问题 | 结论 |
| --- | --- | --- | --- | --- |
| 基础建设层 | `master_backend/infra_services.py`、`infra_sync.py`、`infra_reconciler.py`、`infra_repository.py`、`worker_backend/browser_manager.py` | Worker 健康状态、槽位、标签、能力、资源压力、VNC/CDP 运行时已有独立表达。 | Worker 创建、节点选择、Profile 分配仍有逻辑泄漏在 `master_control.py`。 | 方向正确，但需要继续收敛边界。 |
| 业务层 | `master_backend/biz_services.py`、`biz_sync.py`、`biz_validation.py`、`biz_repository.py`、`worker_backend/automation/` | 业务任务具备幂等、快照、状态事件、运行记录、产物、回写等概念。 | 业务输入 schema 在 Master 校验和 Worker 脚本能力之间存在重复。 | 可继续演进为独立业务域。 |
| 调度层 | `master_backend/master_control.py`、`worker_backend/scheduler.py`、`worker_backend/distributed_worker.py` | Master 全局派发和 Worker 本地队列在概念上是分开的。 | Master 任务状态机散落在 API route、业务服务和控制模块中。 | 需要集中化任务编排器。 |
| 数据层 | `master_backend/database.py`、`worker_backend/database.py` | SQLite 简单、可测试，适合当前阶段。 | 单文件过大，持久化逻辑把 infra/biz/scheduler 的边界拉模糊了。 | MVP 合理，后续应按 bounded context 拆 repository。 |
| 外部适配层 | `source_registry.py`、`source_adapters.py`、`feishu_openapi.py`、`writeback.py` | 本地 JSON、飞书 OpenAPI、noop writeback 已有适配抽象。 | 缺少 retry、限流处理、增量同步、强 schema 契约。 | 适配器形态合理，但还不是生产级。 |
| 前端层 | `worker-frontend/src/*`、`master-frontend/src/App.jsx` | Worker 前端相对模块化且有测试。 | Master 前端是单个大组件，状态、请求、动作、视图混在一起。 | Worker 前端较健康，Master 前端需要拆分。 |

## 当前运行链路

```text
业务来源 / CLI / UI
  -> Master API
  -> biz_sync / biz_services
  -> infra_services 选择 Worker
  -> master_tasks 队列
  -> Worker distributed_worker 拉取任务
  -> Worker scheduler 创建本地 task/run
  -> BrowserManager 启动 profile 和 VNC/CDP
  -> automation/profile_runtime 执行动作
  -> Worker 回报结果给 Master
  -> biz_services 更新业务状态并执行 writeback
```

这条链路本身是合理的。真正薄弱的位置是“状态迁移归谁管”不够明确。例如任务创建、分配、profile 自动选择、重试、取消、恢复、业务状态更新，目前不是由一个统一 orchestrator 负责，而是被拆散在多个模块里。

## 高优先级问题

| 优先级 | 问题 | 证据 | 影响 | 建议 |
| --- | --- | --- | --- | --- |
| 高 | Master/Worker API 和 UI 默认开放。 | README 中说明公网 MVP 暂无 token auth；Worker 暴露 VNC/CDP/clipboard API。 | 只要能访问网络，就可能控制浏览器 profile 和任务。 | 增加 API token、反向代理认证、mTLS 或签名 worker token。至少保护所有非 health endpoint。 |
| 高 | Worker VNC 内部无认证。 | `worker_backend/vnc_manager.py` 启动 Xvnc 时使用 `-SecurityTypes None` 和 `-DisableBasicAuth`。 | 只有在绑定 `127.0.0.1` 且 API 代理受保护时才相对安全，一旦配置错误风险很高。 | 保持本地绑定，增加 Worker API 鉴权，并在部署文档中明确防火墙假设。 |
| 高 | `master_control.py` 职责混杂。 | 包含 provider 选择、调度、profile 自动分配、SSH 命令构造、provision 执行、heartbeat 校验。 | 部署逻辑、调度逻辑、profile 分配逻辑互相影响，改动回归风险高。 | 拆成 provider、provision、profile allocator、master scheduler 等服务。 |
| 高 | Master 任务状态机分散。 | `master_backend/main.py` 直接处理 pull/report/retry/cancel，`biz_services` 也会修改相关业务状态。 | 失败、重试、取消、卡住任务恢复时，容易出现状态不一致。 | 增加 `TaskOrchestrator` 或 `master_scheduler.py`，由它统一拥有任务状态迁移。 |
| 高 | Worker 前端记录剪贴板内容。 | `worker-frontend/src/components/ProfileViewer.tsx` 中有多处围绕 clipboard text 的 `console.log`。 | 敏感复制内容可能进入浏览器日志或远程调试工具。 | 删除日志，或只保留开发环境日志；永远不要打印剪贴板正文。 |
| 高 | 示例文档包含真实公网 IP。 | `examples/master-worker/mvp.md` 中出现 2026-05-07 的 Master/Worker 具体公网 IP。 | 信息暴露，也会让公开文档带有过期运维记录。 | 替换成脱敏示例值，或将验收记录迁到私有文档。 |

## 中优先级问题

| 优先级 | 问题 | 证据 | 影响 | 建议 |
| --- | --- | --- | --- | --- |
| 中 | 数据库模块过大。 | `master_backend/database.py` 约 920 行，`worker_backend/database.py` 约 515 行。 | ownership 不清晰，后续迁移和测试成本升高。 | 按 schema/migration/repository/bounded context 拆分。 |
| 中 | Worker 选择逻辑重复。 | `master_control.pick_target_node()` 和 `infra_services.find_available_worker()` 都在判断可用性。 | 调度策略容易漂移，线上行为不一致。 | 所有 Worker 选择统一走 `infra_services`。 |
| 中 | `automation_script` 没有在 API client/CLI/前端中完整对齐。 | 后端模型支持，但 Master/Worker CLI 和 Worker 前端 task type 常只列出 `open_url`、`external_cdp`。 | 不同入口能力不一致，用户会误判系统实际支持的任务类型。 | 同步 models、CLI、frontend、docs 的 task type 支持。 |
| 中 | `worker_backend/main.py` 过大。 | 同时包含 profile CRUD、task API、VNC proxy、RFB filtering、clipboard、CDP proxy、SPA serving。 | 回归风险高，测试粒度粗。 | 按 profiles、tasks、vnc、cdp、clipboard、static 拆 router/module。 |
| 中 | Master 前端是单个大组件。 | `master-frontend/src/App.jsx` 约 1217 行。 | 状态、API、视图耦合，难以测试和维护。 | 拆 API client、hooks、pages、components；可考虑迁到 TypeScript。 |
| 中 | Docker 构建不够可复现。 | Dockerfile 使用 `npm install`、Python 依赖范围较宽，并直接下载 KasmVNC 且未校验 checksum。 | 上游变化可能导致构建漂移或失败。 | 使用 `npm ci`，锁定 Python 依赖，对下载产物做 checksum 校验。 |
| 中 | CI 只构建和推送镜像。 | `.github/workflows/docker-image.yml` 没有 test/lint gate。 | 有问题的代码仍可能被打包并发布。 | 镜像构建前增加 Python tests、前端 tests/build，可选 lint/typecheck。 |
| 中 | 飞书 adapter 仍是 MVP 级别。 | 主要是全量分页；缺少明确 retry、backoff、rate limit 处理、sync cursor。 | Base 变大或遇到瞬时错误时，同步会变脆弱。 | 增加 retry/backoff、cursor/checkpoint、partial sync、更好的错误记录。 |

## 低优先级 / 质量问题

| 优先级 | 问题 | 影响 | 建议 |
| --- | --- | --- | --- |
| 低 | 大量宽泛的 `except Exception`。 | 容易隐藏根因，错误分类不稳定。 | 对外部请求、子进程、文件、DB、自动化异常做分类处理。 |
| 低 | 列表 API 缺少分页。 | tasks、events、runs、artifacts 变多后会拖慢。 | 增加 pagination、filters、default limit。 |
| 低 | README 过长且混合多种关注点。 | 难维护，也容易留下过期运维信息。 | 拆成 `docs/deploy.md`、`docs/architecture.md`、`docs/security.md`。 |
| 低 | `architecture.py` 目前只提供计数类信息。 | 架构页不能真实反映健康度和风险。 | 增加 health/risk checklist 聚合。 |
| 低 | 本地辅助脚本直接 source env 文件。 | 本地使用方便，但可能让操作者误解作用范围。 | 明确保持 local-only，并写清楚使用边界。 |

## 文件级 Review

| 区域 | 文件 | 评估 |
| --- | --- | --- |
| Master API | `master_backend/main.py` | API 覆盖面广，但 route 中承载了过多编排逻辑。 |
| Master 控制面 | `master_backend/master_control.py` | 后端最大技术债之一；认证之后应优先拆分。 |
| Master 基础设施 | `infra_services.py`、`infra_sync.py`、`infra_reconciler.py`、`infra_repository.py` | 方向正确，`find_available_worker` 应成为基础设施调度的统一边界。 |
| Master 业务域 | `biz_services.py`、`biz_sync.py`、`biz_validation.py`、`biz_repository.py` | 业务状态流较清楚；输入 schema 应与 Worker capabilities 统一。 |
| Master 外部来源 | `source_registry.py`、`source_adapters.py`、`feishu_openapi.py`、`writeback.py` | adapter 形态有价值，但生产韧性不足。 |
| Worker API | `worker_backend/main.py` | 功能完整但过大，应按 route domain 拆分。 |
| Worker 运行时 | `browser_manager.py`、`vnc_manager.py`、`runtime_limits.py` | 运行时边界清晰，资源检查也比较合理。 |
| Worker 调度 | `scheduler.py`、`distributed_worker.py`、`profile_runtime.py` | 本地调度清晰；`external_cdp` 行为需要更完整的文档说明。 |
| 自动化能力 | `worker_backend/automation/*`、`worker_backend/automation/scripts/*` | registry/plugin 点比较干净；脚本 schema 应成为 capability metadata 的一部分。 |
| Worker 前端 | `worker-frontend/src/*` | 比 Master 前端更模块化；测试和构建通过。需要移除剪贴板 debug 日志。 |
| Master 前端 | `master-frontend/src/App.jsx` | 控制台功能有用，但太多逻辑集中在一个文件，且缺少测试。 |
| Docker/CI | `Dockerfile`、`Dockerfile.master`、`.github/workflows/docker-image.yml` | 构建实用，但需要提升可复现性并加入测试门禁。 |
| 配置和示例 | `config/*.example`、`examples/*` | 对部署有帮助，但需要移除真实 IP，secret 示例必须保持明显 fake。 |

## 层间独立性判断

| 判断项 | 当前状态 | 风险 | 是否合理 | 优化方向 |
| --- | --- | --- | --- | --- |
| 基础建设层是否独立 | 部分独立。infra repository/service/reconciler 已经存在，但 provision 和 worker selection 仍与 master control 混杂。 | 基础设施策略变化可能影响调度和业务任务。 | 基本合理，但还不够清晰。 | 让 `infra_services` 成为 Worker 选择、资源判断、节点能力的唯一入口。 |
| 业务层是否独立 | 业务服务、校验、同步、回写已独立。 | 输入 schema 和 Worker 能力重复，新增业务任务时容易漏改入口。 | 合理。 | 建立统一 task capability/schema catalog。 |
| 调度层是否独立 | Worker 本地调度比较独立，Master 全局调度不够独立。 | 任务状态迁移散落，失败恢复复杂。 | 方向合理，但当前实现不够集中。 | 建立 `TaskOrchestrator`，统一 create/allocate/report/retry/cancel/recover。 |
| 前端是否独立 | Worker 前端较独立，Master 前端不够。 | 单文件状态膨胀，后续功能扩展困难。 | Worker 合理，Master 需要重构。 | 拆 API client、hooks、页面组件。 |
| 外部适配是否独立 | registry/adapter 已有抽象。 | 生产韧性不足。 | 合理但偏 MVP。 | 加 retry、限流、增量同步、错误持久化。 |

## 推荐优化路线图

| 阶段 | 目标 | 动作 |
| --- | --- | --- |
| 1 | 降低安全和运维风险 | 给 Master/Worker API 增加认证；移除剪贴板日志；脱敏 examples 中真实 IP。 |
| 2 | 稳定调度状态机 | 建立统一 Master task orchestrator，覆盖 create、allocate、report、retry、cancel、requeue、recover。 |
| 3 | 拆大模块 | 拆 `master_control.py`、`worker_backend/main.py`、`master-frontend/App.jsx`。 |
| 4 | 统一契约 | Worker capability 中包含输入 schema；Master validation 消费同一份 catalog。 |
| 5 | 提升工程门禁 | CI 增加 pytest、前端 test/build，测试通过后再 Docker build；安装命令改为可复现方式。 |
| 6 | 为规模化准备 | 增加 API 分页、事件保留策略、飞书增量同步、task lease、卡住任务恢复策略。 |

## 建议目标模块形态

```text
master_backend/
  api/
    nodes.py
    tasks.py
    infra.py
    biz.py
    provision.py
  services/
    task_orchestrator.py
    provision_service.py
    provider_service.py
    profile_allocator.py
    infra_scheduler.py
    biz_service.py
  repositories/
    master_task_repository.py
    infra_repository.py
    biz_repository.py
  adapters/
    local_json.py
    feishu_openapi.py
    writeback.py
```

```text
worker_backend/
  api/
    profiles.py
    tasks.py
    proxies.py
    vnc.py
    cdp.py
    clipboard.py
  runtime/
    browser_manager.py
    vnc_manager.py
    runtime_limits.py
  scheduling/
    local_scheduler.py
    distributed_worker.py
  automation/
    registry.py
    runner.py
    schemas.py
```

## 最终结论

这个项目当前架构是合理的，但还没有达到“层级边界强约束”的程度。Master 作为控制面、Worker 作为执行面，基础设施关注点和业务任务分离，全局调度和本地 profile 执行分离，这些核心方向都正确。

下一阶段不建议继续单纯堆功能，应该优先做三件事：第一，保护公网 API/UI，补齐认证；第二，移除敏感日志和真实运维信息；第三，把 Master 任务状态机集中到一个明确的 orchestrator。完成这三件事后，再优化基础建设层、业务层、调度层的功能会更安全，模块边界也会更稳定。
