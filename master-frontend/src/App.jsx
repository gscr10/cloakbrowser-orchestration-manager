import { useEffect, useMemo, useState } from "react";

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText || "Request failed");
  }
  return res.json();
}

const NAV_ITEMS = [
  { id: "overview", label: "分层总览", desc: "跨层健康与阻塞点", icon: "grid" },
  { id: "infra", label: "基础设施层", desc: "Worker、部署、资源、能力", icon: "server" },
  { id: "biz", label: "业务自动化层", desc: "输入、幂等、调度、结果", icon: "briefcase" },
  { id: "profiles", label: "Profile 监控", desc: "浏览器实例与 VNC/CDP", icon: "browser" },
  { id: "events", label: "事件与回写", desc: "Infra/Biz 事件分流", icon: "activity" },
  { id: "settings", label: "配置与数据源", desc: "Provider、Feishu adapter", icon: "settings" }
];

function Icon({ type }) {
  const common = { viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: "1.7", strokeLinecap: "round", strokeLinejoin: "round" };
  if (type === "server") {
    return <svg {...common}><rect x="2" y="2.5" width="12" height="4" rx="1.2" /><rect x="2" y="9.5" width="12" height="4" rx="1.2" /><path d="M5 4.5h.1M5 11.5h.1" /></svg>;
  }
  if (type === "briefcase") {
    return <svg {...common}><rect x="2.2" y="5" width="11.6" height="8" rx="1.4" /><path d="M6 5V3.6h4V5M2.2 8h11.6" /></svg>;
  }
  if (type === "browser") {
    return <svg {...common}><rect x="2" y="3" width="12" height="10" rx="1.4" /><path d="M2 6h12M4.4 4.6h.1M6.2 4.6h.1" /></svg>;
  }
  if (type === "activity") {
    return <svg {...common}><path d="M2 8h2.4l1.2-3.2L8 12l2.2-8 1.2 4H14" /></svg>;
  }
  if (type === "settings") {
    return <svg {...common}><circle cx="8" cy="8" r="2.2" /><path d="M8 2.4v1.5M8 12.1v1.5M3.2 4.2l1.1 1.1M11.7 10.7l1.1 1.1M2.4 8h1.5M12.1 8h1.5M3.2 11.8l1.1-1.1M11.7 5.3l1.1-1.1" /></svg>;
  }
  return <svg {...common}><rect x="2.4" y="2.4" width="4.4" height="4.4" rx="1" /><rect x="9.2" y="2.4" width="4.4" height="4.4" rx="1" /><rect x="2.4" y="9.2" width="4.4" height="4.4" rx="1" /><rect x="9.2" y="9.2" width="4.4" height="4.4" rx="1" /></svg>;
}

function StatusPill({ value }) {
  const normalized = value || "-";
  const tone = {
    online: "success",
    success: "success",
    running: "info",
    assigned: "info",
    dispatched: "info",
    queued: "warning",
    pending_schedule: "warning",
    pending_deploy: "warning",
    imported: "neutral",
    validated: "neutral",
    stale: "warning",
    failed: "danger",
    final_failed: "danger",
    cancelled: "neutral",
    offline: "danger",
    disabled: "neutral"
  }[normalized] || "neutral";
  return <span className={`pill ${tone}`}>{statusText(normalized)}</span>;
}

function statusText(value) {
  return ({
    queued: "排队中",
    dispatched: "已下发",
    assigned: "已分配",
    running: "执行中",
    success: "成功",
    failed: "失败",
    final_failed: "最终失败",
    cancelled: "已取消",
    online: "在线",
    stale: "过期",
    offline: "离线",
    degraded: "降级",
    partial_success: "部分成功",
    imported: "已导入",
    validated: "已校验",
    pending_schedule: "待调度",
    pending_deploy: "待部署",
    deploy_failed: "部署失败",
    disabled: "停用",
    created: "已创建"
  }[value] || value || "-");
}

function shortId(value) {
  return value ? String(value).slice(0, 8) : "-";
}

function fmtTime(value) {
  if (!value) return "-";
  return String(value).replace("T", " ").replace("+00:00", " UTC").slice(0, 22);
}

function safeJson(value) {
  if (!value) return "-";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function StatCard({ label, value, tone, hint }) {
  return (
    <div className={`stat-card ${tone || ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  );
}

function EmptyRow({ colSpan, message = "暂无数据" }) {
  return <tr><td colSpan={colSpan} className="empty">{message}</td></tr>;
}

export default function App() {
  const [activePage, setActivePage] = useState("overview");
  const [nodes, setNodes] = useState([]);
  const [cluster, setCluster] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [taskEvents, setTaskEvents] = useState([]);
  const [providers, setProviders] = useState({ active: "", providers: [] });
  const [provisionServers, setProvisionServers] = useState({ provider: "", servers: [] });
  const [architectureSummary, setArchitectureSummary] = useState(null);
  const [infraWorkers, setInfraWorkers] = useState([]);
  const [infraCapabilities, setInfraCapabilities] = useState([]);
  const [infraProfiles, setInfraProfiles] = useState([]);
  const [infraEvents, setInfraEvents] = useState([]);
  const [infraSyncRuns, setInfraSyncRuns] = useState([]);
  const [bizJobs, setBizJobs] = useState([]);
  const [bizRuns, setBizRuns] = useState([]);
  const [bizEvents, setBizEvents] = useState([]);
  const [bizArtifacts, setBizArtifacts] = useState([]);
  const [provisionJobs, setProvisionJobs] = useState([]);
  const [jobDetail, setJobDetail] = useState(null);
  const [taskDetail, setTaskDetail] = useState(null);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedJobId, setSelectedJobId] = useState("");
  const [selectedBizJobId, setSelectedBizJobId] = useState("");
  const [showEnabledOnly, setShowEnabledOnly] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [feishuCheck, setFeishuCheck] = useState(null);
  const [feishuSmoke, setFeishuSmoke] = useState(null);
  const [sourceRegistry, setSourceRegistry] = useState({ sources: [], sinks: [] });
  const [infraSource, setInfraSource] = useState("local_json");
  const [bizSource, setBizSource] = useState("local_json");
  const [reconcileResult, setReconcileResult] = useState(null);
  const [newTask, setNewTask] = useState({
    profile_id: "",
    authorized_target: "internal test app",
    task_type: "open_url",
    url: "",
    timeout_seconds: 300,
    max_retries: 1
  });

  const totals = useMemo(() => {
    const online = nodes.filter((n) => n.status === "online").length;
    const stale = nodes.filter((n) => n.status === "stale").length;
    const offline = nodes.filter((n) => n.status === "offline").length;
    const queued = cluster?.tasks?.queued ?? tasks.filter((t) => t.status === "queued").length;
    const dispatched = cluster?.tasks?.dispatched ?? tasks.filter((t) => t.status === "dispatched").length;
    const running = cluster?.tasks?.running ?? tasks.filter((t) => t.status === "running").length;
    return { online, stale, offline, queued, dispatched, running, total: nodes.length };
  }, [cluster, nodes, tasks]);

  const taskStats = useMemo(() => ({
    success: tasks.filter((t) => t.status === "success").length,
    failed: tasks.filter((t) => t.status === "failed").length,
    running: tasks.filter((t) => t.status === "running").length
  }), [tasks]);

  const bizStats = useMemo(() => ({
    total: bizJobs.length,
    pending: bizJobs.filter((j) => j.status === "pending_schedule").length,
    assigned: bizJobs.filter((j) => j.status === "assigned").length,
    running: bizJobs.filter((j) => j.status === "running").length,
    success: bizJobs.filter((j) => j.status === "success").length,
    failed: bizJobs.filter((j) => ["failed", "final_failed"].includes(j.status)).length
  }), [bizJobs]);

  const visibleProvisionServers = useMemo(() => {
    const servers = provisionServers.servers || [];
    if (!showEnabledOnly) return servers;
    return servers.filter((s) => s.enabled);
  }, [provisionServers, showEnabledOnly]);

  const selectedBizJob = useMemo(() => {
    return bizJobs.find((job) => job.id === selectedBizJobId) || bizJobs[0] || null;
  }, [bizJobs, selectedBizJobId]);

  const refreshCore = async () => {
    setLoading(true);
    try {
      const [
        nextNodes,
        nextCluster,
        nextTasks,
        nextProviders,
        nextProvisionJobs,
        nextServers,
        nextArchitecture,
        nextInfraWorkers,
        nextInfraCapabilities,
        nextInfraProfiles,
        nextInfraEvents,
        nextInfraSyncRuns,
        nextBizJobs,
        nextBizRuns,
        nextBizEvents,
        nextBizArtifacts,
        nextSources
      ] = await Promise.all([
        api("/api/master/nodes"),
        api("/api/master/cluster/status"),
        api("/api/master/tasks"),
        api("/api/master/providers"),
        api("/api/master/provision/jobs"),
        api("/api/master/provision/servers"),
        api("/api/master/architecture/summary"),
        api("/api/master/infra/workers"),
        api("/api/master/infra/capabilities"),
        api("/api/master/infra/profiles"),
        api("/api/master/infra/events"),
        api("/api/master/infra/sync-runs"),
        api("/api/master/biz/jobs"),
        api("/api/master/biz/runs"),
        api("/api/master/biz/events"),
        api("/api/master/biz/artifacts"),
        api("/api/master/sources")
      ]);
      setNodes(nextNodes);
      setCluster(nextCluster);
      setTasks(nextTasks);
      setProviders(nextProviders);
      setProvisionJobs(nextProvisionJobs);
      setProvisionServers(nextServers);
      setArchitectureSummary(nextArchitecture);
      setInfraWorkers(nextInfraWorkers);
      setInfraCapabilities(nextInfraCapabilities);
      setInfraProfiles(nextInfraProfiles);
      setInfraEvents(nextInfraEvents);
      setInfraSyncRuns(nextInfraSyncRuns);
      setBizJobs(nextBizJobs);
      setBizRuns(nextBizRuns);
      setBizEvents(nextBizEvents);
      setBizArtifacts(nextBizArtifacts);
      setSourceRegistry(nextSources);
      if (!selectedTaskId && nextTasks[0]) setSelectedTaskId(nextTasks[0].id);
      if (!selectedJobId && nextProvisionJobs[0]) setSelectedJobId(nextProvisionJobs[0].id);
      if (!selectedBizJobId && nextBizJobs[0]) setSelectedBizJobId(nextBizJobs[0].id);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshCore();
    const timer = window.setInterval(refreshCore, 4000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedTaskId) return;
    Promise.all([
      api(`/api/master/tasks/${selectedTaskId}/events`),
      api(`/api/master/tasks/${selectedTaskId}`)
    ]).then(([nextEvents, nextTask]) => {
      setTaskEvents(nextEvents);
      setTaskDetail(nextTask);
    }).catch(() => {
      setTaskEvents([]);
      setTaskDetail(null);
    });
  }, [selectedTaskId]);

  useEffect(() => {
    if (!selectedJobId) return;
    api(`/api/master/provision/jobs/${selectedJobId}`).then(setJobDetail).catch(() => setJobDetail(null));
  }, [selectedJobId]);

  const createTask = async () => {
    const payload = {
      profile_id: newTask.profile_id || null,
      authorized_target: newTask.authorized_target,
      task_type: newTask.task_type,
      url: newTask.task_type === "open_url" ? (newTask.url.trim() || null) : null,
      timeout_seconds: Number(newTask.timeout_seconds) || 300,
      max_retries: newTask.max_retries === "" ? 1 : Number(newTask.max_retries)
    };
    await api("/api/master/tasks", { method: "POST", body: JSON.stringify(payload) });
    setNotice("任务已创建");
    await refreshCore();
  };

  const runProvision = async (dryRun, nodeId = null) => {
    const payload = { dry_run: dryRun };
    if (nodeId) payload.node_id = nodeId;
    const result = await api("/api/master/provision/run", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    const nextJobId = result?.job?.id;
    if (nextJobId) {
      setSelectedJobId(nextJobId);
      setJobDetail(result);
    }
    setActivePage("infra");
    setNotice(`${dryRun ? "演练任务" : "部署任务"}已提交${nodeId ? `：${nodeId}` : ""}`);
    await refreshCore();
  };

  const syncInfra = async () => {
    const result = await api("/api/master/infra/sync", { method: "POST", body: JSON.stringify({ source: infraSource }) });
    setActivePage("infra");
    setNotice(`基础设施同步完成：${result.count || 0} 条（${result.source || infraSource}）`);
    await refreshCore();
  };

  const syncBiz = async (schedule = false) => {
    const result = await api("/api/master/biz/sync", {
      method: "POST",
      body: JSON.stringify({ schedule, source: bizSource })
    });
    setActivePage("biz");
    setNotice(schedule ? `业务同步并调度完成：${result.count || 0} 条（${result.source || bizSource}）` : `业务同步完成：${result.count || 0} 条（${result.source || bizSource}）`);
    await refreshCore();
  };

  const setProvider = async (provider) => {
    if (provider === "feishu_openapi") {
      setNotice("feishu_openapi 尚未配置，暂不能作为服务器提供方");
      return;
    }
    await api("/api/master/providers/active", {
      method: "PUT",
      body: JSON.stringify({ provider })
    });
    setNotice(`已切换提供方：${provider}`);
    await refreshCore();
  };

  const validateFeishu = async () => {
    const result = await api("/api/master/providers/feishu-openapi/validate", { method: "POST" });
    setFeishuCheck(result);
  };

  const smokeFeishu = async () => {
    const result = await api("/api/master/providers/feishu-openapi/smoke", { method: "POST" });
    setFeishuSmoke(result);
  };

  const reconcileInfra = async (dryRun = true, nodeId = null) => {
    const payload = { dry_run: dryRun };
    if (nodeId) payload.node_id = nodeId;
    const result = await api("/api/master/infra/reconcile", { method: "POST", body: JSON.stringify(payload) });
    setReconcileResult(result);
    setActivePage("infra");
    setNotice(dryRun ? "基础设施 reconcile 计划已生成" : "基础设施 reconcile 已执行");
    await refreshCore();
  };

  const recoverStuckTasks = async () => {
    const result = await api("/api/master/tasks/recover-stuck", { method: "POST", body: JSON.stringify({ older_than_seconds: 600 }) });
    setNotice(`Stuck task 回收完成：${result.count || 0} 个`);
    await refreshCore();
  };

  const cancelTask = async (taskId) => {
    await api(`/api/master/tasks/${taskId}/cancel`, { method: "POST" });
    setNotice("任务已取消");
    await refreshCore();
  };

  const requeueTask = async (taskId) => {
    await api(`/api/master/tasks/${taskId}/requeue`, { method: "POST" });
    setNotice("任务已重新排队");
    await refreshCore();
  };

  const cancelBizJob = async (jobId) => {
    await api(`/api/master/biz/jobs/${jobId}/cancel`, { method: "POST" });
    setNotice("业务任务已取消");
    await refreshCore();
  };

  const requeueBizJob = async (jobId) => {
    await api(`/api/master/biz/jobs/${jobId}/requeue`, { method: "POST" });
    setNotice("业务任务已重新进入待调度");
    await refreshCore();
  };

  const renderPage = () => {
    if (activePage === "infra") {
      return (
        <InfraPage
          infraWorkers={infraWorkers}
          infraCapabilities={infraCapabilities}
          infraEvents={infraEvents}
          infraSyncRuns={infraSyncRuns}
          nodes={nodes}
          provisionServers={provisionServers}
          visibleProvisionServers={visibleProvisionServers}
          showEnabledOnly={showEnabledOnly}
          setShowEnabledOnly={setShowEnabledOnly}
          provisionJobs={provisionJobs}
          selectedJobId={selectedJobId}
          setSelectedJobId={setSelectedJobId}
          jobDetail={jobDetail}
          runProvision={runProvision}
          syncInfra={syncInfra}
          reconcileInfra={reconcileInfra}
          reconcileResult={reconcileResult}
          infraSource={infraSource}
          setInfraSource={setInfraSource}
          sourceRegistry={sourceRegistry}
        />
      );
    }
    if (activePage === "biz") {
      return (
        <BizPage
          bizJobs={bizJobs}
          bizRuns={bizRuns}
          bizArtifacts={bizArtifacts}
          selectedBizJob={selectedBizJob}
          setSelectedBizJobId={setSelectedBizJobId}
          syncBiz={syncBiz}
          cancelBizJob={cancelBizJob}
          requeueBizJob={requeueBizJob}
          bizSource={bizSource}
          setBizSource={setBizSource}
          sourceRegistry={sourceRegistry}
        />
      );
    }
    if (activePage === "profiles") {
      return (
        <ProfilesPage
          infraProfiles={infraProfiles}
          nodes={nodes}
          tasks={tasks}
          selectedTaskId={selectedTaskId}
          setSelectedTaskId={setSelectedTaskId}
          taskDetail={taskDetail}
          taskEvents={taskEvents}
          createTask={createTask}
          newTask={newTask}
          setNewTask={setNewTask}
          recoverStuckTasks={recoverStuckTasks}
          cancelTask={cancelTask}
          requeueTask={requeueTask}
        />
      );
    }
    if (activePage === "events") {
      return <EventsPage infraEvents={infraEvents} bizEvents={bizEvents} taskEvents={taskEvents} />;
    }
    if (activePage === "settings") {
      return (
        <SettingsPage
          providers={providers}
          provisionServers={provisionServers}
          setProvider={setProvider}
          validateFeishu={validateFeishu}
          smokeFeishu={smokeFeishu}
          feishuCheck={feishuCheck}
          feishuSmoke={feishuSmoke}
          sourceRegistry={sourceRegistry}
        />
      );
    }
    return (
      <OverviewPage
        totals={totals}
        taskStats={taskStats}
        bizStats={bizStats}
        architectureSummary={architectureSummary}
        infraWorkers={infraWorkers}
        infraProfiles={infraProfiles}
        infraEvents={infraEvents}
        bizEvents={bizEvents}
        setActivePage={setActivePage}
        syncInfra={syncInfra}
        syncBiz={syncBiz}
      />
    );
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Icon type="grid" /></div>
          <div>
            <h1>Master Console</h1>
            <p>公网编排控制台</p>
          </div>
        </div>
        <nav className="side-nav">
          {NAV_ITEMS.map((item) => (
            <button key={item.id} className={activePage === item.id ? "nav-item active" : "nav-item"} onClick={() => setActivePage(item.id)}>
              <span className="nav-icon"><Icon type={item.icon} /></span>
              <span>
                <b>{item.label}</b>
                <small>{item.desc}</small>
              </span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span>当前 Provider</span>
          <b>{providers.active || "-"}</b>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <p className="eyebrow">architecture-infra-biz-split</p>
            <h2>{NAV_ITEMS.find((item) => item.id === activePage)?.label || "分层总览"}</h2>
          </div>
          <div className="toolbar">
            <button onClick={refreshCore} disabled={loading}>{loading ? "刷新中..." : "刷新"}</button>
          </div>
        </header>

        {error && <div className="alert danger">{error}</div>}
        {notice && <div className="alert success">{notice}</div>}
        {renderPage()}
      </main>
    </div>
  );
}

function OverviewPage({ totals, taskStats, bizStats, architectureSummary, infraWorkers, infraProfiles, infraEvents, bizEvents, setActivePage, syncInfra, syncBiz }) {
  return (
    <div className="page-stack">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Layered orchestration</p>
          <h2>按基础设施流、业务流、执行观测流拆分管理入口</h2>
          <p>首页只看跨层健康和阻塞点，具体操作进入对应页面，避免部署 Worker、调度任务、Profile 监控混在一个长页面里。</p>
        </div>
        <div className="hero-actions">
          <button onClick={syncInfra}>同步基础设施</button>
          <button className="secondary" onClick={() => syncBiz(true)}>同步并调度业务</button>
        </div>
      </section>

      <section className="stat-grid wide">
        <StatCard label="Worker 在线" value={`${totals.online}/${totals.total}`} tone="success" hint={`${totals.stale} 过期 / ${totals.offline} 离线`} />
        <StatCard label="运行 Profile" value={architectureSummary?.infra?.running_profiles ?? infraProfiles.filter((p) => p.status === "running").length} />
        <StatCard label="业务任务" value={bizStats.total} hint={`${bizStats.pending} 待调度`} />
        <StatCard label="业务成功/失败" value={`${bizStats.success}/${bizStats.failed}`} tone={bizStats.failed ? "danger" : "success"} />
        <StatCard label="Master 队列" value={totals.queued} hint={`${totals.running} 执行中`} />
        <StatCard label="任务成功/失败" value={`${taskStats.success}/${taskStats.failed}`} />
      </section>

      <section className="layer-map">
        <LayerCard title="基础设施层" icon="server" tone="success" onOpen={() => setActivePage("infra")} items={["Worker 清单", "Provision 阶段", "心跳与资源", "Capabilities", "调度契约"]}>
          只处理服务器、Docker、部署、Worker 健康和可调度能力。
        </LayerCard>
        <LayerCard title="业务自动化层" icon="briefcase" tone="info" onOpen={() => setActivePage("biz")} items={["业务输入", "幂等快照", "调度队列", "运行记录", "结果回写"]}>
          只处理业务参数、脚本 key/version、业务状态机和回写结果。
        </LayerCard>
        <LayerCard title="Profile / Worker 监控" icon="browser" tone="warning" onOpen={() => setActivePage("profiles")} items={["Profile 状态", "VNC 入口", "CDP 端口", "容量水位", "任务来源"]}>
          连接实际浏览器实例和任务，但不承载部署或业务决策。
        </LayerCard>
      </section>

      <section className="grid two">
        <div className="panel">
          <div className="panel-title"><h3>跨层流程</h3></div>
          <div className="flow">
            <FlowStep title="飞书 Worker 表" desc="服务器、标签、期望状态" />
            <FlowArrow />
            <FlowStep title="基础设施同步" desc="infra_workers / capabilities" />
            <FlowArrow />
            <FlowStep title="调度契约" desc="可用 Worker 查询" />
            <FlowStep title="飞书业务表" desc="账号、脚本、参数" />
            <FlowArrow />
            <FlowStep title="业务同步" desc="幂等键与输入快照" />
            <FlowArrow />
            <FlowStep title="Worker 运行时" desc="Profile、脚本、结果" />
          </div>
        </div>
        <div className="panel">
          <div className="panel-title"><h3>最近事件</h3><button className="ghost" onClick={() => setActivePage("events")}>查看全部</button></div>
          <EventList events={[...infraEvents.slice(0, 3).map((e) => ({ ...e, stream: "infra" })), ...bizEvents.slice(0, 3).map((e) => ({ ...e, stream: "biz" }))].slice(0, 6)} />
        </div>
      </section>
    </div>
  );
}

function LayerCard({ title, icon, tone, items, children, onOpen }) {
  return (
    <div className={`layer-card ${tone}`}>
      <div className="layer-head">
        <span className="layer-icon"><Icon type={icon} /></span>
        <h3>{title}</h3>
      </div>
      <p>{children}</p>
      <div className="chip-row">
        {items.map((item) => <span key={item} className="chip">{item}</span>)}
      </div>
      <button className="secondary" onClick={onOpen}>进入页面</button>
    </div>
  );
}

function FlowStep({ title, desc }) {
  return <div className="flow-step"><b>{title}</b><span>{desc}</span></div>;
}

function FlowArrow() {
  return <div className="flow-arrow">→</div>;
}

function InfraPage({ infraWorkers, infraCapabilities, infraEvents, infraSyncRuns, nodes, provisionServers, visibleProvisionServers, showEnabledOnly, setShowEnabledOnly, provisionJobs, selectedJobId, setSelectedJobId, jobDetail, runProvision, syncInfra, reconcileInfra, reconcileResult, infraSource, setInfraSource, sourceRegistry }) {
  const workerByNode = new Map(nodes.map((node) => [node.node_id, node]));
  const infraSources = (sourceRegistry?.sources || []).filter((source) => source.kind === "infra" || source.kind === "infra_biz");
  return (
    <div className="page-stack">
      <section className="page-header-card">
        <div>
          <p className="eyebrow">Infrastructure stream</p>
          <h2>Worker 服务器、部署、心跳、资源、能力独立管理</h2>
          <p>基础设施层不理解账号密码和购票流程，只向业务层提供可调度 Worker 查询能力。</p>
        </div>
        <div className="header-actions">
          <select className="source-select" value={infraSource} onChange={(e) => setInfraSource(e.target.value)}>
            {infraSources.length === 0 && <option value="local_json">local_json</option>}
            {infraSources.map((source) => <option key={`${source.name}-${source.kind}`} value={source.name}>{source.name}{source.ready ? "" : "（未就绪）"}</option>)}
          </select>
          <button onClick={syncInfra}>同步 Worker 表</button>
          <button className="secondary" onClick={() => reconcileInfra(true)}>Reconcile 计划</button>
          <button className="secondary" onClick={() => runProvision(true)}>部署演练</button>
          <button className="warn" onClick={() => runProvision(false)}>真实部署</button>
        </div>
      </section>

      <section className="stat-grid">
        <StatCard label="Infra Worker" value={infraWorkers.length} />
        <StatCard label="在线节点" value={nodes.filter((n) => n.status === "online").length} tone="success" />
        <StatCard label="待部署" value={infraWorkers.filter((w) => w.desired_state === "active" && ["imported", "pending_deploy"].includes(w.status)).length} tone="warning" />
        <StatCard label="Capabilities" value={infraCapabilities.length} />
      </section>

      <section className="grid two">
        <div className="panel">
          <div className="panel-title">
            <h3>Worker 清单</h3>
            <span className="muted">desired / actual / tags / slots</span>
          </div>
          <table>
            <thead><tr><th>Node</th><th>状态</th><th>Host</th><th>标签</th><th>Profile</th><th>资源</th></tr></thead>
            <tbody>
              {infraWorkers.length === 0 && <EmptyRow colSpan={6} />}
              {infraWorkers.map((worker) => {
                const node = workerByNode.get(worker.node_id);
                return (
                  <tr key={worker.node_id}>
                    <td><b>{worker.node_id}</b><small>{worker.source || "local"}</small></td>
                    <td><StatusPill value={node?.status || worker.status} /></td>
                    <td>{worker.host}:{worker.ssh_port || 22}</td>
                    <td><TagList values={worker.tags} /></td>
                    <td>{node?.running_profiles ?? 0}/{node?.max_profiles ?? worker.max_profiles ?? "-"}</td>
                    <td>{node?.mem_used_mb || 0}/{node?.mem_total_mb || 0} MB</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <div className="panel-title">
            <h3>Worker 能力</h3>
            <span className="muted">script_key / version / schema</span>
          </div>
          <table>
            <thead><tr><th>Node</th><th>脚本</th><th>版本</th><th>输入 schema</th><th>更新时间</th></tr></thead>
            <tbody>
              {infraCapabilities.length === 0 && <EmptyRow colSpan={5} />}
              {infraCapabilities.map((cap, idx) => (
                <tr key={`${cap.node_id}-${cap.script_key}-${idx}`}>
                  <td>{cap.node_id}</td>
                  <td><b>{cap.script_key}</b></td>
                  <td>{cap.script_version}</td>
                  <td>{cap.input_schema_version || "v1"}</td>
                  <td>{fmtTime(cap.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid three">
        <div className="panel">
          <div className="panel-title">
            <h3>部署服务器来源</h3>
            <label className="checkbox"><input type="checkbox" checked={showEnabledOnly} onChange={(e) => setShowEnabledOnly(e.target.checked)} />仅启用</label>
          </div>
          <table>
            <thead><tr><th>节点</th><th>主机</th><th>用户</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              {visibleProvisionServers.length === 0 && <EmptyRow colSpan={5} />}
              {visibleProvisionServers.map((server) => (
                <tr key={server.node_id}>
                  <td>{server.node_id}</td>
                  <td>{server.host}:{server.port || server.ssh_port || 22}</td>
                  <td>{server.username || server.ssh_user || "-"}</td>
                  <td>{server.enabled ? "启用" : "禁用"}</td>
                  <td>
                    <div className="button-row compact">
                      <button className="secondary" onClick={() => runProvision(true, server.node_id)}>演练</button>
                      <button className="warn" onClick={() => runProvision(false, server.node_id)}>部署</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">Provider：{provisionServers.provider || "-"}</p>
        </div>

        <div className="panel">
          <div className="panel-title"><h3>Provision Jobs</h3></div>
          <select value={selectedJobId} onChange={(e) => setSelectedJobId(e.target.value)}>
            <option value="">选择部署任务</option>
            {provisionJobs.map((job) => <option key={job.id} value={job.id}>{shortId(job.id)} | {statusText(job.status)}</option>)}
          </select>
          <div className="detail-grid">
            <Detail label="任务状态" value={<StatusPill value={jobDetail?.job?.status} />} />
            <Detail label="成功/失败" value={`${jobDetail?.job?.success_count ?? 0}/${jobDetail?.job?.failed_count ?? 0}`} />
            <Detail label="服务器数" value={jobDetail?.job?.total_servers ?? 0} />
            <Detail label="模式" value={jobDetail?.job?.dry_run ? "演练" : "真实部署"} />
          </div>
          <CompactList items={jobDetail?.items || []} primary="node_id" secondary="status" message="message" />
        </div>

        <div className="panel">
          <div className="panel-title"><h3>基础设施事件</h3></div>
          <EventList events={infraEvents.slice(0, 8).map((event) => ({ ...event, stream: "infra" }))} />
        </div>
      </section>

      <section className="panel">
        <div className="panel-title">
          <h3>Desired State Reconcile</h3>
          <span className="muted">把 Worker 期望状态转换为部署、停用、重部署或清理动作</span>
        </div>
        <table>
          <thead><tr><th>Node</th><th>Desired</th><th>Actual</th><th>Infra</th><th>动作</th><th>原因</th></tr></thead>
          <tbody>
            {(!reconcileResult?.actions?.length) && <EmptyRow colSpan={6} message="点击 Reconcile 计划生成动作列表" />}
            {(reconcileResult?.actions || []).map((item, idx) => (
              <tr key={`${item.node_id}-${idx}`}>
                <td>{item.node_id}</td>
                <td>{item.desired_state}</td>
                <td><StatusPill value={item.actual_status} /></td>
                <td><StatusPill value={item.infra_status} /></td>
                <td><b>{item.action}</b><small>{item.applied ? "已执行" : "未执行"}</small></td>
                <td>{item.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <div className="panel-title"><h3>同步记录</h3></div>
        <table>
          <thead><tr><th>ID</th><th>来源</th><th>类型</th><th>状态</th><th>导入数</th><th>时间</th><th>错误</th></tr></thead>
          <tbody>
            {infraSyncRuns.length === 0 && <EmptyRow colSpan={7} />}
            {infraSyncRuns.map((run) => (
              <tr key={run.id}>
                <td>{shortId(run.id)}</td>
                <td>{run.source}</td>
                <td>{run.sync_type}</td>
                <td><StatusPill value={run.status} /></td>
                <td>{run.imported_count}</td>
                <td>{fmtTime(run.updated_at || run.created_at)}</td>
                <td>{run.error_message || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function BizPage({ bizJobs, bizRuns, bizArtifacts, selectedBizJob, setSelectedBizJobId, syncBiz, cancelBizJob, requeueBizJob, bizSource, setBizSource, sourceRegistry }) {
  const runsForJob = selectedBizJob ? bizRuns.filter((run) => run.biz_job_id === selectedBizJob.id) : [];
  const bizSources = (sourceRegistry?.sources || []).filter((source) => source.kind === "biz" || source.kind === "infra_biz");
  return (
    <div className="page-stack">
      <section className="page-header-card">
        <div>
          <p className="eyebrow">Business automation stream</p>
          <h2>业务输入、幂等快照、调度状态、执行结果独立管理</h2>
          <p>业务层不处理 SSH 和 Docker，只依赖基础设施层返回的可调度 Worker。</p>
        </div>
        <div className="header-actions">
          <select className="source-select" value={bizSource} onChange={(e) => setBizSource(e.target.value)}>
            {bizSources.length === 0 && <option value="local_json">local_json</option>}
            {bizSources.map((source) => <option key={`${source.name}-${source.kind}`} value={source.name}>{source.name}{source.ready ? "" : "（未就绪）"}</option>)}
          </select>
          <button onClick={() => syncBiz(false)}>同步业务表</button>
          <button className="secondary" onClick={() => syncBiz(true)}>同步并调度</button>
        </div>
      </section>

      <section className="stat-grid">
        <StatCard label="业务任务" value={bizJobs.length} />
        <StatCard label="待调度" value={bizJobs.filter((j) => j.status === "pending_schedule").length} tone="warning" />
        <StatCard label="运行中" value={bizJobs.filter((j) => j.status === "running").length} />
        <StatCard label="成功" value={bizJobs.filter((j) => j.status === "success").length} tone="success" />
      </section>

      <section className="grid biz-layout">
        <div className="panel">
          <div className="panel-title">
            <h3>业务任务列表</h3>
            <span className="muted">source_record_id + run_generation 幂等</span>
          </div>
          <table>
            <thead><tr><th>幂等键</th><th>状态</th><th>脚本</th><th>Worker</th><th>Profile</th><th>结果</th></tr></thead>
            <tbody>
              {bizJobs.length === 0 && <EmptyRow colSpan={6} />}
              {bizJobs.map((job) => (
                <tr key={job.id} className={selectedBizJob?.id === job.id ? "selected-row" : ""} onClick={() => setSelectedBizJobId(job.id)}>
                  <td><b>{job.idempotency_key}</b><small>{job.job_key}</small></td>
                  <td><StatusPill value={job.status} /></td>
                  <td>{job.script_key} {job.script_version}</td>
                  <td>{job.assigned_worker || "-"}</td>
                  <td>{shortId(job.profile_id)}</td>
                  <td className="truncate">{job.result_summary || job.error_message || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel detail-panel">
          <div className="panel-title">
            <h3>任务详情</h3>
            {selectedBizJob && (
              <div className="button-row compact">
                <button className="secondary" onClick={() => requeueBizJob(selectedBizJob.id)}>重排队</button>
                <button className="warn" onClick={() => cancelBizJob(selectedBizJob.id)}>取消</button>
              </div>
            )}
          </div>
          {selectedBizJob ? (
            <>
              <div className="detail-grid">
                <Detail label="状态" value={<StatusPill value={selectedBizJob.status} />} />
                <Detail label="来源记录" value={selectedBizJob.source_record_id} />
                <Detail label="Run generation" value={selectedBizJob.run_generation} />
                <Detail label="Master Task" value={shortId(selectedBizJob.master_task_id)} />
                <Detail label="Worker" value={selectedBizJob.assigned_worker || "-"} />
                <Detail label="Profile" value={shortId(selectedBizJob.profile_id)} />
              </div>
              <h4>输入快照</h4>
              <pre>{safeJson(selectedBizJob.input_snapshot)}</pre>
              <h4>结果摘要</h4>
              <pre>{selectedBizJob.result_summary || selectedBizJob.error_message || "-"}</pre>
            </>
          ) : <p className="muted">请选择业务任务</p>}
        </div>
      </section>

      <section className="grid two">
        <div className="panel">
          <div className="panel-title"><h3>运行记录</h3></div>
          <table>
            <thead><tr><th>Run</th><th>状态</th><th>Worker</th><th>Task</th><th>开始</th><th>结束</th></tr></thead>
            <tbody>
              {runsForJob.length === 0 && <EmptyRow colSpan={6} />}
              {runsForJob.map((run) => (
                <tr key={run.id}>
                  <td>{shortId(run.id)}</td>
                  <td><StatusPill value={run.status} /></td>
                  <td>{run.node_id || "-"}</td>
                  <td>{shortId(run.master_task_id)}</td>
                  <td>{fmtTime(run.started_at)}</td>
                  <td>{fmtTime(run.finished_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <div className="panel-title"><h3>Artifacts / 回写</h3></div>
          <table>
            <thead><tr><th>类型</th><th>URI</th><th>Job</th><th>Run</th><th>操作</th></tr></thead>
            <tbody>
              {bizArtifacts.length === 0 && <EmptyRow colSpan={5} message="暂无 artifacts，MVP 当前以结构化 result 为主" />}
              {bizArtifacts.map((artifact) => (
                <tr key={artifact.id}>
                  <td>{artifact.artifact_type}</td>
                  <td>{artifact.uri}</td>
                  <td>{shortId(artifact.biz_job_id)}</td>
                  <td>{shortId(artifact.run_id)}</td>
                  <td><a href={`/api/master/biz/artifacts/${artifact.id}/download`} target="_blank" rel="noreferrer">打开</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function ProfilesPage({ infraProfiles, nodes, tasks, selectedTaskId, setSelectedTaskId, taskDetail, taskEvents, createTask, newTask, setNewTask, recoverStuckTasks, cancelTask, requeueTask }) {
  const runningProfiles = infraProfiles.filter((p) => p.status === "running").length;
  const stoppedProfiles = infraProfiles.filter((p) => p.status === "stopped").length;
  return (
    <div className="page-stack">
      <section className="page-header-card">
        <div>
          <p className="eyebrow">Profile observability</p>
          <h2>浏览器实例、VNC/CDP 入口和执行任务来源独立展示</h2>
          <p>这里是执行面监控页，用来定位正在跑的 Profile、所属 Worker、任务来源和浏览器入口。</p>
        </div>
        <div className="header-actions">
          <button className="secondary" onClick={recoverStuckTasks}>回收 stuck task</button>
        </div>
      </section>

      <section className="stat-grid">
        <StatCard label="运行中 Profile" value={runningProfiles} tone="success" />
        <StatCard label="观测记录" value={infraProfiles.length} hint="含已停止记录" />
        <StatCard label="已停止记录" value={stoppedProfiles} />
        <StatCard label="运行中任务" value={tasks.filter((t) => t.status === "running").length} />
        <StatCard label="可用节点" value={nodes.filter((n) => n.status === "online").length} />
      </section>

      <section className="grid two">
        <div className="panel">
          <div className="panel-title"><h3>Profile 列表</h3></div>
          <table>
            <thead><tr><th>Profile</th><th>状态</th><th>Worker</th><th>VNC</th><th>CDP</th><th>标题</th><th>最后观测</th></tr></thead>
            <tbody>
              {infraProfiles.length === 0 && <EmptyRow colSpan={7} />}
              {infraProfiles.map((profile) => (
                <tr key={`${profile.node_id}-${profile.profile_id}`}>
                  <td><b>{shortId(profile.profile_id)}</b><small>{profile.display ? `display ${profile.display}` : ""}</small></td>
                  <td><StatusPill value={profile.status} /></td>
                  <td>{profile.node_id}</td>
                  <td>{profile.vnc_ws_port || "-"}</td>
                  <td>{profile.cdp_port || "-"}</td>
                  <td className="truncate">{profile.title || profile.current_url || "-"}</td>
                  <td>{fmtTime(profile.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <div className="panel-title">
            <h3>Master 任务与事件</h3>
            {taskDetail && (
              <div className="button-row compact">
                <button className="secondary" onClick={() => requeueTask(taskDetail.id)}>重排队</button>
                <button className="warn" onClick={() => cancelTask(taskDetail.id)}>取消</button>
              </div>
            )}
          </div>
          <select value={selectedTaskId} onChange={(e) => setSelectedTaskId(e.target.value)}>
            <option value="">选择任务</option>
            {tasks.map((task) => <option key={task.id} value={task.id}>{shortId(task.id)} | {statusText(task.status)} | {task.target_node_id || "未分配"}</option>)}
          </select>
          <div className="detail-grid">
            <Detail label="状态" value={<StatusPill value={taskDetail?.status} />} />
            <Detail label="节点" value={taskDetail?.target_node_id || "-"} />
            <Detail label="Profile" value={shortId(taskDetail?.profile_id)} />
            <Detail label="类型" value={taskDetail?.task_type || "-"} />
          </div>
          <CompactList items={taskEvents} primary="event_type" secondary="node_id" message="message" />
        </div>
      </section>

      <section className="panel">
        <div className="panel-title"><h3>手动创建 Master 任务</h3><span className="muted">调试入口，业务流建议走业务任务表</span></div>
        <div className="form-grid">
          <input value={newTask.profile_id} onChange={(e) => setNewTask({ ...newTask, profile_id: e.target.value })} placeholder="profile_id（可选）" />
          <input value={newTask.authorized_target} onChange={(e) => setNewTask({ ...newTask, authorized_target: e.target.value })} placeholder="authorized_target" />
          <select value={newTask.task_type} onChange={(e) => setNewTask({ ...newTask, task_type: e.target.value })}>
            <option value="open_url">open_url</option>
            <option value="external_cdp">external_cdp</option>
          </select>
          <input value={newTask.url} onChange={(e) => setNewTask({ ...newTask, url: e.target.value })} placeholder="url（仅 open_url）" />
          <input type="number" value={newTask.timeout_seconds} onChange={(e) => setNewTask({ ...newTask, timeout_seconds: e.target.value })} placeholder="超时秒数" />
          <input type="number" value={newTask.max_retries} onChange={(e) => setNewTask({ ...newTask, max_retries: e.target.value })} placeholder="最大重试" />
          <button onClick={createTask}>创建任务</button>
        </div>
      </section>
    </div>
  );
}

function EventsPage({ infraEvents, bizEvents, taskEvents }) {
  const merged = [
    ...infraEvents.map((event) => ({ ...event, stream: "infra" })),
    ...bizEvents.map((event) => ({ ...event, stream: "biz" })),
    ...taskEvents.map((event) => ({ ...event, stream: "task" }))
  ].sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  return (
    <div className="page-stack">
      <section className="page-header-card">
        <div>
          <p className="eyebrow">Events and write-back</p>
          <h2>基础设施事件和业务事件分流查看</h2>
          <p>部署失败、心跳异常、业务脚本失败、结果回写应分别归因，避免排障时混在一起。</p>
        </div>
      </section>

      <section className="grid two">
        <div className="panel">
          <div className="panel-title"><h3>事件时间线</h3></div>
          <EventList events={merged} />
        </div>
        <div className="panel">
          <div className="panel-title"><h3>分流原则</h3></div>
          <div className="principles">
            <Principle title="Infra events" desc="Worker 导入、部署阶段、Docker 权限、心跳、资源、capability。" />
            <Principle title="Biz events" desc="业务任务导入、校验、调度、脚本开始、成功/失败、结果回写。" />
            <Principle title="Task events" desc="Master task 下发、Worker report、重试、最终失败，用于连接执行链路。" />
          </div>
        </div>
      </section>
    </div>
  );
}

function SettingsPage({ providers, provisionServers, setProvider, validateFeishu, smokeFeishu, feishuCheck, feishuSmoke, sourceRegistry }) {
  return (
    <div className="page-stack">
      <section className="page-header-card">
        <div>
          <p className="eyebrow">Sources and adapters</p>
          <h2>配置、Provider、Feishu adapter 独立管理</h2>
          <p>Local JSON 是 Feishu OpenAPI 前的替身，字段名保持可替换，后续只换同步 adapter。</p>
        </div>
      </section>

      <section className="grid two">
        <div className="panel">
          <div className="panel-title"><h3>Source Registry</h3><span className="muted">统一数据源健康检查</span></div>
          <table>
            <thead><tr><th>Source</th><th>类型</th><th>状态</th><th>说明</th></tr></thead>
            <tbody>
              {(!sourceRegistry?.sources?.length) && <EmptyRow colSpan={4} />}
              {(sourceRegistry?.sources || []).map((source, idx) => (
                <tr key={`${source.name}-${source.kind}-${idx}`}>
                  <td><b>{source.name}</b></td>
                  <td>{source.kind}</td>
                  <td><StatusPill value={source.ready ? "success" : "pending_schedule"} /></td>
                  <td>{source.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <div className="panel-title"><h3>Writeback Sink</h3><span className="muted">业务结果回写目标</span></div>
          <table>
            <thead><tr><th>Sink</th><th>状态</th><th>说明</th></tr></thead>
            <tbody>
              {(!sourceRegistry?.sinks?.length) && <EmptyRow colSpan={3} />}
              {(sourceRegistry?.sinks || []).map((sink) => (
                <tr key={sink.name}>
                  <td><b>{sink.name}</b></td>
                  <td><StatusPill value={sink.ready ? "success" : "pending_schedule"} /></td>
                  <td>{sink.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid two">
        <div className="panel">
          <div className="panel-title"><h3>Provider</h3><span className="muted">当前：{providers.active || "-"}</span></div>
          <div className="button-row">
            {providers.providers?.map((name) => {
              const reserved = name === "feishu_openapi";
              return (
                <button key={name} className={providers.active === name ? "" : "secondary"} onClick={() => setProvider(name)} disabled={reserved} title={reserved ? "feishu_openapi 尚未配置" : undefined}>
                  {reserved ? `${name}（未实现）` : name}
                </button>
              );
            })}
            <button className="secondary" onClick={validateFeishu}>查看 feishu_openapi 状态</button>
            <button className="secondary" onClick={smokeFeishu}>Feishu 联调检查</button>
          </div>
          {feishuCheck && <div className="detail-box">校验结果：{feishuCheck.ready ? "可用" : "未就绪"}（{feishuCheck.message || "-"}）</div>}
          {feishuSmoke && <pre>{safeJson(feishuSmoke)}</pre>}
        </div>

        <div className="panel">
          <div className="panel-title"><h3>数据源设计</h3></div>
          <table>
            <thead><tr><th>配置组</th><th>作用</th><th>归属层</th></tr></thead>
            <tbody>
              <tr><td>infra_workers</td><td>Worker 服务器清单、tags、desired state</td><td>基础设施层</td></tr>
              <tr><td>biz_tasks</td><td>业务输入、run_generation、脚本和参数</td><td>业务层</td></tr>
              <tr><td>provision</td><td>SSH/Docker 命令、超时、心跳校验</td><td>基础设施层</td></tr>
              <tr><td>capability registry</td><td>Worker 镜像内脚本模板版本</td><td>执行运行时</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel-title"><h3>当前部署服务器来源</h3><span className="muted">Provider：{provisionServers.provider || providers.active || "-"}</span></div>
        <table>
          <thead><tr><th>Node</th><th>Host</th><th>User</th><th>Enabled</th><th>Max Profiles</th></tr></thead>
          <tbody>
            {(provisionServers.servers || []).length === 0 && <EmptyRow colSpan={5} />}
            {(provisionServers.servers || []).map((server) => (
              <tr key={server.node_id}>
                <td>{server.node_id}</td>
                <td>{server.host}:{server.port || server.ssh_port || 22}</td>
                <td>{server.username || server.ssh_user || "-"}</td>
                <td>{server.enabled ? "启用" : "禁用"}</td>
                <td>{server.max_profiles || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function TagList({ values }) {
  const tags = values || [];
  if (!tags.length) return <span className="muted">-</span>;
  return <div className="chip-row compact">{tags.map((tag) => <span key={tag} className="chip">{tag}</span>)}</div>;
}

function Detail({ label, value }) {
  return <div className="detail-cell"><span>{label}</span><b>{value}</b></div>;
}

function CompactList({ items, primary, secondary, message }) {
  if (!items?.length) return <p className="muted">暂无记录</p>;
  return (
    <div className="compact-list">
      {items.map((item, idx) => (
        <div key={item.id || idx} className="compact-item">
          <div><b>{item[primary] || "-"}</b><StatusPill value={item[secondary]} /></div>
          <p>{item[message] || ""}</p>
        </div>
      ))}
    </div>
  );
}

function EventList({ events }) {
  if (!events?.length) return <p className="muted">暂无事件</p>;
  return (
    <div className="event-list">
      {events.map((event, idx) => (
        <div key={event.id || idx} className="event-item">
          <span className={`stream ${event.stream || "task"}`}>{event.stream || "task"}</span>
          <div>
            <b>{event.event_type}</b>
            <p>{event.message || event.stage || "-"}</p>
            <small>{event.node_id || event.biz_job_id || event.task_id || "-"} · {fmtTime(event.created_at)}</small>
          </div>
        </div>
      ))}
    </div>
  );
}

function Principle({ title, desc }) {
  return <div className="principle"><b>{title}</b><p>{desc}</p></div>;
}
